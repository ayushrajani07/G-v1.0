from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from .._index_norm import normalize_index
from .._date_norm import resolve_date
from .._now_norm import build_realized_map_and_times, nearest_time_key

from ._bands_archive import iter_bands_quantile_rows
from ._api_contract import base_headers


async def handle_path_coverage_history(
    *,
    index: str,
    horizon: int,
    window_minutes: int,
    history_minutes: int,
    step_minutes: int,
    expiry_tag: str,
    offset: str,
    bucket_ms: int,
    date_str: Optional[str],
    max_points: int,
    # injected deps
    project_root: Callable[[], object],
    find_live_csv: Callable[..., object],
    load_csv_rows_full: Callable[[object], list[dict]],
    load_calibration: Callable[[str], dict],
    extract_tp: Callable[[dict], object],
) -> JSONResponse:
    """Implementation of /api/ml/path_coverage_history extracted from router."""

    try:
        from datetime import datetime, timezone
        import bisect
        import csv

        idx = normalize_index(index)
        the_date = resolve_date(date_str)

        hdr_base = base_headers(
            route_version="covhist-v1",
            index=idx,
            date=(the_date.isoformat() if the_date else None),
        )
        try:
            hdr_base["X-Expiry-Tag"] = str(expiry_tag or "")
            hdr_base["X-Offset"] = str(offset or "")
        except (TypeError, ValueError):
            pass

        base = project_root() / "data" / "g6_data"
        p_live = find_live_csv(base, idx, expiry_tag, offset, the_date)
        try:
            if (not p_live) or (not getattr(p_live, "exists")()):
                hdr_base["X-Empty-Reason"] = "live_csv_not_found"
                return JSONResponse([], headers=hdr_base)
        except (AttributeError, TypeError):
            hdr_base["X-Empty-Reason"] = "live_csv_not_found"
            return JSONResponse([], headers=hdr_base)

        # Build realized map from live CSV (robust TP extraction + optional bucketing)
        rows_live = load_csv_rows_full(p_live)
        realized, ts_sorted = build_realized_map_and_times(
            rows_live,
            bucket_ms=int(bucket_ms),
            tp_getter=extract_tp,
            non_negative=True,
        )
        if not realized or not ts_sorted:
            hdr_base["X-Empty-Reason"] = "no_realized_map"
            return JSONResponse([], headers=hdr_base)
        now_ms = int(ts_sorted[-1])

        # Load bands archive rows for the day (only entries for the selected horizon)
        arch_dir = project_root() / "data" / "ml" / "path_forecasts" / idx
        day_str = the_date.strftime("%Y-%m-%d")
        arch_file_bands = arch_dir / f"{day_str}_bands.csv"
        if not arch_file_bands.exists():
            hdr_base["X-Empty-Reason"] = "bands_archive_missing"
            return JSONResponse([], headers=hdr_base)

        tol = max(1, int(bucket_ms) // 2)

        # Read bands into memory (filtered by horizon)
        band_rows: list[tuple[int, int, float, float]] = []  # (gen_ms, tgt_ms, q10, q90)
        for gen_ms, tgt_ms, _hmin, qvals, _band_scale in iter_bands_quantile_rows(
            arch_file_bands,
            quantiles=[10, 90],
            horizon_min=int(horizon),
        ):
            q10v = qvals.get(10)
            q90v = qvals.get(90)
            if q10v is None or q90v is None:
                continue
            band_rows.append((gen_ms, tgt_ms, float(q10v), float(q90v)))

        if not band_rows:
            hdr_base["X-Empty-Reason"] = "no_band_rows"
            return JSONResponse([], headers=hdr_base)

        # Calibration history for historical band_scale/target if available
        hist_dir = project_root() / "data" / "ml" / "path_forecasts" / "_calibration_history"
        p_hist = hist_dir / f"{idx}.csv"
        hist_ts: list[int] = []
        hist_vals: list[tuple[object, object]] = []  # (band_scale, target)
        if p_hist.exists():
            with p_hist.open("r", encoding="utf-8", newline="") as f:
                rd = csv.DictReader(f)
                for row in rd:
                    try:
                        t = int(row.get("ts_ms") or "0")
                    except (TypeError, ValueError):
                        continue
                    try:
                        bs = float(f"{row.get('band_scale')}") if row.get("band_scale") not in (None, "") else None
                    except (TypeError, ValueError):
                        bs = None
                    try:
                        tgt = float(f"{row.get('target')}") if row.get("target") not in (None, "") else None
                    except (TypeError, ValueError):
                        tgt = None
                    if t:
                        hist_ts.append(t)
                        hist_vals.append((bs, tgt))

        # fallback current cal snapshot
        cal = load_calibration(idx)
        cur_band_scale = float(cal.get("band_scale", 1.0)) if isinstance(cal.get("band_scale"), (int, float)) else None
        cur_target = float(cal.get("target", 0.8)) if isinstance(cal.get("target"), (int, float)) else 0.8

        # Prepare snapshots
        window_ms = int(window_minutes) * 60_000
        history_ms = int(history_minutes) * 60_000
        step_ms = int(step_minutes) * 60_000
        start_ms = max(0, now_ms - history_ms)

        # Compute number of points, respect cap
        total_steps = int((now_ms - start_ms) // max(1, step_ms)) + 1
        if total_steps > int(max_points):
            # increase step to reduce points within cap
            factor = (total_steps + max_points - 1) // max_points
            step_ms *= max(1, factor)
            total_steps = int((now_ms - start_ms) // max(1, step_ms)) + 1

        out: list[dict[str, object]] = []
        for i in range(total_steps):
            t = start_ms + i * step_ms
            if t > now_ms:
                break
            cutoff_gen = t - window_ms
            total = 0
            cover = 0

            # iterate band rows and evaluate coverage using NN align to realized at tgt_ms
            for gen_ms, tgt_ms, q10v, q90v in band_rows:
                if gen_ms < cutoff_gen or tgt_ms > t:
                    continue

                # NN align
                best_r = nearest_time_key(ts_sorted, tgt_ms, tol)
                if best_r is None:
                    continue
                rv = realized.get(best_r)
                if rv is None:
                    continue
                total += 1
                if q10v <= rv <= q90v:
                    cover += 1

            cov = (cover / float(total)) if total > 0 else None

            # Historical calibration values at time t if available
            bs = cur_band_scale
            tgt = cur_target
            if hist_ts:
                k = bisect.bisect_right(hist_ts, t) - 1
                if k >= 0:
                    bs_k, tgt_k = hist_vals[k]
                    if isinstance(bs_k, (int, float)):
                        bs = float(bs_k)
                    if isinstance(tgt_k, (int, float)):
                        tgt = float(tgt_k)

            try:
                gap_abs = (
                    abs(float(cov) - float(tgt))
                    if (cov is not None and isinstance(tgt, (int, float)))
                    else None
                )
            except (TypeError, ValueError):
                gap_abs = None

            out.append(
                {
                    "ts_ms": int(t),
                    "ts_iso": datetime.fromtimestamp(int(t) / 1000.0, tz=timezone.utc).isoformat(),
                    "coverage": cov,
                    "target": tgt,
                    "gap_abs": gap_abs,
                    "samples": int(total),
                    "band_scale": bs,
                }
            )

        # Remove trailing points with no samples to keep chart tidy
        while out and (out[-1].get("samples") == 0):
            out.pop()

        return JSONResponse(out)

    except BaseException as e:
        import asyncio
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))
