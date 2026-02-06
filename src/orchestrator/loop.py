"""Execution loop abstraction for orchestrator.

Currently a thin wrapper that will later encapsulate:
  * Per-cycle timing & sleep regulation
  * Error handling & backoff policies
  * Cardinality / gating hooks
  * Event bus publication points
  * Graceful shutdown signaling
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable

from src.config.env_config import EnvConfig
from src.orchestrator.context import RuntimeContext
from src.utils.exceptions import APIError, G6Exception, RetryError
from src.utils.env_flags import is_truthy_env  # type: ignore

try:  # optional gating utilities (early slice)
    from src.orchestrator.gating import should_skip_cycle_market_hours  # type: ignore
except (ImportError, AttributeError):  # pragma: no cover
    # Handle missing module or function
    def should_skip_cycle_market_hours(*_, **__):  # type: ignore
        return False

logger = logging.getLogger(__name__)


def _is_likely_network_error(e: BaseException) -> bool:
    """Best-effort classification for transient connectivity/API failures.

    Goal: keep the loop alive and apply a reconnection backoff when the upstream
    API is unreachable (WiFi drop, ISP hiccup, provider timeout).
    """
    if isinstance(e, (RetryError, APIError)):
        return True
    msg = str(e).lower()
    if any(s in msg for s in ("timed out", "timeout", "temporarily", "connection", "dns", "name or service not known")):
        return True
    # Walk causes (requests/urllib3 exceptions often live in __cause__)
    cur: BaseException | None = e  # type: ignore[assignment]
    for _ in range(6):
        if cur is None:
            break
        if isinstance(cur, (RetryError, APIError)):
            return True
        cmsg = str(cur).lower()
        if any(s in cmsg for s in ("read timed out", "connect timeout", "connection aborted", "connection reset")):
            return True
        cur = getattr(cur, "__cause__", None)
    return False


def _compute_backoff_seconds(streak: int) -> float:
    """Compute extra sleep for consecutive transient failures.

    Controlled by:
    - G6_LOOP_ERROR_BACKOFF_BASE_SEC (default 5)
    - G6_LOOP_ERROR_BACKOFF_MAX_SEC (default 60)
    """
    base = EnvConfig.get_float("G6_LOOP_ERROR_BACKOFF_BASE_SEC", 5.0)
    cap = EnvConfig.get_float("G6_LOOP_ERROR_BACKOFF_MAX_SEC", 60.0)
    if base <= 0 or cap <= 0 or streak <= 0:
        return 0.0
    # Exponential with cap: base, 2*base, 4*base, ...
    try:
        backoff = base * (2 ** max(0, int(streak) - 1))
    except (OverflowError, ValueError, TypeError):
        backoff = base
    return float(min(cap, max(0.0, backoff)))


def run_loop(ctx: RuntimeContext, *, cycle_fn: Callable[[RuntimeContext], None], interval: float) -> None:
    """Run the main orchestration loop using provided cycle function.

    The cycle function encapsulates the legacy work previously inside the
    monolithic unified_main loop. This indirection enables unit testing and
    future pluggable behaviors (e.g., adaptive interval, partial refresh).
    """
    logger.info("Starting orchestration loop interval=%s", interval)
    # Micro-cache frequently-read environment flags at loop startup to avoid
    # repeated os.getenv calls inside the loop.
    market_hours_only = is_truthy_env('G6_LOOP_MARKET_HOURS')
    # Optional max cycles (dev/test convenience) - only counts executed (non-skipped) cycles
    # Support legacy alias G6_MAX_CYCLES (prefer new name if both present)
    max_cycles_raw = EnvConfig.get_str('G6_LOOP_MAX_CYCLES', '') or EnvConfig.get_str('G6_MAX_CYCLES', '')
    max_cycles: int | None = None
    if max_cycles_raw:
        try:
            parsed = int(max_cycles_raw)
            if parsed > 0:
                max_cycles = parsed
                logger.info("[loop] Max cycles limit enabled: %s", max_cycles)
            else:
                logger.debug("[loop] Ignoring non-positive G6_LOOP_MAX_CYCLES=%s", max_cycles_raw)
        except (ValueError, TypeError):
            # Handle integer conversion failures
            logger.warning("[loop] Invalid G6_LOOP_MAX_CYCLES=%r (must be int)", max_cycles_raw)
    executed_cycles = 0
    consecutive_failures = 0
    last_failure_was_network = False
    try:
        while not ctx.shutdown:
            start = time.time()
            try:
                if market_hours_only and should_skip_cycle_market_hours(True):  # reuse gating util semantics
                    logger.debug("[loop] Skipping cycle (market closed)")
                else:
                    cycle_fn(ctx)
                    executed_cycles += 1
                    consecutive_failures = 0
                    last_failure_was_network = False
                    if max_cycles is not None and executed_cycles >= max_cycles:
                        logger.info("[loop] Reached max cycles (%s) -> terminating", max_cycles)
                        break
            except KeyboardInterrupt:  # direct interrupt inside cycle_fn
                logger.info("[loop] KeyboardInterrupt received inside cycle; initiating shutdown")
                ctx.shutdown = True  # type: ignore[attr-defined]
                break
            except SystemExit:
                # Preserve explicit exit semantics (used by some legacy abort policies).
                raise
            except BaseException as e:  # noqa
                if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                    raise
                # Never allow transient errors (e.g., internet drop) to terminate the loop.
                consecutive_failures += 1
                last_failure_was_network = _is_likely_network_error(e)
                if last_failure_was_network:
                    logger.warning(
                        "[loop] Cycle failed due to network/provider error (streak=%s). Will keep running.",
                        consecutive_failures,
                        exc_info=True,
                    )
                elif isinstance(e, G6Exception):
                    logger.exception("[loop] Cycle failed (G6Exception)")
                else:
                    logger.exception("[loop] Cycle execution failed")
            elapsed = time.time() - start
            sleep_for = max(0.0, interval - elapsed)
            if consecutive_failures and sleep_for >= 0:
                # Add extra backoff only for likely network errors.
                # This avoids tight retry loops when the internet is down.
                if last_failure_was_network:
                    sleep_for += _compute_backoff_seconds(consecutive_failures)
            try:
                if sleep_for:
                    time.sleep(sleep_for)
            except KeyboardInterrupt:
                logger.info("[loop] KeyboardInterrupt during sleep; terminating")
                ctx.shutdown = True  # type: ignore[attr-defined]
                break
    except KeyboardInterrupt:
        logger.info("[loop] KeyboardInterrupt (outer) -> graceful shutdown")
    finally:
        logger.info("Orchestration loop terminated")

__all__ = ["run_loop"]
