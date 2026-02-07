from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from .._index_norm import normalize_index
from .._date_norm import resolve_date
from .._now_norm import build_realized_map_and_times, now_and_cutoff

from ._bands_archive import iter_bands_quantile_rows, parse_float, parse_int
from ._api_contract import add_common_headers, base_headers, error_payload
from ._archive_paths import forecast_archive_path

logger = logging.getLogger(__name__)


async def handle_path_diagnostics(
    *,
    index: str,
    window_minutes: int,
    horizons: str,
    expiry_tag: str,
    offset: str,
    bucket_ms: int,
    date_str: Optional[str],
    # injected deps
    project_root: Callable[[], object],
    normalize_expiry_tag: Callable[[str, str], str],
    find_live_csv: Callable[..., object],
    load_csv_rows_full: Callable[[object], list[dict]],
    extract_tp: Callable[[dict], object],
) -> JSONResponse:
    """Implementation of /api/ml/path_diagnostics extracted from router."""

    try:
        idx_norm = normalize_index(index)
        the_date = resolve_date(date_str)
        hdr_base = base_headers(
            route_version="diag-v1",
            index=idx_norm,
            date=(the_date.isoformat() if the_date else None),
        )
        add_common_headers(hdr_base, expiry_tag=str(expiry_tag or ""), offset=str(offset or ""))

        eff_tag = normalize_expiry_tag(idx_norm, expiry_tag)
        p_live = find_live_csv((project_root() / "data" / "g6_data"), idx_norm, eff_tag, offset, the_date)
        try:
            if (not p_live) or (not getattr(p_live, "exists")()) :
                hdr_base["X-Empty-Reason"] = "live_csv_not_found"
                return JSONResponse(
                    error_payload(
                        error="live_csv file not found",
                        index=idx_norm,
                        expiry_tag=eff_tag,
                        offset=offset,
                        date=(the_date.isoformat() if the_date else None),
                    ),
                    status_code=200,
                    headers=hdr_base,
                )
        except HTTPException:
            raise
        except (AttributeError, TypeError):
            hdr_base["X-Empty-Reason"] = "live_csv_not_found"
            return JSONResponse(
                error_payload(
                    error="live_csv file not found",
                    index=idx_norm,
                    expiry_tag=eff_tag,
                    offset=offset,
                    date=(the_date.isoformat() if the_date else None),
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
                    index=idx_norm,
                    expiry_tag=eff_tag,
                    offset=offset,
                    date=(the_date.isoformat() if the_date else None),
                ),
                status_code=200,
                headers=hdr_base,
            )

        # Build realized map by ms bucket
        realized, ts_sorted = build_realized_map_and_times(
            rows,
            bucket_ms=int(bucket_ms),
            tp_getter=extract_tp,
        )
        if not realized:
            hdr_base["X-Empty-Reason"] = "no_realized_map"
            return JSONResponse(
                error_payload(
                    error="no realized map",
                    index=idx_norm,
                    expiry_tag=eff_tag,
                    offset=offset,
                    date=(the_date.isoformat() if the_date else None),
                ),
                status_code=200,
                headers=hdr_base,
            )
        now_ms, cutoff_gen = now_and_cutoff(ts_sorted, window_minutes)
        add_common_headers(hdr_base, expiry_tag=str(eff_tag or ""), offset=str(offset or ""), gen_ms=now_ms)
        if now_ms is None or cutoff_gen is None:
            hdr_base["X-Empty-Reason"] = "no_realized_timestamps"
            return JSONResponse(
                error_payload(
                    error="no realized timestamps",
                    index=idx_norm,
                    expiry_tag=eff_tag,
                    offset=offset,
                    date=(the_date.isoformat() if the_date else None),
                ),
                status_code=200,
                headers=hdr_base,
            )

        # Locate archive file for today
        arch_file = forecast_archive_path(project_root=project_root, index=idx_norm, d=the_date)
        if not arch_file.exists():
            hdr_base["X-Empty-Reason"] = "archive_missing"
            return JSONResponse(
                error_payload(
                    error="no archive for today",
                    index=idx_norm,
                    expiry_tag=eff_tag,
                    offset=offset,
                    date=(the_date.isoformat() if the_date else None),
                ),
                status_code=200,
                headers=hdr_base,
            )

        # Parse horizons
        Hs: list[int] = []
        for tok in str(horizons).split(","):
            tok = tok.strip()
            if not tok:
                continue
            try:
                Hs.append(int(tok))
            except (TypeError, ValueError):
                continue
        Hs = [h for h in Hs if 1 <= h <= 480]
        if not Hs:
            Hs = [30, 60]

        # Load archive rows within window
        import csv

        # Map (h) -> list of (pred, realized)
        pairs: dict[int, list[tuple[float, float]]] = {h: [] for h in Hs}
        # For jitter: map target_ms -> list of q50 predictions in generation order
        jitter_series: dict[int, list[float]] = {}
        with arch_file.open("r", encoding="utf-8", newline="") as f:
            rd = csv.DictReader(f)
            for row in rd:
                gen_ms = parse_int(row, "gen_ms") or 0
                tgt_ms = parse_int(row, "target_ms") or 0
                hmin = parse_int(row, "horizon_min") or 0
                q50 = parse_float(row, "q50")
                if q50 is None:
                    continue
                if not gen_ms or not tgt_ms:
                    continue
                if gen_ms < cutoff_gen:
                    continue
                # Consider only targets <= now and exactly matching requested horizons
                if tgt_ms > now_ms:
                    continue
                if hmin in pairs and tgt_ms in realized:
                    pairs[hmin].append((q50, realized[tgt_ms]))
                # Jitter accumulation
                if tgt_ms <= now_ms:
                    jitter_series.setdefault(tgt_ms, []).append(q50)

        # Optional: compute coverage and band width using companion bands file (if present)
        coverage_by_h: dict[int, float] = {}
        bandw_by_h: dict[int, float] = {}
        try:
            from ._archive_paths import bands_archive_path
            arch_file_bands = bands_archive_path(project_root=project_root, index=idx_norm, d=the_date)
            if arch_file_bands.exists():
                # Accumulators per horizon
                cover_counts: dict[int, int] = {h: 0 for h in Hs}
                total_counts: dict[int, int] = {h: 0 for h in Hs}
                bw_sums: dict[int, float] = {h: 0.0 for h in Hs}

                for gen_ms, tgt_ms, hmin, qvals, _band_scale in iter_bands_quantile_rows(
                    arch_file_bands,
                    quantiles=[10, 90],
                    horizon_min=None,
                    gen_ms_min=int(cutoff_gen),
                    target_ms_max=int(now_ms),
                ):
                    if hmin not in total_counts:
                        continue
                    if tgt_ms not in realized:
                        continue
                    q10v = qvals.get(10)
                    q90v = qvals.get(90)
                    if q10v is None or q90v is None:
                        continue
                    rv = realized[tgt_ms]
                    total_counts[hmin] += 1
                    if float(q10v) <= float(rv) <= float(q90v):
                        cover_counts[hmin] += 1
                    bw_sums[hmin] += float(q90v) - float(q10v)

                # finalize
                for h in Hs:
                    tot = total_counts.get(h, 0)
                    if tot <= 0:
                        coverage_by_h[h] = float("nan")
                        bandw_by_h[h] = float("nan")
                    else:
                        coverage_by_h[h] = cover_counts.get(h, 0) / float(tot)
                        bandw_by_h[h] = bw_sums.get(h, 0.0) / float(tot)
        except BaseException as e:
            import asyncio
            if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
                raise
            # Optional bands; ignore errors
            pass

        # Compute metrics
        import math

        def _mae(vals: list[tuple[float, float]]) -> float:
            if not vals:
                return float("nan")
            s = 0.0
            for a, b in vals:
                s += abs(a - b)
            return s / len(vals)

        def _bias(vals: list[tuple[float, float]]) -> float:
            if not vals:
                return float("nan")
            s = 0.0
            for a, b in vals:
                s += a - b
            return s / len(vals)

        def _jitter(js: dict[int, list[float]]) -> float:
            # Average absolute change between consecutive predictions for same target
            deltas = []
            for seq in js.values():
                if len(seq) < 2:
                    continue
                deltas.extend(abs(seq[i] - seq[i - 1]) for i in range(1, len(seq)))
            if not deltas:
                return float("nan")
            return sum(deltas) / len(deltas)

        def _clean(v: object) -> object:
            try:
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    return None
            except (TypeError, ValueError):
                pass
            return v

        out = {
            "index": idx_norm,
            "window_minutes": window_minutes,
            "count_by_horizon": {h: len(pairs[h]) for h in Hs},
            "mae_by_horizon": {h: _clean(_mae(pairs[h])) for h in Hs},
            "bias_by_horizon": {h: _clean(_bias(pairs[h])) for h in Hs},
            "jitter_mean_abs": _clean(_jitter(jitter_series)),
        }
        # include coverage metrics if available
        if coverage_by_h or bandw_by_h:
            out["coverage_p10_p90_by_horizon"] = {h: _clean(coverage_by_h.get(h, float("nan"))) for h in Hs}
            out["band_width_mean_by_horizon"] = {h: _clean(bandw_by_h.get(h, float("nan"))) for h in Hs}
        return JSONResponse(out, headers=hdr_base)

    except HTTPException:
        raise
    except BaseException as e:
        import asyncio
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))
