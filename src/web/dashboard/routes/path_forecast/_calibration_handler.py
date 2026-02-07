from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from .._index_norm import normalize_index
from .._date_norm import resolve_date
from .._now_norm import build_realized_map_and_times, nearest_time_key, now_and_cutoff

from ._bands_archive import detect_quantile_columns, parse_float, parse_int
from ._archive_paths import bands_archive_path, calibration_history_dir


def _compute_calibration_suggestion(
    *,
    idx: str,
    horizon: int,
    window_minutes: int,
    target: float,
    expiry_tag: str,
    offset: str,
    bucket_ms: int,
    the_date,  # datetime.date
    project_root: Callable[[], object],
    find_live_csv: Callable[..., object],
    load_csv_rows_full: Callable[[object], list[dict]],
    load_calibration: Callable[[str], dict],
) -> dict:
    import csv

    # Load realized from live_csv
    base = project_root() / "data" / "g6_data"
    p_live = find_live_csv(base, idx, expiry_tag, offset, the_date)
    try:
        if (not p_live) or (not getattr(p_live, "exists")()):
            raise HTTPException(status_code=404, detail="live_csv not found for date")
    except HTTPException:
        raise
    except (AttributeError, TypeError):
        raise HTTPException(status_code=404, detail="live_csv not found for date")

    rows = load_csv_rows_full(p_live)
    if not rows:
        raise HTTPException(status_code=503, detail="no live rows")

    realized, ts_sorted = build_realized_map_and_times(
        rows,
        bucket_ms=None,
        tp_getter=lambda r: r.get("tp"),
    )

    if not realized:
        raise HTTPException(status_code=503, detail="no realized map")

    now_ms, _cutoff_ignored = now_and_cutoff(ts_sorted, window_minutes)
    if now_ms is None:
        raise HTTPException(status_code=503, detail="no realized timestamps")

    # Load bands archive (today)
    arch_file_bands = bands_archive_path(project_root=project_root, index=idx, d=the_date)
    if not arch_file_bands.exists():
        raise HTTPException(status_code=404, detail="no bands archive for date")

    tol = max(1, int(bucket_ms) // 2)
    cutoff_gen = now_ms - int(window_minutes) * 60_000
    total = cover = 0
    bw_sum = 0.0

    # current calibration snapshot (for prev)
    cal = load_calibration(idx)
    prev_scale = float(cal.get("band_scale", 1.0)) if isinstance(cal.get("band_scale"), (int, float)) else 1.0

    with arch_file_bands.open("r", encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        qcols = detect_quantile_columns(rd.fieldnames)
        q10_name = qcols.get(10)
        q90_name = qcols.get(90)

        for row in rd:
            gen_ms = parse_int(row, "gen_ms") or 0
            tgt_ms = parse_int(row, "target_ms") or 0
            hmin = parse_int(row, "horizon_min") or 0
            if not gen_ms or not tgt_ms or hmin != int(horizon):
                continue
            if gen_ms < cutoff_gen or tgt_ms > now_ms:
                continue
            if not q10_name or not q90_name:
                continue
            q10v = parse_float(row, q10_name)
            q90v = parse_float(row, q90_name)
            if q10v is None or q90v is None:
                continue

            # nearest realized alignment
            best_r = nearest_time_key(ts_sorted, tgt_ms, tol)
            if best_r is None:
                continue
            rv = realized.get(best_r)
            if rv is None:
                continue
            total += 1
            if q10v <= rv <= q90v:
                cover += 1
            bw_sum += q90v - q10v

    actual = (cover / float(total)) if total > 0 else None
    if actual is None:
        raise HTTPException(status_code=404, detail="no coverage samples in window")

    # heuristic update rule: scale *= (target/actual) ** 0.5, clamped
    try:
        ratio = float(target) / max(1e-9, float(actual))
    except (TypeError, ValueError, ZeroDivisionError):
        ratio = 1.0
    new_scale = prev_scale * (ratio**0.5)
    new_scale = max(0.5, min(5.0, float(new_scale)))

    return {
        "index": idx,
        "horizon": int(horizon),
        "window_minutes": int(window_minutes),
        "band_scale": float(new_scale),
        "prev": float(prev_scale),
        "target": float(target),
        "actual": float(actual),
        "samples": int(total),
    }


async def handle_path_calibrate_now(
    *,
    index: str,
    horizon: int,
    window_minutes: int,
    target: float,
    expiry_tag: str,
    offset: str,
    bucket_ms: int,
    date_str: Optional[str],
    # injected deps
    project_root: Callable[[], object],
    find_live_csv: Callable[..., object],
    load_csv_rows_full: Callable[[object], list[dict]],
    load_calibration: Callable[[str], dict],
) -> JSONResponse:
    """Implementation of /api/ml/path_calibrate_now extracted from router."""

    idx = normalize_index(index)
    the_date = resolve_date(date_str)

    data = _compute_calibration_suggestion(
        idx=idx,
        horizon=horizon,
        window_minutes=window_minutes,
        target=target,
        expiry_tag=expiry_tag,
        offset=offset,
        bucket_ms=bucket_ms,
        the_date=the_date,
        project_root=project_root,
        find_live_csv=find_live_csv,
        load_csv_rows_full=load_csv_rows_full,
        load_calibration=load_calibration,
    )
    return JSONResponse(data)


async def handle_path_calibrate(
    *,
    index: str,
    horizon: int,
    window_minutes: int,
    target: float,
    expiry_tag: str,
    offset: str,
    bucket_ms: int,
    date_str: Optional[str],
    # injected deps
    project_root: Callable[[], object],
    find_live_csv: Callable[..., object],
    load_csv_rows_full: Callable[[object], list[dict]],
    load_calibration: Callable[[str], dict],
    save_calibration: Callable[..., None],
) -> JSONResponse:
    """Implementation of /api/ml/path_calibrate extracted from router."""

    idx = normalize_index(index)
    the_date = resolve_date(date_str)

    data = _compute_calibration_suggestion(
        idx=idx,
        horizon=horizon,
        window_minutes=window_minutes,
        target=target,
        expiry_tag=expiry_tag,
        offset=offset,
        bucket_ms=bucket_ms,
        the_date=the_date,
        project_root=project_root,
        find_live_csv=find_live_csv,
        load_csv_rows_full=load_csv_rows_full,
        load_calibration=load_calibration,
    )

    band_scale = data.get("band_scale")
    prev = data.get("prev", 1.0)
    actual = data.get("actual")
    samples = data.get("samples", 0)

    if not isinstance(band_scale, (int, float)):
        # Shouldn't happen, but mirror old defensive behavior.
        return JSONResponse(data)

    save_calibration(
        index,
        band_scale=float(band_scale),
        prev=float(prev) if isinstance(prev, (int, float)) else 1.0,
        target=float(target),
        actual=(float(actual) if isinstance(actual, (int, float)) else None),
        samples=int(samples) if isinstance(samples, (int, float)) else 0,
    )

    return JSONResponse(data)


async def handle_path_calibration_history(
    *,
    index: str,
    limit: int,
    # injected deps
    project_root: Callable[[], object],
) -> JSONResponse:
    """Implementation of /api/ml/path_calibration_history extracted from router."""

    idx = normalize_index(index)
    hdr_base = base_headers(route_version="calhist-v1", index=idx, date=None)
    hist_dir = calibration_history_dir(project_root=project_root)
    p_hist = hist_dir / f"{idx}.csv"
    if not p_hist.exists():
        try:
            hdr_base["X-Empty-Reason"] = "calibration_history_missing"
        except (TypeError, ValueError):
            pass
        return JSONResponse([], status_code=200, headers=hdr_base)

    import csv

    def _to_float(v):
        try:
            return float(f"{v}")
        except (TypeError, ValueError):
            return None

    def _to_int(v):
        try:
            return int(float(f"{v}"))
        except (TypeError, ValueError):
            return None

    rows: list[dict[str, object]] = []
    with p_hist.open("r", encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        for row in rd:
            try:
                ts_ms = int(row.get("ts_ms") or "0")
            except (TypeError, ValueError):
                ts_ms = 0

            _band_scale = _to_float(row.get("band_scale"))
            _target = _to_float(row.get("target"))
            _actual = _to_float(row.get("actual"))

            try:
                _gap_abs = (
                    abs(float(_actual) - float(_target))
                    if (_actual is not None and _target is not None)
                    else None
                )
            except (TypeError, ValueError):
                _gap_abs = None

            rows.append(
                {
                    "ts_ms": ts_ms,
                    "ts_iso": row.get("ts_iso"),
                    "band_scale": _band_scale,
                    "target": _target,
                    "actual": _actual,
                    "samples": _to_int(row.get("samples")),
                    "gap_abs": _gap_abs,
                }
            )

    rows.sort(key=lambda x: x.get("ts_ms") or 0, reverse=True)
    return JSONResponse(rows[: int(limit)], headers=hdr_base)
