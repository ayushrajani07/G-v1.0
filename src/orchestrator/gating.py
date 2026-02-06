"""Gating utilities for orchestrator loop.

Encapsulates readiness and market hours gating logic previously embedded
in `unified_main.collection_loop` and surrounding startup code.

Early slice focuses on:
  * Market open check & sleep decision helper
  * Provider readiness probe wrapper (reusable by legacy path)
  * Context update convenience functions

Future (planned):
  * Adaptive interval backoff on consecutive failures
  * Dynamic strike depth scaling triggers
  * Event bus emission for gate state changes
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
import sys
import time
from collections.abc import Callable
from typing import Any

from src.config.env_config import EnvConfig
from src.utils.env_flags import is_truthy_env  # type: ignore

from .gating_types import ProviderLike

try:
    from src.utils.market_hours import (  # type: ignore
        get_next_market_open,
        is_market_open,
        is_premarket_window,
        sleep_until_market_open,
    )
except (ImportError, AttributeError):  # pragma: no cover
    # Provide precise fallback signatures to satisfy type checkers when import fails
    def is_market_open(*, market_type: str = "equity", session_type: str = "regular",
                       reference_time: _dt.datetime | None = None, holidays: list[Any] | None = None) -> bool:  # type: ignore[override]
        return True
    def get_next_market_open() -> _dt.datetime:  # type: ignore[override]
        return _dt.datetime.now(_dt.UTC)
    def sleep_until_market_open(*, market_type: str = "equity", session_type: str = "regular",
                                check_interval: int = 60, on_wait_start: Any | None = None,
                                on_wait_tick: Any | None = None) -> None:  # type: ignore[override]
        time.sleep(0.1)
    def is_premarket_window(reference_time: _dt.datetime | None = None) -> bool:  # type: ignore[override]
        return False

logger = logging.getLogger(__name__)


_MARKET_PROMPT_DONE: bool = False


def _maybe_prompt_force_open(*, log_prefix: str = "[gating]") -> bool:
    """If enabled and interactive, prompt user to force-open when market is closed.

    Returns True if user chose to force-open (and env was updated), else False.
    Prompt is shown at most once per process.
    """
    global _MARKET_PROMPT_DONE
    if _MARKET_PROMPT_DONE:
        return False
    try:
        if not is_truthy_env('G6_MARKET_GATE_INTERACTIVE_PROMPT'):
            return False
    except (AttributeError, TypeError, KeyError, ValueError):
        return False

    # Only prompt on a real terminal.
    try:
        if not (sys.stdin and sys.stdin.isatty() and sys.stdout and sys.stdout.isatty()):
            return False
    except (AttributeError, OSError):
        return False

    # Only offer prompt outside normal market hours:
    # - Weekends
    # - Weekdays after market close (15:30 IST)
    # Do NOT prompt in the morning/pre-open window.
    try:
        now_utc = _dt.datetime.now(_dt.UTC)
        ist_now = now_utc + _dt.timedelta(hours=5, minutes=30)
        if ist_now.weekday() >= 5:
            pass  # weekend -> allow prompt
        else:
            if ist_now.time() < _dt.time(15, 30, 0):
                return False
    except (AttributeError, TypeError, ValueError, OSError, OverflowError):
        return False

    # Avoid interactive prompts during tests.
    if os.getenv('PYTEST_CURRENT_TEST'):
        return False

    _MARKET_PROMPT_DONE = True
    try:
        next_open = get_next_market_open()
        wait_minutes = (next_open - _dt.datetime.now(_dt.UTC)).total_seconds() / 60.0
    except (AttributeError, TypeError, ValueError, OSError, OverflowError):
        next_open = None
        wait_minutes = None

    msg = "Market is closed"
    if next_open is not None:
        msg += f". Next open: {next_open}"
    if wait_minutes is not None:
        msg += f" (in {wait_minutes:.1f} minutes)"
    msg += ".\nForce-open and run anyway? [y/N]: "

    try:
        ans = input(msg).strip().lower()
    except (EOFError, KeyboardInterrupt):
        logger.info("%s Interactive market prompt cancelled; continuing with normal gating", log_prefix)
        return False
    if ans in ("y", "yes"):
        os.environ['G6_FORCE_MARKET_OPEN'] = '1'
        try:
            EnvConfig.clear_cache()
        except (AttributeError, TypeError, RuntimeError):
            pass
        logger.warning("%s Market gate override accepted interactively: G6_FORCE_MARKET_OPEN=1", log_prefix)
        return True
    return False


def wait_for_market_open(market_type: str = "equity", session_type: str = "regular", check_interval: int = 10,
                          log_prefix: str = "[gating]") -> None:
    """Block until the next market open.

    Mirrors legacy behavior but extracted for reuse; logs a concise
    progress line every ~5 minutes (configurable via check_interval).
    """
    next_open = get_next_market_open()
    wait_secs = (next_open - _dt.datetime.now(_dt.UTC)).total_seconds()
    logger.info("%s Market closed. Waiting %s minutes until %s", log_prefix, wait_secs / 60, next_open)
    def _on_wait_start(dt):  # pragma: no cover (callback wiring)
        logger.info("%s Waiting for market open at %s", log_prefix, dt)
    def _on_wait_tick(rem):  # pragma: no cover
        if rem % 300 == 0:  # every 5 minutes
            logger.info("%s Still waiting: %sm", log_prefix, rem / 60)
        return True
    sleep_until_market_open(
        market_type=market_type,
        session_type=session_type,
        check_interval=check_interval,
        on_wait_start=_on_wait_start,
        on_wait_tick=_on_wait_tick,
    )


def provider_readiness_probe(
    providers: ProviderLike | Any,
    symbol: str = "NIFTY",
    error_handler: Callable[..., Any] | None = None,
) -> tuple[bool, str]:
    """Perform a lightweight provider readiness probe using get_ltp.

    Parameters
    ----------
    providers: Providers facade (must expose get_ltp)
    symbol: str
        Index symbol used for probe
    error_handler: Optional[Callable]
        Error handler for structured reporting (signature loosely compatible
        with get_error_handler().handle_error)
    Returns
    -------
    (ok, reason)
    """
    try:
        ltp = providers.get_ltp(symbol)  # type: ignore[attr-defined]
        if isinstance(ltp, (int, float)) and ltp > 0:
            return True, f"LTP={ltp}"
        return False, f"Non-positive LTP={ltp}"
    except (AttributeError, TypeError, ValueError, RuntimeError) as e:  # pragma: no cover
        # Handle provider access, type issues, or LTP retrieval failures
        if error_handler:
            try:
                error_handler(
                    e,
                    category=getattr(
                        __import__('src.error_handling', fromlist=['ErrorCategory']).error_handling,
                        'ErrorCategory',
                        object,
                    ),  # type: ignore
                    severity=getattr(
                        __import__('src.error_handling', fromlist=['ErrorSeverity']).error_handling,
                        'ErrorSeverity',
                        object,
                    ),  # type: ignore
                    component="orchestrator.gating",
                    function_name="provider_readiness_probe",
                    message="Provider readiness probe exception",
                    context={"symbol": symbol},
                )
            except (AttributeError, TypeError, ImportError, RuntimeError):
                # Handle error handler invocation failures
                pass
        return False, f"Exception {e}"


def should_skip_cycle_market_hours(only_during_market_hours: bool, *, log_prefix: str = "[gating]") -> bool:
    """Return True if current time is outside market hours and collection should pause."""
    if not only_during_market_hours:
        return False
    # Force-open override
    try:
        if is_truthy_env('G6_FORCE_MARKET_OPEN'):
            return False
    except (AttributeError, TypeError, KeyError):
        # Handle environment variable access failures
        pass

    # Conditional override: if the next market open is far away, allow cycles to run.
    # This is useful for offline/dev operations while keeping normal behavior near market open.
    try:
        raw = os.getenv('G6_FORCE_MARKET_OPEN_IF_NEXT_OPEN_GT_MINUTES', '').strip()
        threshold_minutes = float(raw) if raw else 0.0
    except (ValueError, TypeError):
        threshold_minutes = 0.0
    if threshold_minutes > 0:
        try:
            next_open = get_next_market_open()
            wait_minutes = (next_open - _dt.datetime.now(_dt.UTC)).total_seconds() / 60.0
            if wait_minutes > threshold_minutes:
                return False
        except (AttributeError, TypeError, ValueError, OSError, OverflowError):  # pragma: no cover
            pass
    # Weekend mode support removed: collection always suppressed outside market hours based solely on is_market_open.

    try:
        open_now = is_market_open()
    except (AttributeError, TypeError, RuntimeError):  # pragma: no cover
        # Handle market hours check failures
        open_now = True
    if open_now:
        return False

    # Optional interactive override (terminal prompt).
    try:
        if _maybe_prompt_force_open(log_prefix=log_prefix):
            return False
    except BaseException as e:  # pragma: no cover
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit)):
            raise
        pass
    # If we are in the broader premarket init window (08:00–09:15 IST) allow cycles whose callers
    # will internally gate expensive collection until regular session. We log at debug for clarity.
    try:
        if is_premarket_window():  # type: ignore
            logger.debug("%s Premarket window active (init-only); allowing lightweight cycle", log_prefix)
            return False
    except (AttributeError, TypeError, RuntimeError):  # pragma: no cover
        # Handle premarket window check failures
        pass
    logger.debug("%s Market closed; cycle skipped", log_prefix)
    return True


def market_will_be_closed(next_interval_seconds: float) -> bool:
    """Heuristic to detect if market will be closed by next planned cycle.

    Reuses is_market_open reference time evaluation to avoid starting a cycle
    that would complete after close.
    """
    try:
        ref_time = _dt.datetime.now(_dt.UTC) + _dt.timedelta(seconds=next_interval_seconds)
        return not is_market_open(reference_time=ref_time)  # type: ignore[arg-type]
    except (AttributeError, TypeError, ValueError, RuntimeError):  # pragma: no cover
        # Handle time calculation or market check failures
        return False

__all__ = [
    "wait_for_market_open",
    "provider_readiness_probe",
    "should_skip_cycle_market_hours",
    "market_will_be_closed",
]
