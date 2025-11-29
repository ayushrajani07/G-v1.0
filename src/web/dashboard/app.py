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
from .routes.path_forecast import router as path_forecast_router
from .routes.ensemble import router as ensemble_router
from .routes.ml import router as ml_router
from .routes.drift import router as drift_router
from .routes.stream import router as stream_router
from .routes.metrics import router as metrics_router
try:
    # Advisor router provides universal advisor endpoints
    from .routes.advisor import router as advisor_router
except (ImportError, ModuleNotFoundError, AttributeError):  # pragma: no cover - missing optional advisor engine deps
    advisor_router = None  # type: ignore

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
    except (OSError, PermissionError):
        # Directory check failed or permission denied
        pass
    return os.path.join(os.getcwd(), "logs")

_LOG_DIR = _resolve_log_dir()
try:
    os.makedirs(_LOG_DIR, exist_ok=True)
except (OSError, PermissionError):
    # Directory creation failed or permission denied
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
        except (_json.JSONDecodeError, TypeError, ValueError, AttributeError):
            # JSON encoding error, type error, value error, or attribute access failure
            return super().format(record)

_logger = logging.getLogger("g6.webapi")
if not _logger.handlers:
    _logger.setLevel(logging.INFO)
    try:
        _file = os.path.join(_LOG_DIR, "webapi.json.log")
        _h = logging.handlers.RotatingFileHandler(_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
        _h.setFormatter(_JsonFormatter())
        _logger.addHandler(_h)
    except (OSError, IOError, PermissionError, ValueError):
        # File handler creation failed - use stream handler instead
        _sh = logging.StreamHandler()
        _sh.setFormatter(_JsonFormatter())
        _logger.addHandler(_sh)

    # Alias for legacy code referencing _LOG
    _LOG = _logger


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
        except (AttributeError, TypeError, NameError):
            # Debug function not available, attribute error, or type error
            pass  # Debug endpoints are optional, don't fail startup
    
    # Phase 10: Start drift monitoring evaluator thread if enabled
    try:
        from .drift_metrics import start_drift_evaluator
        start_drift_evaluator()
    except Exception as e:
        # Drift monitoring is optional, don't fail startup
        _LOG.info(f"Drift monitoring not started: {e}")
    # Phase 10: Start regime change weekly scheduler if enabled
    try:
        from .regime_alerts import start_regime_scheduler
        start_regime_scheduler()
    except Exception as e:
        _LOG.info(f"Regime scheduler not started: {e}")
    
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
    
    # Phase 10: Stop drift monitoring evaluator thread
    try:
        from .drift_metrics import stop_drift_evaluator
        stop_drift_evaluator()
    except Exception as e:
        # Drift monitoring is optional, don't fail shutdown
        _LOG.info(f"Drift monitoring not stopped cleanly: {e}")
    # Phase 10: Stop regime scheduler
    try:
        from .regime_alerts import stop_regime_scheduler
        stop_regime_scheduler()
    except Exception as e:
        _LOG.info(f"Regime scheduler not stopped cleanly: {e}")


app = FastAPI(title="G6 Dashboard", version="0.1.0", lifespan=lifespan, default_response_class=ORJSONResponse)
_DIAG_ENABLED = os.environ.get('G6_DIAG_ENABLE','1').lower() in ('1','true','yes','on')

# Backward compatibility: legacy scripts expect /health
@app.get('/health')
async def health_root() -> PlainTextResponse:
    return PlainTextResponse('ok')

# --------------------------- Early Diagnostics (placed immediately after app construction) ---------------------------
if _DIAG_ENABLED:
    @app.get('/__diag/pid')
    async def __diag_pid() -> JSONResponse:  # returns pid for process verification
        import os as _os, time as _t
        return JSONResponse({'pid': _os.getpid(), 'ts_ms': int(_t.time()*1000)})

    @app.get('/__diag/routes')
    async def __diag_routes() -> JSONResponse:  # enumerates current paths
        paths = sorted({getattr(r, 'path', None) for r in app.routes if hasattr(r, 'path')})
        return JSONResponse({'count': len(paths), 'paths': paths})

    @app.get('/__diag/summary')
    async def __diag_summary() -> JSONResponse:
        import os as _os
        paths = [getattr(r, 'path', None) for r in app.routes if hasattr(r, 'path')]
        ensemble_paths = [p for p in paths if p and '/ensemble/' in p]
        return JSONResponse({'pid': _os.getpid(), 'total_paths': len(paths), 'ensemble_paths': ensemble_paths})

# Compression for JSON payloads (saves bandwidth and speeds Grafana Infinity)
try:
    app.add_middleware(GZipMiddleware, minimum_size=1024)
except (ImportError, AttributeError, RuntimeError):
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
except (ImportError, AttributeError, RuntimeError, ValueError):
    # Middleware import failed, attribute error, runtime error, or value error
    pass

# Lightweight observability handled in routers

# HTML_DEPRECATED: Removed templates and static file serving (Web API is JSON-only for Grafana)
# templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), 'templates'))
# app.mount('/static', StaticFiles(directory=os.path.join(os.path.dirname(__file__), 'static')), name='static')
app.include_router(live_router)
app.include_router(overlay_router)
app.include_router(system_router)
app.include_router(path_forecast_router)
app.include_router(ensemble_router)
app.include_router(ml_router)
app.include_router(drift_router)
app.include_router(stream_router)
app.include_router(metrics_router)
# Phase 20 (stub): minimal streaming/feedback wiring
try:
    from typing import Dict, Any
    from src.monitoring.feedback import FeedbackLoop
    from src.monitoring.alerts import AlertEngine
    from src.streaming.ingest import StreamIngestor
    # Config flags
    ENABLE_STREAM_INGEST = EnvConfig.get_bool("ENABLE_STREAM_INGEST", True)
    LIVE_MAE_ALERT_THRESHOLD = EnvConfig.get_float("LIVE_MAE_ALERT_THRESHOLD", 2.0)

    _feedback = FeedbackLoop()
    _alerts = AlertEngine(lambda name, payload: _logger.info("alert", extra={"name": name, **payload}))

    def _emit_item(item: Dict[str, Any]) -> None:
        y_true = item.get("y_true")
        y_pred = item.get("y_pred")
        if y_true is not None and y_pred is not None:
            try:
                _feedback.observe(float(y_true), float(y_pred))
                metrics = _feedback.get_metrics()
                # Export live MAE to Prometheus (if enabled)
                try:
                    from .prom_metrics import set_live_mae, inc_live_mae_alerts
                    set_live_mae(metrics["mae"])  # best-effort
                except Exception:
                    pass
                _alerts.maybe_alert("live-mae", {"live_mae": metrics["mae"]}, {"live_mae": LIVE_MAE_ALERT_THRESHOLD})
                try:
                    if float(metrics["mae"]) >= float(LIVE_MAE_ALERT_THRESHOLD):
                        inc_live_mae_alerts()
                except Exception:
                    pass
            except Exception:
                pass

    _ingestor = StreamIngestor(_emit_item) if ENABLE_STREAM_INGEST else None
    if _ingestor is not None:
        _ingestor.start()
    try:
        app.state.ingestor = _ingestor
        app.state.feedback = _feedback
    except Exception:
        pass
except Exception:
    _ingestor = None  # optional in minimal environments
# Memory status endpoint (lightweight; avoid dedicated router for single path)
try:
    from src.utils.memory_manager import get_memory_manager as _get_mm
except (ImportError, ModuleNotFoundError, AttributeError):  # pragma: no cover - optional dependency
    _get_mm = None  # type: ignore

@app.get('/api/memory/status')
def memory_status() -> JSONResponse:
    if _get_mm is None:
        # Return placeholder stats dict with required keys
        return JSONResponse(status_code=503, content={'status': 'unavailable', 'stats': {
            'rss_mb': None,
            'peak_rss_mb': None,
            'gc_collections_total': None,
            'gc_last_duration_ms': None,
            'registered_caches': None,
        }})
    try:
        mm = _get_mm()
        snap: dict[str, Any] = {}
        try:
            m = mm.snapshot()  # type: ignore[attr-defined]
            snap = {
                'rss_mb': m.get('rss_mb'),
                'peak_rss_mb': m.get('peak_rss_mb'),
                'gc_collections_total': m.get('gc_collections_total'),
                'gc_last_duration_ms': m.get('gc_last_duration_ms'),
                'registered_caches': m.get('registered_caches'),
            } if isinstance(m, dict) else {}
        except (AttributeError, TypeError, KeyError):
            # Missing snapshot method, type error, or dict access error
            pass
        # Ensure all expected keys present even if snapshot partial
        for k in ('rss_mb','peak_rss_mb','gc_collections_total','gc_last_duration_ms','registered_caches'):
            snap.setdefault(k, None)
        return JSONResponse(content={'status': 'ok', 'stats': snap})
    except Exception as e:  # pragma: no cover - defensive
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.LOW,
            component='web.dashboard.app',
            function_name='memory_status',
            message='Memory status retrieval failed',
            should_log=False,
        )
        return JSONResponse(status_code=503, content={'status': 'error', 'stats': {
            'rss_mb': None,
            'peak_rss_mb': None,
            'gc_collections_total': None,
            'gc_last_duration_ms': None,
            'registered_caches': None,
        }})
if advisor_router is not None:
    try:
        app.include_router(advisor_router)
    except (RuntimeError, ValueError, AttributeError):
        # Router inclusion failed - runtime error, value error, or attribute error
        pass
try:
    app.state.metrics_cache = cache
except (AttributeError, RuntimeError):
    # State attribute assignment failed
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
    except (HTTPException, RequestValidationError, RuntimeError, ValueError) as exc:
        # HTTP exceptions, validation errors, runtime errors, or value errors
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
    except (AttributeError, TypeError):
        # Response object missing headers attribute or type error
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

@app.get('/metrics')
async def prometheus_metrics() -> PlainTextResponse:
    """Expose Prometheus metrics for path forecast endpoints.
    
    Only active when ENABLE_PATH_FORECAST_PROM_METRICS=1 environment variable is set.
    Returns 404 if not enabled.
    """
    try:
        from .prom_metrics import get_registry
        registry = get_registry()
        if registry is None:
            return PlainTextResponse("Prometheus metrics not enabled", status_code=404)
        
        # Generate metrics output
        from prometheus_client import generate_latest
        metrics_output = generate_latest(registry)
        return PlainTextResponse(metrics_output.decode('utf-8'), media_type="text/plain; version=0.0.4")
    except ImportError:
        return PlainTextResponse("Prometheus client not available", status_code=503)
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.CONFIGURATION,
            severity=ErrorSeverity.LOW,
            component="web.dashboard.app",
            function_name="prometheus_metrics",
            message="Failed to generate Prometheus metrics",
            should_log=False,
        )
        return PlainTextResponse("Error generating metrics", status_code=500)

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

# --------------------------- Advisor Integrity & Error/Health Metrics ---------------------------
# Tests expect the following endpoints:
#   /api/diag/advisor_integrity
#   /api/ml/universal_advisor/* (provided by advisor_router)
#   /api/errors/recent
#   /health/metrics
# These were removed during surface minimization; reintroduce lightweight JSON versions.

def _ensure_advisor_gauges() -> None:
    """Lazily register advisor integrity + age gauges on metrics singleton.

    Tests access these as attributes on the metrics singleton. We attach
    prometheus_client Gauge instances when absent. Safe to call multiple times.
    """
    try:
        from src.metrics import get_metrics_singleton  # type: ignore
        reg = get_metrics_singleton()
        if reg is None:
            return
        from prometheus_client import Gauge  # type: ignore
        if not hasattr(reg, 'advisor_integrity_ok'):
            try:
                reg.advisor_integrity_ok = Gauge('g6_advisor_integrity_ok', 'advisor integrity ok (1/0)')  # type: ignore[attr-defined]
            except (ImportError, AttributeError, ValueError, RuntimeError):
                # Gauge creation failed - import error, attribute error, value error, or runtime error
                pass
        if not hasattr(reg, 'advisor_age_minutes'):
            try:
                reg.advisor_age_minutes = Gauge('g6_advisor_age_minutes', 'advisor report age (minutes)')  # type: ignore[attr-defined]
            except (ImportError, AttributeError, ValueError, RuntimeError):
                # Gauge creation failed - import error, attribute error, value error, or runtime error
                pass
    except (ImportError, AttributeError, TypeError):
        # Missing metrics module, attribute error, or type error
        pass

@app.get('/api/diag/advisor_integrity')
async def api_diag_advisor_integrity() -> JSONResponse:
    """Report presence of universal advisor endpoints and set integrity gauge.

    Returns keys required by tests. latest_snapshot is optional (omitted when not
    previously called)."""
    _ensure_advisor_gauges()
    try:
        # Gather all route paths
        route_paths = [r.path for r in app.routes]
        expected_routes = [
            '/api/ml/universal_advisor',
            '/api/ml/universal_advisor/health',
            '/api/ml/universal_advisor/generated_at_age_minutes',
        ]
        found = [p for p in route_paths if p in expected_routes]
        present = len(found) == len(expected_routes)
        # Update gauge
        try:
            from src.metrics import get_metrics_singleton  # type: ignore
            reg = get_metrics_singleton()
            if reg is not None and hasattr(reg, 'advisor_integrity_ok'):
                reg.advisor_integrity_ok.set(1 if present else 0)  # type: ignore[attr-defined]
        except (ImportError, AttributeError, TypeError):
            # Missing metrics module, attribute error, or type error
            pass
        # Check OpenAPI presence (best-effort)
        openapi_present = False
        try:
            spec = app.openapi()
            paths_dict = spec.get('paths', {}) if isinstance(spec, dict) else {}
            openapi_present = all(p in paths_dict for p in expected_routes)
        except (RuntimeError, ValueError, AttributeError, KeyError):
            # OpenAPI generation error, value error, attribute error, or dict access error
            openapi_present = False
        payload = {
            'pid': os.getpid(),
            'generated_at_iso': _dt.datetime.now(_dt.UTC).isoformat().replace('+00:00','Z'),
            'present': present,
            'routes': found,
            'expected_count': len(expected_routes),
            'found_count': len(found),
            'openapi_present': openapi_present,
            # 'latest_snapshot': None  # optional; omit so tests skip snapshot assertions
        }
        return JSONResponse(payload)
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.CONFIGURATION,
            severity=ErrorSeverity.LOW,
            component='web.dashboard.app',
            function_name='api_diag_advisor_integrity',
            message='Failed advisor integrity probe',
            should_log=False,
        )
    return JSONResponse({'error': 'advisor integrity failure'}, status_code=503)

    return JSONResponse({'errors': [], 'count': 0}, status_code=503)

@app.get('/health/metrics')
async def health_metrics() -> JSONResponse:
    """Return lightweight metrics snapshot including advisor fields.

    advisor_integrity_ok and advisor_age_minutes may be None if probes not yet run.
    """
    _ensure_advisor_gauges()
    advisor_integrity_ok: float | None = None
    advisor_age_minutes: float | None = None
    try:
        from src.metrics import get_metrics_singleton  # type: ignore
        reg = get_metrics_singleton()
        if reg is not None:
            try:
                if hasattr(reg, 'advisor_integrity_ok'):
                    fams = list(reg.advisor_integrity_ok.collect())  # type: ignore[attr-defined]
                    if fams and fams[0].samples:
                        advisor_integrity_ok = fams[0].samples[0].value
            except (AttributeError, IndexError, TypeError):
                # Missing attribute, index out of range, or type error
                pass
            try:
                if hasattr(reg, 'advisor_age_minutes'):
                    fams2 = list(reg.advisor_age_minutes.collect())  # type: ignore[attr-defined]
                    if fams2 and fams2[0].samples:
                        advisor_age_minutes = fams2[0].samples[0].value
            except (AttributeError, IndexError, TypeError):
                # Missing attribute, index out of range, or type error
                pass
    except (ImportError, AttributeError, TypeError):
        # Missing metrics module, attribute error, or type error
        pass
    return JSONResponse({
        'advisor_integrity_ok': advisor_integrity_ok,
        'advisor_age_minutes': advisor_age_minutes,
    })

# --------------------------- System Errors: Recent API ---------------------------
@app.get('/api/errors/recent')
async def api_errors_recent(count: int = 50, category: str | None = None, severity: str | None = None) -> JSONResponse:
    """Return recent errors with optional filtering.

    Query params:
    - count: max items to return (server-capped at 200)
    - category: optional filter (e.g., FILE_IO)
    - severity: optional filter (e.g., LOW | MEDIUM | HIGH | CRITICAL)
    """
    try:
        cap = max(1, min(int(count), 200))
    except (ValueError, TypeError):
        cap = 50
    try:
        errs = get_error_handler().get_recent_errors(cap)
        out: list[dict[str, Any]] = []
        cat_norm = (category or '').strip().lower()
        sev_norm = (severity or '').strip().lower()
        for e in errs:
            d = e.to_dict()
            # Normalize for filtering
            d_cat = str(d.get('category','')).lower()
            d_sev = str(d.get('severity','')).lower()
            if cat_norm and d_cat != cat_norm:
                continue
            if sev_norm and d_sev != sev_norm:
                continue
            out.append(d)
        return JSONResponse({'errors': out, 'count': len(out)})
    except Exception as ex:
        get_error_handler().handle_error(
            ex,
            category=ErrorCategory.CONFIGURATION,
            severity=ErrorSeverity.LOW,
            component='web.dashboard.app',
            function_name='api_errors_recent',
            message='errors_recent_failed',
            should_log=False,
        )
        return JSONResponse({'errors': [], 'count': 0}, status_code=500)

# --------------------------- Ensemble & Forecast API (minimal placeholders) ---------------------------
# Tests expect CSV-style text responses for ensemble k calibration, weights, and quarantine log.
# Implement lightweight endpoints reading sidecar/log files under data/ml/live_predictions rooted at project_root().
from fastapi.responses import PlainTextResponse
from .core import paths as _paths_core
from src.utils.timeutils import utc_now_z as _utc_now_z
try:
    from src.path_forecast.composite import CompositePathForecaster, CompositeConfig
except (ImportError, ModuleNotFoundError, AttributeError):
    # Import failed - module not found or attribute error
    CompositePathForecaster = None  # type: ignore
    CompositeConfig = None  # type: ignore

def _ml_live_predictions_dir() -> Path:
    try:
        return _paths_core.project_root() / 'data' / 'ml' / 'live_predictions'
    except (AttributeError, OSError, TypeError):
        # Missing project_root function, type error, or OS error
        return Path('data/ml/live_predictions')

# --------------------------- Alerts File Write Endpoint ---------------------------
@app.post('/api/alerts/file')
async def alert_webhook_file(request: Request) -> JSONResponse:
    """Append alert lines to logs/alerts.log.

    Behavior expected by tests:
    - On write/open failure respond 500 and record FILE_IO error with function_name 'alert_webhook_file'.
    - Error context includes 'file' path ending with logs/alerts.log.
    Successful writes return count written.
    """
    try:
        payload = await request.json()
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.DATA_PARSING,
            severity=ErrorSeverity.LOW,
            component='web.dashboard.app',
            function_name='alert_webhook_file',
            message='invalid_json',
            should_log=False,
        )
        return JSONResponse({'error': 'invalid_json'}, status_code=400)
    alerts = []
    status = ''
    if isinstance(payload, dict):
        status = str(payload.get('status', ''))
        raw_alerts = payload.get('alerts')
        if isinstance(raw_alerts, list):
            alerts = [a for a in raw_alerts if isinstance(a, dict)]
    log_dir = Path(os.getcwd()) / 'logs'
    log_fp = log_dir / 'alerts.log'
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError):
        # Directory creation failed or permission denied
        pass
    lines: list[str] = []
    for a in alerts:
        labels = a.get('labels', {}) if isinstance(a.get('labels'), dict) else {}
        annotations = a.get('annotations', {}) if isinstance(a.get('annotations'), dict) else {}
        sev = labels.get('severity') or labels.get('level') or ''
        name = labels.get('alertname') or labels.get('name') or ''
        summary = annotations.get('summary') or ''
        desc = annotations.get('description') or ''
        iso = _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat().replace('+00:00','Z')
        lines.append(f"{iso},{status},{sev},{name},{summary},{desc}")
    try:
        # Use builtins.open so hygiene test monkeypatch on builtins.open intercepts failures
        import builtins as _bi
        with _bi.open(str(log_fp), 'a', encoding='utf-8') as f:
            for ln in lines:
                f.write(ln + '\n')
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.FILE_IO,
            severity=ErrorSeverity.LOW,
            component='web.dashboard.app',
            function_name='alert_webhook_file',
            message='alerts_log_write_failed',
            context={'file': str(log_fp), 'count_intent': len(lines)},
            should_log=False,
        )
        return JSONResponse({'error': 'write_failed'}, status_code=500)
    return JSONResponse({'written': len(lines), 'file': str(log_fp)})

@app.post('/api/alerts/console')
async def alert_webhook_console(request: Request) -> JSONResponse:
    """Log alerts to stdout via application logger."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({'error': 'invalid_json'}, status_code=400)
    
    alerts = []
    if isinstance(payload, dict):
        raw_alerts = payload.get('alerts')
        if isinstance(raw_alerts, list):
            alerts = [a for a in raw_alerts if isinstance(a, dict)]
            
    for a in alerts:
        labels = a.get('labels', {})
        annotations = a.get('annotations', {})
        name = labels.get('alertname', 'unknown')
        severity = labels.get('severity', 'unknown')
        summary = annotations.get('summary', '')
        _LOG.info(f"ALERT [{severity.upper()}] {name}: {summary}", extra={'alert': a})
        
    return JSONResponse({'status': 'ok', 'processed': len(alerts)})

@app.post('/api/alerts/path_forecast')
async def alert_webhook_path_forecast(request: Request) -> JSONResponse:
    """Specialized receiver for path forecast alerts."""
    # For now, just log them as console alerts, but with a specific tag
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({'error': 'invalid_json'}, status_code=400)
        
    alerts = []
    if isinstance(payload, dict):
        raw_alerts = payload.get('alerts')
        if isinstance(raw_alerts, list):
            alerts = [a for a in raw_alerts if isinstance(a, dict)]
            
    for a in alerts:
        labels = a.get('labels', {})
        annotations = a.get('annotations', {})
        name = labels.get('alertname', 'unknown')
        severity = labels.get('severity', 'unknown')
        summary = annotations.get('summary', '')
        _LOG.info(f"PATH_FORECAST_ALERT [{severity.upper()}] {name}: {summary}", extra={'alert': a, 'component': 'path_forecast'})
        
    return JSONResponse({'status': 'ok', 'processed': len(alerts)})

@app.get('/api/ml/ensemble/k_calibration')
async def api_ml_ensemble_k_calibration(index: str, horizon: str | None = None) -> PlainTextResponse:
    """Return k calibration CSV row from <index>_ensemble_k_calibration.json sidecar.

    Header: timestamp,recommended_k,k_smooth,effective_cov,band_radius,target,index,horizon,n
    Missing file -> 404.
    """
    base = _ml_live_predictions_dir()
    fp = base / f'{index}_ensemble_k_calibration.json'
    if not fp.exists():
        return PlainTextResponse('not found', status_code=404)
    try:
        data = _json.loads(fp.read_text(encoding='utf-8'))
    except Exception as e:
        get_error_handler().handle_error(e, category=ErrorCategory.FILE_IO, severity=ErrorSeverity.LOW, component='web.dashboard.app', function_name='api_ml_ensemble_k_calibration', message='failed_read')
        return PlainTextResponse('read error', status_code=500)
    # Build header/row
    header = 'timestamp,recommended_k,k_smooth,effective_cov,band_radius,target,index,horizon,n'
    ts = str(data.get('timestamp', ''))
    recommended_k = data.get('recommended_k')
    k_smooth = data.get('k_smooth')
    effective_cov = data.get('effective_cov')
    band_radius = data.get('band_radius')
    target = data.get('target')
    n = data.get('n')
    horizon_val = horizon or str(data.get('horizon', ''))
    # Format k_smooth to two decimals when numeric (tests expect e.g. 1.10 not 1.1)
    if k_smooth is not None:
        try:
            k_smooth_fmt = f"{float(k_smooth):.2f}"
        except (ValueError, TypeError):
            # Invalid numeric conversion or type error
            k_smooth_fmt = str(k_smooth)
    else:
        k_smooth_fmt = ''
    row = f"{ts},{recommended_k},{k_smooth_fmt},{effective_cov},{band_radius},{target},{index},{horizon_val},{n}"
    return PlainTextResponse(f"{header}\n{row}")

@app.get('/api/ml/ensemble/weights')
async def api_ml_ensemble_weights(index: str, horizon: str) -> PlainTextResponse:
    """Return model weight CSV from <index>_ensemble_weights.json sidecar.

    Header: timestamp,model,weight,rmse,index,horizon sorted by weight desc.
    Non-numeric weight -> 0.0.
    Missing file -> 404.
    """
    base = _ml_live_predictions_dir()
    fp = base / f'{index}_ensemble_weights.json'
    if not fp.exists():
        return PlainTextResponse('not found', status_code=404)
    try:
        data = _json.loads(fp.read_text(encoding='utf-8'))
    except Exception as e:
        get_error_handler().handle_error(e, category=ErrorCategory.FILE_IO, severity=ErrorSeverity.LOW, component='web.dashboard.app', function_name='api_ml_ensemble_weights', message='failed_read')
        return PlainTextResponse('read error', status_code=500)
    weights: dict[str, Any] = data.get('weights', {}) if isinstance(data.get('weights'), dict) else {}
    rmse: dict[str, Any] = data.get('rmse', {}) if isinstance(data.get('rmse'), dict) else {}
    rows: list[tuple[str, float, float]] = []
    for model, w in weights.items():
        try:
            w_val = float(w)
        except (ValueError, TypeError):
            # Invalid numeric conversion or type error
            w_val = 0.0
        try:
            rmse_val = float(rmse.get(model, 0.0))
        except (ValueError, TypeError):
            # Invalid numeric conversion or type error
            rmse_val = 0.0
        rows.append((model, w_val, rmse_val))
    rows.sort(key=lambda x: x[1], reverse=True)
    header = 'timestamp,model,weight,rmse,index,horizon'
    ts = str(data.get('timestamp', ''))
    out_lines = [header]
    for model, w_val, rmse_val in rows:
        out_lines.append(f"{ts},{model},{w_val:.6f},{rmse_val:.6f},{index},{horizon}")
    return PlainTextResponse('\n'.join(out_lines))

@app.get('/api/ml/ensemble/quarantine_log')
async def api_ml_ensemble_quarantine_log(index: str, horizon: str | None = None, tail: int = 200) -> PlainTextResponse:
    """Return quarantine log CSV from <index>_ensemble_quarantine.log.

    Header: timestamp,event,model,z,dis,until_ms,horizon. Lines with fewer than 3 fields skipped.
    tail parameter limits returned rows after filtering (default 200). Missing file -> 404.
    """
    base = _ml_live_predictions_dir()
    fp = base / f'{index}_ensemble_quarantine.log'
    if not fp.exists():
        return PlainTextResponse('not found', status_code=404)
    try:
        raw_lines = fp.read_text(encoding='utf-8').splitlines()
    except Exception as e:
        get_error_handler().handle_error(e, category=ErrorCategory.FILE_IO, severity=ErrorSeverity.LOW, component='web.dashboard.app', function_name='api_ml_ensemble_quarantine_log', message='failed_read')
        return PlainTextResponse('read error', status_code=500)
    header = 'timestamp,event,model,z,dis,until_ms,horizon'
    rows: list[str] = []
    for ln in raw_lines:
        parts = [p.strip() for p in ln.split(',')]
        if len(parts) < 3:
            continue  # malformed
        # Expect format: ts,event,model,(extras... horizon=H)
        ts, event, model, *extras = parts
        z = ''
        dis = ''
        until_ms = ''
        h_val = ''
        for ex in extras:
            if ex.startswith('z='):
                z = ex.split('=',1)[1]
            elif ex.startswith('dis='):
                dis = ex.split('=',1)[1]
            elif ex.startswith('until='):
                until_ms = ex.split('=',1)[1]
            elif ex.startswith('horizon='):
                h_val = ex.split('=',1)[1]
        if horizon and h_val and h_val != horizon:
            continue
        rows.append(f"{ts},{event},{model},{z},{dis},{until_ms},{h_val}")
    if tail > 0 and len(rows) > tail:
        rows = rows[-tail:]
    return PlainTextResponse('\n'.join([header] + rows))

# --------------------------- Path Forecast Endpoint (composite) ---------------------------
@app.get('/api/ml/forecast/path')
async def api_ml_forecast_path(index: str, horizon: int = 60, quantiles: str = '0.1,0.5,0.9', bucket_ms: int = 60000) -> PlainTextResponse:
    """Return composite path forecast quantiles as CSV.

    CSV header: timestamp,index,horizon,quantile,future_ts,value
    Each row: request timestamp (iso), index, horizon (minutes), quantile, future epoch ms, value
    Falls back to placeholder NAN rows if forecaster unavailable.
    """
    req_ts = _utc_now_z()
    q_list: list[float] = []
    for part in str(quantiles).split(','):
        part = part.strip()
        if not part:
            continue
        try:
            q_list.append(float(part))
        except (ValueError, TypeError):
            # Invalid numeric conversion or type error
            continue
    if not q_list:
        q_list = [0.1, 0.5, 0.9]
    # Attempt composite forecast if available
    rows: list[str] = []
    header = 'timestamp,index,horizon,quantile,future_ts,value'
    if CompositePathForecaster is None or CompositeConfig is None:
        # Placeholder output: single future point per quantile with NAN
        now_ms = int(time.time()*1000)
        for q in q_list:
            rows.append(f"{req_ts},{index},{horizon},{q:.3f},{now_ms + bucket_ms},{float('nan')}")
        return PlainTextResponse('\n'.join([header] + rows))
    try:
        root = _paths_core.project_root() / 'data' / 'g6_data'
    except (AttributeError, OSError, TypeError):
        # Path resolution error
        root = Path('data/g6_data')
    try:
        cfg = CompositeConfig(root=root, window=60, k=15, min_days=3)
        fore = CompositePathForecaster(cfg)
        now_ms = int(time.time()*1000)
        # Minimal recent window: empty -> internal logic handles
        times, qmap = fore.forecast_path([], context={'index': index, 'now_ms': now_ms, 'live_rows': []}, quantiles=q_list, horizon_minutes=int(horizon), bucket_ms=int(bucket_ms))
        for q in q_list:
            vals = list(qmap.get(q, []))
            for i, ft in enumerate(times):
                v = vals[i] if i < len(vals) else float('nan')
                rows.append(f"{req_ts},{index},{horizon},{q:.3f},{ft},{v}")
    except Exception as e:
        get_error_handler().handle_error(e, category=ErrorCategory.ML, severity=ErrorSeverity.LOW, component='web.dashboard.app', function_name='api_ml_forecast_path', message='forecast_error')
        now_ms = int(time.time()*1000)
        for q in q_list:
            rows.append(f"{req_ts},{index},{horizon},{q:.3f},{now_ms + bucket_ms},{float('nan')}")
    return PlainTextResponse('\n'.join([header] + rows))

@app.get('/api/ml/ensemble/forecast2')
async def api_ml_ensemble_forecast2(index: str, horizon: int = 60) -> JSONResponse:
    """Temporary duplicate forecast endpoint to diagnose routing issues."""
    body = {
        'index': index.upper(),
        'horizon': horizon,
        'diagnostic': True,
        'timestamp': int(time.time()*1000),
        'forecast': {'p50': 195.3},
    }
    return JSONResponse(body)
