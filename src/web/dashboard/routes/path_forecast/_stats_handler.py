from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from .._index_norm import normalize_index
from .._date_norm import resolve_date
from .._now_norm import build_realized_map_and_times, nearest_time_key, now_and_cutoff

from ._bands_archive import iter_bands_quantile_rows
from ._api_contract import add_common_headers, base_headers, error_payload
from ._archive_paths import bands_archive_path


async def handle_path_stats(
    *,
    index: str,
    horizon: int,
    window_minutes: int,
    expiry_tag: str,
    offset: str,
    bucket_ms: int,
    date_str: Optional[str],
    variant: str,
    # injected deps
    project_root: Callable[[], object],
    find_live_csv: Callable[..., object],
    load_csv_rows_full: Callable[[object], list[dict]],
    extract_tp: Callable[[dict], object],
    load_calibration: Callable[[str], dict],
) -> JSONResponse:
    """Implementation of /api/ml/path_stats extracted from router."""

    try:
        import csv

        idx = normalize_index(index)
        the_date = resolve_date(date_str)
        hdr_base = base_headers(
            route_version="stats-v1",
            index=idx,
            date=(the_date.isoformat() if the_date else None),
        )
        add_common_headers(hdr_base, expiry_tag=str(expiry_tag or ""), offset=str(offset or ""))

        base = project_root() / "data" / "g6_data"
        p_live = find_live_csv(base, idx, expiry_tag, offset, the_date)
        try:
            if (not p_live) or (not getattr(p_live, "exists")()):
                hdr_base["X-Empty-Reason"] = "live_csv_not_found"
                return JSONResponse(
                    error_payload(
                        error="live_csv not found",
                        index=idx,
                        expiry_tag=str(expiry_tag),
                        offset=str(offset),
                        date=(the_date.isoformat() if the_date else None),
                        horizon=int(horizon),
                        window_minutes=int(window_minutes),
                        variant=str(variant),
                        coverage_p10_p90=None,
                        band_width_mean=None,
                        samples=0,
                    ),
                    status_code=200,
                    headers=hdr_base,
                )
        except (AttributeError, TypeError):
            hdr_base["X-Empty-Reason"] = "live_csv_not_found"
            return JSONResponse(
                error_payload(
                    error="live_csv not found",
                    index=idx,
                    expiry_tag=str(expiry_tag),
                    offset=str(offset),
                    date=(the_date.isoformat() if the_date else None),
                    horizon=int(horizon),
                    window_minutes=int(window_minutes),
                    variant=str(variant),
                    coverage_p10_p90=None,
                    band_width_mean=None,
                    samples=0,
                ),
                status_code=200,
                headers=hdr_base,
            )

        rows = load_csv_rows_full(p_live)
        if not rows:
            hdr_base["X-Empty-Reason"] = "no_live_rows"
            return JSONResponse(
                error_payload(
                    error="no live rows",
                    index=idx,
                    expiry_tag=str(expiry_tag),
                    offset=str(offset),
                    date=(the_date.isoformat() if the_date else None),
                    horizon=int(horizon),
                    window_minutes=int(window_minutes),
                    variant=str(variant),
                    coverage_p10_p90=None,
                    band_width_mean=None,
                    samples=0,
                ),
                status_code=200,
                headers=hdr_base,
            )

        # realized timestamps (sorted) and map — robust TP extraction and bucket alignment
        realized, ts_sorted = build_realized_map_and_times(
            rows,
            bucket_ms=int(bucket_ms),
            tp_getter=extract_tp,
            non_negative=True,
        )

        if not realized:
            hdr_base["X-Empty-Reason"] = "no_realized_map"
            return JSONResponse(
                error_payload(
                    error="no realized map",
                    index=idx,
                    expiry_tag=str(expiry_tag),
                    offset=str(offset),
                    date=(the_date.isoformat() if the_date else None),
                    horizon=int(horizon),
                    window_minutes=int(window_minutes),
                    variant=str(variant),
                    coverage_p10_p90=None,
                    band_width_mean=None,
                    samples=0,
                ),
                status_code=200,
                headers=hdr_base,
            )

        now_ms, cutoff_gen = now_and_cutoff(ts_sorted, window_minutes)
        add_common_headers(hdr_base, expiry_tag=str(expiry_tag or ""), offset=str(offset or ""), gen_ms=now_ms)
        if now_ms is None or cutoff_gen is None:
            hdr_base["X-Empty-Reason"] = "no_realized_timestamps"
            return JSONResponse(
                error_payload(
                    error="no realized timestamps",
                    index=idx,
                    expiry_tag=str(expiry_tag),
                    offset=str(offset),
                    date=(the_date.isoformat() if the_date else None),
                    horizon=int(horizon),
                    window_minutes=int(window_minutes),
                    variant=str(variant),
                    coverage_p10_p90=None,
                    band_width_mean=None,
                    samples=0,
                ),
                status_code=200,
                headers=hdr_base,
            )

        arch_file_bands = bands_archive_path(project_root=project_root, index=idx, d=the_date)
        if not arch_file_bands.exists():
            hdr_base["X-Empty-Reason"] = "bands_archive_missing"
            return JSONResponse(
                error_payload(
                    error="no bands archive for date",
                    index=idx,
                    expiry_tag=str(expiry_tag),
                    offset=str(offset),
                    date=(the_date.isoformat() if the_date else None),
                    horizon=int(horizon),
                    window_minutes=int(window_minutes),
                    variant=str(variant),
                    coverage_p10_p90=None,
                    band_width_mean=None,
                    samples=0,
                ),
                status_code=200,
                headers=hdr_base,
            )

        # Compute coverage and average band width from archived bands
        total = cover = 0
        bw_sum = 0.0
        tol = max(1, int(bucket_ms) // 2)

        # Current calibration band_scale (for reverse-scaling when variant='raw')
        try:
            cal = load_calibration(idx)
            cal_scale = float(cal.get("band_scale", 1.0)) or 1.0
        except (AttributeError, TypeError, ValueError):
            cal_scale = 1.0

        for gen_ms, tgt_ms, _hmin, qvals, band_scale in iter_bands_quantile_rows(
            arch_file_bands,
            quantiles=[10, 50, 90],
            horizon_min=int(horizon),
            gen_ms_min=int(cutoff_gen),
        ):
            q10v = qvals.get(10)
            q50v = qvals.get(50)
            q90v = qvals.get(90)
            if q10v is None or q90v is None:
                continue

            # Nearest realized value within tolerance
            kk = nearest_time_key(ts_sorted, tgt_ms, tol)
            if kk is None:
                continue
            rv = realized.get(kk)
            if rv is None:
                continue

            # Reverse-scale to approximate raw if requested
            if str(variant) == "raw" and isinstance(q50v, (int, float)):
                m = float(q50v)
                s = float(band_scale) if isinstance(band_scale, (int, float)) else float(cal_scale)
                if s and s > 1e-9:
                    q10v = m - (m - float(q10v)) / s
                    q90v = m + (float(q90v) - m) / s

            total += 1
            if float(q10v) <= float(rv) <= float(q90v):
                cover += 1
            bw_sum += float(q90v) - float(q10v)

        cov = (cover / float(total)) if total > 0 else None
        bw = (bw_sum / float(total)) if total > 0 else None
        out = {
            "index": idx,
            "horizon": int(horizon),
            "window_minutes": int(window_minutes),
            "date": the_date.isoformat(),
            "coverage_p10_p90": cov,
            "band_width_mean": bw,
            "samples": int(total),
            "variant": str(variant),
        }
        return JSONResponse(out, headers=hdr_base)

    except BaseException as e:
        import asyncio
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))
