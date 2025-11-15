from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path
import os
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Body, Request
from pydantic import BaseModel
from fastapi.responses import PlainTextResponse
from src.utils.timeutils import utc_now_z as _utc_now_z
from ..core.csv_io import find_live_csv as _find_live_csv, load_csv_rows_full as _load_csv_rows_full
import datetime as _dt

from ..core import paths as _paths

logger = logging.getLogger(__name__)

# Optional centralized error handler (guarded import)
try:  # pragma: no cover
    from src.error_handling import get_error_handler as _get_eh, ErrorCategory as _ErrCat, ErrorSeverity as _ErrSev  # type: ignore
except Exception:  # pragma: no cover
    _get_eh = None  # type: ignore
    class _ErrCat:  # type: ignore
        FILE_IO = "file_io"
        UNKNOWN = "unknown"
    class _ErrSev:  # type: ignore
        LOW = "low"

def _project_root() -> Path:
    """Dynamic project root resolution respecting test monkeypatches.

    Order:
    - G6_PROJECT_ROOT env override if set
    - Delegate to core.paths.project_root (module attribute, so monkeypatching
      paths.project_root in tests affects this wrapper)
    - Fallback to current working directory if it contains a 'data' directory
      (useful for isolated tmp test setups)
    """
    try:
        env_root = os.environ.get("G6_PROJECT_ROOT", "").strip()
        if env_root:
            p = Path(env_root)
            if p.exists():
                return p
    except Exception:
        pass
    try:
        # If tests monkeypatch _paths.project_root, we pick it up here
        return _paths.project_root()
    except Exception:
        cwd = Path.cwd()
        if (cwd / "data").exists():
            return cwd
        return cwd  # last resort

router = APIRouter()
def _resolve_live_csv_path(idx_norm: str, expiry_tag: str, offset: str, day: _dt.date) -> Path | None:
    base = _project_root() / "data" / "g6_data"
    p = None
    try:
        p = _find_live_csv(base, idx_norm, expiry_tag, offset, day)
    except Exception:
        p = None
    if p and p.exists():
        return p
    # Flat fallback used in tests: data/g6_data/<INDEX>_<expiry_tag>_<offset>.csv
    try:
        flat = base / f"{idx_norm}_{expiry_tag}_{offset}.csv"
        if flat.exists():
            return flat
        # Also try +N form for positive numeric offsets
        if offset and offset.isdigit():
            flat2 = base / f"{idx_norm}_{expiry_tag}_+{offset}.csv"
            if flat2.exists():
                return flat2
    except Exception:
        pass
    return None



@router.get("/api/ml/predictions", response_model=None)
async def api_ml_predictions(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
    horizon: Optional[str] = Query(None, description="Filter by horizon label (string) if present in CSV"),
    model: Optional[str] = Query(None, description="Filter by model name"),
    tail: int = Query(600, ge=1, le=20000, description="Return last N rows for small payloads"),
    # Optional: compute and include conformal bands inline (requires model & horizon)
    include_bands: bool = Query(False, description="If true, include conformal bands computed over a recent window"),
    coverage: float = Query(0.8, ge=0.5, le=0.99, description="Target coverage for conformal bands (e.g., 0.8)"),
    window_minutes: int = Query(120, ge=5, le=24*60, description="Lookback window for band calibration (minutes)"),
    expiry_tag: str = Query("this_week", description="Expiry tag for live_csv lookup when bands are requested"),
    offset: str = Query("0", description="Offset for live_csv lookup when bands are requested"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000, description="Bucket size for time alignment in ms when bands are requested"),
):  # PlainTextResponse returned explicitly
    """
    Serve live prediction CSV for Grafana Infinity.

    Expects file at data/ml/live_predictions/<INDEX>.csv with header:
      timestamp,prediction,model,index,horizon

    Optional filters: horizon, model. Use tail to limit payload.
    """
    # Be forgiving if a placeholder like ${index} is accidentally passed from copy/paste
    idx_norm = (index or "NIFTY").strip().upper()
    if any(ch in idx_norm for ch in ("$", "{", "}")):
        idx_norm = "NIFTY"

    base = _project_root() / "data" / "ml" / "live_predictions"
    fp = base / f"{idx_norm}.csv"
    if not fp.exists():
        raise HTTPException(status_code=404, detail=f"predictions file not found: {fp}")

    # Read lines efficiently; tail last N
    try:
        # Simple approach: read all and slice; acceptable for small files
        lines = fp.read_text(encoding="utf-8").splitlines()
        if not lines:
            return PlainTextResponse("", media_type="text/csv")
        header = lines[0]
        rows = lines[1:]
        if tail and len(rows) > tail:
            rows = rows[-tail:]
        # Prefer a correct 'time' column derived from 'timestamp' when available.
        # Some writers have been seen to emit a malformed 'time' (e.g., epoch seconds * 100),
        # so if a 'timestamp' exists we rebuild 'time' from it and place it as the first column.
        cols = header.split(",")
        has_time = "time" in cols
        has_ts = "timestamp" in cols
        if has_ts:
            created_time = False
            # First try with pandas for broad format support
            try:
                import pandas as pd  # type: ignore
                # Place 'time' first and drop any existing 'time' to avoid duplicates
                cols_wo_time = [c for c in cols if c != "time"]
                # emit both ISO time and epoch ms for robustness
                new_cols = ["time", "time_ms"] + cols_wo_time
                out_lines = [",".join(new_cols)]
                ts_idx = cols.index("timestamp")
                for r in rows:
                    parts = r.split(",")
                    if len(parts) <= ts_idx:
                        continue
                    ts = pd.to_datetime(parts[ts_idx], errors="coerce", dayfirst=True)
                    if pd.isna(ts):
                        continue
                    epoch_ms = int(ts.value // 1_000_000)
                    # ISO string without microseconds for Grafana friendliness
                    try:
                        iso_str = ts.to_pydatetime().replace(microsecond=0).isoformat()
                    except Exception:
                        iso_str = str(ts)
                    # rebuild row without old 'time' if it existed
                    if has_time:
                        # remove the original 'time' column value by constructing via selected columns
                        # map column name -> value
                        mapping = {name: parts[i] if i < len(parts) else "" for i, name in enumerate(cols)}
                        reordered = [mapping.get(name, "") for name in cols_wo_time]
                        out_lines.append(",".join([iso_str, str(epoch_ms), *reordered]))
                    else:
                        out_lines.append(f"{iso_str},{epoch_ms},{r}")
                header = out_lines[0]
                rows = out_lines[1:]
                cols = new_cols
                created_time = True
            except Exception:
                created_time = False
            # Fallback without pandas: try common formats
            if not created_time:
                from datetime import datetime
                import time as _time

                def _parse_epoch_ms(s: str) -> Optional[int]:
                    s = s.strip()
                    # Try ISO first
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%d-%m-%Y %H:%M:%S"):
                        try:
                            dt = datetime.strptime(s, fmt)
                            return int(dt.timestamp() * 1000)
                        except Exception:
                            continue
                    # Try integer seconds
                    try:
                        if s.isdigit():
                            # Heuristic: treat 13-digit as ms, 10-digit as s
                            if len(s) >= 13:
                                return int(s[:13])
                            return int(int(s) * 1000)
                    except Exception:
                        pass
                    return None

                ts_idx = cols.index("timestamp")
                cols_wo_time = [c for c in cols if c != "time"]
                new_cols = ["time", "time_ms"] + cols_wo_time
                out_lines = [",".join(new_cols)]
                for r in rows:
                    parts = r.split(",")
                    if len(parts) <= ts_idx:
                        continue
                    ems = _parse_epoch_ms(parts[ts_idx])
                    if ems is None:
                        continue
                    if has_time:
                        mapping = {name: parts[i] if i < len(parts) else "" for i, name in enumerate(cols)}
                        reordered = [mapping.get(name, "") for name in cols_wo_time]
                        iso = datetime.fromtimestamp(ems / 1000).replace(microsecond=0).isoformat()
                        out_lines.append(",".join([iso, str(ems), *reordered]))
                    else:
                        iso = datetime.fromtimestamp(ems / 1000).replace(microsecond=0).isoformat()
                        out_lines.append(f"{iso},{ems},{r}")
                if len(out_lines) > 1:
                    header = out_lines[0]
                    rows = out_lines[1:]
                    cols = new_cols
        # Filter if requested
        if horizon or model:
            out = [header]
            # Column positions
            try:
                idx_pred = cols.index("prediction")  # noqa: F841
                idx_model = cols.index("model")
                idx_index = cols.index("index")  # noqa: F841
                idx_hor = cols.index("horizon")
            except Exception:
                # Malformed header; return unfiltered
                out.extend(rows)
                return PlainTextResponse("\n".join(out), media_type="text/csv")

            # If bands requested, we compute a conformal radius from recent joined residuals
            band_radius: Optional[float] = None
            if include_bands:
                # Require both model and horizon for meaningful band computation
                if not model or not horizon:
                    # Return filtered rows without bands if insufficient params
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

                # Build bucketed predictions for the selected model/horizon within window
                def _to_epoch_ms(s: str) -> int | None:
                    try:
                        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M:%S"):
                            try:
                                dt = _dt.datetime.strptime(s.strip(), fmt)
                                return int(dt.timestamp() * 1000)
                            except Exception:
                                continue
                        s2 = s.strip()
                        if s2.isdigit():
                            if len(s2) >= 13:
                                return int(s2[:13])
                            return int(s2) * 1000
                    except Exception:
                        pass
                    return None

                # indexes for timestamp and prediction if present
                try:
                    ts_idx = cols.index("timestamp")
                    pred_idx = cols.index("prediction")
                except Exception:
                    ts_idx = -1
                    pred_idx = -1

                now_ms = int(_dt.datetime.now(tz=_dt.timezone.utc).timestamp() * 1000)
                cutoff_ms = now_ms - window_minutes * 60_000
                pred_by_bucket: dict[int, float] = {}
                for r in rows[-max(tail * 2, 100):]:
                    parts = r.split(",")
                    if len(parts) <= max(ts_idx, pred_idx, idx_model, idx_hor):
                        continue
                    if parts[idx_model] != model or parts[idx_hor] != str(horizon):
                        continue
                    ems = _to_epoch_ms(parts[ts_idx]) if ts_idx >= 0 else None
                    if ems is None or ems < cutoff_ms:
                        continue
                    bucket = (ems // bucket_ms) * bucket_ms
                    try:
                        pv = float(parts[pred_idx]) if pred_idx >= 0 else None
                    except Exception:
                        pv = None
                    if pv is None:
                        continue
                    pred_by_bucket[bucket] = pv

                # Load live tp for joining
                tp_by_bucket: dict[int, float] = {}
                try:
                    from datetime import date as _date
                    p = _resolve_live_csv_path(idx_norm, expiry_tag, offset, _date.today())
                except Exception:
                    p = None
                if p and p.exists():
                    live_rows = _load_csv_rows_full(p)
                    for row in live_rows:
                        try:
                            ems = int(row.get("ts") or row.get("time") or 0)
                        except Exception:
                            continue
                        if not ems or ems < cutoff_ms:
                            continue
                        bucket = (ems // bucket_ms) * bucket_ms
                        tp = row.get("tp")
                        if isinstance(tp, (int, float)):
                            tp_by_bucket[bucket] = float(tp)

                keys = sorted(set(pred_by_bucket.keys()) & set(tp_by_bucket.keys()))
                if keys:
                    # Compute absolute residuals and take desired quantile
                    abs_res = [abs(pred_by_bucket[k] - tp_by_bucket[k]) for k in keys]
                    s = sorted(abs_res)
                    q = min(max(coverage, 0.5), 0.99)
                    kf = (len(s) - 1) * q
                    fi = int(kf)
                    ci = min(fi + 1, len(s) - 1)
                    band_radius = s[fi] if fi == ci else (s[fi] + (s[ci] - s[fi]) * (kf - fi))

            # If we need to append band columns, adjust header first
            add_bands = include_bands and band_radius is not None
            if add_bands:
                if "band_low" not in cols or "band_high" not in cols:
                    header = ",".join([*cols, "band_low", "band_high"])
                out = [header]

            for r in rows:
                parts = r.split(",")
                if len(parts) < max(idx_model, idx_hor) + 1:
                    continue
                if model and parts[idx_model] != model:
                    continue
                if horizon and parts[idx_hor] != str(horizon):
                    continue
                if add_bands:
                    # Append band columns based on current prediction value
                    try:
                        pred_val = float(parts[cols.index("prediction")])
                    except Exception:
                        pred_val = None
                    if pred_val is not None:
                        br = float(band_radius)  # type: ignore[arg-type]
                        out.append(r + f",{pred_val - br:.6f},{pred_val + br:.6f}")
                    else:
                        out.append(r + ",,")
                else:
                    out.append(r)
            return PlainTextResponse("\n".join(out), media_type="text/csv")
        else:
            # No filters; if bands requested, require model & horizon to avoid ambiguity
            if include_bands:
                return PlainTextResponse("\n".join([header, *rows]), media_type="text/csv")
            return PlainTextResponse("\n".join([header, *rows]), media_type="text/csv")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/ml/ensemble")
async def api_ml_ensemble(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
    horizon: Optional[str] = Query(None, description="Filter by horizon label (string) if present in CSV"),
    tail: int = Query(600, ge=1, le=20000, description="Return last N rows for small payloads"),
    include_placeholders: bool = Query(False, description="If false, suppress rows with applied_k_source=placeholder"),
) -> PlainTextResponse:
    """Serve ensemble consensus CSV built by exporter.

    Expects file at data/ml/live_predictions/<INDEX>_ensemble.csv with header:
      timestamp,consensus,disagreement,models_count,models,index,horizon
    """
    try:
        idx_norm = (index or "NIFTY").strip().upper()
        if any(ch in idx_norm for ch in ("$", "{", "}")):
            idx_norm = "NIFTY"

        base = _project_root() / "data" / "ml" / "live_predictions"
        fp = base / f"{idx_norm}_ensemble.csv"
        if not fp.exists():
            raise HTTPException(status_code=404, detail=f"ensemble file not found: {fp}")

        lines = fp.read_text(encoding="utf-8").splitlines()
        if not lines:
            return PlainTextResponse("", media_type="text/csv")
        header = lines[0]
        rows = lines[1:]
        if tail and len(rows) > tail:
            rows = rows[-tail:]

        cols = header.split(",")
        has_time = "time" in cols
        has_ts = "timestamp" in cols
        if has_ts:
            # Rebuild time,time_ms columns like predictions endpoint for Grafana
            from datetime import datetime as _dt_dt

            def _to_epoch_ms(s: str) -> int | None:
                try:
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M:%S"):
                        try:
                            dt = _dt_dt.strptime(s.strip(), fmt)
                            return int(dt.timestamp() * 1000)
                        except Exception:
                            continue
                    s2 = s.strip()
                    if s2.isdigit():
                        if len(s2) >= 13:
                            return int(s2[:13])
                        return int(s2) * 1000
                except Exception:
                    pass
                return None

            ts_idx = cols.index("timestamp")
            cols_wo_time = [c for c in cols if c != "time"]
            new_cols = ["time", "time_ms"] + cols_wo_time
            out_lines = [",".join(new_cols)]
            for r in rows:
                parts = r.split(",")
                if len(parts) <= ts_idx:
                    continue
                ems = _to_epoch_ms(parts[ts_idx])
                if ems is None:
                    continue
                iso = _dt.datetime.fromtimestamp(ems / 1000).replace(microsecond=0).isoformat()
                if has_time:
                    mapping = {name: parts[i] if i < len(parts) else "" for i, name in enumerate(cols)}
                    reordered = [mapping.get(name, "") for name in cols_wo_time]
                    out_lines.append(",".join([iso, str(ems), *reordered]))
                else:
                    out_lines.append(f"{iso},{ems},{r}")
            header = out_lines[0]
            rows = out_lines[1:]
            cols = new_cols

        if horizon or (not include_placeholders):
            try:
                idx_hor = cols.index("horizon")
            except Exception:
                # if malformed header, just return unfiltered
                return PlainTextResponse("\n".join([header, *rows]), media_type="text/csv")
            filtered = []
            for r in rows:
                parts = r.split(",")
                if horizon and not (len(parts) > idx_hor and parts[idx_hor] == str(horizon)):
                    continue
                if not include_placeholders:
                    try:
                        src_idx = cols.index("applied_k_source") if "applied_k_source" in cols else -1
                        if src_idx >= 0 and len(parts) > src_idx and parts[src_idx] == "placeholder":
                            continue
                    except Exception:
                        pass
                filtered.append(r)
            rows = filtered

        return PlainTextResponse("\n".join([header, *rows]), media_type="text/csv")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/ml/ensemble/weights")
async def api_ml_ensemble_weights(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
    horizon: str = Query("1", description="Horizon label (the exporter is typically run per-horizon)"),
) -> PlainTextResponse:
    """Serve latest inverse-RMSE model weights from exporter sidecar as CSV.

    Source file: data/ml/live_predictions/<INDEX>_ensemble_weights.json

    Output columns: timestamp,model,weight,rmse,index,horizon
    """
    try:
        idx_norm = (index or "NIFTY").strip().upper()
        if any(ch in idx_norm for ch in ("$", "{", "}")):
            idx_norm = "NIFTY"
        base = _project_root() / "data" / "ml" / "live_predictions"
        fp = base / f"{idx_norm}_ensemble_weights.json"
        if not fp.exists():
            raise HTTPException(status_code=404, detail=f"weights sidecar not found: {fp}")
        try:
            import json as _json
            obj = _json.loads(fp.read_text(encoding="utf-8"))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"failed to parse weights JSON: {e}")
        ts = obj.get("timestamp")
        weights = obj.get("weights") or {}
        rmses = obj.get("rmse") or {}
        # Normalize weights to numeric (fallback 0.0)
        norm_weights: dict[str, float] = {}
        for k, v in weights.items():
            try:
                norm_weights[str(k)] = float(v)
            except Exception:
                norm_weights[str(k)] = 0.0
        # Build CSV
        out = ["timestamp,model,weight,rmse,index,horizon"]
        # Sort by weight desc for readability (stable tie-breaker by model name)
        keys = sorted(norm_weights.keys(), key=lambda k: (-(norm_weights.get(k) or 0.0), k))
        for m in keys:
            w = norm_weights.get(m, 0.0)
            try:
                r = float(rmses.get(m) or 0.0)
            except Exception:
                r = 0.0
            out.append(f"{ts},{m},{w:.6f},{r:.6f},{idx_norm},{horizon}")
        try:
            # Temporary debug (now via logging): CSV for inspection in tests
            logger.info("%s", "\n".join(out))
        except Exception:
            pass
        return PlainTextResponse("\n".join(out), media_type="text/csv")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/ml/ensemble/quarantine_log")
async def api_ml_ensemble_quarantine_log(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
    horizon: Optional[str] = Query(None, description="Filter by horizon label if present in log"),
    tail: int = Query(200, ge=1, le=10000, description="Return last N events"),
) -> PlainTextResponse:
    """Serve recent quarantine events from ensemble exporter log as CSV.

    Source file: data/ml/live_predictions/<INDEX>_ensemble_quarantine.log

    Output columns: timestamp,event,model,z,dis,until_ms,horizon
    """
    try:
        idx_norm = (index or "NIFTY").strip().upper()
        if any(ch in idx_norm for ch in ("$", "{", "}")):
            idx_norm = "NIFTY"
        base = _project_root() / "data" / "ml" / "live_predictions"
        fp = base / f"{idx_norm}_ensemble_quarantine.log"
        if not fp.exists():
            raise HTTPException(status_code=404, detail=f"quarantine log not found: {fp}")
        try:
            lines = fp.read_text(encoding="utf-8").splitlines()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"failed to read quarantine log: {e}")
        out = ["timestamp,event,model,z,dis,until_ms,horizon"]
        valid_rows: list[str] = []
        for ln in lines:
            try:
                parts = [p.strip() for p in ln.split(",")]
                if len(parts) < 3:
                    continue
                ts_iso, ev, model = parts[0], parts[1], parts[2]
                # parse kv extras
                z = dis = until_ms = h = ""
                for p in parts[3:]:
                    if p.startswith("z="):
                        z = p.split("=", 1)[1]
                    elif p.startswith("dis="):
                        dis = p.split("=", 1)[1]
                    elif p.startswith("until="):
                        until_ms = p.split("=", 1)[1]
                    elif p.startswith("horizon="):
                        h = p.split("=", 1)[1]
                if horizon is not None and h and h != str(horizon):
                    continue
                # Build normalized row
                row = ",".join([
                    ts_iso,
                    ev,
                    model,
                    z,
                    dis,
                    until_ms,
                    h,
                ])
                # Skip header-like lines (if any)
                if row.startswith("timestamp,event,model"):
                    continue
                valid_rows.append(row)
            except Exception:
                continue
        # Apply tail after filtering valid rows
        if tail and len(valid_rows) > tail:
            valid_rows = valid_rows[-tail:]
        out.extend(valid_rows)
        return PlainTextResponse("\n".join(out), media_type="text/csv")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/ml/ensemble/k_calibration")
async def api_ml_ensemble_k_calibration(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
    horizon: Optional[str] = Query(None, description="Horizon label to surface (optional filter)"),
) -> PlainTextResponse:
    """Serve latest auto-calibration sidecar for disagreement scaling k as CSV.

    Source file: data/ml/live_predictions/<INDEX>_ensemble_k_calibration.json

    Output columns: timestamp,recommended_k,effective_cov,band_radius,target,index,horizon,n
    """
    try:
        idx_norm = (index or "NIFTY").strip().upper()
        if any(ch in idx_norm for ch in ("$", "{", "}")):
            idx_norm = "NIFTY"
        base = _project_root() / "data" / "ml" / "live_predictions"
        fp = base / f"{idx_norm}_ensemble_k_calibration.json"
        if not fp.exists():
            raise HTTPException(status_code=404, detail=f"k calibration sidecar not found: {fp}")
        import json as _json
        try:
            obj = _json.loads(fp.read_text(encoding="utf-8"))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"failed to parse calibration JSON: {e}")
        # Basic validation
        ts = obj.get("timestamp")
        rec_k = obj.get("recommended_k")
        k_smooth = obj.get("k_smooth")
        eff_cov = obj.get("effective_cov")
        band_radius = obj.get("band_radius")
        target = obj.get("target")
        n = obj.get("n")
        side_horizon = obj.get("horizon")
        side_index = obj.get("index") or idx_norm
        if horizon and side_horizon and str(side_horizon) != str(horizon):
            # filter mismatch: return header only (no data)
            header = "timestamp,recommended_k,k_smooth,effective_cov,band_radius,target,index,horizon,n"
            return PlainTextResponse(header + "\n", media_type="text/csv")
        header = "timestamp,recommended_k,k_smooth,effective_cov,band_radius,target,index,horizon,n"
        # Format k_smooth to two decimals when present to satisfy CSV contract (e.g., 1.10)
        if k_smooth is not None:
            try:
                k_smooth_str = f"{float(k_smooth):.2f}"
            except Exception:
                k_smooth_str = str(k_smooth)
        else:
            k_smooth_str = ""
        row = f"{ts},{rec_k},{k_smooth_str},{eff_cov},{band_radius},{target},{side_index},{side_horizon},{n}"
        return PlainTextResponse("\n".join([header, row]) + "\n", media_type="text/csv")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/ml/ensemble/k_applied")
async def api_ml_ensemble_k_applied(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
    horizon: Optional[str] = Query(None, description="Horizon label to surface (optional filter)"),
    tail: int = Query(1, ge=1, le=1000, description="How many latest rows to return"),
    include_placeholders: bool = Query(False, description="Include placeholder rows (applied_k_source=placeholder) if true"),
) -> PlainTextResponse:
    """Return latest applied_k values from ensemble CSV.

    Source: data/ml/live_predictions/<INDEX>_ensemble.csv

    Output columns: timestamp,applied_k,applied_k_source,scaled_radius,index,horizon
    """
    try:
        idx_norm = (index or "NIFTY").strip().upper()
        if any(ch in idx_norm for ch in ("$", "{", "}")):
            idx_norm = "NIFTY"
        base = _project_root() / "data" / "ml" / "live_predictions"
        fp = base / f"{idx_norm}_ensemble.csv"
        if not fp.exists():
            raise HTTPException(status_code=404, detail=f"ensemble file not found: {fp}")
        lines = fp.read_text(encoding="utf-8").splitlines()
        if not lines:
            return PlainTextResponse("timestamp,applied_k,applied_k_source,scaled_radius,index,horizon\n", media_type="text/csv")
        header = lines[0].split(",")
        try:
            ts_idx = header.index("timestamp")
            k_idx = header.index("applied_k")
            src_idx = header.index("applied_k_source")
            rad_idx = header.index("scaled_radius")
            idx_idx = header.index("index")
            hor_idx = header.index("horizon")
        except Exception:
            # If columns missing, return only header
            return PlainTextResponse("timestamp,applied_k,applied_k_source,scaled_radius,index,horizon\n", media_type="text/csv")
        data = lines[1:]
        if horizon is not None:
            data = [r for r in data if (len(r.split(",")) > hor_idx and r.split(",")[hor_idx] == str(horizon))]
        if not data:
            return PlainTextResponse("timestamp,applied_k,applied_k_source,scaled_radius,index,horizon\n", media_type="text/csv")
        if tail and len(data) > tail:
            data = data[-tail:]
        out = ["timestamp,applied_k,applied_k_source,scaled_radius,index,horizon"]
        for r in data:
            parts = r.split(",")
            if not include_placeholders:
                try:
                    src_val = parts[src_idx]
                except Exception:
                    src_val = ""
                if src_val == "placeholder":
                    continue
            out.append(
                ",".join([
                    parts[ts_idx],
                    parts[k_idx],
                    parts[src_idx],
                    parts[rad_idx],
                    parts[idx_idx],
                    parts[hor_idx],
                ])
            )
        return PlainTextResponse("\n".join(out) + "\n", media_type="text/csv")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class KOverrideRequest(BaseModel):
    index: str
    horizon: str
    k: float
    ttl_minutes: Optional[int] = None
    actor: Optional[str] = None
    reason: Optional[str] = None
    classification: Optional[str] = None  # Override class: emergency|strategic|test|other


@router.post("/api/ml/ensemble/k_override", response_model=None)
async def api_ml_ensemble_k_override(
    request: Request,
    payload: KOverrideRequest = Body(
        ..., description="Override payload with index,horizon,k, ttl_minutes(optional), and optional actor/reason/classification"
    ),
):  # PlainTextResponse returned explicitly
    """Create or update a temporary override for applied_k.

    Writes to: data/ml/live_predictions/<INDEX>_ensemble_k_overrides.json
    Structure: {"overrides": {"<horizon>": {"k": <float>, "expires": <epoch_ms or null>}}}
    """
    try:
        idx_norm = (payload.index or "NIFTY").strip().upper()
        base = _project_root() / "data" / "ml" / "live_predictions"
        base.mkdir(parents=True, exist_ok=True)
        fp = base / f"{idx_norm}_ensemble_k_overrides.json"
        import json as _json, time as _time
        obj = {"overrides": {}}
        if fp.exists():
            try:
                obj = _json.loads(fp.read_text(encoding="utf-8")) or {"overrides": {}}
            except Exception:
                obj = {"overrides": {}}
        now_ms = int(_time.time() * 1000)
        exp = None
        if payload.ttl_minutes is not None and payload.ttl_minutes > 0:
            exp = int(now_ms + payload.ttl_minutes * 60_000)
        # Capture metadata
        src_ip = None
        try:
            if request is not None and request.client is not None:  # defensive; request is required
                src_ip = str(request.client.host)
        except Exception:
            src_ip = None
        meta = {
            "k": float(payload.k),
            "expires": exp,
            "created": now_ms,
            "actor": (payload.actor or None),
            "reason": (payload.reason or None),
            "class": (payload.classification or None),
            "source_ip": src_ip,
        }
        obj.setdefault("overrides", {})[str(payload.horizon)] = meta
        try:
            fp.write_text(_json.dumps(obj, indent=2), encoding="utf-8")
        except Exception as _e:
            try:
                if _get_eh is not None:
                    _get_eh().handle_error(
                        _e,
                        category=_ErrCat.FILE_IO,  # type: ignore[arg-type]
                        severity=_ErrSev.LOW,  # type: ignore[arg-type]
                        component="dashboard_ml_routes",
                        function_name="api_ml_set_ensemble_k_override",
                        message="Failed to persist ensemble k override JSON",
                        context={"path": str(fp)},
                    )
            except Exception:
                pass
        # Append audit log
        try:
            iso = _dt.datetime.now(tz=_dt.timezone.utc).replace(microsecond=0).isoformat()
            log_fp = base / f"{idx_norm}_ensemble_k_overrides.log"
            with log_fp.open("a", encoding="utf-8") as lf:
                extras = []
                if payload.actor:
                    extras.append(f"actor={payload.actor}")
                if payload.reason:
                    # Replace commas to keep CSV-ish log stable
                    extras.append(f"reason={str(payload.reason).replace(',', ';')}")
                if payload.classification:
                    extras.append(f"class={payload.classification}")
                if src_ip:
                    extras.append(f"source_ip={src_ip}")
                extras.append(f"created_ms={now_ms}")
                extras_s = (",".join(extras)) if extras else ""
                lf.write(
                    f"{iso},index={idx_norm},horizon={payload.horizon},k={float(payload.k)},expires_ms={(exp if exp is not None else '')}{(',' + extras_s) if extras_s else ''}\n"
                )
        except Exception as _e:
            try:
                if _get_eh is not None:
                    _get_eh().handle_error(
                        _e,
                        category=_ErrCat.FILE_IO,  # type: ignore[arg-type]
                        severity=_ErrSev.LOW,  # type: ignore[arg-type]
                        component="dashboard_ml_routes",
                        function_name="api_ml_set_ensemble_k_override",
                        message="Failed to append ensemble k override audit log",
                        context={"path": str(base)},
                    )
            except Exception:
                pass
        return PlainTextResponse("ok\n", media_type="text/plain")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/ml/ensemble/k_overrides", response_model=None)
async def api_ml_ensemble_k_overrides(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
):  # PlainTextResponse returned explicitly
    """List current overrides for an index as CSV.

    Output columns: horizon,k,expires_ms,created_ms,actor,reason,class,source_ip,index
    """
    try:
        idx_norm = (index or "NIFTY").strip().upper()
        if any(ch in idx_norm for ch in ("$", "{", "}")):
            idx_norm = "NIFTY"
        base = _project_root() / "data" / "ml" / "live_predictions"
        fp = base / f"{idx_norm}_ensemble_k_overrides.json"
        import json as _json
        out = ["horizon,k,expires_ms,created_ms,actor,reason,class,source_ip,index"]
        if not fp.exists():
            return PlainTextResponse("\n".join(out) + "\n", media_type="text/csv")
        try:
            obj = _json.loads(fp.read_text(encoding="utf-8")) or {"overrides": {}}
        except Exception:
            return PlainTextResponse("\n".join(out) + "\n", media_type="text/csv")
        ovs = obj.get("overrides") or {}
        for h, meta in sorted(ovs.items(), key=lambda kv: str(kv[0])):
            try:
                k = float(meta.get("k")) if isinstance(meta.get("k"), (int, float)) else ""
            except Exception:
                k = ""
            exp = meta.get("expires") if isinstance(meta.get("expires"), (int, float)) else ""
            created = meta.get("created") if isinstance(meta.get("created"), (int, float)) else ""
            actor = meta.get("actor") or ""
            reason = meta.get("reason") or ""
            cls = meta.get("class") or ""
            src_ip = meta.get("source_ip") or ""
            # sanitize commas in reason to keep CSV shape
            try:
                if isinstance(reason, str):
                    reason = reason.replace(",", ";")
            except Exception:
                pass
            out.append(f"{h},{k},{exp},{created},{actor},{reason},{cls},{src_ip},{idx_norm}")
        return PlainTextResponse("\n".join(out) + "\n", media_type="text/csv")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/ml/delta", response_model=None)
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
        idx_norm = (index or "NIFTY").strip().upper()
        if any(ch in idx_norm for ch in ("$", "{", "}")):
            idx_norm = "NIFTY"

        # --- Load predictions CSV ---
        base = _project_root() / "data" / "ml" / "live_predictions"
        pred_fp = base / f"{idx_norm}.csv"
        if not pred_fp.exists():
            raise HTTPException(status_code=404, detail=f"predictions file not found: {pred_fp}")
        lines = pred_fp.read_text(encoding="utf-8").splitlines()
        if not lines:
            return PlainTextResponse("", media_type="text/csv")
        header = lines[0]
        rows = lines[1:]
        cols = header.split(",")
        # Column indexes (best-effort)
        try:
            ts_idx = cols.index("timestamp")
            pred_idx = cols.index("prediction")
            mdl_idx = cols.index("model")
            hor_idx = cols.index("horizon")
        except Exception:
            raise HTTPException(status_code=500, detail="malformed predictions CSV header")

        def _to_epoch_ms(s: str) -> int | None:
            try:
                # Try ISO and dd-mm-YYYY HH:MM:SS
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M:%S"):
                    try:
                        dt = _dt.datetime.strptime(s.strip(), fmt)
                        return int(dt.timestamp() * 1000)
                    except Exception:
                        continue
                # Fallback: integer seconds or ms
                s2 = s.strip()
                if s2.isdigit():
                    if len(s2) >= 13:
                        return int(s2[:13])
                    return int(s2) * 1000
            except Exception:
                pass
            return None

        pred_by_bucket: dict[int, float] = {}
        for r in rows[-max(tail * 2, 100):]:  # read a bit extra for safety then trim by bucket
            parts = r.split(",")
            if len(parts) <= max(ts_idx, pred_idx, mdl_idx, hor_idx):
                continue
            if parts[mdl_idx] != model or parts[hor_idx] != str(horizon):
                continue
            ems = _to_epoch_ms(parts[ts_idx])
            if ems is None:
                continue
            bucket = (ems // bucket_ms) * bucket_ms
            try:
                pred_val = float(parts[pred_idx])
            except Exception:
                continue
            pred_by_bucket[bucket] = pred_val  # keep last in bucket

        if not pred_by_bucket:
            return PlainTextResponse("time,delta,model,index,horizon\n", media_type="text/csv")

        # --- Load live_csv for tp ---
        from datetime import date
        p = _resolve_live_csv_path(idx_norm, expiry_tag, offset, date.today())
        if not p or not p.exists():
            raise HTTPException(status_code=404, detail="live_csv file not found")
        live_rows = _load_csv_rows_full(p)
        tp_by_bucket: dict[int, float] = {}
        for row in live_rows[-max(tail * 2, 100):]:
            try:
                ems = int(row.get("ts") or row.get("time") or 0)
            except Exception:
                continue
            if not ems:
                continue
            bucket = (ems // bucket_ms) * bucket_ms
            tp = row.get("tp")
            if isinstance(tp, (int, float)):
                tp_by_bucket[bucket] = float(tp)

        # --- Join by bucket and emit CSV ---
        keys = sorted(set(pred_by_bucket.keys()) & set(tp_by_bucket.keys()))
        if tail and len(keys) > tail:
            keys = keys[-tail:]
        out = ["time,delta,model,index,horizon"]
        for k in keys:
            delta = pred_by_bucket[k] - tp_by_bucket[k]
            # ISO time (seconds) for readability
            iso = _dt.datetime.fromtimestamp(k / 1000).replace(microsecond=0).isoformat()
            out.append(f"{iso},{delta},{model},{idx_norm},{horizon}")
        return PlainTextResponse("\n".join(out), media_type="text/csv")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/ml/correlations")
async def api_ml_correlations(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
    expiry_tag: str = Query("this_month", description="Expiry tag for live_csv lookup"),
    offset: str = Query("0", description="Offset for live_csv lookup"),
    window_minutes: int = Query(120, ge=1, le=24*60, description="Lookback window in minutes"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000, description="Bucket size for time alignment in ms"),
    set_name: str = Query("set1", description="Which predefined set to use: set1, set2, or 'all'"),
    set_param: Optional[str] = Query(None, description="Deprecated: use set_name", alias="set"),
    cols: Optional[str] = Query(None, description="Comma-separated explicit column list to use"),
    method: str = Query("pearson", description="Correlation method (currently pearson only)"),
    format: str = Query("long", description="Output format: 'long' (tidy) or 'wide' (matrix)"),
) -> PlainTextResponse:
    """Return correlation matrix for selected columns from live_csv over a window.

    Predefined sets:
      - set1: index_price, ce_vol, pe_vol, ce_oi, pe_oi, ce_iv, pe_iv, tp
      - set2: set1 + ce_delta, pe_delta, ce_theta, pe_theta, ce_vega, pe_vega, ce_gamma, pe_gamma, ce_rho, pe_rho, tp_net_change, tp_day_change

    Output (long): col_i,col_j,correlation,count,window_minutes
    Output (wide): first row is header with column names; cells are correlation values
    """
    try:
        idx_norm = (index or "NIFTY").strip().upper()
        if any(ch in idx_norm for ch in ("$", "{", "}")):
            idx_norm = "NIFTY"

        # Locate live_csv
        from datetime import date
        p = _resolve_live_csv_path(idx_norm, expiry_tag, offset, date.today())
        if not p or not p.exists():
            raise HTTPException(status_code=404, detail="live_csv file not found")
        rows = _load_csv_rows_full(p)

        # Window cutoff
        now_ms = int(_dt.datetime.now(tz=_dt.timezone.utc).timestamp() * 1000)
        cutoff_ms = now_ms - window_minutes * 60_000

        # Candidate columns by set
        set1 = [
            "index_price", "ce_vol", "pe_vol", "ce_oi", "pe_oi", "ce_iv", "pe_iv", "tp",
        ]
        set2 = set1 + [
            "ce_delta", "pe_delta", "ce_theta", "pe_theta", "ce_vega", "pe_vega", "ce_gamma", "pe_gamma", "ce_rho", "pe_rho",
            "tp_net_change", "tp_day_change",
        ]
        # Back-compat: allow 'set' if provided
        chosen = (set_name or "").strip() or (set_param or "").strip() or "set1"
        if cols:
            use_cols = [c.strip() for c in cols.split(",") if c.strip()]
        else:
            if chosen.lower() == "set2":
                use_cols = set2
            elif chosen.lower() == "all":
                # union of all numeric columns present
                # infer from first row keys, filtered later
                try:
                    keys = set()
                    for r in rows[:200]:
                        try:
                            keys.update(r.keys())
                        except Exception:
                            continue
                except Exception:
                    keys = set()
                use_cols = sorted([
                    k for k in keys if k not in {"time", "ts", "time_str", "time_epoch_s"}
                ])
            else:
                use_cols = set1

        # Build per-bucket latest values
        # Also compute tp_net_change and tp_day_change on the fly if not present
        buckets: dict[int, dict[str, float]] = {}
        day_open_tp: Optional[float] = None
        last_tp: Optional[float] = None
        for r in rows:
            try:
                ems = int(r.get("ts") or r.get("time") or 0)
            except Exception:
                continue
            if not ems or ems < cutoff_ms:
                continue
            bucket = (ems // bucket_ms) * bucket_ms
            rec = buckets.get(bucket)
            if rec is None:
                rec = {}
                buckets[bucket] = rec
            # copy numeric values
            for c in use_cols:
                v = r.get(c)
                if isinstance(v, (int, float)):
                    rec[c] = float(v)
            # enrich tp-derived fields if relevant
            tp = r.get("tp")
            if isinstance(tp, (int, float)):
                tp_f = float(tp)
                if last_tp is not None:
                    rec.setdefault("tp_net_change", tp_f - last_tp)
                last_tp = tp_f
                # approximate day open: first tp seen after 09:15 local bucket
                if day_open_tp is None:
                    day_open_tp = tp_f
                rec.setdefault("tp_day_change", tp_f - (day_open_tp or tp_f))

        # Gather aligned rows
        keys = sorted(buckets.keys())
        if not keys:
            return PlainTextResponse("col_i,col_j,correlation,count,window_minutes\n", media_type="text/csv")

        # Filter columns to those that actually have data
        present_cols: list[str] = []
        for c in use_cols:
            has = any(c in buckets[k] for k in keys)
            if has:
                present_cols.append(c)
        # Convert to column-vectors aligned on keys
        series: dict[str, list[float]] = {c: [] for c in present_cols}
        counts: dict[str, int] = {c: 0 for c in present_cols}
        for k in keys:
            rec = buckets[k]
            for c in present_cols:
                if c in rec and isinstance(rec[c], (int, float)):
                    series[c].append(float(rec[c]))
                    counts[c] += 1
                else:
                    series[c].append(float("nan"))

        # Simple pearson correlation ignoring NaNs pairwise
        def _pair_corr(xs: list[float], ys: list[float]) -> tuple[float, int]:
            try:
                import math
                pairs = [(x, y) for x, y in zip(xs, ys) if (x == x) and (y == y)]  # filter NaNs
                n = len(pairs)
                if n < 3:
                    return float("nan"), n
                mean_x = sum(x for x, _ in pairs) / n
                mean_y = sum(y for _, y in pairs) / n
                cov = sum((x - mean_x) * (y - mean_y) for x, y in pairs) / (n - 1)
                var_x = sum((x - mean_x) ** 2 for x, _ in pairs) / (n - 1)
                var_y = sum((y - mean_y) ** 2 for _, y in pairs) / (n - 1)
                if var_x <= 0 or var_y <= 0:
                    return float("nan"), n
                return cov / math.sqrt(var_x * var_y), n
            except Exception:
                return float("nan"), 0

        cols_eff = present_cols
        if format.lower() == "wide":
            # header row
            out = [",".join(["col", *cols_eff])]
            for i, ci in enumerate(cols_eff):
                row_vals = [ci]
                xi = series[ci]
                for j, cj in enumerate(cols_eff):
                    xj = series[cj]
                    if i == j:
                        row_vals.append("1.0")
                    else:
                        r, n = _pair_corr(xi, xj)
                        row_vals.append(f"{r:.4f}" if (r == r) else "")
                out.append(",".join(row_vals))
            return PlainTextResponse("\n".join(out), media_type="text/csv")
        else:
            out = ["col_i,col_j,correlation,count,window_minutes"]
            for i, ci in enumerate(cols_eff):
                for j in range(i, len(cols_eff)):
                    cj = cols_eff[j]
                    if ci == cj:
                        out.append(f"{ci},{cj},1.0,{counts[ci]},{window_minutes}")
                    else:
                        r, n = _pair_corr(series[ci], series[cj])
                        out.append(f"{ci},{cj},{(f'{r:.4f}' if (r == r) else '')},{n},{window_minutes}")
            return PlainTextResponse("\n".join(out), media_type="text/csv")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/ml/model_matrix")
async def api_ml_model_matrix(
    window_minutes: int = Query(60, ge=1, le=24*60, description="Lookback window in minutes for diagnostics"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000, description="Bucket size for time alignment in ms"),
) -> PlainTextResponse:
    """Return a CSV matrix summarizing models across indices/horizons.

    Sources:
    - models/champions.json for model selection, config and artifact
    - configs/ml/*.json for features, params, FE options
    - models/*.fe.json sidecars for used_features and normalize stats (if present)
    - Live diagnostics computed like /api/ml/diagnostics over the given window

    Columns:
    model,index,horizon,config,artifact,features_count,used_features_count,fe_horizon,lag_columns,lags,roll_windows,add_time,add_moneyness,normalize_keys,normalize_cols_count,params_summary,champion_metric,champion_score,diag_count,diag_mae,diag_rmse,diag_bias_mean,diag_bias_median,diag_corr,diag_slope_pred,diag_slope_tp,diag_delta_p10,diag_delta_p90,diag_last_pred,diag_last_tp,diag_last_delta,window_minutes
    """
    try:
        import json as _json
        base = _project_root()
        champs_path = base / "models" / "champions.json"
        if not champs_path.exists():
            raise HTTPException(status_code=404, detail="champions.json not found")
        champs = _json.loads(champs_path.read_text(encoding="utf-8"))
        champions = champs.get("champions", {}) or {}

        # Helpers (reuse from diagnostics)
        def _to_epoch_ms(s: str) -> int | None:
            try:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M:%S"):
                    try:
                        dt = _dt.datetime.strptime(s.strip(), fmt)
                        return int(dt.timestamp() * 1000)
                    except Exception:
                        continue
                s2 = s.strip()
                if s2.isdigit():
                    if len(s2) >= 13:
                        return int(s2[:13])
                    return int(s2) * 1000
            except Exception:
                pass
            return None

        def _corr(xs: list[float], ys: list[float]) -> float:
            try:
                import math
                n = len(xs)
                if n < 3:
                    return float("nan")
                mean_x = sum(xs) / n
                mean_y = sum(ys) / n
                cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / (n - 1)
                var_x = sum((x - mean_x) ** 2 for x in xs) / (n - 1)
                var_y = sum((y - mean_y) ** 2 for y in ys) / (n - 1)
                if var_x <= 0 or var_y <= 0:
                    return float("nan")
                return cov / math.sqrt(var_x * var_y)
            except Exception:
                return float("nan")

        def _slope_per_hr(ts_ms: list[int], vals: list[float]) -> float:
            try:
                n = len(ts_ms)
                if n < 2:
                    return float("nan")
                xs = [t / 3_600_000.0 for t in ts_ms]
                mean_x = sum(xs) / n
                mean_y = sum(vals) / n
                denom = sum((x - mean_x) ** 2 for x in xs)
                if denom == 0:
                    return float(0.0)
                numer = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, vals))
                return numer / denom
            except Exception:
                return float("nan")

        # Build header
        out = [
            "model,index,horizon,config,artifact,features_count,used_features_count,fe_horizon,lag_columns,lags,roll_windows,add_time,add_moneyness,normalize_keys,normalize_cols_count,params_summary,champion_metric,champion_score,diag_count,diag_mae,diag_rmse,diag_bias_mean,diag_bias_median,diag_corr,diag_slope_pred,diag_slope_tp,diag_delta_p10,diag_delta_p90,diag_last_pred,diag_last_tp,diag_last_delta,window_minutes"
        ]

        for key, meta in sorted(champions.items()):
            try:
                idx = str(meta.get("index", "")).upper()
                horizon = str(meta.get("horizon", ""))
                model = str(meta.get("model_name", meta.get("model") or ""))
                cfg_rel = meta.get("config") or ""
                art_rel = meta.get("artifact") or ""
                metric = meta.get("metric") or ""
                score = meta.get("score")
                cfg_path = (base / cfg_rel) if cfg_rel else None
                art_path = (base / art_rel) if art_rel else None

                # Extract config info
                features_count = used_features_count = fe_hor = 0
                lag_cols: list[str] = []
                lags: list[int] = []
                roll_windows: list[int] = []
                add_time = add_moneyness = False
                norm_keys: list[str] = []
                norm_cols_count = 0
                params_summary = ""
                if cfg_path and cfg_path.exists():
                    cfg_json = _json.loads(cfg_path.read_text(encoding="utf-8"))
                    feats = list(cfg_json.get("features") or [])
                    features_count = len(feats)
                    fe = cfg_json.get("feature_engineering") or {}
                    fe_hor = int(fe.get("forecast_horizon", 0))
                    lag_cols = list(fe.get("lag_columns") or [])
                    lags = list(fe.get("lags") or [])
                    roll_windows = list(fe.get("roll_windows") or [])
                    add_time = bool(fe.get("add_time", False))
                    add_moneyness = bool(fe.get("add_moneyness", False))
                    nb = fe.get("normalize_by") or {}
                    norm_keys = list(nb.get("keys") or [])
                    norm_cols = list(nb.get("columns") or [])
                    norm_cols_count = len(norm_cols)
                    params = cfg_json.get("params") or {}
                    # compact summary: key1=val1;key2=val2
                    try:
                        params_summary = ";".join(f"{k}={v}" for k, v in list(params.items())[:8])
                    except Exception:
                        params_summary = ""

                # Sidecar used_features
                if art_path and art_path.exists():
                    # Try <artifact>.fe.json first; then if not, try replacing extension with .fe.json
                    sidecar = None
                    cand1 = art_path.with_suffix(art_path.suffix + ".fe.json")
                    cand2 = art_path.with_suffix(".fe.json")
                    for c in (cand1, cand2):
                        if c.exists():
                            sidecar = c
                            break
                    if sidecar is None:
                        # Heuristic: try models/<basename>.fe.json without extra suffix
                        try:
                            sc_guess = art_path.parent / (art_path.name + ".fe.json")
                            if sc_guess.exists():
                                sidecar = sc_guess
                        except Exception:
                            pass
                    if sidecar and sidecar.exists():
                        try:
                            sc = _json.loads(sidecar.read_text(encoding="utf-8"))
                            used_features = list(sc.get("used_features") or [])
                            used_features_count = len(used_features)
                        except Exception:
                            used_features_count = 0

                # Diagnostics (window)
                # Load predictions
                pred_fp = base / "data" / "ml" / "live_predictions" / f"{idx}.csv"
                now_ms = int(_dt.datetime.now(tz=_dt.timezone.utc).timestamp() * 1000)
                cutoff_ms = now_ms - window_minutes * 60_000
                preds_map: dict[int, float] = {}
                diag_count = 0
                mae = rmse = bias_mean = bias_median = float("nan")
                corr = slope_pred = slope_tp = float("nan")
                p10 = p90 = last_pred = last_tp = last_delta = float("nan")
                if pred_fp.exists():
                    lines = pred_fp.read_text(encoding="utf-8").splitlines()
                    if lines:
                        cols = lines[0].split(",")
                        try:
                            ts_idx = cols.index("timestamp")
                            pred_idx = cols.index("prediction")
                            mdl_idx = cols.index("model")
                            hor_idx = cols.index("horizon")
                        except Exception:
                            ts_idx = pred_idx = mdl_idx = hor_idx = -1
                        for r in lines[-5000:]:
                            parts = r.split(",")
                            if ts_idx < 0 or len(parts) <= max(ts_idx, pred_idx, mdl_idx, hor_idx):
                                continue
                            if parts[mdl_idx] != model or parts[hor_idx] != str(horizon):
                                continue
                            ems = _to_epoch_ms(parts[ts_idx])
                            if ems is None or ems < cutoff_ms:
                                continue
                            bucket = (ems // bucket_ms) * bucket_ms
                            try:
                                pv = float(parts[pred_idx])
                            except Exception:
                                continue
                            preds_map[bucket] = pv

                # Load tp
                tp_by_bucket: dict[int, float] = {}
                from datetime import date
                p = _resolve_live_csv_path(idx, "this_week", "0", date.today())
                if p and p.exists():
                    live_rows = _load_csv_rows_full(p)
                    for row in live_rows:
                        try:
                            ems = int(row.get("ts") or row.get("time") or 0)
                        except Exception:
                            continue
                        if not ems or ems < cutoff_ms:
                            continue
                        bucket = (ems // bucket_ms) * bucket_ms
                        tp = row.get("tp")
                        if isinstance(tp, (int, float)):
                            tp_by_bucket[bucket] = float(tp)

                keys = sorted(set(preds_map.keys()) & set(tp_by_bucket.keys()))
                if keys:
                    import math
                    diag_count = len(keys)
                    preds = [preds_map[k] for k in keys]
                    tps = [tp_by_bucket[k] for k in keys]
                    deltas = [a - b for a, b in zip(preds, tps)]
                    mae = sum(abs(d) for d in deltas) / diag_count
                    rmse = math.sqrt(sum((d) ** 2 for d in deltas) / diag_count)
                    bias_mean = sum(deltas) / diag_count
                    sd = sorted(deltas)
                    m = diag_count // 2
                    bias_median = sd[m] if diag_count % 2 == 1 else 0.5 * (sd[m - 1] + sd[m])
                    corr = _corr(preds, tps)
                    slope_pred = _slope_per_hr(keys, preds)
                    slope_tp = _slope_per_hr(keys, tps)
                    def _pct(vals: list[float], p: float) -> float:
                        if not vals:
                            return float("nan")
                        s = sorted(vals)
                        k = (len(s) - 1) * p
                        f = int(k)
                        c = min(f + 1, len(s) - 1)
                        if f == c:
                            return s[f]
                        return s[f] + (s[c] - s[f]) * (k - f)
                    p10 = _pct(deltas, 0.10)
                    p90 = _pct(deltas, 0.90)
                    last_k = keys[-1]
                    last_pred = preds_map[last_k]
                    last_tp = tp_by_bucket[last_k]
                    last_delta = last_pred - last_tp

                # Emit row
                out.append(
                    ",".join([
                        model,
                        idx,
                        str(horizon),
                        (cfg_rel or ""),
                        (art_rel or ""),
                        str(features_count),
                        str(used_features_count),
                        str(fe_hor),
                        "|".join(map(str, lag_cols)) if lag_cols else "",
                        "|".join(map(str, lags)) if lags else "",
                        "|".join(map(str, roll_windows)) if roll_windows else "",
                        "1" if add_time else "0",
                        "1" if add_moneyness else "0",
                        "|".join(map(str, norm_keys)) if norm_keys else "",
                        str(norm_cols_count),
                        params_summary.replace(",", ";"),
                        str(metric),
                        (f"{float(score):.6f}" if isinstance(score, (int, float)) else str(score or "")),
                        str(diag_count),
                        (f"{mae:.4f}" if diag_count else ""),
                        (f"{rmse:.4f}" if diag_count else ""),
                        (f"{bias_mean:.4f}" if diag_count else ""),
                        (f"{bias_median:.4f}" if diag_count else ""),
                        (f"{corr:.4f}" if diag_count and corr == corr else ""),
                        (f"{slope_pred:.4f}" if diag_count else ""),
                        (f"{slope_tp:.4f}" if diag_count else ""),
                        (f"{p10:.4f}" if diag_count else ""),
                        (f"{p90:.4f}" if diag_count else ""),
                        (f"{last_pred:.4f}" if diag_count else ""),
                        (f"{last_tp:.4f}" if diag_count else ""),
                        (f"{last_delta:.4f}" if diag_count else ""),
                        str(window_minutes),
                    ])
                )
            except Exception as e:
                # Non-fatal per-row error; include minimal row with error marker
                out.append(
                    ",".join([
                        str(meta.get("model_name", "")),
                        str(meta.get("index", "")),
                        str(meta.get("horizon", "")),
                        str(meta.get("config", "")),
                        str(meta.get("artifact", "")),
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        str(meta.get("metric", "")),
                        str(meta.get("score", "")),
                        "0",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        str(window_minutes),
                    ])
                )

        return PlainTextResponse("\n".join(out), media_type="text/csv")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/ml/diagnostics")
async def api_ml_diagnostics(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
    horizon: str = Query("1", description="Horizon label to select (string)"),
    model: str = Query("all", description="Model name to select or 'all' for all models found"),
    expiry_tag: str = Query("this_month", description="Expiry tag for live_csv lookup"),
    offset: str = Query("0", description="Offset for live_csv lookup"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000, description="Bucket size for time alignment in ms"),
    window_minutes: int = Query(120, ge=1, le=24*60, description="Lookback window in minutes"),
    include_bands: bool = Query(False, description="If true, compute conformal band radius and coverage estimate"),
    coverage: float = Query(0.8, ge=0.5, le=0.99, description="Target coverage for conformal radius"),
    include_move_stats: bool = Query(False, description="If true, include move probability and conditional magnitude stats from <INDEX>_move.csv"),
    move_prob_threshold: float = Query(0.6, ge=0.0, le=1.0, description="Threshold to consider a 'high probability' move for stats"),
    include_effective_bands: bool = Query(False, description="If true, compute effective bands = max(conformal_radius, k * disagreement) using ensemble disagreement"),
    disagreement_k: float = Query(1.0, ge=0.1, le=5.0, description="Scaling factor k for disagreement component"),
    ensemble_models: str = Query("sk_hgb_regressor,xgb_regressor,torch_lstm_regressor,sk_hgb_residual", description="Comma-separated models to compute disagreement over"),
) -> PlainTextResponse:
    """Return CSV diagnostics over a recent window, per model.

    Metrics include: count, MAE, RMSE, mean/median bias (prediction - tp),
    Pearson correlation, trend slopes (per hour) for pred and tp, last values.

    Output columns:
    model,index,horizon,count,mae,rmse,bias_mean,bias_median,corr,slope_pred_per_hr,slope_tp_per_hr,delta_p10,delta_p90,last_pred,last_tp,last_delta,window_minutes
    """
    try:
        idx_norm = (index or "NIFTY").strip().upper()
        if any(ch in idx_norm for ch in ("$", "{", "}")):
            idx_norm = "NIFTY"

        # Load predictions from primary file and optionally hybrid file
        base = _project_root() / "data" / "ml" / "live_predictions"
        pred_fp = base / f"{idx_norm}.csv"
        hybrid_fp = base / f"{idx_norm}_hybrid.csv"

        lines: list[str] = []
        rows: list[str] = []
        cols: list[str] = []
        ts_idx = pred_idx = mdl_idx = hor_idx = -1

        if pred_fp.exists():
            lines = pred_fp.read_text(encoding="utf-8").splitlines()
            if lines:
                header = lines[0]
                rows = lines[1:]
                cols = header.split(",")
                try:
                    ts_idx = cols.index("timestamp")
                    pred_idx = cols.index("prediction")
                    mdl_idx = cols.index("model")
                    hor_idx = cols.index("horizon")
                except Exception:
                    # If primary file exists but malformed, treat as no rows
                    rows = []
                    cols = []
                    ts_idx = pred_idx = mdl_idx = hor_idx = -1
        # If neither file exists, error
        if not pred_fp.exists() and not hybrid_fp.exists():
            raise HTTPException(status_code=404, detail=f"predictions file not found: {pred_fp} or {hybrid_fp}")
        # If both missing or empty, return header only
        if (not rows) and (not hybrid_fp.exists()):
            return PlainTextResponse("model,index,horizon,count,mae,rmse,bias_mean,bias_median,corr,slope_pred_per_hr,slope_tp_per_hr,delta_p10,delta_p90,last_pred,last_tp,last_delta,window_minutes\n", media_type="text/csv")

        def _to_epoch_ms(s: str) -> int | None:
            try:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M:%S"):
                    try:
                        dt = _dt.datetime.strptime(s.strip(), fmt)
                        return int(dt.timestamp() * 1000)
                    except Exception:
                        continue
                s2 = s.strip()
                if s2.isdigit():
                    if len(s2) >= 13:
                        return int(s2[:13])
                    return int(s2) * 1000
            except Exception:
                pass
            return None

        # Determine which models to include
        include_models: set[str] = set()
        if model and model.lower() != "all":
            include_models.add(model)
        else:
            # Discover from tail of primary file
            for r in rows[-500:]:
                parts = r.split(",")
                if mdl_idx >= 0 and len(parts) > mdl_idx:
                    include_models.add(parts[mdl_idx])
            # Also discover from hybrid file
            if hybrid_fp.exists():
                try:
                    h_lines = hybrid_fp.read_text(encoding="utf-8").splitlines()
                    if h_lines:
                        h_cols = h_lines[0].split(",")
                        try:
                            h_mdl_idx = h_cols.index("model")
                        except Exception:
                            h_mdl_idx = -1
                        for r in h_lines[-500:]:
                            parts = r.split(",")
                            if h_mdl_idx >= 0 and len(parts) > h_mdl_idx:
                                include_models.add(parts[h_mdl_idx])
                except Exception:
                    pass
        # Ensure hybrid model can be requested even if not discovered from primary file
        if model and model == "sk_hgb_residual":
            include_models.add(model)

        # Collect predictions by model and bucket
        now_ms = int(_dt.datetime.now(tz=_dt.timezone.utc).timestamp() * 1000)
        cutoff_ms = now_ms - window_minutes * 60_000
        preds_map: dict[str, dict[int, float]] = {m: {} for m in include_models}
        # Primary predictions
        for r in rows[-max(5000, window_minutes * 4) :] :  # heuristic slice
            if ts_idx < 0:
                break
            parts = r.split(",")
            if len(parts) <= max(ts_idx, pred_idx, mdl_idx, hor_idx):
                continue
            mname = parts[mdl_idx]
            if mname not in include_models:
                continue
            if parts[hor_idx] != str(horizon):
                continue
            ems = _to_epoch_ms(parts[ts_idx])
            if ems is None or ems < cutoff_ms:
                continue
            bucket = (ems // bucket_ms) * bucket_ms
            try:
                pv = float(parts[pred_idx])
            except Exception:
                continue
            preds_map[mname][bucket] = pv
        # Hybrid predictions (also capture baseline/residual if present)
        hybrid_baseline_by_bucket: dict[int, float] = {}
        hybrid_residual_by_bucket: dict[int, float] = {}
        if hybrid_fp.exists() and ("sk_hgb_residual" in include_models or (model and model.lower() == "all")):
            try:
                h_lines = hybrid_fp.read_text(encoding="utf-8").splitlines()
                if h_lines:
                    h_cols = h_lines[0].split(",")
                    try:
                        h_ts_idx = h_cols.index("timestamp")
                        h_pred_idx = h_cols.index("prediction")
                        h_mdl_idx = h_cols.index("model")
                        h_hor_idx = h_cols.index("horizon")
                        h_base_idx = h_cols.index("baseline") if "baseline" in h_cols else -1
                        h_resid_idx = h_cols.index("residual") if "residual" in h_cols else -1
                    except Exception:
                        h_ts_idx = h_pred_idx = h_mdl_idx = h_hor_idx = -1
                        h_base_idx = h_resid_idx = -1
                    for r in h_lines[-max(5000, window_minutes * 4) :]:
                        parts = r.split(",")
                        if h_ts_idx < 0 or len(parts) <= max(h_ts_idx, h_pred_idx, h_mdl_idx, h_hor_idx):
                            continue
                        if parts[h_hor_idx] != str(horizon):
                            continue
                        # model constant expected: sk_hgb_residual
                        mname = parts[h_mdl_idx]
                        if mname not in include_models:
                            # include if user asked for all
                            include_models.add(mname)
                            preds_map.setdefault(mname, {})
                        ems = _to_epoch_ms(parts[h_ts_idx])
                        if ems is None or ems < cutoff_ms:
                            continue
                        bucket = (ems // bucket_ms) * bucket_ms
                        try:
                            pv = float(parts[h_pred_idx])
                        except Exception:
                            continue
                        preds_map[mname][bucket] = pv
                        if h_base_idx >= 0 and len(parts) > h_base_idx:
                            try:
                                hybrid_baseline_by_bucket[bucket] = float(parts[h_base_idx])
                            except Exception:
                                pass
                        if h_resid_idx >= 0 and len(parts) > h_resid_idx:
                            try:
                                hybrid_residual_by_bucket[bucket] = float(parts[h_resid_idx])
                            except Exception:
                                pass
            except Exception:
                pass

        # Load tp from live_csv
        from datetime import date
        p = _resolve_live_csv_path(idx_norm, expiry_tag, offset, date.today())
        if not p or not p.exists():
            raise HTTPException(status_code=404, detail="live_csv file not found")
        live_rows = _load_csv_rows_full(p)
        tp_by_bucket: dict[int, float] = {}
        for row in live_rows:
            try:
                ems = int(row.get("ts") or row.get("time") or 0)
            except Exception:
                continue
            if not ems or ems < cutoff_ms:
                continue
            bucket = (ems // bucket_ms) * bucket_ms
            # accept numeric strings for tp as well
            tp_raw = row.get("tp")
            try:
                tp_val = float(tp_raw) if tp_raw is not None else None
            except Exception:
                tp_val = None
            if isinstance(tp_val, (int, float)):
                tp_by_bucket[bucket] = float(tp_val)

        # If no overlap between predictions and tp within the time window, do a permissive fallback scan
        try:
            joined_any = any(set(pmap.keys()) & set(tp_by_bucket.keys()) for pmap in preds_map.values())
        except Exception:
            joined_any = False
        # Prepare simple sequence-aligned fallbacks (by order) if needed
        seq_pred_by_model: dict[str, list[float]] = {}
        seq_hybrid_baseline: list[float] = []
        seq_hybrid_residual: list[float] = []
        seq_tp: list[float] = []
        if not joined_any:
            # Re-scan predictions without cutoff
            preds_map = {m: {} for m in include_models}
            # Primary (no cutoff)
            for r in rows:
                if ts_idx < 0:
                    break
                parts = r.split(",")
                if len(parts) <= max(ts_idx, pred_idx, mdl_idx, hor_idx):
                    continue
                mname = parts[mdl_idx]
                if mname not in include_models:
                    continue
                if parts[hor_idx] != str(horizon):
                    continue
                ems = _to_epoch_ms(parts[ts_idx])
                if ems is None:
                    continue
                b = (ems // bucket_ms) * bucket_ms
                try:
                    pv = float(parts[pred_idx])
                except Exception:
                    continue
                preds_map[mname][b] = pv
            # Hybrid (no cutoff)
            if hybrid_fp.exists() and ("sk_hgb_residual" in include_models or (model and model.lower() == "all")):
                try:
                    h_lines = hybrid_fp.read_text(encoding="utf-8").splitlines()
                    if h_lines:
                        h_cols = h_lines[0].split(",")
                        try:
                            h_ts_idx = h_cols.index("timestamp")
                            h_pred_idx = h_cols.index("prediction")
                            h_mdl_idx = h_cols.index("model")
                            h_hor_idx = h_cols.index("horizon")
                            h_base_idx = h_cols.index("baseline") if "baseline" in h_cols else -1
                            h_resid_idx = h_cols.index("residual") if "residual" in h_cols else -1
                        except Exception:
                            h_ts_idx = h_pred_idx = h_mdl_idx = h_hor_idx = -1
                            h_base_idx = h_resid_idx = -1
                        hybrid_baseline_by_bucket.clear()
                        hybrid_residual_by_bucket.clear()
                        for r in h_lines:
                            parts = r.split(",")
                            if h_ts_idx < 0 or len(parts) <= max(h_ts_idx, h_pred_idx, h_mdl_idx, h_hor_idx):
                                continue
                            if parts[h_hor_idx] != str(horizon):
                                continue
                            mname = parts[h_mdl_idx]
                            if mname not in include_models:
                                include_models.add(mname)
                                preds_map.setdefault(mname, {})
                            ems = _to_epoch_ms(parts[h_ts_idx])
                            if ems is None:
                                continue
                            b = (ems // bucket_ms) * bucket_ms
                            try:
                                pv = float(parts[h_pred_idx])
                            except Exception:
                                continue
                            preds_map[mname][b] = pv
                            if h_base_idx >= 0 and len(parts) > h_base_idx:
                                try:
                                    hybrid_baseline_by_bucket[b] = float(parts[h_base_idx])
                                except Exception:
                                    pass
                            if h_resid_idx >= 0 and len(parts) > h_resid_idx:
                                try:
                                    hybrid_residual_by_bucket[b] = float(parts[h_resid_idx])
                                except Exception:
                                    pass
                except Exception:
                    pass
            # TP without cutoff (also collect sequence)
            tp_by_bucket = {}
            for row in live_rows:
                try:
                    ems = int(row.get("ts") or row.get("time") or 0)
                except Exception:
                    continue
                if not ems:
                    continue
                b = (ems // bucket_ms) * bucket_ms
                tp_raw = row.get("tp")
                try:
                    tp_val = float(tp_raw) if tp_raw is not None else None
                except Exception:
                    tp_val = None
                if isinstance(tp_val, (int, float)):
                    tp_by_bucket[b] = float(tp_val)
                    seq_tp.append(float(tp_val))
            # Also collect sequence-ordered predictions per model/horizon
            # Primary sequence
            for r in rows:
                if ts_idx < 0:
                    break
                parts = r.split(",")
                if len(parts) <= max(ts_idx, pred_idx, mdl_idx, hor_idx):
                    continue
                if parts[hor_idx] != str(horizon):
                    continue
                mname = parts[mdl_idx]
                if mname not in include_models:
                    continue
                try:
                    pv = float(parts[pred_idx])
                except Exception:
                    continue
                seq_pred_by_model.setdefault(mname, []).append(pv)
            # Hybrid sequence
            if hybrid_fp.exists():
                try:
                    h_lines = hybrid_fp.read_text(encoding="utf-8").splitlines()
                    if h_lines:
                        h_cols = h_lines[0].split(",")
                        try:
                            h_pred_idx = h_cols.index("prediction")
                            h_mdl_idx = h_cols.index("model")
                            h_hor_idx = h_cols.index("horizon")
                            h_base_idx = h_cols.index("baseline") if "baseline" in h_cols else -1
                            h_resid_idx = h_cols.index("residual") if "residual" in h_cols else -1
                        except Exception:
                            h_pred_idx = h_mdl_idx = h_hor_idx = -1
                            h_base_idx = h_resid_idx = -1
                        for r in h_lines[1:]:
                            parts = r.split(",")
                            if h_hor_idx < 0 or len(parts) <= max(h_pred_idx, h_mdl_idx, h_hor_idx):
                                continue
                            if parts[h_hor_idx] != str(horizon):
                                continue
                            mname = parts[h_mdl_idx]
                            if mname not in include_models:
                                continue
                            try:
                                pv = float(parts[h_pred_idx])
                            except Exception:
                                pv = None
                            if pv is not None:
                                seq_pred_by_model.setdefault(mname, []).append(pv)
                            if h_base_idx >= 0 and len(parts) > h_base_idx:
                                try:
                                    seq_hybrid_baseline.append(float(parts[h_base_idx]))
                                except Exception:
                                    pass
                            if h_resid_idx >= 0 and len(parts) > h_resid_idx:
                                try:
                                    seq_hybrid_residual.append(float(parts[h_resid_idx]))
                                except Exception:
                                    pass
                except Exception:
                    # If hybrid sequence parsing fails, fall back silently; diagnostics can proceed without it
                    pass

        # Prepare diagnostics
        # Build dynamic header
        base_header = "model,index,horizon,count,mae,rmse,bias_mean,bias_median,corr,slope_pred_per_hr,slope_tp_per_hr,delta_p10,delta_p90,last_pred,last_tp,last_delta,window_minutes"
        hybrid_extras = ",baseline_rmse,hybrid_rmse,improvement_ratio,last_baseline,last_residual" if ("sk_hgb_residual" in include_models) else ""
        band_header = ",band_radius,coverage_estimate" if include_bands else ""
        eff_header = ",effective_cov_estimate,effective_radius_avg,effective_radius_last" if (include_bands and include_effective_bands) else ""
        move_header = ",avg_move_probability,move_high_prob_share,move_mag_p10,move_mag_p50,move_mag_p90,move_last_prob,move_last_mag" if include_move_stats else ""
        out = [base_header + hybrid_extras + band_header + eff_header + move_header]
        header_cols = out[0].split(",")
        expected_len = len(header_cols)

        # Precompute ensemble disagreement per bucket over selected models (for effective bands)
        dis_by_bucket: dict[int, float] = {}
        if include_bands and include_effective_bands:
            try:
                ens_models = [m.strip() for m in (ensemble_models or "").split(",") if m.strip()]
                # Build per-bucket values from predictions CSV rows within window
                vals_by_bucket: dict[int, list[float]] = {}
                for r in rows[-max(5000, window_minutes * 4) :]:
                    if ts_idx < 0:
                        break
                    parts = r.split(",")
                    if len(parts) <= max(ts_idx, pred_idx, mdl_idx, hor_idx):
                        continue
                    if parts[hor_idx] != str(horizon):
                        continue
                    if ens_models and parts[mdl_idx] not in ens_models:
                        continue
                    ems = _to_epoch_ms(parts[ts_idx])
                    if ems is None or ems < cutoff_ms:
                        continue
                    b = (ems // bucket_ms) * bucket_ms
                    try:
                        pv = float(parts[pred_idx])
                    except Exception:
                        continue
                    vals_by_bucket.setdefault(b, []).append(pv)
                # Compute std per bucket
                try:
                    import math
                except Exception:
                    math = None  # type: ignore
                for b, vs in vals_by_bucket.items():
                    if len(vs) >= 2:
                        if math is not None:
                            mean = sum(vs) / len(vs)
                            var = sum((x - mean) ** 2 for x in vs) / (len(vs) - 1)
                            dis_by_bucket[b] = (var ** 0.5)
                        else:
                            dis_by_bucket[b] = 0.0
            except Exception:
                dis_by_bucket = {}

        # Optional: compute move stats once for window and reuse per row
        move_stats_row: list[str] | None = None
        if include_move_stats:
            try:
                mv_fp = (_project_root() / "data" / "ml" / "live_predictions") / f"{idx_norm}_move.csv"
                if mv_fp.exists():
                    lines_mv = mv_fp.read_text(encoding="utf-8").splitlines()
                    if lines_mv:
                        cols_mv = lines_mv[0].split(",")
                        try:
                            mv_ts = cols_mv.index("timestamp")
                            mv_prob = cols_mv.index("move_prob")
                            mv_lbl = cols_mv.index("move_label_pred")
                            mv_mag = cols_mv.index("conditional_magnitude")
                            mv_hor = cols_mv.index("horizon")
                        except Exception:
                            mv_ts = mv_prob = mv_lbl = mv_mag = mv_hor = -1
                        now_ms_mv = int(_dt.datetime.now(tz=_dt.timezone.utc).timestamp() * 1000)
                        cutoff_mv = now_ms_mv - window_minutes * 60_000
                        probs: list[float] = []
                        mags_on_pred: list[float] = []
                        last_prob: Optional[float] = None
                        last_mag: Optional[float] = None
                        hi_count = 0
                        total = 0
                        # scan reasonable tail
                        for r in lines_mv[-max(5000, window_minutes * 4):]:
                            parts = r.split(",")
                            if mv_ts < 0 or len(parts) <= max(mv_ts, mv_prob, mv_lbl, mv_mag, mv_hor):
                                continue
                            if parts[mv_hor] != str(horizon):
                                continue
                            # parse timestamp (reuse simple logic here)
                            ems = None
                            try:
                                s = parts[mv_ts].strip()
                                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M:%S"):
                                    try:
                                        dt = _dt.datetime.strptime(s, fmt)
                                        ems = int(dt.timestamp() * 1000)
                                        break
                                    except Exception:
                                        continue
                                if ems is None and s.isdigit():
                                    ems = int(s[:13]) if len(s) >= 13 else int(s) * 1000
                            except Exception:
                                ems = None
                            if ems is None or ems < cutoff_mv:
                                continue
                            try:
                                p = float(parts[mv_prob])
                            except Exception:
                                p = None  # type: ignore
                            try:
                                lbl = int(parts[mv_lbl])
                            except Exception:
                                lbl = 0
                            try:
                                mag = float(parts[mv_mag])
                            except Exception:
                                mag = None  # type: ignore
                            total += 1
                            if isinstance(p, (int, float)):
                                probs.append(float(p))
                                if p >= move_prob_threshold:
                                    hi_count += 1
                                last_prob = float(p)
                            if lbl == 1 and isinstance(mag, (int, float)):
                                mags_on_pred.append(float(mag))
                                last_mag = float(mag)
                        def _pct_mv(vals: list[float], q: float) -> float:
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
                        p10 = _pct_mv(mags_on_pred, 0.10)
                        p50 = _pct_mv(mags_on_pred, 0.50)
                        p90 = _pct_mv(mags_on_pred, 0.90)
                        move_stats_row = [
                            (f"{avg_prob:.4f}" if count else ""),
                            (f"{hi_share:.4f}" if total else ""),
                            (f"{p10:.4f}" if mags_on_pred else ""),
                            (f"{p50:.4f}" if mags_on_pred else ""),
                            (f"{p90:.4f}" if mags_on_pred else ""),
                            (f"{last_prob:.4f}" if isinstance(last_prob, (int, float)) else ""),
                            (f"{last_mag:.4f}" if isinstance(last_mag, (int, float)) else ""),
                        ]
            except Exception:
                move_stats_row = None

        def _corr(xs: list[float], ys: list[float]) -> float:
            try:
                import math
                n = len(xs)
                if n < 3:
                    return float("nan")
                mean_x = sum(xs) / n
                mean_y = sum(ys) / n
                cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / (n - 1)
                var_x = sum((x - mean_x) ** 2 for x in xs) / (n - 1)
                var_y = sum((y - mean_y) ** 2 for y in ys) / (n - 1)
                if var_x <= 0 or var_y <= 0:
                    return float("nan")
                return cov / math.sqrt(var_x * var_y)
            except Exception:
                return float("nan")

        def _slope_per_hr(ts_ms: list[int], vals: list[float]) -> float:
            # simple OLS slope (units per hour)
            try:
                n = len(ts_ms)
                if n < 2:
                    return float("nan")
                xs = [t / 3_600_000.0 for t in ts_ms]  # hours
                mean_x = sum(xs) / n
                mean_y = sum(vals) / n
                denom = sum((x - mean_x) ** 2 for x in xs)
                if denom == 0:
                    return float(0.0)
                numer = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, vals))
                return numer / denom
            except Exception:
                return float("nan")

        for mname, pmap in preds_map.items():
            keys = sorted(set(pmap.keys()) & set(tp_by_bucket.keys()))
            if not keys:
                # Sequence-aligned fallback if time-based join failed
                if seq_tp and (mname in seq_pred_by_model):
                    try:
                        import math
                        xs = list(seq_pred_by_model.get(mname, []))
                        ys = list(seq_tp)
                        n = min(len(xs), len(ys))
                        xs = xs[:n]
                        ys = ys[:n]
                        if n >= 3:
                            deltas = [a - b for a, b in zip(xs, ys)]
                            mae = sum(abs(d) for d in deltas) / n
                            rmse = math.sqrt(sum((d) ** 2 for d in deltas) / n)
                            bias_mean = sum(deltas) / n
                            sd = sorted(deltas)
                            mpos = n // 2
                            bias_median = sd[mpos] if n % 2 == 1 else 0.5 * (sd[mpos - 1] + sd[mpos])
                            # simple corr and slopes skipped in fallback; leave blanks
                            p10 = sd[int((n - 1) * 0.10)]
                            p90 = sd[int((n - 1) * 0.90)]
                            last_pred = xs[-1]
                            last_tp_v = ys[-1]
                            last_delta = last_pred - last_tp_v
                            row_parts = [
                                mname,
                                idx_norm,
                                str(horizon),
                                str(n),
                                f"{mae:.4f}",
                                f"{rmse:.4f}",
                                f"{bias_mean:.4f}",
                                f"{bias_median:.4f}",
                                "",  # corr
                                "",  # slope_pred_per_hr
                                "",  # slope_tp_per_hr
                                f"{p10:.4f}",
                                f"{p90:.4f}",
                                f"{last_pred:.4f}",
                                f"{last_tp_v:.4f}",
                                f"{last_delta:.4f}",
                                str(window_minutes),
                            ]
                            # Hybrid extras if applicable
                            if "sk_hgb_residual" in include_models:
                                if mname == "sk_hgb_residual":
                                    # compute baseline/hybrid rmse vs seq tp
                                    bxs = list(seq_hybrid_baseline)
                                    nb = min(len(bxs), len(ys))
                                    bxs = bxs[:nb]
                                    ys_b = ys[:nb]
                                    b_rmse = None
                                    if nb >= 3:
                                        bd = [a - b for a, b in zip(bxs, ys_b)]
                                        b_rmse = math.sqrt(sum((d) ** 2 for d in bd) / nb)
                                    h_rmse = rmse
                                    ratio = None
                                    try:
                                        if b_rmse and h_rmse and h_rmse > 0:
                                            ratio = b_rmse / h_rmse
                                    except Exception:
                                        ratio = None
                                    try:
                                        logger.debug(
                                            "DBG_HYBRID_FALLBACK %s",
                                            {
                                                "nb": nb,
                                                "len_seq_base": len(seq_hybrid_baseline),
                                                "len_seq_resid": len(seq_hybrid_residual),
                                                "len_seq_tp": len(seq_tp),
                                                "b_rmse": b_rmse,
                                                "h_rmse": h_rmse,
                                                "ratio": ratio,
                                            },
                                        )
                                    except Exception:
                                        pass
                                    row_parts.extend([
                                        (f"{b_rmse:.4f}" if isinstance(b_rmse, (int, float)) and b_rmse == b_rmse else ""),
                                        (f"{h_rmse:.4f}" if isinstance(h_rmse, (int, float)) and h_rmse == h_rmse else ""),
                                        (f"{ratio:.4f}" if isinstance(ratio, (int, float)) and ratio == ratio else ""),
                                        (f"{(bxs[-1] if bxs else float('nan')):.4f}" if bxs else ""),
                                        (f"{(seq_hybrid_residual[-1] if seq_hybrid_residual else float('nan')):.4f}" if seq_hybrid_residual else ""),
                                    ])
                                else:
                                    row_parts.extend(["", "", "", "", ""])  # blanks for non-hybrid
                            if include_bands:
                                row_parts.extend(["", ""])  # band radius, coverage
                                if include_effective_bands:
                                    row_parts.extend(["", "", ""])  # effective extras
                            if include_move_stats:
                                row_parts.extend(["", "", "", "", "", "", ""])  # move blanks
                            if len(row_parts) < expected_len:
                                row_parts.extend([""] * (expected_len - len(row_parts)))
                            try:
                                # Debug fallback hybrid diagnostics row (temporary instrumentation)
                                if mname == "sk_hgb_residual":
                                    logger.debug("DEBUG_DIAG_FALLBACK_ROW %s", row_parts)
                            except Exception:
                                pass
                            out.append(",".join(row_parts))
                            continue
                    except Exception:
                        pass
                # Build a row; attempt last-chance sequence-aligned metrics even if earlier guard failed
                seq_mae = seq_rmse = None
                seq_bias_mean = seq_bias_median = None
                seq_p10 = seq_p90 = None
                seq_last_pred = seq_last_tp = seq_last_delta = None
                if seq_tp and (mname in seq_pred_by_model):
                    try:
                        import math
                        xs = list(seq_pred_by_model.get(mname, []))
                        ys = list(seq_tp)
                        n2 = min(len(xs), len(ys))
                        xs = xs[:n2]
                        ys = ys[:n2]
                        if n2 >= 3:
                            dd = [a - b for a, b in zip(xs, ys)]
                            seq_mae = sum(abs(d) for d in dd) / n2
                            seq_rmse = math.sqrt(sum(d*d for d in dd) / n2)
                            seq_bias_mean = sum(dd) / n2
                            sdd = sorted(dd)
                            mid2 = n2 // 2
                            seq_bias_median = (sdd[mid2] if n2 % 2 == 1 else 0.5 * (sdd[mid2 - 1] + sdd[mid2]))
                            def _pct_last(vals: list[float], q: float) -> float:
                                if not vals:
                                    return float('nan')
                                s = sorted(vals)
                                k = (len(s) - 1) * q
                                f = int(k)
                                c = min(f + 1, len(s) - 1)
                                return s[f] if f == c else (s[f] + (s[c] - s[f]) * (k - f))
                            seq_p10 = _pct_last(dd, 0.10)
                            seq_p90 = _pct_last(dd, 0.90)
                            seq_last_pred = xs[-1]
                            seq_last_tp = ys[-1]
                            seq_last_delta = seq_last_pred - seq_last_tp
                    except Exception:
                        pass
                base_parts = [
                    mname,
                    idx_norm,
                    str(horizon),
                    "0",
                    (f"{seq_mae:.4f}" if isinstance(seq_mae, (int, float)) and seq_mae == seq_mae else ""),
                    (f"{seq_rmse:.4f}" if isinstance(seq_rmse, (int, float)) and seq_rmse == seq_rmse else ""),
                    (f"{seq_bias_mean:.4f}" if isinstance(seq_bias_mean, (int, float)) and seq_bias_mean == seq_bias_mean else ""),
                    (f"{seq_bias_median:.4f}" if isinstance(seq_bias_median, (int, float)) and seq_bias_median == seq_bias_median else ""),
                    "",
                    "",
                    "",
                    (f"{seq_p10:.4f}" if isinstance(seq_p10, (int, float)) and seq_p10 == seq_p10 else ""),
                    (f"{seq_p90:.4f}" if isinstance(seq_p90, (int, float)) and seq_p90 == seq_p90 else ""),
                    (f"{seq_last_pred:.4f}" if isinstance(seq_last_pred, (int, float)) and seq_last_pred == seq_last_pred else ""),
                    (f"{seq_last_tp:.4f}" if isinstance(seq_last_tp, (int, float)) and seq_last_tp == seq_last_tp else ""),
                    (f"{seq_last_delta:.4f}" if isinstance(seq_last_delta, (int, float)) and seq_last_delta == seq_last_delta else ""),
                    str(window_minutes),
                ]
                # Hybrid extras (5 columns) only if header includes them
                if "sk_hgb_residual" in include_models:
                    if mname == "sk_hgb_residual":
                        # compute baseline/hybrid rmse vs seq tp if possible
                        b_rmse_v = h_rmse_v = ratio_v = None
                        last_base_v = last_resid_v = None
                        try:
                            import math
                            ys = list(seq_tp)
                            bxs = list(seq_hybrid_baseline)
                            xs = list(seq_pred_by_model.get(mname, []))
                            n3 = min(len(bxs), len(ys))
                            if n3 >= 3:
                                bd = [bxs[i] - ys[i] for i in range(n3)]
                                b_rmse_v = math.sqrt(sum(d*d for d in bd) / n3)
                            n4 = min(len(xs), len(ys))
                            if n4 >= 3:
                                dd2 = [xs[i] - ys[i] for i in range(n4)]
                                h_rmse_v = math.sqrt(sum(d*d for d in dd2) / n4)
                            if isinstance(b_rmse_v, (int, float)) and isinstance(h_rmse_v, (int, float)) and h_rmse_v > 0:
                                ratio_v = b_rmse_v / h_rmse_v
                            if seq_hybrid_baseline:
                                last_base_v = seq_hybrid_baseline[-1]
                            if seq_hybrid_residual:
                                last_resid_v = seq_hybrid_residual[-1]
                        except Exception:
                            pass
                        # Ultimate direct-file fallback if still missing
                        if (not isinstance(b_rmse_v, (int, float)) or b_rmse_v == 0 or not (b_rmse_v == b_rmse_v)) and hybrid_fp.exists():
                            try:
                                h_lines3 = hybrid_fp.read_text(encoding="utf-8").splitlines()
                                if len(h_lines3) > 1:
                                    hc = h_lines3[0].split(",")
                                    _p = hc.index("prediction") if "prediction" in hc else -1
                                    _b = hc.index("baseline") if "baseline" in hc else -1
                                    preds_arr: list[float] = []
                                    bases_arr: list[float] = []
                                    for _r in h_lines3[1:]:
                                        _parts = _r.split(",")
                                        try:
                                            if _p >= 0 and len(_parts) > _p:
                                                preds_arr.append(float(_parts[_p]))
                                            if _b >= 0 and len(_parts) > _b:
                                                bases_arr.append(float(_parts[_b]))
                                        except Exception:
                                            continue
                                    # Build tp array from live_rows
                                    tp_arr: list[float] = []
                                    for row in live_rows:
                                        try:
                                            tp_raw = row.get("tp")
                                            tp_val = float(tp_raw) if tp_raw is not None else None
                                        except Exception:
                                            tp_val = None
                                        if isinstance(tp_val, (int, float)):
                                            tp_arr.append(float(tp_val))
                                    import math as _m
                                    n_b = min(len(bases_arr), len(tp_arr))
                                    if n_b >= 3:
                                        bd = [bases_arr[i] - tp_arr[i] for i in range(n_b)]
                                        b_rmse_v = _m.sqrt(sum(d*d for d in bd) / n_b)
                                    n_h = min(len(preds_arr), len(tp_arr))
                                    if n_h >= 3:
                                        dd = [preds_arr[i] - tp_arr[i] for i in range(n_h)]
                                        h_rmse_v = _m.sqrt(sum(d*d for d in dd) / n_h)
                                    if isinstance(b_rmse_v, (int, float)) and isinstance(h_rmse_v, (int, float)) and h_rmse_v > 0:
                                        ratio_v = b_rmse_v / h_rmse_v
                            except Exception:
                                pass
                        base_parts.extend([
                            (f"{b_rmse_v:.4f}" if isinstance(b_rmse_v, (int, float)) and b_rmse_v == b_rmse_v else ""),
                            (f"{h_rmse_v:.4f}" if isinstance(h_rmse_v, (int, float)) and h_rmse_v == h_rmse_v else ""),
                            (f"{ratio_v:.4f}" if isinstance(ratio_v, (int, float)) and ratio_v == ratio_v else ""),
                            (f"{last_base_v:.4f}" if isinstance(last_base_v, (int, float)) and last_base_v == last_base_v else ""),
                            (f"{last_resid_v:.4f}" if isinstance(last_resid_v, (int, float)) and last_resid_v == last_resid_v else ""),
                        ])
                    else:
                        base_parts.extend(["", "", "", "", ""])  # non-hybrid rows
                # Bands
                if include_bands:
                    base_parts.extend(["", ""])  # band_radius,coverage_estimate
                    if include_effective_bands:
                        base_parts.extend(["", "", ""])  # effective_cov_estimate,effective_radius_avg,effective_radius_last
                # Move stats
                if include_move_stats:
                    base_parts.extend(["", "", "", "", "", "", ""])  # 7 move stat columns
                # Pad to header length defensively
                if len(base_parts) < expected_len:
                    base_parts.extend([""] * (expected_len - len(base_parts)))
                out.append(",".join(base_parts))
                continue
            preds = [pmap[k] for k in keys]
            tps = [tp_by_bucket[k] for k in keys]
            deltas = [a - b for a, b in zip(preds, tps)]
            # Metrics
            import math
            n = len(keys)
            mae = sum(abs(d) for d in deltas) / n
            rmse = math.sqrt(sum((d) ** 2 for d in deltas) / n)
            bias_mean = sum(deltas) / n
            sorted_d = sorted(deltas)
            mid = n // 2
            if n % 2 == 1:
                bias_median = sorted_d[mid]
            else:
                bias_median = 0.5 * (sorted_d[mid - 1] + sorted_d[mid])
            corr = _corr(preds, tps)
            slope_pred = _slope_per_hr(keys, preds)
            slope_tp = _slope_per_hr(keys, tps)
            # percentiles
            def _pct(vals: list[float], p: float) -> float:
                if not vals:
                    return float("nan")
                s = sorted(vals)
                k = (len(s) - 1) * p
                f = int(k)
                c = min(f + 1, len(s) - 1)
                if f == c:
                    return s[f]
                return s[f] + (s[c] - s[f]) * (k - f)

            p10 = _pct(deltas, 0.10)
            p90 = _pct(deltas, 0.90)
            last_k = keys[-1]
            last_pred = pmap[last_k]
            last_tp = tp_by_bucket[last_k]
            last_delta = last_pred - last_tp
            # Hybrid extras (only for hybrid residual model)
            baseline_rmse = hybrid_rmse = improv_ratio = None
            last_base = last_resid = None
            if mname == "sk_hgb_residual":
                # Compute baseline RMSE on overlapping keys where baseline is present
                b_keys = [k for k in keys if k in hybrid_baseline_by_bucket]
                if b_keys:
                    b_deltas = [hybrid_baseline_by_bucket[k] - tp_by_bucket[k] for k in b_keys]
                    if b_deltas:
                        baseline_rmse = math.sqrt(sum((d) ** 2 for d in b_deltas) / len(b_deltas))
                    hybrid_rmse = rmse  # already computed from hybrid preds
                    try:
                        if hybrid_rmse and hybrid_rmse > 0:
                            improv_ratio = baseline_rmse / hybrid_rmse  # >1 means hybrid improves over baseline
                    except Exception:
                        improv_ratio = None
                    # last baseline/residual if present
                    if last_k in hybrid_baseline_by_bucket:
                        try:
                            last_base = float(hybrid_baseline_by_bucket[last_k])
                        except Exception:
                            last_base = None
                    if last_k in hybrid_residual_by_bucket:
                        try:
                            last_resid = float(hybrid_residual_by_bucket[last_k])
                        except Exception:
                            last_resid = None
                # If overlapping-key computation unavailable or NaN, fall back to sequence-aligned RMSE
                def _seq_rmse(xs: list[float], ys: list[float]) -> float | None:
                    try:
                        n = min(len(xs), len(ys))
                        if n < 3:
                            return None
                        xs2 = xs[:n]
                        ys2 = ys[:n]
                        dd = [(a - b) for a, b in zip(xs2, ys2)]
                        return math.sqrt(sum((d) ** 2 for d in dd) / n)
                    except Exception:
                        return None
                try:
                    if (not isinstance(baseline_rmse, (int, float)) or not (baseline_rmse == baseline_rmse)):
                        b_rmse_seq = _seq_rmse(list(seq_hybrid_baseline), list(seq_tp))
                        if isinstance(b_rmse_seq, (int, float)) and b_rmse_seq == b_rmse_seq:
                            baseline_rmse = b_rmse_seq
                    if (not isinstance(hybrid_rmse, (int, float)) or not (hybrid_rmse == hybrid_rmse)):
                        h_rmse_seq = _seq_rmse(list(seq_pred_by_model.get(mname, [])), list(seq_tp))
                        if isinstance(h_rmse_seq, (int, float)) and h_rmse_seq == h_rmse_seq:
                            hybrid_rmse = h_rmse_seq
                    # Ultimate fallback: parse full hybrid file if sequence lists empty
                    if (mname == "sk_hgb_residual" and (not isinstance(baseline_rmse, (int, float)) or baseline_rmse == 0.0)) and hybrid_fp.exists():
                        try:
                            h_lines2 = hybrid_fp.read_text(encoding="utf-8").splitlines()
                            if len(h_lines2) > 1:
                                h_cols2 = h_lines2[0].split(",")
                                try:
                                    _h_pred = h_cols2.index("prediction")
                                    _h_base = h_cols2.index("baseline") if "baseline" in h_cols2 else -1
                                    _h_resid = h_cols2.index("residual") if "residual" in h_cols2 else -1
                                except Exception:
                                    _h_pred = _h_base = _h_resid = -1
                                bases_seq: list[float] = []
                                hybrid_seq: list[float] = []
                                for _r in h_lines2[1:]:
                                    _parts = _r.split(",")
                                    if _h_pred < 0 or len(_parts) <= _h_pred:
                                        continue
                                    try:
                                        hybrid_seq.append(float(_parts[_h_pred]))
                                    except Exception:
                                        continue
                                    if _h_base >= 0 and len(_parts) > _h_base:
                                        try:
                                            bases_seq.append(float(_parts[_h_base]))
                                        except Exception:
                                            pass
                                # Compute direct baseline rmse if possible (baseline vs tp joined by position)
                                if not seq_tp:
                                    for row in live_rows:
                                        try:
                                            tp_raw = row.get("tp")
                                            tp_val = float(tp_raw) if tp_raw is not None else None
                                        except Exception:
                                            tp_val = None
                                        if isinstance(tp_val, (int, float)):
                                            seq_tp.append(float(tp_val))
                                # Positional RMSE baseline
                                pos_n = min(len(bases_seq), len(seq_tp))
                                if pos_n >= 3 and (not isinstance(baseline_rmse, (int, float)) or baseline_rmse == 0.0):
                                    pos_dd = [(bases_seq[i] - seq_tp[i]) for i in range(pos_n)]
                                    try:
                                        baseline_rmse = math.sqrt(sum(d*d for d in pos_dd) / pos_n)
                                    except Exception:
                                        pass
                                # Build seq_tp if still empty (no cutoff)
                                # (Already handled positional collection above)
                                b_rmse_seq2 = _seq_rmse(bases_seq, list(seq_tp))
                                h_rmse_seq2 = _seq_rmse(hybrid_seq, list(seq_tp))
                                if isinstance(b_rmse_seq2, (int, float)) and b_rmse_seq2 == b_rmse_seq2:
                                    baseline_rmse = b_rmse_seq2
                                if isinstance(h_rmse_seq2, (int, float)) and h_rmse_seq2 == h_rmse_seq2 and (not isinstance(hybrid_rmse, (int, float)) or hybrid_rmse == hybrid_rmse):
                                    hybrid_rmse = h_rmse_seq2 or hybrid_rmse
                                if isinstance(baseline_rmse, (int, float)) and isinstance(hybrid_rmse, (int, float)) and hybrid_rmse > 0:
                                    improv_ratio = baseline_rmse / hybrid_rmse
                                if last_base is None and bases_seq:
                                    try:
                                        last_base = float(bases_seq[-1])
                                    except Exception:
                                        pass
                                if last_resid is None and _h_resid >= 0 and len(h_lines2) > 1:
                                    try:
                                        # reuse residual sequence if needed
                                        last_resid = float(h_lines2[-1].split(",")[_h_resid])
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                    if (isinstance(baseline_rmse, (int, float)) and baseline_rmse == baseline_rmse
                        and isinstance(hybrid_rmse, (int, float)) and hybrid_rmse == hybrid_rmse and hybrid_rmse > 0):
                        improv_ratio = baseline_rmse / hybrid_rmse
                    # Last values fallback
                    if last_base is None and seq_hybrid_baseline:
                        try:
                            last_base = float(seq_hybrid_baseline[-1])
                        except Exception:
                            last_base = None
                    if last_resid is None and seq_hybrid_residual:
                        try:
                            last_resid = float(seq_hybrid_residual[-1])
                        except Exception:
                            last_resid = None
                except Exception:
                    pass
            # Optional conformal band computation per model
            band_radius = None
            cov_est = None
            if include_bands:
                abs_res = [abs(d) for d in deltas]
                if abs_res:
                    s = sorted(abs_res)
                    q = min(max(coverage, 0.5), 0.99)
                    kf = (len(s) - 1) * q
                    fi = int(kf)
                    ci = min(fi + 1, len(s) - 1)
                    band_radius = s[fi] if fi == ci else (s[fi] + (s[ci] - s[fi]) * (kf - fi))
                    inside = sum(1 for r in abs_res if r <= band_radius)
                    cov_est = inside / len(abs_res)
                    # Effective bands coverage: radius_e(b) = max(band_radius, k * dis[b])
                    if include_effective_bands:
                        kfac = float(disagreement_k)
                        eff_inside = 0
                        eff_radii: list[float] = []
                        for i, k_b in enumerate(keys):
                            r = abs_res[i]
                            dis_b = float(dis_by_bucket.get(k_b, 0.0))
                            rad_b = band_radius if band_radius is not None else 0.0
                            eff_r = max(float(rad_b), kfac * dis_b)
                            eff_radii.append(eff_r)
                            if r <= eff_r:
                                eff_inside += 1
                        eff_cov = eff_inside / len(abs_res) if abs_res else float("nan")
                        eff_avg = (sum(eff_radii) / len(eff_radii)) if eff_radii else float("nan")
                        eff_last = (eff_radii[-1] if eff_radii else float("nan"))

            row_parts = [
                mname,
                idx_norm,
                str(horizon),
                str(n),
                f"{mae:.4f}",
                f"{rmse:.4f}",
                f"{bias_mean:.4f}",
                f"{bias_median:.4f}",
                f"{corr:.4f}" if corr == corr else "",
                f"{slope_pred:.4f}",
                f"{slope_tp:.4f}",
                f"{p10:.4f}",
                f"{p90:.4f}",
                f"{last_pred:.4f}",
                f"{last_tp:.4f}",
                f"{last_delta:.4f}",
                str(window_minutes),
            ]
            # Append hybrid extras if header includes them
            if "sk_hgb_residual" in include_models:
                if mname == "sk_hgb_residual":
                    row_parts.extend([
                        (f"{baseline_rmse:.4f}" if isinstance(baseline_rmse, (int, float)) and baseline_rmse == baseline_rmse else ""),
                        (f"{hybrid_rmse:.4f}" if isinstance(hybrid_rmse, (int, float)) and hybrid_rmse == hybrid_rmse else f"{rmse:.4f}"),
                        (f"{improv_ratio:.4f}" if isinstance(improv_ratio, (int, float)) and improv_ratio == improv_ratio else ""),
                        (f"{last_base:.4f}" if isinstance(last_base, (int, float)) else ""),
                        (f"{last_resid:.4f}" if isinstance(last_resid, (int, float)) else ""),
                    ])
                else:
                    # non-hybrid model: blanks for hybrid columns
                    row_parts.extend(["", "", "", "", ""])            
            if include_bands:
                row_parts.append(f"{(band_radius if band_radius is not None else float('nan')):.4f}")
                row_parts.append(f"{(cov_est if cov_est is not None else float('nan')):.4f}")
                if include_effective_bands:
                    try:
                        row_parts.append(f"{eff_cov:.4f}")
                        row_parts.append(f"{eff_avg:.4f}")
                        row_parts.append(f"{eff_last:.4f}")
                    except Exception:
                        row_parts.extend(["", "", ""])            
            if include_move_stats:
                if move_stats_row is not None:
                    row_parts.extend(move_stats_row)
                else:
                    # append blanks for move columns
                    row_parts.extend(["", "", "", "", "", "", ""])
            # Pad to header length defensively to avoid mismatches
            if len(row_parts) < expected_len:
                row_parts.extend([""] * (expected_len - len(row_parts)))
            out.append(",".join(row_parts))

        return PlainTextResponse("\n".join(out), media_type="text/csv")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/ml/move_stats")
async def api_ml_move_stats(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
    horizon: str = Query("1", description="Horizon label to select (string)"),
    window_minutes: int = Query(180, ge=5, le=24 * 60, description="Lookback window in minutes"),
    prob_threshold: float = Query(0.6, ge=0.0, le=1.0, description="Threshold to consider a 'high probability' move"),
    tail: int = Query(5000, ge=10, le=200000, description="Max rows to read from tail of file for efficiency"),
) -> PlainTextResponse:
    """Summarize move signal stream over a recent window.

    Input source: data/ml/live_predictions/<INDEX>_move.csv with columns
      timestamp,move_prob,move_label_pred,conditional_magnitude,model,index,horizon

    Output columns:
      index,horizon,count,avg_probability,high_prob_share,mag_p10,mag_p50,mag_p90,last_prob,last_mag,window_minutes
    """
    try:
        idx_norm = (index or "NIFTY").strip().upper()
        if any(ch in idx_norm for ch in ("$", "{", "}")):
            idx_norm = "NIFTY"

        base = _project_root() / "data" / "ml" / "live_predictions"
        fp = base / f"{idx_norm}_move.csv"
        if not fp.exists():
            raise HTTPException(status_code=404, detail=f"move file not found: {fp}")

        lines = fp.read_text(encoding="utf-8").splitlines()
        if not lines:
            return PlainTextResponse(
                "index,horizon,count,avg_probability,high_prob_share,mag_p10,mag_p50,mag_p90,last_prob,last_mag,window_minutes\n",
                media_type="text/csv",
            )

        header = lines[0].split(",")
        try:
            ts_idx = header.index("timestamp")
            prob_idx = header.index("move_prob")
            lbl_idx = header.index("move_label_pred")
            mag_idx = header.index("conditional_magnitude")
            hor_idx = header.index("horizon")
        except Exception:
            raise HTTPException(status_code=500, detail="malformed move CSV header")

        # Helpers
        def _to_epoch_ms(s: str) -> int | None:
            try:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M:%S"):
                    try:
                        dt = _dt.datetime.strptime(s.strip(), fmt)
                        return int(dt.timestamp() * 1000)
                    except Exception:
                        continue
                s2 = s.strip()
                if s2.isdigit():
                    if len(s2) >= 13:
                        return int(s2[:13])
                    return int(s2) * 1000
            except Exception:
                pass
            return None

        now_ms = int(_dt.datetime.now(tz=_dt.timezone.utc).timestamp() * 1000)
        cutoff_ms = now_ms - window_minutes * 60_000

        probs: list[float] = []
        mags_on_pred: list[float] = []
        last_prob: Optional[float] = None
        last_mag: Optional[float] = None
        hi_count = 0
        total = 0

        for r in lines[-tail:]:
            parts = r.split(",")
            if len(parts) <= max(ts_idx, prob_idx, lbl_idx, mag_idx, hor_idx):
                continue
            if parts[hor_idx] != str(horizon):
                continue
            ems = _to_epoch_ms(parts[ts_idx])
            if ems is None or ems < cutoff_ms:
                continue
            try:
                p = float(parts[prob_idx])
            except Exception:
                p = None  # type: ignore
            try:
                lbl = int(parts[lbl_idx])
            except Exception:
                lbl = 0
            try:
                mag = float(parts[mag_idx])
            except Exception:
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/ml/move_stats_archive")
async def api_ml_move_stats_archive(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
    horizon: str = Query("1", description="Horizon label to select (string)"),
    days: int = Query(3, ge=1, le=30, description="Number of past days to include"),
    tail: int = Query(5000, ge=10, le=200000, description="Max rows per daily file"),
) -> PlainTextResponse:
    """Return concatenated historical move stats rows from snapshot CSVs.

    Source files: data/ml/live_predictions/snapshots/<INDEX>_move_YYYY-MM-DD.csv

    Output columns mirror live move file:
      timestamp,move_prob,move_label_pred,conditional_magnitude,model,index,horizon
    """
    try:
        idx_norm = (index or "NIFTY").strip().upper()
        if any(ch in idx_norm for ch in ("$", "{", "}")):
            idx_norm = "NIFTY"
        base = _project_root() / "data" / "ml" / "live_predictions" / "snapshots"
        if not base.exists():
            raise HTTPException(status_code=404, detail="snapshot directory not found")
        # gather files for last N days
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
                lines = fp.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            if not lines:
                continue
            # assume first line header
            data_lines = lines[1:]
            if tail and len(data_lines) > tail:
                data_lines = data_lines[-tail:]
            # Filter by horizon column if present
            # Determine positions from header
            hcols = lines[0].split(",")
            try:
                hor_idx = hcols.index("horizon")
            except Exception:
                hor_idx = -1
            for r in data_lines:
                parts = r.split(",")
                if hor_idx >= 0 and len(parts) > hor_idx and parts[hor_idx] != str(horizon):
                    continue
                out_rows.append(r)
        out_rows.sort()  # chronological sort by timestamp string (ISO format assumption)
        return PlainTextResponse("\n".join([header, *out_rows]), media_type="text/csv")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
