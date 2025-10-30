#!/usr/bin/env python3
"""
Tiny adaptive circuit breaker registry and decorators (opt-in).
Safe-by-default: nothing changes unless explicitly used.
"""
from __future__ import annotations

import os
import threading
from collections.abc import Callable
from typing import Any, TypeVar

# Phase 2: Centralized environment variable access
from src.config.env_config import EnvConfig
from src.health import runtime as health_runtime
from src.health.models import HealthLevel, HealthState

from .adaptive_circuit_breaker import AdaptiveCircuitBreaker, BreakerConfig, CircuitOpenError, CircuitState

# Optional imports
try:
    from src.utils.env_flags import is_truthy_env  # type: ignore
except ImportError:
    is_truthy_env = None  # type: ignore

_REG_LOCK = threading.RLock()
_REGISTRY: dict[str, AdaptiveCircuitBreaker] = {}


def get_breaker(name: str) -> AdaptiveCircuitBreaker:
    with _REG_LOCK:
        b = _REGISTRY.get(name)
        if b is not None:
            return b
        # Build from env defaults using EnvConfig (Phase 2)
        cfg = BreakerConfig(
            name=name,
            failure_threshold=EnvConfig.get_int("G6_CB_FAILURES", 5),
            min_reset_timeout=EnvConfig.get_float("G6_CB_MIN_RESET", 10.0),
            max_reset_timeout=EnvConfig.get_float("G6_CB_MAX_RESET", 300.0),
            backoff_factor=EnvConfig.get_float("G6_CB_BACKOFF", 2.0),
            jitter=EnvConfig.get_float("G6_CB_JITTER", 0.2),
            half_open_successes=EnvConfig.get_int("G6_CB_HALF_OPEN_SUCC", 1),
            persistence_dir=EnvConfig.get_str("G6_CB_STATE_DIR", "") or None,
        )
        b = AdaptiveCircuitBreaker(cfg)
        _REGISTRY[name] = b
        return b


P = TypeVar("P")
F = TypeVar("F")


def circuit_protected(
    name: str | None = None,
    fallback: Callable[..., Any] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        cb_name = name or f"cb:{func.__module__}.{func.__name__}"
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            br = get_breaker(cb_name)
            try:
                result = br.execute(func, *args, **kwargs)
                # On success, update health based on current breaker state
                if is_truthy_env is not None:
                    try:
                        if is_truthy_env('G6_HEALTH_COMPONENTS'):
                            st = br.state
                            if st == CircuitState.CLOSED:
                                health_runtime.set_component(cb_name, HealthLevel.HEALTHY, HealthState.HEALTHY)
                            elif st == CircuitState.HALF_OPEN:
                                health_runtime.set_component(cb_name, HealthLevel.WARNING, HealthState.WARNING)
                            # OPEN state on success is unlikely; ignore here
                    except Exception:
                        pass
                return result
            except CircuitOpenError:
                if is_truthy_env is not None:
                    try:
                        if is_truthy_env('G6_HEALTH_COMPONENTS'):
                            health_runtime.set_component(cb_name, HealthLevel.CRITICAL, HealthState.CRITICAL)
                    except Exception:
                        pass
                if callable(fallback):
                    return fallback(*args, **kwargs)
                raise
        return wrapper
    return deco


__all__ = ["get_breaker", "circuit_protected"]
