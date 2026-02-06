from __future__ import annotations

from collections.abc import Mapping, Sequence
import contextlib
import logging
import os

# Hoisted trivial stdlib imports used within functions
import sys
from typing import Any
import uuid

from src.utils.output_components import (
    JsonLike,
    JsonlSink,
    LoggingSink,
    MemorySink,
    OutputEvent,
    OutputSink,
    PanelFileSink,
    RichSink,
    StdoutSink,
)
from src.utils.output_components.panels_txn_fallback import (
    fallback_cleanup_after_abort,
    fallback_copy_and_cleanup_after_commit,
)

try:
    # Prefer central env adapter for consistency
    from src.collectors.env_adapter import (
        get_bool as _env_get_bool,
        get_float as _env_get_float,
        get_int as _env_get_int,
        get_str as _env_get_str,  # type: ignore
    )
except Exception:  # pragma: no cover
    # Safe fallbacks if adapter not available early in import graph
    def _env_get_str(name: str, default: str = "") -> str:
        try:
            v = os.getenv(name)
            return default if v is None else v
        except Exception:
            return default
    def _env_get_bool(name: str, default: bool = False) -> bool:
        try:
            v = os.getenv(name)
            if v is None:
                return default
            return v.strip().lower() in {"1","true","yes","on","y"}
        except Exception:
            return default
    def _env_get_int(name: str, default: int) -> int:
        try:
            v = os.getenv(name)
            if v is None or str(v).strip() == "":
                return default
            return int(str(v).strip())
        except Exception:
            return default
    def _env_get_float(name: str, default: float) -> float:
        try:
            v = os.getenv(name)
            if v is None or str(v).strip() == "":
                return default
            return float(str(v).strip())
        except Exception:
            return default

# Backward-compat shim for existing truthy checks used in this module
def is_truthy_env(name: str) -> bool:
    return _env_get_bool(name, False)

# Optional Rich support
try:
    import rich.console as _rich_console
except Exception:  # pragma: no cover
    _rich_console = None  # type: ignore[assignment]

# Optional imports for late import elimination (Batch 29)
try:
    from src.health import runtime as health_runtime
except ImportError:
    health_runtime = None  # type: ignore
try:
    from src.health.models import HealthLevel, HealthState
except ImportError:
    HealthLevel = None  # type: ignore
    HealthState = None  # type: ignore
try:
    from src.metrics import get_metrics_singleton
except ImportError:
    get_metrics_singleton = None  # type: ignore
try:
    from src.panels.version import PANEL_SCHEMA_VERSION
except ImportError:
    PANEL_SCHEMA_VERSION = None  # type: ignore


# ---------------
# Colorizing Filter (applies to standard logging handlers not using Rich)
# ---------------
class _ColorizingFilter(logging.Filter):  # pragma: no cover (cosmetic)
    LEVEL_COLORS = {
        logging.DEBUG: '\x1b[2m',          # dim
        logging.INFO: '\x1b[36m',           # cyan
        logging.WARNING: '\x1b[33m',       # yellow
        logging.ERROR: '\x1b[31m',         # red
        logging.CRITICAL: '\x1b[1;41m',    # bold white on red bg
    }
    KEYWORD_COLORS = [
        ('success', '\x1b[32m'),  # green
        ('passed', '\x1b[32m'),
        ('fail', '\x1b[31m'),
        ('error', '\x1b[31m'),
        ('warning', '\x1b[33m'),
    ]
    RESET = '\x1b[0m'
    def __init__(self):
        super().__init__('g6.color_filter')
        self._tty = sys.stdout.isatty() if hasattr(sys.stdout, 'isatty') else False
        self._mode = _env_get_str('G6_LOG_COLOR_MODE','auto').lower()
        if self._mode not in {'auto','on','off'}:
            self._mode = 'auto'
        if self._mode == 'off':
            self._enabled = False
        elif self._mode == 'on':
            self._enabled = True
        else:  # auto
            self._enabled = self._tty
        # Allow explicit force (overrides auto/tty) mainly for Windows terminals supporting ANSI
        if is_truthy_env('G6_LOG_COLOR_FORCE'):
            self._enabled = True
        # Windows ANSI enable (best-effort)
        if self._enabled and os.name == 'nt':
            try:
                import colorama  # type: ignore
                colorama.just_fix_windows_console()  # initialize if available
            except Exception:
                pass
    def filter(self, record: logging.LogRecord) -> bool:
        if not self._enabled:
            return True
        try:
            msg = record.getMessage()
            base_color = self.LEVEL_COLORS.get(record.levelno)
            if base_color:
                # Apply keyword highlight precedence: if keyword found, override base color
                lower_msg = msg.lower()
                for kw, col in self.KEYWORD_COLORS:
                    if kw in lower_msg:
                        base_color = col
                        break
                record.msg = f"{base_color}{msg}{self.RESET}"  # type: ignore[assignment]
        except Exception:
            pass
        return True

def _install_color_filter():  # pragma: no cover (runtime cosmetic)
    try:
        # Avoid if Rich sink likely handling color (Rich provides own styling)
        sinks_env = _env_get_str('G6_OUTPUT_SINKS','stdout,logging').lower()
        if 'rich' in sinks_env:
            return
        root = logging.getLogger()
        if any(isinstance(f, _ColorizingFilter) for f in getattr(root,'filters',[])):
            return
        root.addFilter(_ColorizingFilter())
    except Exception:
        pass


# ------------------------------
# Router
# ------------------------------

_LEVEL_ORDER = {
    "debug": 10,
    "info": 20,
    "success": 20,
    "warning": 30,
    "warn": 30,
    "error": 40,
    "critical": 50,
}


def _normalize_level(level: str) -> str:
    level_lc = level.lower()
    if level_lc == "warn":
        return "warning"
    if level_lc not in _LEVEL_ORDER:
        return "info"
    return level_lc


class OutputRouter:
    def __init__(self, sinks: list[OutputSink] | None = None, min_level: str = "info") -> None:
        self._sinks: list[OutputSink] = list(sinks or [])
        self._min_level = _normalize_level(min_level)
        # Maintain a simple transaction stack for panel writes
        self._panel_txn_stack: list[str] = []

    def add_sink(self, sink: OutputSink) -> None:
        self._sinks.append(sink)

    def set_min_level(self, level: str) -> None:
        self._min_level = _normalize_level(level)

    def should_emit(self, level: str) -> bool:
        return _LEVEL_ORDER[_normalize_level(level)] >= _LEVEL_ORDER[self._min_level]

    def emit(
        self,
        message: str,
        *,
        level: str = "info",
        scope: str | None = None,
        tags: list[str] | Mapping[str, str] | None = None,
        data: JsonLike | None = None,
        extra: Mapping[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> None:
        level_n = _normalize_level(level)
        if not self.should_emit(level_n):
            return
        evt = OutputEvent(
            timestamp=timestamp or OutputEvent.now_iso(),
            level=level_n,
            message=message,
            scope=scope,
            tags=tags,
            data=data,
            extra=extra,
        )
        for s in self._sinks:
            try:
                s.emit(evt)
            except Exception:
                # Sinks should not break others
                with contextlib.suppress(Exception):
                    logging.getLogger("g6").exception("Output sink failed: %s", type(s).__name__)

    # Convenience level methods
    def debug(self, msg: str, **kw: Any) -> None: self.emit(msg, level="debug", **kw)
    def info(self, msg: str, **kw: Any) -> None: self.emit(msg, level="info", **kw)
    def success(self, msg: str, **kw: Any) -> None: self.emit(msg, level="success", **kw)
    def warning(self, msg: str, **kw: Any) -> None: self.emit(msg, level="warning", **kw)
    def error(self, msg: str, **kw: Any) -> None: self.emit(msg, level="error", **kw)
    def critical(self, msg: str, **kw: Any) -> None: self.emit(msg, level="critical", **kw)

    # Panel update helper: directs to panel sinks without printing human output
    def panel_update(self, panel: str, data: JsonLike, *, kind: str | None = None) -> None:
        # Attach txn context if any
        extra_base: dict[str, Any] = {"_panel": panel}
        if kind:
            extra_base["_kind"] = kind
        if self._panel_txn_stack:
            extra_base["_txn_id"] = self._panel_txn_stack[-1]
        evt = OutputEvent(
            timestamp=OutputEvent.now_iso(),
            level="info",
            message=f"panel_update:{panel}",
            scope="panel",
            tags=None,
            data=data,
            extra=extra_base,
        )
        for s in self._sinks:
            try:
                # Only sinks that care (e.g., PanelFileSink) will act
                s.emit(evt)
            except Exception:
                with contextlib.suppress(Exception):
                    logging.getLogger("g6").exception("Output sink failed: %s", type(s).__name__)

    def panel_append(self, panel: str, item: JsonLike, *, cap: int = 100, kind: str | None = None) -> None:
        extra_base: dict[str, Any] = {"_panel": panel, "_mode": "append", "_cap": cap}
        if kind:
            extra_base["_kind"] = kind
        if self._panel_txn_stack:
            extra_base["_txn_id"] = self._panel_txn_stack[-1]
        evt = OutputEvent(
            timestamp=OutputEvent.now_iso(),
            level="info",
            message=f"panel_append:{panel}",
            scope="panel",
            tags=None,
            data=item,
            extra=extra_base,
        )
        for s in self._sinks:
            try:
                s.emit(evt)
            except Exception:
                with contextlib.suppress(Exception):
                    logging.getLogger("g6").exception("Output sink failed: %s", type(s).__name__)

    def panel_extend(self, panel: str, items: Sequence[JsonLike], *, cap: int = 100, kind: str | None = None) -> None:
        extra_base: dict[str, Any] = {"_panel": panel, "_mode": "extend", "_cap": cap}
        if kind:
            extra_base["_kind"] = kind
        if self._panel_txn_stack:
            extra_base["_txn_id"] = self._panel_txn_stack[-1]
        evt = OutputEvent(
            timestamp=OutputEvent.now_iso(),
            level="info",
            message=f"panel_extend:{panel}",
            scope="panel",
            tags=None,
            data=list(items),
            extra=extra_base,
        )
        for s in self._sinks:
            try:
                s.emit(evt)
            except Exception:
                with contextlib.suppress(Exception):
                    logging.getLogger("g6").exception("Output sink failed: %s", type(s).__name__)

    # ---------------
    # Panel transactions
    # ---------------
    class PanelsTransaction:
        def __init__(self, router: OutputRouter, txn_id: str | None = None) -> None:
            self._router = router
            self._txn_id = txn_id or str(uuid.uuid4())
            self._active = False
        @property
        def id(self) -> str:
            return self._txn_id
        def __enter__(self) -> OutputRouter.PanelsTransaction:
            self._router._panel_txn_stack.append(self._txn_id)
            self._active = True
            return self
        def commit(self) -> None:
            if not self._active:
                return
            self._router._panel_txn_stack.pop()
            # Tell sinks to commit this txn id
            self._router.emit(
                "panels_txn_commit",
                level="info",
                scope="panel",
                data=None,
                extra={"_txn_action": "commit", "_txn_id": self._txn_id},
            )
            self._active = False
        def abort(self) -> None:
            if not self._active:
                return
            self._router._panel_txn_stack.pop()
            # Tell sinks to abort this txn id
            self._router.emit(
                "panels_txn_abort",
                level="info",
                scope="panel",
                data=None,
                extra={"_txn_action": "abort", "_txn_id": self._txn_id},
            )
            self._active = False
        def __exit__(self, exc_type, exc, tb) -> None:
            if exc_type is None:
                self.commit()
                base_dir = _env_get_str('G6_PANELS_DIR', os.path.join('data','panels'))
                fallback_copy_and_cleanup_after_commit(
                    base_dir,
                    txn_id=self._txn_id,
                    committed_at=OutputEvent.now_iso(),
                )
            else:
                self.abort()
                base_dir = _env_get_str('G6_PANELS_DIR', os.path.join('data','panels'))
                fallback_cleanup_after_abort(base_dir, txn_id=self._txn_id)

    def begin_panels_txn(self, txn_id: str | None = None) -> OutputRouter.PanelsTransaction:
        """Begin a panels transaction. Use as a context manager:
        with router.begin_panels_txn():
            router.panel_update(...)
            ...
        """
        return OutputRouter.PanelsTransaction(self, txn_id)

    def close(self) -> None:  # pragma: no cover - cleanup helper for tests
        # Give sinks a chance to cleanup
        for s in self._sinks:
            try:
                close_fn = getattr(s, 'close', None)
                if callable(close_fn):
                    close_fn()
            except Exception:
                pass
        self._sinks.clear()
        self._panel_txn_stack.clear()


# ------------------------------
# Factory / singleton
# ------------------------------

_router_singleton: OutputRouter | None = None


def _build_from_env() -> OutputRouter:
    sinks_env = _env_get_str("G6_OUTPUT_SINKS", "stdout,logging").strip()
    min_level = _env_get_str("G6_OUTPUT_LEVEL", "info").strip().lower() or "info"
    sinks: list[OutputSink] = []

    for token in [s.strip().lower() for s in sinks_env.split(",") if s.strip()]:
        if token == "stdout":
            sinks.append(StdoutSink())
        elif token == "logging":
            sinks.append(LoggingSink())
        elif token == "rich":
            if _rich_console is not None:
                sinks.append(RichSink())
        elif token == "jsonl":
            path = _env_get_str("G6_OUTPUT_JSONL_PATH", "g6_output.jsonl")
            sinks.append(JsonlSink(path))
        elif token == "memory":
            sinks.append(MemorySink())
        elif token == "panels":
            base_dir = _env_get_str("G6_PANELS_DIR", os.path.join("data", "panels"))
            include = _env_get_str("G6_PANELS_INCLUDE", "").strip()
            include_set = [s for s in include.split(",") if s.strip()] if include else None
            atomic = _env_get_bool("G6_PANELS_ATOMIC", True)
            sinks.append(PanelFileSink(base_dir, include=include_set, atomic=atomic))
        # Unknown tokens are ignored to be forgiving

    if not sinks:
        # Always have at least a stdout sink
        sinks.append(StdoutSink())
    # Install colorizing filter (safe no-op if mode disabled or Rich active)
    with contextlib.suppress(Exception):
        _install_color_filter()
    return OutputRouter(sinks=sinks, min_level=min_level)


def get_output(reset: bool = False) -> OutputRouter:
    global _router_singleton
    if reset or _router_singleton is None:
        if _router_singleton is not None and reset:
            with contextlib.suppress(Exception):
                _router_singleton.close()
        _router_singleton = _build_from_env()
    return _router_singleton
