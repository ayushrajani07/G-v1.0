from __future__ import annotations
# ruff: noqa: I001

import asyncio
import csv
import time
import zlib as _z
from datetime import date, timedelta
import datetime as _dt
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, ORJSONResponse

from src.error_handling import ErrorCategory, ErrorSeverity, get_error_handler
from ..core.config import MAX_CONCURRENCY as _MAX_CONCURRENCY
from ..core.csv_io import find_overlay_csv as _find_overlay_csv, parse_time_any as _parse_time_any, parse_time_epoch_ms as _parse_time_epoch_ms
from ..core.obs import obs_begin as _obs_begin, obs_end as _obs_end, obs_too_many as _obs_too_many
from ..core.paths import project_root as _project_root


router = APIRouter()
_SEM = asyncio.Semaphore(max(1, _MAX_CONCURRENCY))


def _weekday_name_for(d: date) -> str:
    return [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ][d.weekday()]


def _parse_bool_flag(v: str | None, default: bool = True) -> bool:
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in ("1", "true", "t", "yes", "y", "on"):
        return True
    if s in ("0", "false", "f", "no", "n", "off"):
        return False
    return default


@router.get("/api/overlay")
async def api_overlay(
    request: Request,
    index: str,
    expiry_tag: str,
    offset: str,
    weekday: str | None = None,
    limit: int | None = None,
    no_cache: str | None = None,
) -> JSONResponse:
    t0 = _obs_begin("overlay")
    acquired = False
    try:
        try:
            await asyncio.wait_for(_SEM.acquire(), timeout=0.001)
            acquired = True
        except Exception:
            _obs_too_many("overlay")
            return JSONResponse(
                {"error": "too_many_requests", "retry_after": 1},
                status_code=429,
                headers={"Retry-After": "1"},
            )

        base = _project_root() / "data" / "weekday_master"
        disable_cache = _parse_bool_flag(no_cache, False)

        if not weekday:
            # Use IST (Indian Standard Time) for weekday determination
            # This ensures correct weekday matching for Indian market hours
            ist = _dt.timezone(timedelta(hours=5, minutes=30))
            weekday = _weekday_name_for(_dt.datetime.now(ist).date())
        weekday = str(weekday).capitalize()

        path = _find_overlay_csv(base, weekday, index, expiry_tag, offset)
        if not path:
            path = _find_overlay_csv(base, weekday, index.upper(), expiry_tag, offset)
        if not path:
            raise HTTPException(
                status_code=404,
                detail=f"overlay file not found for {weekday} {index} {expiry_tag} {offset}",
            )

        # Get today's date in IST for timestamp reconstruction
        today = _dt.datetime.now(_dt.timezone(timedelta(hours=5, minutes=30))).date()
        
        rows: list[dict[str, Any]] = []
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                # CSV has time-only (HH:MM:SS), combine with today's date
                time_str = str(r.get("timestamp", "")).strip()
                if time_str:
                    # Create full datetime string: "YYYY-MM-DD HH:MM:SS"
                    full_timestamp = f"{today} {time_str}"
                    ts = _parse_time_epoch_ms(full_timestamp)
                else:
                    ts = None
                obj: dict[str, Any] = {"time": ts}
                for col in ("tp_mean", "tp_ema", "avg_tp_mean", "avg_tp_ema"):
                    val = r.get(col)
                    if val is None or val == "":
                        obj[col] = None
                    else:
                        try:
                            obj[col] = float(val)
                        except Exception:
                            obj[col] = None
                rows.append(obj)

        if isinstance(limit, int) and limit > 0:
            rows = rows[:limit]

        headers: dict[str, str] = {"Cache-Control": "public, max-age=15, must-revalidate"}
        try:
            if path and path.exists():
                st = path.stat()
                lm = time.gmtime(st.st_mtime_ns / 1_000_000_000)
                headers["Last-Modified"] = time.strftime("%a, %d %b %Y %H:%M:%S GMT", lm)
                etag_src = f"{index}|{expiry_tag}|{offset}|{weekday}|{limit}|{st.st_mtime_ns}|{st.st_size}".encode()
                etag = _z.crc32(etag_src)
                headers["ETag"] = f"W/\"{etag:x}\""
                inm = request.headers.get("if-none-match") if isinstance(request, Request) else None
                if (not disable_cache) and inm and inm == headers["ETag"]:
                    _obs_end("overlay", t0, ok=True)
                    return JSONResponse(None, status_code=304, headers=headers)
        except Exception:
            pass

        resp = ORJSONResponse(rows, headers=headers)
        _obs_end("overlay", t0, ok=True)
        return resp
    except HTTPException:
        _obs_end("overlay", t0, ok=False)
        raise
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.FILE_IO,
            severity=ErrorSeverity.LOW,
            component="web.dashboard.routes.overlay",
            function_name="api_overlay",
            message="Failed serving overlay JSON",
            should_log=False,
        )
        _obs_end("overlay", t0, ok=False)
        raise HTTPException(status_code=500, detail="overlay endpoint error") from None
    finally:
        if acquired:
            try:
                _SEM.release()
            except Exception:
                pass
