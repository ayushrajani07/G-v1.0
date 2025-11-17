"""Prometheus metrics exposure for path forecast endpoints.

This module provides conditional Prometheus metrics exposition via the /metrics endpoint.
It is enabled only when ENABLE_PATH_FORECAST_PROM_METRICS environment variable is set.

Metrics exposed:
- g6_forecast_latency_ms: Histogram of forecast request latency
- g6_forecast_cache_hits_total: Counter of forecast cache hits
- g6_forecast_cache_misses_total: Counter of forecast cache misses
- g6_recent_window_cache_hits_total: Counter of recent window cache hits
- g6_recent_window_cache_misses_total: Counter of recent window cache misses
- g6_forecast_cache_size: Gauge of current forecast cache entries
- g6_recent_window_cache_size: Gauge of current recent window cache entries
- g6_forecast_mae: Gauge of rolling mean absolute error for p50 forecasts (per index,horizon)
"""
from __future__ import annotations

import os
import logging
from typing import Optional, Any

_LOG = logging.getLogger(__name__)

# Prometheus registry and metrics (initialized lazily)
_REGISTRY: Any = None
_METRICS_INITIALIZED = False

# Metric instances
_FORECAST_LATENCY: Any = None
_FORECAST_CACHE_HITS: Any = None
_FORECAST_CACHE_MISSES: Any = None
_RECENT_WINDOW_CACHE_HITS: Any = None
_RECENT_WINDOW_CACHE_MISSES: Any = None
_FORECAST_CACHE_SIZE: Any = None
_RECENT_WINDOW_CACHE_SIZE: Any = None
_FORECAST_ROLLING_MAE: Any = None


def _is_enabled() -> bool:
    """Check if Prometheus metrics are enabled via environment variable."""
    return os.environ.get("ENABLE_PATH_FORECAST_PROM_METRICS", "").strip() == "1"


def _init_metrics() -> bool:
    """Initialize Prometheus metrics. Returns True if successful, False otherwise."""
    global _METRICS_INITIALIZED, _REGISTRY
    global _FORECAST_LATENCY, _FORECAST_CACHE_HITS, _FORECAST_CACHE_MISSES
    global _RECENT_WINDOW_CACHE_HITS, _RECENT_WINDOW_CACHE_MISSES
    global _FORECAST_CACHE_SIZE, _RECENT_WINDOW_CACHE_SIZE

    if _METRICS_INITIALIZED:
        return True

    if not _is_enabled():
        return False

    try:
        from prometheus_client import (
            CollectorRegistry,
            Histogram,
            Counter,
            Gauge,
        )

        # Create a custom registry to avoid conflicts with other metrics
        _REGISTRY = CollectorRegistry()

        # Histogram for forecast latency with specified buckets
        _FORECAST_LATENCY = Histogram(
            "g6_forecast_latency_ms",
            "Latency distribution for forecast requests",
            labelnames=["index", "horizon"],
            buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000],
            registry=_REGISTRY,
        )

        # Counters for forecast cache
        _FORECAST_CACHE_HITS = Counter(
            "g6_forecast_cache_hits_total",
            "Forecast cache hits",
            labelnames=["index"],
            registry=_REGISTRY,
        )

        _FORECAST_CACHE_MISSES = Counter(
            "g6_forecast_cache_misses_total",
            "Forecast cache misses",
            labelnames=["index"],
            registry=_REGISTRY,
        )

        # Counters for recent window cache
        _RECENT_WINDOW_CACHE_HITS = Counter(
            "g6_recent_window_cache_hits_total",
            "Recent file cache hits",
            labelnames=["index"],
            registry=_REGISTRY,
        )

        _RECENT_WINDOW_CACHE_MISSES = Counter(
            "g6_recent_window_cache_misses_total",
            "Recent file cache misses",
            labelnames=["index"],
            registry=_REGISTRY,
        )

        # Gauges for cache sizes
        _FORECAST_CACHE_SIZE = Gauge(
            "g6_forecast_cache_size",
            "Current forecast cache entries",
            registry=_REGISTRY,
        )

        _RECENT_WINDOW_CACHE_SIZE = Gauge(
            "g6_recent_window_cache_size",
            "Current file cache entries",
            registry=_REGISTRY,
        )

        _FORECAST_ROLLING_MAE = Gauge(
            "g6_forecast_mae",
            "Rolling mean absolute error for p50 forecast",
            labelnames=["index", "horizon"],
            registry=_REGISTRY,
        )

        _METRICS_INITIALIZED = True
        _LOG.info("Prometheus metrics initialized for path forecast")
        return True

    except ImportError as e:
        _LOG.warning(f"Failed to initialize Prometheus metrics: {e}")
        return False
    except Exception as e:
        _LOG.error(f"Unexpected error initializing Prometheus metrics: {e}")
        return False


def observe_forecast_latency(index: str, horizon: int, latency_ms: float) -> None:
    """Record a forecast latency observation.

    Args:
        index: Index name (e.g., "NIFTY")
        horizon: Forecast horizon in minutes
        latency_ms: Latency in milliseconds
    """
    if not _is_enabled():
        return

    _init_metrics()
    if _FORECAST_LATENCY is not None:
        try:
            _FORECAST_LATENCY.labels(index=index, horizon=str(horizon)).observe(latency_ms)
        except Exception as e:
            _LOG.debug(f"Failed to observe forecast latency: {e}")


def increment_forecast_cache_hit(index: str) -> None:
    """Increment forecast cache hit counter.

    Args:
        index: Index name (e.g., "NIFTY")
    """
    if not _is_enabled():
        return

    _init_metrics()
    if _FORECAST_CACHE_HITS is not None:
        try:
            _FORECAST_CACHE_HITS.labels(index=index).inc()
        except Exception as e:
            _LOG.debug(f"Failed to increment forecast cache hit: {e}")


def increment_forecast_cache_miss(index: str) -> None:
    """Increment forecast cache miss counter.

    Args:
        index: Index name (e.g., "NIFTY")
    """
    if not _is_enabled():
        return

    _init_metrics()
    if _FORECAST_CACHE_MISSES is not None:
        try:
            _FORECAST_CACHE_MISSES.labels(index=index).inc()
        except Exception as e:
            _LOG.debug(f"Failed to increment forecast cache miss: {e}")


def increment_recent_window_cache_hit(index: str) -> None:
    """Increment recent window cache hit counter.

    Args:
        index: Index name (e.g., "NIFTY")
    """
    if not _is_enabled():
        return

    _init_metrics()
    if _RECENT_WINDOW_CACHE_HITS is not None:
        try:
            _RECENT_WINDOW_CACHE_HITS.labels(index=index).inc()
        except Exception as e:
            _LOG.debug(f"Failed to increment recent window cache hit: {e}")


def increment_recent_window_cache_miss(index: str) -> None:
    """Increment recent window cache miss counter.

    Args:
        index: Index name (e.g., "NIFTY")
    """
    if not _is_enabled():
        return

    _init_metrics()
    if _RECENT_WINDOW_CACHE_MISSES is not None:
        try:
            _RECENT_WINDOW_CACHE_MISSES.labels(index=index).inc()
        except Exception as e:
            _LOG.debug(f"Failed to increment recent window cache miss: {e}")


def set_forecast_cache_size(size: int) -> None:
    """Set the current forecast cache size gauge.

    Args:
        size: Current number of entries in forecast cache
    """
    if not _is_enabled():
        return

    _init_metrics()
    if _FORECAST_CACHE_SIZE is not None:
        try:
            _FORECAST_CACHE_SIZE.set(size)
        except Exception as e:
            _LOG.debug(f"Failed to set forecast cache size: {e}")


def set_recent_window_cache_size(size: int) -> None:
    """Set the current recent window cache size gauge.

    Args:
        size: Current number of entries in recent window cache
    """
    if not _is_enabled():
        return

    _init_metrics()
    if _RECENT_WINDOW_CACHE_SIZE is not None:
        try:
            _RECENT_WINDOW_CACHE_SIZE.set(size)
        except Exception as e:
            _LOG.debug(f"Failed to set recent window cache size: {e}")


def set_forecast_mae(index: str, horizon: int, mae: float) -> None:
    """Set rolling mean absolute error gauge.

    Args:
        index: Index name
        horizon: Horizon minutes
        mae: Mean absolute error value
    """
    if not _is_enabled():
        return
    _init_metrics()
    if _FORECAST_ROLLING_MAE is not None:
        try:
            _FORECAST_ROLLING_MAE.labels(index=index, horizon=str(horizon)).set(mae)
        except Exception as e:
            _LOG.debug(f"Failed to set forecast MAE: {e}")


def get_registry() -> Optional[Any]:
    """Get the Prometheus registry if metrics are enabled.

    Returns:
        CollectorRegistry if metrics are initialized, None otherwise
    """
    if not _is_enabled():
        return None

    _init_metrics()
    return _REGISTRY


__all__ = [
    "observe_forecast_latency",
    "increment_forecast_cache_hit",
    "increment_forecast_cache_miss",
    "increment_recent_window_cache_hit",
    "increment_recent_window_cache_miss",
    "set_forecast_cache_size",
    "set_recent_window_cache_size",
    "set_forecast_mae",
    "get_registry",
]
