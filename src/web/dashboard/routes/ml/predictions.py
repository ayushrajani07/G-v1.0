from __future__ import annotations

import asyncio
import datetime as _dt
import logging
from typing import Optional

from fastapi import HTTPException, Query
from fastapi.responses import PlainTextResponse

from src.utils.timeutils import utc_now_z as _utc_now_z

from ...core.csv_io import (
    load_csv_rows_full as _load_csv_rows_full,
    parse_time_epoch_ms as _parse_time_epoch_ms,
)
from .._csv_time_columns import rebuild_time_time_ms_from_timestamp
from .._index_norm import normalize_index
from ._common import project_root as _project_root, resolve_live_csv_path as _resolve_live_csv_path
from .._tabular_file import read_header_and_rows, tail_rows

logger = logging.getLogger(__name__)
async def api_ml_predictions(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
    horizon: Optional[str] = Query(None, description="Filter by horizon label (string) if present in CSV"),
    model: Optional[str] = Query(None, description="Filter by model name"),
    tail: int = Query(600, ge=1, le=20000, description="Return last N rows for small payloads"),
    # Optional: compute and include conformal bands inline (requires model & horizon)
    include_bands: bool = Query(False, description="If true, include conformal bands computed over a recent window"),
    coverage: float = Query(0.8, ge=0.5, le=0.99, description="Target coverage for conformal bands (e.g., 0.8)"),
    window_minutes: int = Query(120, ge=5, le=24 * 60, description="Lookback window for band calibration (minutes)"),
    expiry_tag: str = Query("this_week", description="Expiry tag for live_csv lookup when bands are requested"),
    offset: str = Query("0", description="Offset for live_csv lookup when bands are requested"),
    bucket_ms: int = Query(
        60_000,
        ge=1_000,
        le=3_600_000,
        description="Bucket size for time alignment in ms when bands are requested",
    ),
):  # PlainTextResponse returned explicitly
    """Serve live prediction CSV for Grafana Infinity.

    Expects file at data/ml/live_predictions/<INDEX>.csv with header:
      timestamp,prediction,model,index,horizon

    Optional filters: horizon, model. Use tail to limit payload.
    """
    idx_norm = normalize_index(index)

    base = _project_root() / "data" / "ml" / "live_predictions"
    fp = base / f"{idx_norm}.csv"
    if not fp.exists():
        raise HTTPException(status_code=404, detail=f"predictions file not found: {fp}")

    try:
        header, rows = read_header_and_rows(fp)
        if not header:
            return PlainTextResponse("", media_type="text/csv")
        rows = tail_rows(rows, tail)
        header, rows = rebuild_time_time_ms_from_timestamp(header, rows)
        cols = header.split(",")

        if horizon or model:
            out = [header]
            try:
                idx_model = cols.index("model")
                idx_hor = cols.index("horizon")
            except ValueError:
                out.extend(rows)
                return PlainTextResponse("\n".join(out), media_type="text/csv")

            band_radius: Optional[float] = None
            if include_bands:
                if not model or not horizon:
                    for r in rows:
                        parts = r.split(",")
                        if len(parts) < max(idx_model, idx_hor) + 1:
                            continue
                        if model and parts[idx_model] != model:
                            continue
                        if horizon and parts[idx_hor] != str(horizon):
                            continue
                        out.append(r)
                    return PlainTextResponse("\n".join(out), media_type="text/csv")

                try:
                    ts_idx = cols.index("timestamp")
                    pred_idx = cols.index("prediction")
                except ValueError:
                    ts_idx = -1
                    pred_idx = -1

                now_ms = int(_dt.datetime.now(tz=_dt.timezone.utc).timestamp() * 1000)
                cutoff_ms = now_ms - window_minutes * 60_000
                pred_by_bucket: dict[int, float] = {}
                for r in rows[-max(tail * 2, 100) :]:
                    parts = r.split(",")
                    if len(parts) <= max(ts_idx, pred_idx, idx_model, idx_hor):
                        continue
                    if parts[idx_model] != model or parts[idx_hor] != str(horizon):
                        continue
                    ems = _parse_time_epoch_ms(parts[ts_idx]) if ts_idx >= 0 else None
                    if ems is None or ems < cutoff_ms:
                        continue
                    bucket = (ems // bucket_ms) * bucket_ms
                    try:
                        pv = float(parts[pred_idx]) if pred_idx >= 0 else None
                    except (TypeError, ValueError):
                        pv = None
                    if pv is None:
                        continue
                    pred_by_bucket[bucket] = pv

                tp_by_bucket: dict[int, float] = {}
                from datetime import date as _date

                try:
                    p = _resolve_live_csv_path(idx_norm, expiry_tag, offset, _date.today())
                except (OSError, TypeError, ValueError):
                    p = None
                if p and p.exists():
                    live_rows = _load_csv_rows_full(p)
                    for row in live_rows:
                        try:
                            ems = int(row.get("ts") or row.get("time") or 0)
                        except (TypeError, ValueError):
                            continue
                        if not ems or ems < cutoff_ms:
                            continue
                        bucket = (ems // bucket_ms) * bucket_ms
                        tp = row.get("tp")
                        if isinstance(tp, (int, float)):
                            tp_by_bucket[bucket] = float(tp)

                keys = sorted(set(pred_by_bucket.keys()) & set(tp_by_bucket.keys()))
                if keys:
                    abs_res = [abs(pred_by_bucket[k] - tp_by_bucket[k]) for k in keys]
                    s = sorted(abs_res)
                    q = min(max(coverage, 0.5), 0.99)
                    kf = (len(s) - 1) * q
                    fi = int(kf)
                    ci = min(fi + 1, len(s) - 1)
                    band_radius = s[fi] if fi == ci else (s[fi] + (s[ci] - s[fi]) * (kf - fi))

            add_bands = include_bands and band_radius is not None
            if add_bands:
                if "band_low" not in cols or "band_high" not in cols:
                    header = ",".join([*cols, "band_low", "band_high"])
                out = [header]

            try:
                pred_col_idx = cols.index("prediction")
            except ValueError:
                pred_col_idx = -1

            for r in rows:
                parts = r.split(",")
                if len(parts) < max(idx_model, idx_hor) + 1:
                    continue
                if model and parts[idx_model] != model:
                    continue
                if horizon and parts[idx_hor] != str(horizon):
                    continue
                if add_bands:
                    try:
                        pred_val = float(parts[pred_col_idx]) if pred_col_idx >= 0 else None
                    except (TypeError, ValueError, IndexError):
                        pred_val = None
                    if pred_val is not None:
                        br = float(band_radius)  # type: ignore[arg-type]
                        out.append(r + f",{pred_val - br:.6f},{pred_val + br:.6f}")
                    else:
                        out.append(r + ",,")
                else:
                    out.append(r)
            return PlainTextResponse("\n".join(out), media_type="text/csv")

        # No filters; if bands requested, require model & horizon to avoid ambiguity
        return PlainTextResponse("\n".join([header, *rows]), media_type="text/csv")

    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))
