from __future__ import annotations
# ruff: noqa: I001

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

# Phase 2: Centralized environment variable access
from src.config.env_config import EnvConfig
from src.error_handling import ErrorCategory, ErrorSeverity, get_error_handler
from ..core.config import (
    CSV_CACHE_MAX as _CSV_CACHE_MAX,
    MAX_CONCURRENCY as _MAX_CONCURRENCY,
)
from ..core.obs import OBS as _OBS


router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    cache = getattr(request.app.state, "metrics_cache", None)
    snap = cache.snapshot() if cache else None
    status = "stale" if (snap and getattr(snap, "stale", False)) else "ok"
    return {"status": status, "age": getattr(snap, "age_seconds", None) if snap else None}


@router.get("/healthz")
async def healthz(request: Request) -> Response:
    """Ultra-light health probe: 204 when snapshot exists (not required to be fresh)."""
    cache = getattr(request.app.state, "metrics_cache", None)
    snap = cache.snapshot() if cache else None
    if snap is None:
        return Response(status_code=503)
    return Response(status_code=204)


@router.get("/api/info")
async def api_info() -> JSONResponse:
    """Return basic runtime info and selected settings for diagnostics."""
    try:
        graf_port = EnvConfig.get_str("G6_GRAFANA_PORT", "3002")
        cors_all = EnvConfig.get_str("G6_CORS_ALL", "0")
        web_workers = EnvConfig.get_str("G6_WEB_WORKERS", "1")
        return JSONResponse(
            {
                "version": "0.1.0",
                "grafana_port": graf_port,
                "cors_all": cors_all,
                "web_workers": web_workers,
                "csv_cache_max": _CSV_CACHE_MAX,
                "concurrency_limit": _MAX_CONCURRENCY,
            }
        )
    except Exception:
        return JSONResponse({"version": "0.1.0"})


@router.get("/api/version")
async def api_version() -> JSONResponse:
    return JSONResponse({"version": "0.1.0"})


def _norm_expiry(s: str | None) -> str:
    return (s or "").strip()


def _norm_offset(s: str | None) -> str:
    v = (s or "").strip()
    if not v:
        return v
    up = v.upper()
    if up == "ATM":
        return "0"
    try:
        if up.startswith("+") or up.startswith("-"):
            int(up)
            return up
        if up.isdigit():
            return f"+{up}"
    except Exception:
        pass
    return v


@router.get("/api/sync_check")
async def api_sync_check(
    expiry_tag_global: str,
    offset_global: str,
    expiry_tag_1: str,
    offset_1: str,
    expiry_tag_2: str,
    offset_2: str,
    expiry_tag_3: str,
    offset_3: str,
    expiry_tag_4: str,
    offset_4: str,
) -> JSONResponse:
    try:
        eg = _norm_expiry(expiry_tag_global)
        og = _norm_offset(offset_global)
        panels: list[dict[str, Any]] = []
        all_match = True
        for i, (et, off) in enumerate(
            [
                (expiry_tag_1, offset_1),
                (expiry_tag_2, offset_2),
                (expiry_tag_3, offset_3),
                (expiry_tag_4, offset_4),
            ],
            start=1,
        ):
            em = _norm_expiry(et)
            om = _norm_offset(off)
            match = (em == eg) and (om == og)
            panels.append({"panel": i, "expiry_tag": em, "offset": om, "match": 1 if match else 0})
            if not match:
                all_match = False
        result = [
            {
                "all_synced_int": 1 if all_match else 0,
                "all_synced_text": "ALL SYNCED" if all_match else "OUT OF SYNC",
                "details": panels,
            }
        ]
        return JSONResponse(result)
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.CONFIGURATION,
            severity=ErrorSeverity.LOW,
            component="web.dashboard.routes.system",
            function_name="api_sync_check",
            message="Failed serving sync check JSON",
            should_log=False,
        )
    raise HTTPException(status_code=500, detail="sync check error") from None


@router.get("/api/_stats")
async def api_stats() -> JSONResponse:
    out = {}
    try:
        for k, v in _OBS.items():
            cnt = float(v.get("count", 0))
            dur_sum = float(v.get("dur_ms_sum", 0.0))
            avg_ms = (dur_sum / cnt) if cnt > 0 else 0.0
            out[k] = {
                "count": int(v.get("count", 0)),
                "errors": int(v.get("errors", 0)),
                "too_many": int(v.get("too_many", 0)),
                "in_flight": int(v.get("in_flight", 0)),
                "avg_ms": round(avg_ms, 2),
                "max_ms": round(float(v.get("dur_ms_max", 0.0)), 2),
            }
    except Exception:
        pass
    out["concurrency_limit"] = max(1, _MAX_CONCURRENCY)
    return JSONResponse(out)


@router.get("/metrics/json")
async def metrics_json(request: Request) -> JSONResponse:
    cache = getattr(request.app.state, "metrics_cache", None)
    snap = cache.snapshot() if cache else None
    if not snap:
        return JSONResponse({"error": "no data yet"}, status_code=503)
    m = snap.raw

    def first(name: str, default: float | None = None) -> float | None:
        samples = m.get(name)
        if not samples:
            return default
        return samples[0].value

    indices: dict[str, dict[str, Any]] = {}
    for metric, samples in m.items():
        if metric == "g6_index_options_processed":
            for s in samples:
                idx = s.labels.get("index")
                if not idx:
                    continue
                indices.setdefault(idx, {}).setdefault("options_processed", s.value)
        elif metric == "g6_index_last_collection_unixtime":
            for s in samples:
                idx = s.labels.get("index")
                if not idx:
                    continue
                indices.setdefault(idx, {}).setdefault("last_collection", s.value)
        elif metric == "g6_index_success_rate_percent":
            for s in samples:
                idx = s.labels.get("index")
                if not idx:
                    continue
                indices.setdefault(idx, {}).setdefault("success_pct", s.value)
        elif metric == "g6_put_call_ratio":
            for s in samples:
                idx = s.labels.get("index")
                exp = s.labels.get("expiry")
                if not idx or not exp:
                    continue
                indices.setdefault(idx, {}).setdefault("pcr", {})[exp] = s.value

    payload = {
        "ts": snap.ts,
        "age_seconds": snap.age_seconds,
        "stale": bool(getattr(snap, "stale", False)),
        "indices": indices,
        "sample": {
            "g6_status_ok": first("g6_status_ok", None),
            "g6_index_options_processed": first("g6_index_options_processed", None),
            "g6_index_last_collection_unixtime": first("g6_index_last_collection_unixtime", None),
            "g6_index_success_rate_percent": first("g6_index_success_rate_percent", None),
        },
    }
    return JSONResponse(payload)
