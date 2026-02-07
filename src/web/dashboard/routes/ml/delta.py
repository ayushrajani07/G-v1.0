from __future__ import annotations

import asyncio
import datetime as _dt

from fastapi import HTTPException, Query
from fastapi.responses import PlainTextResponse

from ...core.csv_io import (
    load_csv_rows_full as _load_csv_rows_full,
    parse_time_epoch_ms as _parse_time_epoch_ms,
)
from .._index_norm import normalize_index
from ._common import project_root as _project_root, resolve_live_csv_path as _resolve_live_csv_path
from .._tabular_file import read_header_and_rows


async def api_ml_delta(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
    horizon: str = Query("1", description="Horizon label to select (string)"),
    model: str = Query("sk_hgb_regressor", description="Model name to select"),
    expiry_tag: str = Query("this_month", description="Expiry tag for live_csv lookup"),
    offset: str = Query("0", description="Offset for live_csv lookup"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000, description="Bucket size for time alignment in ms"),
    tail: int = Query(1200, ge=1, le=20000, description="Return last N buckets"),
):  # PlainTextResponse returned explicitly
    """Return CSV with time-aligned ΔTP = prediction - tp.

    This aligns predictions to live_csv by rounding timestamps down to the nearest
    bucket (default 1 minute), then joins on bucket time.

    Output columns: time,delta,model,index,horizon
    """
    try:
        idx_norm = normalize_index(index)

        base = _project_root() / "data" / "ml" / "live_predictions"
        pred_fp = base / f"{idx_norm}.csv"
        if not pred_fp.exists():
            raise HTTPException(status_code=404, detail=f"predictions file not found: {pred_fp}")
        header, rows = read_header_and_rows(pred_fp)
        if not header:
            return PlainTextResponse("", media_type="text/csv")
        cols = header.split(",")
        try:
            ts_idx = cols.index("timestamp")
            pred_idx = cols.index("prediction")
            mdl_idx = cols.index("model")
            hor_idx = cols.index("horizon")
        except ValueError:
            raise HTTPException(status_code=500, detail="malformed predictions CSV header")

        pred_by_bucket: dict[int, float] = {}
        for r in rows[-max(tail * 2, 100) :]:
            parts = r.split(",")
            if len(parts) <= max(ts_idx, pred_idx, mdl_idx, hor_idx):
                continue
            if parts[mdl_idx] != model or parts[hor_idx] != str(horizon):
                continue
            ems = _parse_time_epoch_ms(parts[ts_idx])
            if ems is None:
                continue
            bucket = (ems // bucket_ms) * bucket_ms
            try:
                pred_val = float(parts[pred_idx])
            except (TypeError, ValueError, IndexError):
                continue
            pred_by_bucket[bucket] = pred_val

        if not pred_by_bucket:
            return PlainTextResponse("time,delta,model,index,horizon\n", media_type="text/csv")

        from datetime import date

        p = _resolve_live_csv_path(idx_norm, expiry_tag, offset, date.today())
        if not p or not p.exists():
            raise HTTPException(status_code=404, detail="live_csv file not found")
        live_rows = _load_csv_rows_full(p)
        tp_by_bucket: dict[int, float] = {}
        for row in live_rows[-max(tail * 2, 100) :]:
            try:
                ems = int(row.get("ts") or row.get("time") or 0)
            except (TypeError, ValueError):
                continue
            if not ems:
                continue
            bucket = (ems // bucket_ms) * bucket_ms
            tp = row.get("tp")
            if isinstance(tp, (int, float)):
                tp_by_bucket[bucket] = float(tp)

        keys = sorted(set(pred_by_bucket.keys()) & set(tp_by_bucket.keys()))
        if tail and len(keys) > tail:
            keys = keys[-tail:]
        out = ["time,delta,model,index,horizon"]
        for k in keys:
            delta = pred_by_bucket[k] - tp_by_bucket[k]
            iso = _dt.datetime.fromtimestamp(k / 1000).replace(microsecond=0).isoformat()
            out.append(f"{iso},{delta},{model},{idx_norm},{horizon}")
        return PlainTextResponse("\n".join(out), media_type="text/csv")

    except HTTPException:
        raise
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))
