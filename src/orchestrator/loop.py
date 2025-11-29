"""Execution loop abstraction for orchestrator.

Currently a thin wrapper that will later encapsulate:
  * Per-cycle timing & sleep regulation
  * Error handling & backoff policies
  * Cardinality / gating hooks
  * Event bus publication points
  * Graceful shutdown signaling
  * Network connectivity monitoring and recovery
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable

from src.config.env_config import EnvConfig
from src.orchestrator.context import RuntimeContext
from src.utils.env_flags import is_truthy_env  # type: ignore
# Phase 2: Use standardized logging helpers
from src.utils.log_helpers import log_info, log_warning

try:
    from src.utils.connectivity import (
        check_internet_connectivity,
        wait_for_connectivity,
        is_connectivity_check_enabled,
    )
except ImportError:
    # Fallback if connectivity module not available
    def check_internet_connectivity(**kwargs) -> bool:  # type: ignore
        return True
    def wait_for_connectivity(**kwargs) -> bool:  # type: ignore
        return True
    def is_connectivity_check_enabled() -> bool:  # type: ignore
        return False

try:
    from src.utils.power_management import prevent_sleep, allow_sleep
except ImportError:
    # Fallback if power management not available
    def prevent_sleep() -> bool:  # type: ignore
        return False
    def allow_sleep() -> bool:  # type: ignore
        return False

try:  # optional gating utilities (early slice)
    from src.orchestrator.gating import should_skip_cycle_market_hours  # type: ignore
except (ImportError, AttributeError):  # pragma: no cover
    # Handle missing module or function
    def should_skip_cycle_market_hours(*_, **__):  # type: ignore
        return False

logger = logging.getLogger(__name__)


def run_loop(ctx: RuntimeContext, *, cycle_fn: Callable[[RuntimeContext], None], interval: float) -> None:
    """Run the main orchestration loop using provided cycle function.

    The cycle function encapsulates the legacy work previously inside the
    monolithic unified_main loop. This indirection enables unit testing and
    future pluggable behaviors (e.g., adaptive interval, partial refresh).
    
    Note: Prevents system sleep during operation to ensure uninterrupted collection.
    """
    # Prevent system from sleeping during collection
    sleep_prevented = prevent_sleep()
    if sleep_prevented:
        log_info(logger, "LOOP", "System sleep prevention enabled")
    
    log_info(logger, "LOOP", "Starting orchestration", interval_seconds=interval)
    # Optional loop-level heartbeat before entering cycles
    try:  # pragma: no cover
        import src.collectors.unified_collectors as _uc  # type: ignore
        _hb = getattr(_uc, '_mark_cycle_progress', None)
        if callable(_hb):
            _hb()
    except Exception:
        pass
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
                log_info(logger, "LOOP", "Max cycles limit enabled", max_cycles=max_cycles)
            else:
                logger.debug("[loop] Ignoring non-positive G6_LOOP_MAX_CYCLES=%s", max_cycles_raw)
        except (ValueError, TypeError):
            # Handle integer conversion failures
            log_warning(logger, "LOOP", "Invalid G6_LOOP_MAX_CYCLES (must be int)", value=max_cycles_raw)
    executed_cycles = 0
    connectivity_enabled = is_connectivity_check_enabled()
    consecutive_failures = 0
    max_consecutive_failures = 3  # Exit after 3 failures with no connectivity
    
    try:
        while not ctx.shutdown:
            start = time.time()
            
            # Check connectivity before each cycle if enabled
            if connectivity_enabled:
                try:
                    if not check_internet_connectivity():
                        log_warning(
                            logger,
                            "LOOP",
                            "No internet connectivity detected, attempting recovery",
                        )
                        if wait_for_connectivity():
                            log_info(logger, "LOOP", "Internet connectivity restored")
                            consecutive_failures = 0
                        else:
                            consecutive_failures += 1
                            log_warning(
                                logger,
                                "LOOP",
                                "Failed to restore connectivity",
                                consecutive_failures=consecutive_failures,
                            )
                            if consecutive_failures >= max_consecutive_failures:
                                logger.error(
                                    "Too many consecutive connectivity failures (%d), exiting",
                                    consecutive_failures
                                )
                                break
                            # Skip this cycle but continue loop
                            time.sleep(interval)
                            continue
                except Exception as conn_e:
                    logger.warning("Connectivity check failed: %s", conn_e)
            
            try:
                if market_hours_only and should_skip_cycle_market_hours(True):  # reuse gating util semantics
                    logger.debug("[loop] Skipping cycle (market closed)")
                else:
                    cycle_fn(ctx)
                    consecutive_failures = 0  # Reset on successful cycle
                    # Heartbeat after each successful cycle invocation
                    try:  # pragma: no cover
                        import src.collectors.unified_collectors as _uc  # type: ignore
                        _hb = getattr(_uc, '_mark_cycle_progress', None)
                        if callable(_hb):
                            _hb()
                    except Exception:
                        pass
                    executed_cycles += 1
                    if max_cycles is not None and executed_cycles >= max_cycles:
                        log_info(logger, "LOOP", "Reached max cycles, terminating", max_cycles=max_cycles)
                        break
            except KeyboardInterrupt:  # direct interrupt inside cycle_fn
                log_info(logger, "LOOP", "KeyboardInterrupt inside cycle, initiating shutdown")
                ctx.shutdown = True  # type: ignore[attr-defined]
                break
            except (AttributeError, TypeError, ValueError, RuntimeError, OSError) as e:  # noqa
                # Handle cycle function failures
                logger.exception("Cycle execution failed")
            elapsed = time.time() - start
            sleep_for = max(0.0, interval - elapsed)
            try:
                if sleep_for:
                    time.sleep(sleep_for)
            except KeyboardInterrupt:
                log_info(logger, "LOOP", "KeyboardInterrupt during sleep, terminating")
                ctx.shutdown = True  # type: ignore[attr-defined]
                break
    except KeyboardInterrupt:
        log_info(logger, "LOOP", "KeyboardInterrupt, graceful shutdown")
    finally:
        # Restore normal sleep behavior
        if sleep_prevented:
            allow_sleep()
            log_info(logger, "LOOP", "System sleep prevention disabled")
        log_info(logger, "LOOP", "Orchestration loop terminated")

__all__ = ["run_loop"]
