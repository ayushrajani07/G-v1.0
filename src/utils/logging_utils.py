"""Unified logging utilities for G6 Platform."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
import logging
import os
import sys
from typing import Any

# Phase 2: Centralized environment variable access
from src.config.env_config import EnvConfig

# Optional imports
try:
    from src.utils.env_flags import is_truthy_env as _is_truthy_env
except ImportError:  # pragma: no cover
    _is_truthy_env = None

try:
    from src.errors import (
        ErrorCategory as _ErrorCategory,
        ErrorSeverity as _ErrorSeverity,
        handle_error as _handle_error,
    )
except ImportError:  # pragma: no cover
    _handle_error = None
    _ErrorCategory = None
    _ErrorSeverity = None

DEFAULT_FORMAT = '%(asctime)s - %(threadName)s - %(name)s - %(levelname)s - %(message)s'
# Minimal console format (message only) used for cleaner terminal output.
MINIMAL_CONSOLE_FORMAT = '%(message)s'

SUPPRESSED_LOGGERS = ['urllib3', 'requests', 'kiteconnect.connection']


def _safe_close_handler(handler: logging.Handler) -> None:
    try:
        handler.flush()
    except Exception:
        return
    try:
        handler.close()
    except Exception:
        return


def _resolve_console_bool_flags() -> tuple[bool, bool, bool]:
    """Resolve (verbose_console, minimal_disabled, json_console).

    If legacy helper `is_truthy_env` is available, use it. If it errors,
    fall back to EnvConfig.
    """
    if _is_truthy_env is not None:
        try:
            return (
                bool(_is_truthy_env('G6_VERBOSE_CONSOLE')),
                bool(_is_truthy_env('G6_DISABLE_MINIMAL_CONSOLE')),
                bool(_is_truthy_env('G6_JSON_LOGS')),
            )
        except Exception:
            pass
    return (
        EnvConfig.get_bool('G6_VERBOSE_CONSOLE', False),
        EnvConfig.get_bool('G6_DISABLE_MINIMAL_CONSOLE', False),
        EnvConfig.get_bool('G6_JSON_LOGS', False),
    )


class _ConsoleNoiseSuppressor(logging.Filter):
    """Suppresses high-volume console logs while keeping file logs intact."""

    def __init__(self, *, verbose_console: bool) -> None:
        super().__init__()
        self._verbose_console = verbose_console

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        try:
            # If the user asked for verbose console, never suppress.
            if self._verbose_console:
                return True

            msg = record.getMessage() or ''

            show_struct = EnvConfig.get_bool('G6_CONSOLE_SHOW_STRUCT_EVENTS', False)
            show_phase = EnvConfig.get_bool('G6_CONSOLE_SHOW_PHASE_TIMING', False)
            show_expiry = EnvConfig.get_bool('G6_CONSOLE_SHOW_EXPIRY_DETAIL', False)
            show_index_detail = EnvConfig.get_bool('G6_CONSOLE_SHOW_INDEX_DETAIL', False)
            show_persist = EnvConfig.get_bool('G6_CONSOLE_SHOW_PERSIST_FLOW', False)
            show_no_exp_warn = EnvConfig.get_bool('G6_CONSOLE_SHOW_NO_EXPIRY_WARNINGS', False)
            show_metrics_gov = EnvConfig.get_bool('G6_CONSOLE_SHOW_METRICS_GOVERNANCE', False)

            # Structured event spam
            if (msg.startswith('STRUCT ') or msg.startswith('STRUCT_H ')) and not show_struct:
                return False

            # Phase timing wall-of-text
            if msg.startswith('PHASE_TIMING') and not show_phase:
                return False

            # Per-expiry verbosity
            if record.name.endswith('expiry_processor') and not show_expiry:
                if msg.startswith('Collecting ') and ' strikes for ' in msg:
                    return False
                if msg.startswith('Successfully collected ') and ' options for ' in msg:
                    return False

            # Per-index verbosity (start + ATM already present in INDEX summary)
            if record.name.endswith('index_processor') and not show_index_detail:
                if msg.startswith('Collecting data for '):
                    return False
                if ' ATM strike: ' in msg:
                    # In human mode we intentionally surface ATM strike (screenshot-style output)
                    try:
                        human_mode = EnvConfig.get_bool('G6_HUMAN_MODE', False)
                        show_atm = EnvConfig.get_bool('G6_HUMAN_SHOW_ATM', True)
                        if human_mode and show_atm:
                            return True
                    except Exception:
                        pass
                    return False

            # Persistence flow write count
            if (
                record.name.endswith('persist_flow')
                and (not show_persist)
                and msg.startswith('Writing ')
                and msg.endswith(' records to CSV sink')
            ):
                return False

            # Noisy non-fatal warning from expiry discovery
            if msg.startswith('no_expiries_extracted_from_instruments') and not show_no_exp_warn:
                return False

            # Metrics governance duplicate chatter
            return not (msg.startswith('registry_guard.duplicate_detected') and (not show_metrics_gov))
        except Exception:
            # Never break logging
            return True


class _ContextEnricherFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        try:
            from . import log_context as _lc

            ctx = _lc.get_context()
            for k in ("run_id", "component", "cycle", "index", "provider"):
                if k in ctx and not hasattr(record, k):
                    setattr(record, k, ctx[k])
        except Exception:
            pass
        return True


class _AsciiSanitizer(logging.Filter):
    _MAP = str.maketrans(
        {
            '╔': '+',
            '╗': '+',
            '╚': '+',
            '╝': '+',
            '═': '=',
            '║': '|',
            '─': '-',
            '┌': '+',
            '┐': '+',
            '└': '+',
            '┘': '+',
            '│': '|',
        }
    )

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        if isinstance(record.msg, str):
            record.msg = record.msg.translate(self._MAP)
        return True


def _make_json_formatter() -> logging.Formatter:
    try:
        import orjson as _orjson

        json_dumps: Callable[[Any], Any] = _orjson.dumps
        is_orjson = True
    except Exception:  # pragma: no cover
        import json as _json

        json_dumps = _json.dumps
        is_orjson = False

    class _JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
            # Use record.created or fall back to time.time() to avoid naive datetime usage
            import time as _time

            # Pull structured context if available
            try:
                from . import log_context as _lc

                ctx = _lc.get_context()
            except Exception:
                ctx = {}
            payload: dict[str, Any] = {
                'ts': getattr(record, 'created', _time.time()),
                'level': record.levelname,
                'logger': record.name,
                'thread': record.threadName,
                'msg': record.getMessage(),
                'ctx': ctx or None,
            }
            if record.exc_info:
                payload['exc_info'] = self.formatException(record.exc_info)
            try:
                if is_orjson:
                    return json_dumps(payload).decode('utf-8')
                s = json_dumps(payload)
                return s if isinstance(s, str) else str(s)
            except Exception:
                return str(payload)

    return _JsonFormatter()


def setup_logging(level: str = 'INFO', log_file: str | None = None, fmt: str = DEFAULT_FORMAT) -> logging.Logger:
    """Configure root logging.

    Console handler: by default uses minimal message-only format to satisfy
    requirement: "REMOVE INFO- AND ALL TEXT BEFORE THAT FROM TERMINAL OUTPUT".
    Override via env G6_VERBOSE_CONSOLE=1 (restores full DEFAULT_FORMAT) or
    explicitly pass a fmt argument.

    File handler (if enabled) always uses full DEFAULT_FORMAT for diagnostics.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(log_level)
    # Remove existing handlers to avoid duplication on re-init
    for h in root.handlers[:]:
        with suppress(Exception):
            root.removeHandler(h)
        _safe_close_handler(h)

    # Decide console format precedence: explicit fmt parameter beats env toggles.
    verbose_console_env, minimal_disabled_env, json_console_env = _resolve_console_bool_flags()
    # If caller passed a custom fmt different from DEFAULT_FORMAT, honor it.
    if fmt != DEFAULT_FORMAT:
        console_fmt = fmt
    else:
        console_fmt = DEFAULT_FORMAT if (verbose_console_env or minimal_disabled_env) else MINIMAL_CONSOLE_FORMAT

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(log_level)

    # Console noise suppression: keep important info visible (cycle/index summaries, real warnings/errors)
    # while hiding high-volume diagnostic lines by default. This does NOT change what gets logged;
    # it only affects the default console handler.
    console.addFilter(_ConsoleNoiseSuppressor(verbose_console=verbose_console_env))
    if json_console_env:
        try:
            console.setFormatter(_make_json_formatter())
        except Exception:
            console.setFormatter(logging.Formatter(console_fmt))
    else:
        # Enrich plain text logs with selected context fields by adding a filter
        console.addFilter(_ContextEnricherFilter())
        console.setFormatter(logging.Formatter(console_fmt))
    try:
        enc = getattr(sys.stdout, 'encoding', '') or ''
        if enc.lower() not in ('utf-8', 'utf8', 'utf_8'):
            console.addFilter(_AsciiSanitizer())
    except Exception:
        pass
    root.addHandler(console)

    if log_file:
        try:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            fh = logging.FileHandler(log_file, encoding='utf-8')
            fh.setLevel(log_level)
            # Always keep detailed format in file for post-mortem analysis
            fh.addFilter(_ContextEnricherFilter())
            fh.setFormatter(logging.Formatter(DEFAULT_FORMAT))
            root.addHandler(fh)
        except Exception as e:
            root.error("Failed to create log file handler: %s", e)
            if _handle_error is not None and _ErrorCategory is not None and _ErrorSeverity is not None:
                with suppress(Exception):
                    # Use facade to avoid circular import (Phase 2 refactoring)
                    _handle_error(
                        e,
                        category=_ErrorCategory.CONFIGURATION,
                        severity=_ErrorSeverity.MEDIUM,
                        context={"op": "create_file_handler", "path": log_file},
                        suppress=True,
                    )

    for name in SUPPRESSED_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    return root


# Best-effort cleanup of logging handlers at interpreter exit to avoid ResourceWarnings in tests
try:
    import atexit

    @atexit.register
    def _g6_close_logging_handlers() -> None:
        # Do not import or call any logging or error-handling code here.
        # During interpreter shutdown, streams may already be closed; simply
        # attempt a quiet flush/close and swallow any exceptions.
        try:
            root = logging.getLogger()
            handlers = list(root.handlers[:])
        except Exception:
            handlers = []
        for h in handlers:
            with suppress(Exception):
                h.flush()
            with suppress(Exception):
                h.close()
except Exception:
    pass

__all__ = ["setup_logging"]
