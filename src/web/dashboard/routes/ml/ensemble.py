from __future__ import annotations

import asyncio
import datetime as _dt
import logging
from typing import Optional

from fastapi import HTTPException, Query, Body, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .._csv_time_columns import rebuild_time_time_ms_from_timestamp
from .._index_norm import normalize_index
from ._common import project_root as _project_root
from .._tabular_file import read_header_and_rows, tail_rows

logger = logging.getLogger(__name__)

# Optional centralized error handler (guarded import)
try:  # pragma: no cover
    from src.error_handling import (
        get_error_handler as _get_eh,
        ErrorCategory as _ErrCat,
        ErrorSeverity as _ErrSev,
    )  # type: ignore
except (ImportError, AttributeError):  # pragma: no cover
    _get_eh = None  # type: ignore

    class _ErrCat:  # type: ignore
        FILE_IO = "file_io"
        UNKNOWN = "unknown"

    class _ErrSev:  # type: ignore
        LOW = "low"
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
        idx_norm = normalize_index(index)

        base = _project_root() / "data" / "ml" / "live_predictions"
        fp = base / f"{idx_norm}_ensemble.csv"
        if not fp.exists():
            raise HTTPException(status_code=404, detail=f"ensemble file not found: {fp}")

        header, rows = read_header_and_rows(fp)
        if not header:
            return PlainTextResponse("", media_type="text/csv")

        rows = tail_rows(rows, tail)

        cols = header.split(",")
        header, rows = rebuild_time_time_ms_from_timestamp(header, rows)
        cols = header.split(",")

        if horizon or (not include_placeholders):
            try:
                idx_hor = cols.index("horizon")
            except ValueError:
                return PlainTextResponse("\n".join([header, *rows]), media_type="text/csv")

            try:
                src_idx = cols.index("applied_k_source")
            except ValueError:
                src_idx = -1
            filtered = []
            for r in rows:
                parts = r.split(",")
                if horizon and not (len(parts) > idx_hor and parts[idx_hor] == str(horizon)):
                    continue
                if not include_placeholders:
                    if src_idx >= 0 and len(parts) > src_idx and parts[src_idx] == "placeholder":
                        continue
                filtered.append(r)
            rows = filtered

        return PlainTextResponse("\n".join([header, *rows]), media_type="text/csv")
    except HTTPException:
        raise
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))


async def api_ml_ensemble_weights(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
    horizon: str = Query("1", description="Horizon label (the exporter is typically run per-horizon)"),
) -> PlainTextResponse:
    """Serve latest inverse-RMSE model weights from exporter sidecar as CSV.

    Source file: data/ml/live_predictions/<INDEX>_ensemble_weights.json

    Output columns: timestamp,model,weight,rmse,index,horizon
    """
    try:
        idx_norm = normalize_index(index)
        base = _project_root() / "data" / "ml" / "live_predictions"
        fp = base / f"{idx_norm}_ensemble_weights.json"
        if not fp.exists():
            raise HTTPException(status_code=404, detail=f"weights sidecar not found: {fp}")
        import json as _json

        try:
            obj = _json.loads(fp.read_text(encoding="utf-8"))
        except (_json.JSONDecodeError, UnicodeDecodeError, OSError, TypeError, ValueError) as e:
            raise HTTPException(status_code=500, detail=f"failed to parse weights JSON: {e}")
        ts = obj.get("timestamp")
        weights = obj.get("weights") or {}
        rmses = obj.get("rmse") or {}
        norm_weights: dict[str, float] = {}
        for k, v in weights.items():
            try:
                norm_weights[str(k)] = float(v)
            except (TypeError, ValueError):
                norm_weights[str(k)] = 0.0
        out = ["timestamp,model,weight,rmse,index,horizon"]
        keys = sorted(norm_weights.keys(), key=lambda k: (-(norm_weights.get(k) or 0.0), k))
        for m in keys:
            w = norm_weights.get(m, 0.0)
            try:
                r = float(rmses.get(m) or 0.0)
            except (TypeError, ValueError):
                r = 0.0
            out.append(f"{ts},{m},{w:.6f},{r:.6f},{idx_norm},{horizon}")
        try:
            logger.info("%s", "\n".join(out))
        except (OSError, ValueError, TypeError):
            pass
        return PlainTextResponse("\n".join(out), media_type="text/csv")
    except HTTPException:
        raise
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))


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
        idx_norm = normalize_index(index)
        base = _project_root() / "data" / "ml" / "live_predictions"
        fp = base / f"{idx_norm}_ensemble_quarantine.log"
        if not fp.exists():
            raise HTTPException(status_code=404, detail=f"quarantine log not found: {fp}")
        try:
            lines = fp.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as e:
            raise HTTPException(status_code=500, detail=f"failed to read quarantine log: {e}")
        out = ["timestamp,event,model,z,dis,until_ms,horizon"]
        valid_rows: list[str] = []
        for ln in lines:
            try:
                parts = [p.strip() for p in ln.split(",")]
                if len(parts) < 3:
                    continue
                ts_iso, ev, model = parts[0], parts[1], parts[2]
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
                row = ",".join([ts_iso, ev, model, z, dis, until_ms, h])
                if row.startswith("timestamp,event,model"):
                    continue
                valid_rows.append(row)
            except (TypeError, ValueError, IndexError):
                continue
        if tail and len(valid_rows) > tail:
            valid_rows = valid_rows[-tail:]
        out.extend(valid_rows)
        return PlainTextResponse("\n".join(out), media_type="text/csv")
    except HTTPException:
        raise
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))


async def api_ml_ensemble_k_calibration(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
    horizon: Optional[str] = Query(None, description="Horizon label to surface (optional filter)"),
) -> PlainTextResponse:
    """Serve latest auto-calibration sidecar for disagreement scaling k as CSV.

    Source file: data/ml/live_predictions/<INDEX>_ensemble_k_calibration.json

    Output columns: timestamp,recommended_k,effective_cov,band_radius,target,index,horizon,n
    """
    try:
        idx_norm = normalize_index(index)
        base = _project_root() / "data" / "ml" / "live_predictions"
        fp = base / f"{idx_norm}_ensemble_k_calibration.json"
        if not fp.exists():
            raise HTTPException(status_code=404, detail=f"k calibration sidecar not found: {fp}")
        import json as _json

        try:
            obj = _json.loads(fp.read_text(encoding="utf-8"))
        except (_json.JSONDecodeError, UnicodeDecodeError, OSError, TypeError, ValueError) as e:
            raise HTTPException(status_code=500, detail=f"failed to parse calibration JSON: {e}")
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
            header = "timestamp,recommended_k,k_smooth,effective_cov,band_radius,target,index,horizon,n"
            return PlainTextResponse(header + "\n", media_type="text/csv")
        header = "timestamp,recommended_k,k_smooth,effective_cov,band_radius,target,index,horizon,n"
        if k_smooth is not None:
            try:
                k_smooth_str = f"{float(k_smooth):.2f}"
            except (TypeError, ValueError):
                k_smooth_str = str(k_smooth)
        else:
            k_smooth_str = ""
        row = f"{ts},{rec_k},{k_smooth_str},{eff_cov},{band_radius},{target},{side_index},{side_horizon},{n}"
        return PlainTextResponse("\n".join([header, row]) + "\n", media_type="text/csv")
    except HTTPException:
        raise
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))


async def api_ml_ensemble_k_applied(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
    horizon: Optional[str] = Query(None, description="Horizon label to surface (optional filter)"),
    tail: int = Query(1, ge=1, le=1000, description="How many latest rows to return"),
    include_placeholders: bool = Query(
        False,
        description="Include placeholder rows (applied_k_source=placeholder) if true",
    ),
) -> PlainTextResponse:
    """Return latest applied_k values from ensemble CSV.

    Source: data/ml/live_predictions/<INDEX>_ensemble.csv

    Output columns: timestamp,applied_k,applied_k_source,scaled_radius,index,horizon
    """
    try:
        idx_norm = normalize_index(index)
        base = _project_root() / "data" / "ml" / "live_predictions"
        fp = base / f"{idx_norm}_ensemble.csv"
        if not fp.exists():
            raise HTTPException(status_code=404, detail=f"ensemble file not found: {fp}")

        header_line, data = read_header_and_rows(fp)
        if not header_line:
            return PlainTextResponse(
                "timestamp,applied_k,applied_k_source,scaled_radius,index,horizon\n",
                media_type="text/csv",
            )
        header = header_line.split(",")
        try:
            ts_idx = header.index("timestamp")
            k_idx = header.index("applied_k")
            src_idx = header.index("applied_k_source")
            rad_idx = header.index("scaled_radius")
            idx_idx = header.index("index")
            hor_idx = header.index("horizon")
        except ValueError:
            return PlainTextResponse(
                "timestamp,applied_k,applied_k_source,scaled_radius,index,horizon\n",
                media_type="text/csv",
            )
        if horizon is not None:
            data = [r for r in data if (len(r.split(",")) > hor_idx and r.split(",")[hor_idx] == str(horizon))]
        if not data:
            return PlainTextResponse(
                "timestamp,applied_k,applied_k_source,scaled_radius,index,horizon\n",
                media_type="text/csv",
            )
        if tail and len(data) > tail:
            data = data[-tail:]
        out = ["timestamp,applied_k,applied_k_source,scaled_radius,index,horizon"]
        for r in data:
            parts = r.split(",")
            if not include_placeholders:
                try:
                    src_val = parts[src_idx]
                except IndexError:
                    src_val = ""
                if src_val == "placeholder":
                    continue
            out.append(
                ",".join(
                    [
                        parts[ts_idx],
                        parts[k_idx],
                        parts[src_idx],
                        parts[rad_idx],
                        parts[idx_idx],
                        parts[hor_idx],
                    ]
                )
            )
        return PlainTextResponse("\n".join(out) + "\n", media_type="text/csv")
    except HTTPException:
        raise
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))


class KOverrideRequest(BaseModel):
    index: str
    horizon: str
    k: float
    ttl_minutes: Optional[int] = None
    actor: Optional[str] = None
    reason: Optional[str] = None
    classification: Optional[str] = None  # Override class: emergency|strategic|test|other


async def api_ml_ensemble_k_override(
    request: Request,
    payload: KOverrideRequest = Body(
        ...,
        description=(
            "Override payload with index,horizon,k, ttl_minutes(optional), and optional actor/reason/classification"
        ),
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
            except (_json.JSONDecodeError, UnicodeDecodeError, OSError, TypeError, ValueError):
                obj = {"overrides": {}}
        now_ms = int(_time.time() * 1000)
        exp = None
        if payload.ttl_minutes is not None and payload.ttl_minutes > 0:
            exp = int(now_ms + payload.ttl_minutes * 60_000)

        src_ip = None
        try:
            if request is not None and request.client is not None:
                src_ip = str(request.client.host)
        except (AttributeError, TypeError):
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
        except (OSError, IOError) as _e:
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
            except (AttributeError, TypeError, ValueError, RuntimeError):
                pass

        try:
            iso = _dt.datetime.now(tz=_dt.timezone.utc).replace(microsecond=0).isoformat()
            log_fp = base / f"{idx_norm}_ensemble_k_overrides.log"
            with log_fp.open("a", encoding="utf-8") as lf:
                extras = []
                if payload.actor:
                    extras.append(f"actor={payload.actor}")
                if payload.reason:
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
        except (OSError, IOError, UnicodeEncodeError) as _e:
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
            except (AttributeError, TypeError, ValueError, RuntimeError):
                pass
        return PlainTextResponse("ok\n", media_type="text/plain")
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))


async def api_ml_ensemble_k_overrides(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
):  # PlainTextResponse returned explicitly
    """List current overrides for an index as CSV.

    Output columns: horizon,k,expires_ms,created_ms,actor,reason,class,source_ip,index
    """
    try:
        idx_norm = normalize_index(index)
        base = _project_root() / "data" / "ml" / "live_predictions"
        fp = base / f"{idx_norm}_ensemble_k_overrides.json"
        import json as _json

        out = ["horizon,k,expires_ms,created_ms,actor,reason,class,source_ip,index"]
        if not fp.exists():
            return PlainTextResponse("\n".join(out) + "\n", media_type="text/csv")
        try:
            obj = _json.loads(fp.read_text(encoding="utf-8")) or {"overrides": {}}
        except (_json.JSONDecodeError, UnicodeDecodeError, OSError, TypeError, ValueError):
            return PlainTextResponse("\n".join(out) + "\n", media_type="text/csv")
        ovs = obj.get("overrides") or {}
        for h, meta in sorted(ovs.items(), key=lambda kv: str(kv[0])):
            try:
                k = float(meta.get("k")) if isinstance(meta.get("k"), (int, float)) else ""
            except (TypeError, ValueError, AttributeError):
                k = ""
            exp = meta.get("expires") if isinstance(meta.get("expires"), (int, float)) else ""
            created = meta.get("created") if isinstance(meta.get("created"), (int, float)) else ""
            actor = meta.get("actor") or ""
            reason = meta.get("reason") or ""
            cls = meta.get("class") or ""
            src_ip = meta.get("source_ip") or ""
            try:
                if isinstance(reason, str):
                    reason = reason.replace(",", ";")
            except AttributeError:
                pass
            out.append(f"{h},{k},{exp},{created},{actor},{reason},{cls},{src_ip},{idx_norm}")
        return PlainTextResponse("\n".join(out) + "\n", media_type="text/csv")
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))
