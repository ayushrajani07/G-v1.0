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
 - g6_forecast_mae_drift_ratio: Gauge of short/long MAE ratio (per index,horizon)
 - g6_forecast_norm_error_drift_ratio: Gauge of short/long normalized error ratio (per index,horizon)
 - g6_forecast_coverage_drift_delta_pct: Gauge of short minus long coverage percentage (per index,horizon)
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
_FORECAST_MAE_DRIFT: Any = None
_FORECAST_NORM_DRIFT: Any = None
_FORECAST_COVERAGE_DRIFT: Any = None
_TTL_STUDY_LATENCY_P95: Any = None
_TTL_STUDY_LATENCY_P50: Any = None
_TTL_STUDY_HIT_RATIO: Any = None
_TTL_STUDY_ERRORS: Any = None
_TTL_STUDY_P95_DELTA: Any = None
_TTL_STUDY_P50_DELTA: Any = None
_TTL_STUDY_HIT_RATIO_DELTA: Any = None
_MANIFEST_CHAIN_VALID: Any = None
_MANIFEST_CHAIN_LENGTH: Any = None


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
        _FORECAST_MAE_DRIFT = Gauge(
            "g6_forecast_mae_drift_ratio",
            "Short/long window MAE ratio (drift)",
            labelnames=["index", "horizon"],
            registry=_REGISTRY,
        )
        _FORECAST_NORM_DRIFT = Gauge(
            "g6_forecast_norm_error_drift_ratio",
            "Short/long window normalized error ratio (drift)",
            labelnames=["index", "horizon"],
            registry=_REGISTRY,
        )
        _FORECAST_COVERAGE_DRIFT = Gauge(
            "g6_forecast_coverage_drift_delta_pct",
            "Short minus long window coverage percentage delta (pct points)",
            labelnames=["index", "horizon"],
            registry=_REGISTRY,
        )
        # TTL study scenario metrics (populated dynamically from JSON file if present)
        _TTL_STUDY_LATENCY_P95 = Gauge(
            "g6_ttl_study_latency_p95_ms",
            "TTL impact study p95 latency (milliseconds) per scenario",
            labelnames=["scenario"],
            registry=_REGISTRY,
        )
        _TTL_STUDY_LATENCY_P50 = Gauge(
            "g6_ttl_study_latency_p50_ms",
            "TTL impact study p50 latency (milliseconds) per scenario",
            labelnames=["scenario"],
            registry=_REGISTRY,
        )
        _TTL_STUDY_HIT_RATIO = Gauge(
            "g6_ttl_study_hit_ratio",
            "TTL impact study cache hit ratio per scenario (0-1)",
            labelnames=["scenario"],
            registry=_REGISTRY,
        )
        _TTL_STUDY_ERRORS = Gauge(
            "g6_ttl_study_errors_total",
            "TTL impact study total request errors per scenario",
            labelnames=["scenario"],
            registry=_REGISTRY,
        )
        _TTL_STUDY_P95_DELTA = Gauge(
            "g6_ttl_study_p95_delta_ms",
            "TTL impact study p95 latency delta vs baseline (milliseconds) per scenario",
            labelnames=["scenario"],
            registry=_REGISTRY,
        )
        _TTL_STUDY_P50_DELTA = Gauge(
            "g6_ttl_study_p50_delta_ms",
            "TTL impact study p50 latency delta vs baseline (milliseconds) per scenario",
            labelnames=["scenario"],
            registry=_REGISTRY,
        )
        _TTL_STUDY_HIT_RATIO_DELTA = Gauge(
            "g6_ttl_study_hit_ratio_delta",
            "TTL impact study hit ratio delta vs baseline per scenario",
            labelnames=["scenario"],
            registry=_REGISTRY,
        )
        # Manifest chain-of-trust gauges
        _MANIFEST_CHAIN_VALID = Gauge(
            "g6_manifest_chain_valid",
            "1 if latest drift manifest chain-of-trust validates, else 0",
            registry=_REGISTRY,
        )
        _MANIFEST_CHAIN_LENGTH = Gauge(
            "g6_manifest_chain_length",
            "Number of manifests verified in the current chain",
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

def set_forecast_drift_ratios(index: str, horizon: int, mae_ratio: float, norm_ratio: float) -> None:
    """Set drift ratio gauges (MAE and normalized error)."""
    if not _is_enabled():
        return
    _init_metrics()
    try:
        if _FORECAST_MAE_DRIFT is not None:
            _FORECAST_MAE_DRIFT.labels(index=index, horizon=str(horizon)).set(mae_ratio)
    except Exception as e:
        _LOG.debug(f"Failed to set MAE drift ratio: {e}")
    try:
        if _FORECAST_NORM_DRIFT is not None:
            _FORECAST_NORM_DRIFT.labels(index=index, horizon=str(horizon)).set(norm_ratio)
    except Exception as e:
        _LOG.debug(f"Failed to set norm drift ratio: {e}")

def set_forecast_coverage_drift(index: str, horizon: int, coverage_delta_pct: float) -> None:
    """Set coverage drift delta gauge."""
    if not _is_enabled():
        return
    _init_metrics()
    try:
        if _FORECAST_COVERAGE_DRIFT is not None:
            _FORECAST_COVERAGE_DRIFT.labels(index=index, horizon=str(horizon)).set(coverage_delta_pct)
    except Exception as e:
        _LOG.debug(f"Failed to set coverage drift delta: {e}")


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
    # Attempt TTL study metrics refresh (best-effort)
    try:  # pragma: no cover - filesystem IO
        import json, os
        path = os.path.join("metrics", "ttl_study", "latest.json")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                blob = json.load(f)
            scenarios = blob.get("scenarios") or []
            deltas = blob.get("deltas_vs_baseline") or {}
            for sc in scenarios:
                scen = sc.get("name")
                if not scen:
                    continue
                try:
                    if _TTL_STUDY_LATENCY_P95 is not None:
                        _TTL_STUDY_LATENCY_P95.labels(scenario=scen).set(float(sc.get("latency_ms_p95", 0.0)))
                    if _TTL_STUDY_LATENCY_P50 is not None:
                        _TTL_STUDY_LATENCY_P50.labels(scenario=scen).set(float(sc.get("latency_ms_p50", 0.0)))
                    if _TTL_STUDY_HIT_RATIO is not None:
                        _TTL_STUDY_HIT_RATIO.labels(scenario=scen).set(float(sc.get("hit_ratio", 0.0)))
                    if _TTL_STUDY_ERRORS is not None:
                        _TTL_STUDY_ERRORS.labels(scenario=scen).set(float(sc.get("errors", 0)))
                    d = deltas.get(sc.get("name")) or {}
                    if _TTL_STUDY_P95_DELTA is not None and "p95_delta_ms" in d:
                        _TTL_STUDY_P95_DELTA.labels(scenario=scen).set(float(d.get("p95_delta_ms", 0.0)))
                    if _TTL_STUDY_P50_DELTA is not None and "p50_delta_ms" in d:
                        _TTL_STUDY_P50_DELTA.labels(scenario=scen).set(float(d.get("p50_delta_ms", 0.0)))
                    if _TTL_STUDY_HIT_RATIO_DELTA is not None and "hit_ratio_delta" in d:
                        _TTL_STUDY_HIT_RATIO_DELTA.labels(scenario=scen).set(float(d.get("hit_ratio_delta", 0.0)))
                except Exception as _e:  # pragma: no cover
                    _LOG.debug(f"Failed setting TTL study metric for {scen}: {_e}")
    except Exception as e:  # pragma: no cover
        _LOG.debug(f"TTL study metrics refresh skipped: {e}")
    # Manifest chain-of-trust best-effort validation
    try:  # pragma: no cover
        import json, os
        mdir = os.path.join("metrics", "drift_manifests")
        latest_ptr = os.path.join(mdir, "latest.json")
        def _load_manifest(fp: str) -> dict:
            with open(fp, "r", encoding="utf-8") as f:
                return json.load(f)
        def _sha256_json(obj: dict) -> str:
            import hashlib
            blob = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
            return hashlib.sha256(blob).hexdigest()
        chain_valid = False
        chain_len = 0
        if os.path.isfile(latest_ptr):
            lp = _load_manifest(latest_ptr)
            mf = lp.get("manifest_file")
            if mf:
                cur_path = os.path.join(mdir, mf)
                prev_sig = None
                depth = 0
                max_depth = 50
                while os.path.isfile(cur_path) and depth < max_depth:
                    m = _load_manifest(cur_path)
                    base_sig = m.get("base_signature")
                    expected = _sha256_json({
                        "prev_signature": m.get("prev_signature"),
                        "base_signature": base_sig,
                        "promoted_at": m.get("promoted_at"),
                        "indices": m.get("indices"),
                    })
                    if m.get("signature") != expected:
                        chain_valid = False
                        chain_len = depth + 1
                        break
                    chain_len = depth + 1
                    prev = m.get("previous_manifest")
                    if not prev:
                        chain_valid = True
                        break
                    cur_path = os.path.join(mdir, prev)
                    depth += 1
        if _MANIFEST_CHAIN_VALID is not None:
            _MANIFEST_CHAIN_VALID.set(1 if chain_valid else 0)
        if _MANIFEST_CHAIN_LENGTH is not None:
            _MANIFEST_CHAIN_LENGTH.set(chain_len)
    except Exception as e:
        _LOG.debug(f"Manifest chain validation skipped: {e}")
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
    # TTL study metrics are auto-refreshed; no public setter functions
]
