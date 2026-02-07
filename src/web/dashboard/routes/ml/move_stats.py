from __future__ import annotations

import asyncio
import datetime as _dt
from typing import Optional

from fastapi import HTTPException, Query
from fastapi.responses import PlainTextResponse

from ...core.csv_io import parse_time_epoch_ms as _parse_time_epoch_ms
from .._index_norm import normalize_index
from ._common import project_root as _project_root
from .._tabular_file import read_header_and_rows

# Exception hygiene buckets (mirrors legacy module style).
_NON_FATAL_HTTP_ERRORS = (OSError, IOError, ValueError, TypeError, KeyError, IndexError, AttributeError, RuntimeError)
_NON_FATAL_PARSE_ERRORS = (ValueError, TypeError, IndexError)


async def api_ml_move_stats(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
    horizon: str = Query("1", description="Horizon label to select (string)"),
    window_minutes: int = Query(180, ge=5, le=24 * 60, description="Lookback window in minutes"),
    prob_threshold: float = Query(0.6, ge=0.0, le=1.0, description="Threshold to consider a 'high probability' move"),
    tail: int = Query(5000, ge=10, le=200000, description="Max rows to read from tail of file for efficiency"),
) -> PlainTextResponse:
    """Summarize move signal stream over a recent window."""
    try:
        idx_norm = normalize_index(index)

        base = _project_root() / "data" / "ml" / "live_predictions"
        fp = base / f"{idx_norm}_move.csv"
        if not fp.exists():
            raise HTTPException(status_code=404, detail=f"move file not found: {fp}")

        header_line, data_lines = read_header_and_rows(fp)
        if not header_line:
            return PlainTextResponse(
                "index,horizon,count,avg_probability,high_prob_share,mag_p10,mag_p50,mag_p90,last_prob,last_mag,window_minutes\n",
                media_type="text/csv",
            )

        header = header_line.split(",")
        try:
            ts_idx = header.index("timestamp")
            prob_idx = header.index("move_prob")
            lbl_idx = header.index("move_label_pred")
            mag_idx = header.index("conditional_magnitude")
            hor_idx = header.index("horizon")
        except ValueError:
            raise HTTPException(status_code=500, detail="malformed move CSV header")

        now_ms = int(_dt.datetime.now(tz=_dt.timezone.utc).timestamp() * 1000)
        cutoff_ms = now_ms - window_minutes * 60_000

        probs: list[float] = []
        mags_on_pred: list[float] = []
        last_prob: Optional[float] = None
        last_mag: Optional[float] = None
        hi_count = 0
        total = 0

        for r in data_lines[-tail:]:
            parts = r.split(",")
            if len(parts) <= max(ts_idx, prob_idx, lbl_idx, mag_idx, hor_idx):
                continue
            if parts[hor_idx] != str(horizon):
                continue
            ems = _parse_time_epoch_ms(parts[ts_idx])
            if ems is None or ems < cutoff_ms:
                continue
            try:
                p = float(parts[prob_idx])
            except _NON_FATAL_PARSE_ERRORS:
                p = None  # type: ignore
            try:
                lbl = int(parts[lbl_idx])
            except _NON_FATAL_PARSE_ERRORS:
                lbl = 0
            try:
                mag = float(parts[mag_idx])
            except _NON_FATAL_PARSE_ERRORS:
                mag = None  # type: ignore

            total += 1
            if isinstance(p, (int, float)):
                probs.append(float(p))
                if p >= prob_threshold:
                    hi_count += 1
                last_prob = float(p)
            if lbl == 1 and isinstance(mag, (int, float)):
                mags_on_pred.append(float(mag))
                last_mag = float(mag)

        def _pct(vals: list[float], q: float) -> float:
            if not vals:
                return float("nan")
            s = sorted(vals)
            k = (len(s) - 1) * q
            f = int(k)
            c = min(f + 1, len(s) - 1)
            if f == c:
                return s[f]
            return s[f] + (s[c] - s[f]) * (k - f)

        count = len(probs)
        avg_prob = (sum(probs) / count) if count else float("nan")
        hi_share = (hi_count / total) if total else float("nan")
        p10 = _pct(mags_on_pred, 0.10)
        p50 = _pct(mags_on_pred, 0.50)
        p90 = _pct(mags_on_pred, 0.90)

        row = [
            idx_norm,
            str(horizon),
            str(count),
            (f"{avg_prob:.4f}" if count else ""),
            (f"{hi_share:.4f}" if total else ""),
            (f"{p10:.4f}" if mags_on_pred else ""),
            (f"{p50:.4f}" if mags_on_pred else ""),
            (f"{p90:.4f}" if mags_on_pred else ""),
            (f"{last_prob:.4f}" if isinstance(last_prob, (int, float)) else ""),
            (f"{last_mag:.4f}" if isinstance(last_mag, (int, float)) else ""),
            str(window_minutes),
        ]

        out = [
            "index,horizon,count,avg_probability,high_prob_share,mag_p10,mag_p50,mag_p90,last_prob,last_mag,window_minutes",
            ",".join(row),
        ]
        return PlainTextResponse("\n".join(out), media_type="text/csv")

    except asyncio.CancelledError:
        raise
    except HTTPException:
        raise
    except _NON_FATAL_HTTP_ERRORS as e:
        raise HTTPException(status_code=500, detail=str(e))


async def api_ml_move_stats_archive(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
    horizon: str = Query("1", description="Horizon label to select (string)"),
    days: int = Query(3, ge=1, le=30, description="Number of past days to include"),
    tail: int = Query(5000, ge=10, le=200000, description="Max rows per daily file"),
) -> PlainTextResponse:
    """Return concatenated historical move stats rows from snapshot CSVs."""
    try:
        idx_norm = normalize_index(index)
        base = _project_root() / "data" / "ml" / "live_predictions" / "snapshots"
        if not base.exists():
            raise HTTPException(status_code=404, detail="snapshot directory not found")

        import datetime as _d

        out_rows: list[str] = []
        header = "timestamp,move_prob,move_label_pred,conditional_magnitude,model,index,horizon"
        today = _d.date.today()
        for i in range(days):
            d = today - _d.timedelta(days=i)
            fp = base / f"{idx_norm}_move_{d.isoformat()}.csv"
            if not fp.exists():
                continue
            try:
                header_line, data_lines = read_header_and_rows(fp)
            except _NON_FATAL_HTTP_ERRORS:
                continue
            if not header_line:
                continue
            if tail and len(data_lines) > tail:
                data_lines = data_lines[-tail:]
            hcols = header_line.split(",")
            try:
                hor_idx = hcols.index("horizon")
            except ValueError:
                hor_idx = -1
            for r in data_lines:
                parts = r.split(",")
                if hor_idx >= 0 and len(parts) > hor_idx and parts[hor_idx] != str(horizon):
                    continue
                out_rows.append(r)

        out_rows.sort()
        return PlainTextResponse("\n".join([header, *out_rows]), media_type="text/csv")

    except asyncio.CancelledError:
        raise
    except HTTPException:
        raise
    except _NON_FATAL_HTTP_ERRORS as e:
        raise HTTPException(status_code=500, detail=str(e))
