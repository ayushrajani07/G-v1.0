"""Market hours gate extraction.

Encapsulates logic deciding whether to proceed with collection or return an
early structured 'market_closed' response. Mirrors legacy behavior in
`unified_collectors.run_unified_collectors` including:
- Dynamic import of market_hours.is_market_open
- Force-open overrides (G6_FORCE_MARKET_OPEN)
- Snapshot test broadening (pytest or G6_SNAPSHOT_TEST_MODE when build_snapshots)
- Next open time & wait seconds computation
- Metrics collection_cycle_in_progress reset (best effort)
- Structured return shape with keys: status, indices_processed, have_raw,
  snapshots, snapshot_count, indices, next_open, wait_seconds

Public API:
    evaluate_market_gate(build_snapshots, metrics) -> (proceed: bool, early_result: dict | None)
"""
from __future__ import annotations

import datetime
import importlib
import logging
import os
import sys
import time
from typing import Any
from src.config.env_config import EnvConfig

logger = logging.getLogger(__name__)

__all__ = ["evaluate_market_gate"]

# Throttle for repeated "market closed" banner to avoid log spam.
# Default to once per minute, override via G6_MARKET_GATE_LOG_INTERVAL_SEC.
_CLOSED_BANNER_INTERVAL_SEC: float = EnvConfig.get_float("G6_MARKET_GATE_LOG_INTERVAL_SEC", 60.0)
_last_closed_banner_ts: float = 0.0
_MARKET_PROMPT_DONE: bool = False


def _maybe_prompt_force_open(*, next_open: datetime.datetime | None, wait_minutes: float | None) -> str | None:
    """Optionally prompt to force market open in an interactive terminal.

    Returns a reason string if user accepted force-open, else None.
    Prompt is shown at most once per process.
    """
    global _MARKET_PROMPT_DONE
    if _MARKET_PROMPT_DONE:
        return None
    # Avoid interactive prompts during tests.
    if os.getenv('PYTEST_CURRENT_TEST'):
        return None
    try:
        if not EnvConfig.get_bool('G6_MARKET_GATE_INTERACTIVE_PROMPT', False):
            return None
    except Exception:
        return None
    # Only prompt on a real terminal.
    try:
        if not (sys.stdin and sys.stdin.isatty() and sys.stdout and sys.stdout.isatty()):
            return None
    except Exception:
        return None

    # Only offer prompt outside normal market hours:
    # - Weekends
    # - Weekdays after market close (15:30 IST)
    # Do NOT prompt in the morning/pre-open window.
    try:
        now_utc = datetime.datetime.now(datetime.UTC)
        ist_now = now_utc + datetime.timedelta(hours=5, minutes=30)
        if ist_now.weekday() >= 5:
            pass  # weekend -> allow prompt
        else:
            if ist_now.time() < datetime.time(15, 30, 0):
                return None
    except Exception:
        # If time conversion fails, be conservative: do not prompt.
        return None

    _MARKET_PROMPT_DONE = True
    msg = "Market is closed"
    if next_open is not None:
        msg += f". Next open: {next_open}"
    if wait_minutes is not None:
        msg += f" (in {wait_minutes:.1f} minutes)"
    msg += ".\nForce-open and run anyway? [y/N]: "
    try:
        ans = input(msg).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    if ans in ("y", "yes"):
        os.environ['G6_FORCE_MARKET_OPEN'] = '1'
        try:
            EnvConfig.clear_cache()
        except Exception:
            pass
        return "interactive"
    return None


def evaluate_market_gate(build_snapshots: bool, metrics: Any | None) -> tuple[bool, dict[str, Any] | None]:
    # Determine market open status (permissive default on failure)
    _market_open = True
    # Explicit force-open override for tests and controlled runs
    _force_open_env = EnvConfig.get_bool('G6_FORCE_MARKET_OPEN', False)
    try:  # pragma: no cover
        _mh = importlib.import_module('src.utils.market_hours')
        _market_open = bool(getattr(_mh, 'is_market_open', lambda **k: True)(market_type="equity", session_type="regular"))
    except Exception:
        _market_open = True

    # Weekend mode logic removed (reverting to strict weekday/holiday market hours only)

    # Snapshot tests may still bypass to prevent flakiness in CI
    force_open = False
    try:  # pragma: no cover (defensive)
        if build_snapshots:
            if ('PYTEST_CURRENT_TEST' in os.environ) or ('pytest' in __import__('sys').modules) or EnvConfig.get_bool('G6_SNAPSHOT_TEST_MODE', False):
                force_open = True
    except Exception:
        pass

    # Honor environment override regardless of snapshot mode
    if _force_open_env:
        force_open = True

    # Optional conditional override: if market is closed AND the next market open is far away,
    # allow collectors to run for offline/dev operations without waiting for open.
    # Example: G6_FORCE_MARKET_OPEN_IF_NEXT_OPEN_GT_MINUTES=120
    force_open_reason: str | None = None
    try:
        threshold_minutes = float(EnvConfig.get_float('G6_FORCE_MARKET_OPEN_IF_NEXT_OPEN_GT_MINUTES', 0.0))
    except Exception:
        threshold_minutes = 0.0
    if (not force_open) and (not _market_open) and threshold_minutes > 0:
        try:
            _mh = importlib.import_module('src.utils.market_hours')
            get_next_market_open = getattr(_mh, 'get_next_market_open', None)
            if callable(get_next_market_open):
                now_utc = datetime.datetime.now(datetime.UTC)
                next_open_dt = get_next_market_open(market_type="equity", session_type="regular", reference_time=now_utc)
                wait_minutes = (next_open_dt - now_utc).total_seconds() / 60.0
                if wait_minutes > threshold_minutes:
                    force_open = True
                    force_open_reason = f"next_open_in={wait_minutes:.1f}m_gt_{threshold_minutes:.0f}m"
        except Exception:
            # Non-fatal; proceed with standard closed behavior.
            pass

    if force_open or _market_open:
        disable_repeat = EnvConfig.get_bool('G6_DISABLE_REPEAT_BANNERS', False)
        single_header_mode = EnvConfig.get_bool('G6_SINGLE_HEADER_MODE', False)
        banner_debug = EnvConfig.get_bool('G6_BANNER_DEBUG', False)
        sentinel = '_g6_logged_market_open'
        is_forced = bool(force_open and (not _market_open))
        if is_forced and force_open_reason:
            msg = f"Equity market is closed, but force-open is enabled ({force_open_reason}); starting collection"
        elif is_forced:
            msg = "Equity market is closed, but force-open is enabled; starting collection"
        else:
            msg = "Equity market is open, starting collection"
        if single_header_mode:
            # In single header mode we always suppress duplicates regardless of disable_repeat
            if sentinel not in globals():
                logger.info(msg)
                globals()[sentinel] = True
            else:
                if banner_debug:
                    logger.debug("banner_suppressed market_open single_header_mode=1")
        else:
            if not (disable_repeat and sentinel in globals()):
                logger.info(msg)
                globals()[sentinel] = True
            elif banner_debug:
                logger.debug("banner_suppressed market_open disable_repeat=1")
        return True, None

    # Market closed path
    try:
        _mh = importlib.import_module('src.utils.market_hours')
        get_next_market_open = _mh.get_next_market_open
        next_open = get_next_market_open(market_type="equity", session_type="regular")
        wait_time = (next_open - datetime.datetime.now(datetime.UTC)).total_seconds()
    except Exception:
        next_open = None; wait_time = 0

    # Optional interactive prompt (default enabled by run_orchestrator_loop.py).
    if not force_open:
        try:
            reason = _maybe_prompt_force_open(
                next_open=next_open,
                wait_minutes=(wait_time / 60.0 if next_open else None),
            )
            if reason:
                force_open = True
                force_open_reason = reason
        except Exception:
            pass

    if force_open:
        # Re-enter open path for unified handling/logging.
        disable_repeat = EnvConfig.get_bool('G6_DISABLE_REPEAT_BANNERS', False)
        single_header_mode = EnvConfig.get_bool('G6_SINGLE_HEADER_MODE', False)
        banner_debug = EnvConfig.get_bool('G6_BANNER_DEBUG', False)
        sentinel = '_g6_logged_market_open'
        msg = "Equity market is closed, but force-open is enabled; starting collection"
        if force_open_reason:
            msg = f"Equity market is closed, but force-open is enabled ({force_open_reason}); starting collection"
        if single_header_mode:
            if sentinel not in globals():
                logger.info(msg)
                globals()[sentinel] = True
            else:
                if banner_debug:
                    logger.debug("banner_suppressed market_open single_header_mode=1")
        else:
            if not (disable_repeat and sentinel in globals()):
                logger.info(msg)
                globals()[sentinel] = True
            elif banner_debug:
                logger.debug("banner_suppressed market_open disable_repeat=1")
        return True, None

    # Throttled banner: emit at most once per configured interval
    global _last_closed_banner_ts
    now_ts = time.time()
    if (_last_closed_banner_ts == 0.0) or (now_ts - _last_closed_banner_ts >= _CLOSED_BANNER_INTERVAL_SEC):
        logger.info(
            "Equity market is closed. Next market open: %s%s",
            next_open,
            (f" (in {wait_time/60:.1f} minutes)" if next_open else ""),
        )
        _last_closed_banner_ts = now_ts
    # Emit trace via existing lightweight tracer if available
    try:  # pragma: no cover
        _se = importlib.import_module('src.collectors.helpers.struct_events')
        emit_trace_event = getattr(_se, 'emit_trace_event', None)
        if callable(emit_trace_event):
            emit_trace_event("market_closed", next_open=str(next_open), wait_s=wait_time)
    except Exception:
        try:
            # Fallback: attempt global _trace imported by unified collectors
            _uc = importlib.import_module('src.collectors.unified_collectors')
            _trace = getattr(_uc, '_trace', None)
            if callable(_trace):
                _trace("market_closed", next_open=str(next_open), wait_s=wait_time)
        except Exception:
            logger.debug("trace_event_failed_market_closed", exc_info=True)

    if metrics and hasattr(metrics, 'collection_cycle_in_progress'):
        try:
            metrics.collection_cycle_in_progress.set(0)
        except Exception:
            pass

    early = {
        'status': 'market_closed',
        'indices_processed': 0,
        'have_raw': False,
        'snapshots': [] if build_snapshots else None,
        'snapshot_count': 0,
        'indices': [],
        'next_open': str(next_open) if next_open else None,
        'wait_seconds': wait_time,
    }
    return False, early
