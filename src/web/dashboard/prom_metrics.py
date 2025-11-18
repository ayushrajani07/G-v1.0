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
- g6_forecast_coverage_pct: Gauge of rolling coverage percentage for band_low/band_high (per index,horizon)
- g6_forecast_norm_error: Gauge of rolling normalized error (MAE divided by band width) (per index,horizon)
 - g6_forecast_error_hist: Histogram of per-evaluation absolute forecast error (per index,horizon)
 - g6_forecast_norm_error_hist: Histogram of per-evaluation normalized error (per index,horizon)
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
_FORECAST_COVERAGE: Any = None
_FORECAST_NORM_ERROR: Any = None
_FORECAST_ERROR_HIST: Any = None
_FORECAST_NORM_ERROR_HIST: Any = None
_FORECAST_CACHE_DYNAMIC_TTL: Any = None


def _is_enabled() -> bool:
    """Check if Prometheus metrics are enabled via environment variable."""
    return os.environ.get("ENABLE_PATH_FORECAST_PROM_METRICS", "").strip() == "1"


def _init_metrics() -> bool:
    """Initialize Prometheus metrics. Returns True if successful, False otherwise."""
    global _METRICS_INITIALIZED, _REGISTRY
    global _FORECAST_LATENCY, _FORECAST_CACHE_HITS, _FORECAST_CACHE_MISSES
    global _RECENT_WINDOW_CACHE_HITS, _RECENT_WINDOW_CACHE_MISSES
    global _FORECAST_CACHE_SIZE, _RECENT_WINDOW_CACHE_SIZE
    global _FORECAST_CACHE_DYNAMIC_TTL

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
        _FORECAST_COVERAGE = Gauge(
            "g6_forecast_coverage_pct",
            "Rolling coverage percentage (0-100) for forecast band",
            labelnames=["index", "horizon"],
            registry=_REGISTRY,
        )
        _FORECAST_NORM_ERROR = Gauge(
            "g6_forecast_norm_error",
            "Rolling normalized error (mean abs error divided by band width)",
            labelnames=["index", "horizon"],
            registry=_REGISTRY,
        )
        _FORECAST_CACHE_DYNAMIC_TTL = Gauge(
            "g6_forecast_cache_dynamic_ttl",
            "Adaptive forecast cache TTL seconds (current applied value)",
            labelnames=["index"],
            registry=_REGISTRY,
        )
        # Optional histograms for percentile analysis; buckets configurable via env vars
        try:
            import os
            def _parse_buckets(env_name: str, default: str) -> list[float]:
                raw = os.environ.get(env_name, default)
                vals = []
                for part in raw.split(','):
                    part = part.strip()
                    if not part:
                        continue
                    try:
                        vals.append(float(part))
                    except ValueError:
                        continue
                vals = sorted(set(vals))
                if not vals or vals[-1] != float('inf'):
                    vals.append(float('inf'))
                return vals
            error_buckets = _parse_buckets('G6_ROLLING_ERROR_BUCKETS', '0.5,1,2,5,10,20,50')
            norm_error_buckets = _parse_buckets('G6_ROLLING_NORM_ERROR_BUCKETS', '0.01,0.02,0.05,0.1,0.2,0.5,1')
            from prometheus_client import Histogram  # type: ignore
            _FORECAST_ERROR_HIST = Histogram(
                "g6_forecast_error_hist",
                "Absolute forecast error distribution",
                labelnames=["index", "horizon"],
                buckets=error_buckets,
                registry=_REGISTRY,
            )
            _FORECAST_NORM_ERROR_HIST = Histogram(
                "g6_forecast_norm_error_hist",
                "Normalized forecast error distribution",
                labelnames=["index", "horizon"],
                buckets=norm_error_buckets,
                registry=_REGISTRY,
            )
        except Exception as _e:  # pragma: no cover
            # Histograms optional; failure should not break init
            _LOG.debug(f"Optional histogram init failed: {_e}")

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


def set_forecast_coverage(index: str, horizon: int, coverage_pct: float) -> None:
    """Set rolling coverage percentage gauge.

    Args:
        index: Index name
        horizon: Horizon minutes
        coverage_pct: Coverage percentage (0-100)
    """
    if not _is_enabled():
        return
    _init_metrics()
    if _FORECAST_COVERAGE is not None:
        try:
            _FORECAST_COVERAGE.labels(index=index, horizon=str(horizon)).set(coverage_pct)
        except Exception as e:
            _LOG.debug(f"Failed to set forecast coverage: {e}")


def set_forecast_norm_error(index: str, horizon: int, norm_error: float) -> None:
    """Set rolling normalized error gauge.

    Args:
        index: Index name
        horizon: Horizon minutes
        norm_error: Normalized error value (error / band_width)
    """
    if not _is_enabled():
        return
    _init_metrics()
    if _FORECAST_NORM_ERROR is not None:
        try:
            _FORECAST_NORM_ERROR.labels(index=index, horizon=str(horizon)).set(norm_error)
        except Exception as e:
            _LOG.debug(f"Failed to set forecast normalized error: {e}")


def observe_forecast_errors(index: str, horizon: int, abs_error: float, norm_error: float) -> None:
    """Observe single evaluation errors into histograms (if enabled)."""
    if not _is_enabled():
        return
    _init_metrics()
    try:
        if _FORECAST_ERROR_HIST is not None:
            _FORECAST_ERROR_HIST.labels(index=index, horizon=str(horizon)).observe(abs_error)
    except Exception as e:
        _LOG.debug(f"Failed to observe abs error: {e}")
    try:
        if _FORECAST_NORM_ERROR_HIST is not None:
            _FORECAST_NORM_ERROR_HIST.labels(index=index, horizon=str(horizon)).observe(norm_error)
    except Exception as e:
        _LOG.debug(f"Failed to observe norm error: {e}")


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
    "set_forecast_coverage",
    "set_forecast_norm_error",
    "observe_forecast_errors",
    "get_registry",
]

def set_forecast_cache_dynamic_ttl(index: str, ttl_sec: float) -> None:
    if not _is_enabled():
        return
    _init_metrics()
    if _FORECAST_CACHE_DYNAMIC_TTL is not None:
        try:
            _FORECAST_CACHE_DYNAMIC_TTL.labels(index=index).set(ttl_sec)
        except Exception as e:  # pragma: no cover
            _LOG.debug(f"Failed to set dynamic ttl gauge: {e}")

__all__.append('set_forecast_cache_dynamic_ttl')

def get_feature_drift_snapshot(index: str | None = None) -> list[dict[str, float | str]]:
    """Snapshot drift metrics from unified drift registry (if drift enabled).

    Delegates to drift_metrics module; does not initialize placeholder gauges locally.
    """
    try:
        from src.web.dashboard import drift_metrics  # type: ignore
        # Ensure drift metrics initialized if enabled
        reg = drift_metrics.get_registry()  # may be None if disabled
        if reg is None:
            return []
        samples = {}
        # Collect only known drift metric families
        wanted = {
            'g6_feature_psi': 'psi',
            'g6_feature_ks_pvalue': 'ks_pvalue',
            'g6_feature_mean_delta': 'mean_delta',
            'g6_feature_var_ratio': 'var_ratio',  # variance ratio gauge
            'g6_feature_drift_severity': 'severity',
        }
        for fam in reg.collect():  # type: ignore[attr-defined]
            name = getattr(fam, 'name', None) or getattr(fam, 'sample_name', None)
            if name not in wanted:
                continue
            key = wanted[name]
            for s in fam.samples:
                feat = s.labels.get('feature')
                idx = s.labels.get('index')
                if feat is None:
                    continue
                if index and idx and idx.upper() != index.upper():
                    continue
                rec = samples.setdefault((idx or '') + '::' + feat, {
                    'index': idx,
                    'feature': feat,
                    'psi': 0.0,
                    'ks_pvalue': 1.0,
                    'mean_delta': 0.0,
                    'var_ratio': 1.0,
                    'severity': 0.0,
                })
                try:
                    rec[key] = float(s.value)
                except Exception:
                    pass
        return list(samples.values())
    except Exception as e:
        _LOG.debug(f"get_feature_drift_snapshot failed: {e}")
        return []

__all__.append('get_feature_drift_snapshot')
