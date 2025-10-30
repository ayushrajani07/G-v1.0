from __future__ import annotations
# ruff: noqa: I001

import asyncio
import zlib
import datetime as _dt
import time as _time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, ORJSONResponse

from src.error_handling import ErrorCategory, ErrorSeverity, get_error_handler
from ..core.config import MAX_CONCURRENCY as _MAX_CONCURRENCY
from ..core.csv_io import (
    find_live_csv as _find_live_csv,
    load_csv_rows_full as _load_csv_rows_full,
)
from ..core.obs import obs_begin as _obs_begin, obs_end as _obs_end, obs_too_many as _obs_too_many
from ..core.paths import project_root as _project_root


router = APIRouter()

# Concurrency guard (back-pressure for heavy endpoints)
_SEM = asyncio.Semaphore(max(1, _MAX_CONCURRENCY))


def _parse_bool_flag(v: str | None, default: bool = True) -> bool:
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in ("1", "true", "t", "yes", "y", "on"):
        return True
    if s in ("0", "false", "f", "no", "n", "off"):
        return False
    return default


@router.get("/api/live_csv")
async def api_live_csv(
    request: Request,
    # Make index optional with a safe default to avoid 422 during probe/inspector/test calls
    index: str | None = Query(default="NIFTY"),
    expiry_tag: str | None = None,
    offset: str | None = None,
    date_str: str | None = None,
    limit: int | None = None,
    from_ms: int | None = None,
    to_ms: int | None = None,
    # Friendly aliases that Grafana/Infinity sometimes use
    # Accept either epoch-ms integers or strings (e.g., 'now-6h') forwarded by Grafana/Infinity
    frm: int | str | None = Query(default=None, alias="from"),
    to_q: int | str | None = Query(default=None, alias="to"),
    no_cache: str | None = None,
    include_avg: str | None = None,
    include_ce: str | None = None,
    include_pe: str | None = None,
    include_index: str | None = None,
    index_pct: str | None = None,
    include_iv: str | None = None,
    include_greeks: str | None = None,
    include_analytics: str | None = None,
    indices: str | None = None,
) -> JSONResponse:
    """Return today's live CSV as JSON rows for Infinity.

    Returns array of objects with: time, ts, tp, avg_tp (and optional ce/pe/index_price/iv/greeks).
    """
    t0 = _obs_begin("live_csv")
    acquired = False
    try:
        # Acquire semaphore very briefly; if saturated, respond 429 quickly
        try:
            await asyncio.wait_for(_SEM.acquire(), timeout=0.002)
            acquired = True
        except Exception:
            _obs_too_many("live_csv")
            return JSONResponse(
                {"error": "too_many_requests", "retry_after": 1},
                status_code=429,
                headers={"Retry-After": "1"},
            )

        base = _project_root() / "data" / "g6_data"
        # Provide sensible defaults to avoid 422 on ad-hoc Explore queries
        expiry_tag = (expiry_tag or "this_week").strip()
        offset = (offset or "0").strip()
        # Only adopt numeric epoch-ms; ignore strings like 'now-6h' to avoid 422 and let panel time range be handled client-side
        if from_ms is None and isinstance(frm, int):
            from_ms = frm
        if to_ms is None and isinstance(to_q, int):
            to_ms = to_q
        day = (
            _dt.datetime.strptime(date_str, "%Y-%m-%d").date()
            if (date_str and date_str.strip())
            else _dt.datetime.now(_dt.UTC).date()
        )

        # Multi-index selection
        idx_list: list[str] | None = None
        if indices and str(indices).strip():
            idx_list = [s.strip().upper() for s in str(indices).split(",") if s.strip()]
        elif index is not None and "," in index:
            idx_list = [s.strip().upper() for s in index.split(",") if s.strip()]

        # Flags
        disable_cache = _parse_bool_flag(no_cache, False)
        inc_avg = _parse_bool_flag(include_avg, True)
        inc_ce = _parse_bool_flag(include_ce, True)
        inc_pe = _parse_bool_flag(include_pe, True)
        inc_index = _parse_bool_flag(include_index, True)
        inc_index_pct = _parse_bool_flag(index_pct, False)
        inc_analytics = _parse_bool_flag(include_analytics, False)
        inc_iv = _parse_bool_flag(include_iv, inc_analytics)
        inc_greeks = _parse_bool_flag(include_greeks, inc_analytics)

        def _find_with_fallback(_idx: str) -> Path | None:
            p = _find_live_csv(base, _idx, expiry_tag, offset, day)
            if p:
                return p
            if not date_str:
                from datetime import timedelta

                for delta in (1, 2, 3):
                    fallback = day - timedelta(days=delta)
                    q = _find_live_csv(base, _idx, expiry_tag, offset, fallback)
                    if q:
                        return q
            return None

        def _build_rows_for(_idx: str) -> tuple[list[dict[str, Any]], Path | None]:
            _path = _find_with_fallback(_idx)
            if not _path:
                raise HTTPException(
                    status_code=404,
                    detail=f"live csv not found for {_idx} {expiry_tag} {offset} {day}",
                )
            rows_full = _load_csv_rows_full(_path)
            keep_keys = {"time", "ts", "time_str", "time_epoch_s", "tp"}
            if inc_avg:
                keep_keys.add("avg_tp")
            if inc_ce:
                keep_keys.add("ce")
            if inc_pe:
                keep_keys.add("pe")
            if inc_index:
                keep_keys.add("index_price")
            if inc_iv:
                keep_keys.update({"ce_iv", "pe_iv"})
            if inc_greeks:
                keep_keys.update(
                    {
                        "ce_delta",
                        "pe_delta",
                        "ce_theta",
                        "pe_theta",
                        "ce_vega",
                        "pe_vega",
                        "ce_gamma",
                        "pe_gamma",
                        "ce_rho",
                        "pe_rho",
                    }
                )

            rows_sel = [{k: r.get(k, None) for k in keep_keys} for r in rows_full]
            # Time range filter
            if from_ms is not None or to_ms is not None:
                fms = from_ms if isinstance(from_ms, int) else None
                tms = to_ms if isinstance(to_ms, int) else None

                def _in_range(v: Any) -> bool:
                    try:
                        if v is None:
                            return False
                        x = int(v)
                    except Exception:
                        return False
                    if fms is not None and x < fms:
                        return False
                    if tms is not None and x > tms:
                        return False
                    return True

                rows_sel = [r for r in rows_sel if _in_range(r.get("ts"))]

            # Derive index_pct if requested
            if inc_index_pct:
                try:
                    base_val: float | None = None
                    for r in rows_sel:
                        v = r.get("index_price")
                        if isinstance(v, (int, float)):
                            base_val = float(v)
                            break
                    if base_val and base_val != 0.0:
                        for r in rows_sel:
                            v = r.get("index_price")
                            if isinstance(v, (int, float)):
                                r["index_pct"] = (float(v) / base_val - 1.0) * 100.0
                            else:
                                r["index_pct"] = None
                    else:
                        for r in rows_sel:
                            r["index_pct"] = None
                except Exception:
                    for r in rows_sel:
                        r["index_pct"] = None

            # Limit after filtering (keep most recent N rows)
            if isinstance(limit, int) and limit > 0 and len(rows_sel) > limit:
                rows_sel = rows_sel[-limit:]
            return rows_sel, _path

        headers: dict[str, str] = {}

        if idx_list:
            groups: dict[str, list[dict[str, Any]]] = {}
            etag_hasher = zlib.crc32(b"")
            lm_ns = 0
            for idx_name in idx_list:
                rows_i, pth = _build_rows_for(idx_name)
                groups[idx_name] = rows_i
                if pth and pth.exists():
                    st = pth.stat()
                    parts = (
                        str(pth).encode("utf-8"),
                        str(st.st_mtime_ns).encode("ascii"),
                        str(st.st_size).encode("ascii"),
                    )
                    for part in parts:
                        etag_hasher = zlib.crc32(part, etag_hasher)
                    lm_ns = max(lm_ns, int(st.st_mtime_ns))
            etag_key = f"W/\"multi-{etag_hasher:x}-{limit}-{from_ms}-{to_ms}\""
            headers["Cache-Control"] = "public, max-age=15, must-revalidate"
            headers["ETag"] = etag_key
            if lm_ns:
                try:
                    lm = _time.gmtime(lm_ns / 1_000_000_000)
                    headers["Last-Modified"] = _time.strftime("%a, %d %b %Y %H:%M:%S GMT", lm)
                except Exception:
                    pass
            inm = request.headers.get("if-none-match") if isinstance(request, Request) else None
            if (not disable_cache) and inm and inm == etag_key:
                _obs_end("live_csv", t0, ok=True)
                return JSONResponse(None, status_code=304, headers=headers)
            _obs_end("live_csv", t0, ok=True)
            return ORJSONResponse({"indices": groups}, headers=headers)
        else:
            rows, pth = _build_rows_for((index or "NIFTY").upper())
            etag_src = (
                f"{index}|{expiry_tag}|{offset}|{date_str}|{limit}|{from_ms}|{to_ms}|"
                f"{include_avg}|{include_ce}|{include_pe}|{include_index}|{index_pct}|"
                f"{include_iv}|{include_greeks}|{include_analytics}"
            ).encode()
            h = zlib.crc32(etag_src)
            if pth and pth.exists():
                st = pth.stat()
                h = zlib.crc32(str(st.st_mtime_ns).encode("ascii"), h)
                h = zlib.crc32(str(st.st_size).encode("ascii"), h)
                try:
                    lm = _time.gmtime(st.st_mtime_ns / 1_000_000_000)
                    headers["Last-Modified"] = _time.strftime("%a, %d %b %Y %H:%M:%S GMT", lm)
                except Exception:
                    pass
            headers["Cache-Control"] = "public, max-age=15, must-revalidate"
            headers["ETag"] = f"W/\"{h:x}\""
            inm = request.headers.get("if-none-match") if isinstance(request, Request) else None
            if (not disable_cache) and inm and inm == headers["ETag"]:
                _obs_end("live_csv", t0, ok=True)
                return JSONResponse(None, status_code=304, headers=headers)
            _obs_end("live_csv", t0, ok=True)
            return ORJSONResponse(rows, headers=headers)
    except HTTPException:
        _obs_end("live_csv", t0, ok=False)
        raise
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.FILE_IO,
            severity=ErrorSeverity.LOW,
            component="web.dashboard.routes.live",
            function_name="api_live_csv",
            message="Failed serving live CSV JSON",
            should_log=False,
        )
        _obs_end("live_csv", t0, ok=False)
        raise HTTPException(status_code=500, detail="live csv endpoint error") from None
    finally:
        if acquired:
            try:
                _SEM.release()
            except Exception:
                pass
