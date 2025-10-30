from __future__ import annotations
# ruff: noqa: I001

import json as _json
import logging
import logging.handlers
import os
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import datetime as _dt
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, ORJSONResponse, PlainTextResponse
# HTML_DEPRECATED: Removed HTMLResponse, StaticFiles, Jinja2Templates (unused by Grafana Infinity)
# from fastapi.responses import HTMLResponse
# from fastapi.staticfiles import StaticFiles
# from fastapi.templating import Jinja2Templates

# Phase 2: Centralized environment variable access
from src.config.env_config import EnvConfig
from src.error_handling import ErrorCategory, ErrorSeverity, get_error_handler
from src.types.dashboard_types import (
    MemorySnapshot,
    UnifiedIndicesResponse,
    UnifiedSourceProtocol,
    UnifiedSourceStatusResponse,
    UnifiedStatusResponse,
)
from .core.config import CORS_ALL as _CORS_ALL, GRAFANA_PORT as _GRAFANA_PORT
from .core.paths import project_root as _project_root
from .metrics_cache import MetricsCache
from .routes.live import router as live_router
from .routes.overlay import router as overlay_router
from .routes.system import router as system_router

# Optional imports for late import elimination (Batch 30)
try:
    from src.utils.memory_manager import get_memory_manager
except ImportError:
    get_memory_manager = None  # type: ignore
try:
    from src.data_access.unified_source import data_source as _unified_source_import
except ImportError:
    _unified_source_import = None  # type: ignore


# --------------------------- Structured Logging (JSON) ---------------------------
def _resolve_log_dir() -> str:
    # Prefer explicit G6_LOG_DIR, then GF_PATHS_LOGS (Grafana env), then C:\GrafanaData\log, else local 'logs'
    for key in ("G6_LOG_DIR", "GF_PATHS_LOGS"):
        p = EnvConfig.get_str(key, "")
        if p and p.strip():
            return p
    try:
        if os.path.isdir(r"C:\GrafanaData\log"):
            return r"C:\GrafanaData\log"
    except Exception:
        pass
    return os.path.join(os.getcwd(), "logs")

_LOG_DIR = _resolve_log_dir()
try:
    os.makedirs(_LOG_DIR, exist_ok=True)
except Exception:
    pass

class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        try:
            payload: dict[str, Any] = {
                # Use timezone-aware UTC timestamp
                "ts": _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat().replace('+00:00','Z'),
                "level": record.levelname,
                "msg": record.getMessage(),
                "logger": record.name,
            }
            for k in ("path", "method", "status", "dur_ms", "cid", "client_ip", "user_agent"):
                v = getattr(record, k, None)
                if v is not None:
                    payload[k] = v
            if record.exc_info:
                payload["exc"] = self.formatException(record.exc_info)
            return _json.dumps(payload, ensure_ascii=False)
        except Exception:
            return super().format(record)

_logger = logging.getLogger("g6.webapi")
if not _logger.handlers:
    _logger.setLevel(logging.INFO)
    try:
        _file = os.path.join(_LOG_DIR, "webapi.json.log")
        _h = logging.handlers.RotatingFileHandler(_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
        _h.setFormatter(_JsonFormatter())
        _logger.addHandler(_h)
    except Exception:
        _sh = logging.StreamHandler()
        _sh.setFormatter(_JsonFormatter())
        _logger.addHandler(_sh)


def _load_unified_source() -> UnifiedSourceProtocol | None:
    """Attempt to import unified data source, return None if unavailable.

    Uses a runtime import guarded by broad exception handling so the dashboard
    can operate (with reduced feature set) when the unified source module or
    its dependencies are absent.
    """
    try:  # runtime import isolation
        if not _unified_source_import:
            return None
        # Cast to protocol for typed downstream usage
        return cast(UnifiedSourceProtocol, _unified_source_import)
    except Exception as e:  # pragma: no cover - optional path
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.CONFIGURATION,
            severity=ErrorSeverity.LOW,
            component="web.dashboard.app",
            function_name="module_import",
            message="Unified data source import failed (optional)",
            should_log=False,
        )
        return None

_unified: UnifiedSourceProtocol | None = _load_unified_source()

# Phase 2: Use EnvConfig for environment variables
LOG_PATH = EnvConfig.get_path("G6_LOG_FILE", "logs/g6_platform.log")
METRICS_ENDPOINT = EnvConfig.get_str("G6_METRICS_ENDPOINT", "http://localhost:9108/metrics")
DEBUG_MODE = EnvConfig.get_bool('G6_DASHBOARD_DEBUG', False)
CORE_REFRESH = EnvConfig.get_int('G6_DASHBOARD_CORE_REFRESH_SEC', 6)
SECONDARY_REFRESH = EnvConfig.get_int('G6_DASHBOARD_SECONDARY_REFRESH_SEC', 12)
"""
Align metrics cache polling with core refresh cadence to reduce staleness/flicker
"""
cache = MetricsCache(METRICS_ENDPOINT, interval=float(max(1, CORE_REFRESH)), timeout=1.5)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup
    try:
        cache.start()
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.LOW,
            component="web.dashboard.app",
            function_name="lifespan_start",
            message="Failed to start metrics cache",
            should_log=False,
        )
    
    # MEDIUM_IMPACT_OPTIMIZATION: Set cache reference for debug endpoints if enabled
    if DEBUG_MODE:
        try:
            set_debug_cache(cache)
        except Exception:
            pass  # Debug endpoints are optional, don't fail startup
    
    yield
    # Shutdown
    try:
        cache.stop()
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.LOW,
            component="web.dashboard.app",
            function_name="lifespan_stop",
            message="Failed to stop metrics cache",
            should_log=False,
        )


app = FastAPI(title="G6 Dashboard", version="0.1.0", lifespan=lifespan, default_response_class=ORJSONResponse)

# Compression for JSON payloads (saves bandwidth and speeds Grafana Infinity)
try:
    app.add_middleware(GZipMiddleware, minimum_size=1024)
except Exception:
    # Defensive: if middleware import fails in minimal envs, continue without gzip
    pass

# CORS: allow Grafana (frontend Infinity queries) to call this API from port 3002
try:
    if _CORS_ALL in ("1", "true", "True"):
        # Development fallback: allow any origin (no credentials)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["GET", "OPTIONS"],
            allow_headers=["*"],
            max_age=300,
        )
    else:
        grafana_port = _GRAFANA_PORT
        _origins = [
            f"http://127.0.0.1:{grafana_port}",
            f"http://localhost:{grafana_port}",
            "http://127.0.0.1",
            "http://localhost",
        ]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=_origins,
            allow_credentials=False,
            allow_methods=["GET", "OPTIONS"],
            allow_headers=["*"],
            max_age=300,
        )
except Exception:
    pass

# Lightweight observability handled in routers

# HTML_DEPRECATED: Removed templates and static file serving (Web API is JSON-only for Grafana)
# templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), 'templates'))
# app.mount('/static', StaticFiles(directory=os.path.join(os.path.dirname(__file__), 'static')), name='static')
app.include_router(live_router)
app.include_router(overlay_router)
app.include_router(system_router)
try:
    app.state.metrics_cache = cache
except Exception:
    pass

# startup handled by lifespan above

# --------------------------- Correlation ID & Access Log Middleware ---------------------------
@app.middleware("http")
async def _access_log_middleware(request: Request, call_next):
    cid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.correlation_id = cid
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = getattr(response, "status_code", 200)
    except Exception:
        status = 500
        _logger.exception(
            "request_error",
            extra={
                "cid": cid,
                "path": str(request.url.path),
                "method": request.method,
                "client_ip": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
            },
        )
        raise
    finally:
        dur_ms = (time.perf_counter() - start) * 1000.0
        _logger.info(
            "access",
            extra={
                "cid": cid,
                "path": str(request.url.path),
                "method": request.method,
                "status": status,
                "dur_ms": round(dur_ms, 2),
                "client_ip": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
            },
        )
    try:
        response.headers["X-Request-ID"] = cid
    except Exception:
        pass
    return response

# --------------------------- Global Exception Handlers ---------------------------
# HTML_DEPRECATED: Removed _wants_html() helper (Web API is JSON-only)
# def _wants_html(request: Request) -> bool:
#     accept = request.headers.get("accept", "")
#     return "text/html" in accept and "application/json" not in accept

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    # Only route 5xx to central handler to avoid noise for expected 4xx
    if exc.status_code >= 500:
        get_error_handler().handle_error(
            exception=exc,
            category=ErrorCategory.CONFIGURATION,
            severity=ErrorSeverity.MEDIUM,
            component="web.dashboard.app",
            function_name=str(request.url.path),
            message=f"HTTPException {exc.status_code}",
            should_log=False,
        )
    return JSONResponse({"error": str(exc.detail), "status_code": exc.status_code}, status_code=exc.status_code)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    get_error_handler().handle_error(
        exception=exc,
        category=ErrorCategory.DATA_VALIDATION,
        severity=ErrorSeverity.LOW,
        component="web.dashboard.app",
        function_name=str(request.url.path),
        message="Request validation failed",
        should_log=False,
    )
    return JSONResponse({"error": "validation_failed", "detail": exc.errors()}, status_code=422)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    get_error_handler().handle_error(
        exception=exc,
        category=ErrorCategory.CONFIGURATION,
        severity=ErrorSeverity.HIGH,
        component="web.dashboard.app",
        function_name=str(request.url.path),
        message="Unhandled server error",
        should_log=False,
    )
    return JSONResponse({"error": "internal_error"}, status_code=500)

## Diagnostics routes are provided by routes/system.py

# HTML_DEPRECATED: Removed /errors/fragment endpoint (HTML-only, not used by Grafana)
# @app.get('/errors/fragment', response_class=HTMLResponse)
# async def errors_fragment(request: Request) -> HTMLResponse:
#     snap = cache.snapshot()
#     return templates.TemplateResponse('_errors_fragment.html', {
#         'request': request,
#         'snapshot': snap,
#     })

# HTML_DEPRECATED: Removed _tail_log helper function (only used by HTML endpoints)
# def _tail_log(path: str, max_lines: int = 120) -> list[str]:
#     p = Path(path)
#     if not p.exists():
#         return [f"(log file not found: {path})"]
#     try:
#         # Efficient tail: read last ~64KB
#         with p.open('rb') as f:
#             f.seek(0, os.SEEK_END)
#             size = f.tell()
#             block = 65536
#             offset = max(size - block, 0)
#             f.seek(offset)
#             data = f.read().decode('utf-8', errors='replace')
#         lines = data.splitlines()
#         return lines[-max_lines:]
#     except Exception as e:
#         get_error_handler().handle_error(
#             e,
#             category=ErrorCategory.FILE_IO,
#             severity=ErrorSeverity.LOW,
#             component="web.dashboard.app",
#             function_name="_tail_log",
#             message="Failed reading log file",
#             context={"path": path},
#             should_log=False,
#         )
#         return [f"(failed reading log: {e})"]

# HTML_DEPRECATED: Removed /logs/fragment endpoint (HTML-only, not used by Grafana)
# @app.get('/logs/fragment', response_class=HTMLResponse)
# async def logs_fragment(request: Request, lines: int = 60) -> HTMLResponse:
#     entries = _tail_log(LOG_PATH, max_lines=lines)
#     return templates.TemplateResponse('_logs_fragment.html', {
#         'request': request,
#         'lines': entries,
#     })

@app.get('/metrics/raw')
async def metrics_raw() -> PlainTextResponse:
    snap = cache.snapshot()
    if not snap:
        return PlainTextResponse("no data", status_code=503)
    # Reconstruct minimal raw view for debugging
    lines = []
    for name, samples in snap.raw.items():
        for s in samples:
            if s.labels:
                label_str = ','.join(f"{k}=\"{v}\"" for k,v in s.labels.items())
                lines.append(f"{name}{{{label_str}}} {s.value}")
            else:
                lines.append(f"{name} {s.value}")
    return PlainTextResponse('\n'.join(lines))

# DEBUG_MODE already defined above

# HTML_DEPRECATED: Removed _build_memory_snapshot helper (only used by HTML endpoints)
# def _build_memory_snapshot() -> MemorySnapshot | None:
#     """Assemble a tiny memory snapshot suitable for the memory panel.
#
#     Reads from the memory manager API; returns None on failure.
#     """
#     try:
#         from src.utils.memory_manager import get_memory_manager
#         mm = get_memory_manager()
#         stats = mm.get_stats() or {}
#         snap: MemorySnapshot = {
#             'rss_mb': stats.get('rss_mb'),
#             'peak_rss_mb': stats.get('peak_rss_mb'),
#             'gc_collections_total': stats.get('gc_collections_total'),
#             'gc_last_duration_ms': stats.get('gc_last_duration_ms'),
#         }
#         return snap
#     except Exception as e:
#         get_error_handler().handle_error(
#             e,
#             category=ErrorCategory.RESOURCE,
#             severity=ErrorSeverity.LOW,
#             component="web.dashboard.app",
#             function_name="_build_memory_snapshot",
#             message="Failed to build memory snapshot",
#             should_log=False,
#         )
#         return None

# HTML_DEPRECATED: Removed /memory/fragment endpoint (HTML-only, not used by Grafana)
# @app.get('/memory/fragment', response_class=HTMLResponse)
# async def memory_fragment(request: Request) -> HTMLResponse:
#     mem = _build_memory_snapshot()
#     # Provide a simple struct-like object so Jinja can access snapshot.memory.*
#     snapshot_obj = type('S', (), {'memory': mem}) if mem is not None else None
#     return templates.TemplateResponse('_memory_fragment.html', {
#         'request': request,
#         'snapshot': snapshot_obj,
#         'debug': DEBUG_MODE,
#     })

# --------------------------- Unified JSON Endpoints ---------------------------
@app.get('/api/unified/status')
async def api_unified_status() -> JSONResponse:
    if _unified is None:
        raise HTTPException(status_code=503, detail='unified source unavailable')
    try:
        st = _unified.get_runtime_status()
        payload: UnifiedStatusResponse | dict
        if isinstance(st, dict):
            # Accept partial user-provided dict; rely on TypedDict being total=False
            payload = cast(UnifiedStatusResponse, st)
        else:
            payload = {}
        return JSONResponse(payload)
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.MEDIUM,
            component="web.dashboard.app",
            function_name="api_unified_status",
            message="Error fetching unified runtime status",
            should_log=False,
    )
    raise HTTPException(status_code=500, detail='unified status error') from None


@app.get('/api/unified/indices')
async def api_unified_indices() -> JSONResponse:
    if _unified is None:
        raise HTTPException(status_code=503, detail='unified source unavailable')
    try:
        inds = _unified.get_indices_data()
        payload: UnifiedIndicesResponse | dict
        if isinstance(inds, dict):
            payload = cast(UnifiedIndicesResponse, inds)
        else:
            payload = {}
        return JSONResponse(payload)
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.MEDIUM,
            component="web.dashboard.app",
            function_name="api_unified_indices",
            message="Error fetching unified indices",
            should_log=False,
    )
    raise HTTPException(status_code=500, detail='unified indices error') from None

@app.get('/api/unified/source-status')
async def api_unified_source_status() -> JSONResponse:
    if _unified is None:
        raise HTTPException(status_code=503, detail='unified source unavailable')
    try:
        st = _unified.get_source_status()
        payload: UnifiedSourceStatusResponse | dict
        if isinstance(st, dict):
            payload = cast(UnifiedSourceStatusResponse, st)
        else:
            payload = {}
        return JSONResponse(payload)
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.MEDIUM,
            component="web.dashboard.app",
            function_name="api_unified_source_status",
            message="Error fetching unified source status",
            should_log=False,
    )
    raise HTTPException(status_code=500, detail='unified source-status error') from None

@app.post('/api/memory/gc')
async def api_memory_gc(request: Request) -> JSONResponse:
    """Trigger a GC cycle via MemoryManager. Guarded by G6_DASHBOARD_DEBUG=1."""
    if not DEBUG_MODE:
        raise HTTPException(status_code=403, detail='forbidden')
    try:
        if not get_memory_manager:
            raise HTTPException(status_code=503, detail='memory manager unavailable')
        mm = get_memory_manager()
        # Read optional aggressive flag
        aggressive = False
        try:
            form = await request.form()
            aggressive = str(form.get('aggressive','0')).lower() in ('1','true','yes','on')
        except Exception as e:
            # Non-fatal form parse issue
            get_error_handler().handle_error(
                e,
                category=ErrorCategory.DATA_PARSING,
                severity=ErrorSeverity.LOW,
                component="web.dashboard.app",
                function_name="api_memory_gc",
                message="Failed to parse GC form",
                should_log=False,
            )
        # Use post_cycle_cleanup for consistent metrics/stats updates
        mm.post_cycle_cleanup(aggressive=aggressive)
        return JSONResponse({"status": "ok", "aggressive": aggressive, "stats": mm.get_stats()})
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.MEDIUM,
            component="web.dashboard.app",
            function_name="api_memory_gc",
            message="Memory GC endpoint failure",
            should_log=False,
    )
    raise HTTPException(status_code=500, detail='memory gc error') from None

# --------------------------- Unified Cache Stats (JSON) ---------------------------
@app.get('/api/unified/cache-stats')
async def api_unified_cache_stats(reset: bool = False) -> JSONResponse:
    """Return UnifiedDataSource cache statistics.

    If reset=true, counters are zeroed after snapshot is taken.
    """
    if _unified is None:
        raise HTTPException(status_code=503, detail='unified source unavailable')
    try:
        # Cast to satisfy type checker for global Optional narrowing
        ds = cast(UnifiedSourceProtocol, _unified)
        # Safely probe for get_cache_stats availability
        getter = getattr(ds, 'get_cache_stats', None)
        if not callable(getter):
            return JSONResponse({'error': 'cache stats not available'}, status_code=404)
        stats = getter(reset=reset)
        if not isinstance(stats, dict):
            stats = {}
        return JSONResponse(stats)
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.LOW,
            component="web.dashboard.app",
            function_name="api_unified_cache_stats",
            message="Error fetching cache stats",
            should_log=False,
    )
    raise HTTPException(status_code=500, detail='unified cache-stats error') from None

# --------------------------- DEBUG ENDPOINTS (ONE-TIME DIAGNOSTIC BLOCK) ---------------------------
# DEBUG_CLEANUP_BEGIN: temporary debug/observability endpoints. Enabled only when
# G6_DASHBOARD_DEBUG=1 to keep production surface minimal.
_EXPECTED_CORE = [
    'g6_uptime_seconds', 'g6_collection_cycle_time_seconds', 'g6_options_processed_per_minute',
    'g6_collection_success_rate_percent', 'g6_api_success_rate_percent', 'g6_cpu_usage_percent',
    'g6_memory_usage_mb', 'g6_index_cycle_attempts', 'g6_index_cycle_success_percent',
    'g6_index_options_processed', 'g6_index_options_processed_total'
]

# MEDIUM_IMPACT_OPTIMIZATION (Opportunity 5): DEBUG endpoints moved to separate module
# Conditionally include debug router only when DEBUG_MODE=1
if DEBUG_MODE:
    from src.web.dashboard.debug import debug_router, set_cache as set_debug_cache
    app.include_router(debug_router)
    # Set cache reference after cache is initialized (see startup event)

# HTML_DEPRECATED: Removed _scan_options_fs, _read_text_file helpers (only used by HTML endpoints)
# def _scan_options_fs(base: Path | None = None) -> dict[str, Any]:
#     """Scan filesystem under data/g6_data to derive available indices/expiries/offsets.
#
#     Returns a dict with shapes:
#       {
#         "root": str,
#         "indices": ["NIFTY", ...],
#         "matrix": { "NIFTY": { "expiry_tags": [..], "offsets": {"this_week": ["ATM", ...] } } },
#       }
#     """
#     try:
#         root = (base or _project_root()) / 'data' / 'g6_data'
#         out: dict[str, Any] = {"root": str(root), "indices": [], "matrix": {}}
#         if not root.exists():
#             return out
#         for idx_dir in sorted([p for p in root.iterdir() if p.is_dir()]):
#             idx = idx_dir.name
#             out["indices"].append(idx)  # indices: list[str]
#             exp_tags: list[str] = []
#             offsets_map: dict[str, list[str]] = {}
#             for exp_dir in sorted([p for p in idx_dir.iterdir() if p.is_dir()]):
#                 exp = exp_dir.name
#                 exp_tags.append(exp)
#                 offs: list[str] = [
#                     off_dir.name for off_dir in sorted([p for p in exp_dir.iterdir() if p.is_dir()])
#                 ]
#                 offsets_map[exp] = offs
#             out["matrix"][idx] = {"expiry_tags": exp_tags, "offsets": offsets_map}
#         return out
#     except Exception as e:  # pragma: no cover - defensive filesystem scan
#         get_error_handler().handle_error(
#             e,
#             category=ErrorCategory.FILE_IO,
#             severity=ErrorSeverity.LOW,
#             component="web.dashboard.app",
#             function_name="_scan_options_fs",
#             message="Failed to scan options filesystem",
#             should_log=False,
#         )
#     return {"root": str((base or _project_root()) / 'data' / 'g6_data'), "indices": [], "matrix": {}}

# HTML_DEPRECATED: Removed /options endpoint (HTML-only, not used by Grafana)
# @app.get('/options', response_class=HTMLResponse)
# async def options_page(request: Request) -> HTMLResponse:
#     """Options metadata overview derived from filesystem (no provider required)."""
#     fs_meta = _scan_options_fs()
#     return templates.TemplateResponse('options.html', {
#         'request': request,
#         'fs': fs_meta,
#     })

# HTML_DEPRECATED: Removed _read_text_file helper (only used by HTML endpoints)
# def _read_text_file(p: Path) -> str | None:
#     try:
#         return p.read_text(encoding='utf-8')
#     except Exception:
#         return None

# HTML_DEPRECATED: Removed /weekday/overlays endpoint (HTML-only, not used by Grafana)
# @app.get('/weekday/overlays', response_class=HTMLResponse)
# async def weekday_overlays_page(request: Request) -> HTMLResponse:
#     """Embed a generated weekday overlays HTML if present, else show guidance."""
#     base = _project_root()
#     html_path = Path(os.environ.get('G6_WEEKDAY_OVERLAYS_HTML', str(base / 'weekday_overlays.html')))
#     meta_path = Path(os.environ.get('G6_WEEKDAY_OVERLAYS_META', str(base / 'weekday_overlays_meta.json')))
#     embedded_html = _read_text_file(html_path) if html_path.exists() else None
#     meta_json = None
#     if meta_path.exists():
#         try:
#             meta_json = meta_path.read_text(encoding='utf-8')
#         except Exception:
#             meta_json = None
#     return templates.TemplateResponse('weekday_overlays.html', {
#         'request': request,
#         'html_present': embedded_html is not None,
#         'embedded_html': embedded_html or '',
#         'html_path': str(html_path),
#         'meta_json': meta_json,
#         'meta_path': str(meta_path),
#     })

## Routes moved: /api/live_csv and /api/overlay handled via included routers


# Diagnostics and stats routes are provided by routes/system.py
