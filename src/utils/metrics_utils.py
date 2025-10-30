"""Metrics utilities centralizing Prometheus server setup for G6.

Abstraction layer so scripts do not import deep metrics implementation details.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

try:
    from src.metrics import setup_metrics_server as _setup_metrics_server  # facade import
except Exception:
    # Define a stub to keep the name callable for type-checkers; real call will be guarded.
    def _setup_metrics_server(*args: Any, **kwargs: Any) -> Any:  # type: ignore[no-redef]
        raise RuntimeError("metrics backend not available")


def init_metrics(port: int = 9108) -> tuple[Any, Callable[[], None]]:
    """Initialize metrics server returning (registry, stop_fn).

    If metrics backend unavailable, returns (None, noop_stop).
    """
    def _noop() -> None:
        pass

    try:
        # setup_metrics_server returns (registry, stop_fn); type cast to keep Any from leaking
        return cast(tuple[Any, Callable[[], None]], _setup_metrics_server(port=port))
    except Exception:
        return None, _noop

__all__ = ["init_metrics"]
