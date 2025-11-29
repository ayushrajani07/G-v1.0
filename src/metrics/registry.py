"""Metrics registry scaffold (Phase 5 implementation).

Provides centralized, idempotent metric registration to eliminate scattered
lazy creation via setattr. Consolidates common collector metrics (stale tracking,
cycle histograms, alert categories) into reusable getters.

Usage:
    from src.metrics.registry import get_registry, ensure_stale_metrics
    
    metrics = get_registry()
    stale_metrics = ensure_stale_metrics(metrics)
    stale_metrics['stale_active'].labels(index='NIFTY').set(0)

Design:
- Idempotent: calling ensure_* multiple times is safe (no duplicates)
- Backward compatible: returns existing MetricsRegistry with attributes attached
- Gradual migration: old setattr patterns still work during transition
"""
from __future__ import annotations

import logging
from collections.abc import Callable  # noqa: F401 (retained for backward compat hints)
from typing import Any

from . import _singleton as _anchor  # central anchor
from . import metrics as _legacy

MetricsRegistry = _legacy.MetricsRegistry  # re-export for compatibility

logger = logging.getLogger(__name__)

def _new_registry() -> MetricsRegistry:
    """Construct a fresh MetricsRegistry and publish to central anchor.

    Avoid starting HTTP server (tests generally don't need duplicate port binds).
    """
    reg = MetricsRegistry()
    try:  # publish to central anchor only if empty to avoid clobbering active server singleton
        _anchor.set_singleton(reg)
    except (AttributeError, TypeError, RuntimeError):  # pragma: no cover - defensive
        # Handle missing method, type mismatch, or singleton operation failure
        pass
    return reg

def get_registry(reset: bool = False) -> MetricsRegistry:
    """Return process-wide MetricsRegistry unified with central singleton anchor.

    This replaces the earlier ad-hoc module-local singleton which produced a
    second registry instance (breaking identity tests) when code imported
    `src.metrics.registry` before calling the public `get_metrics()` facade.

    Parameters
    ----------
    reset : bool
        If True, forces creation of a new MetricsRegistry (publishes it to the
        central anchor only if no existing instance was present). Intended for
        isolated test scenarios; production code should avoid reset semantics.
    """
    existing = _anchor.get_singleton()
    if existing is not None and not reset:
        return existing  # already unified
    if reset:
        return _new_registry()
    # Defer to legacy bootstrap path (will set anchor); fallback to direct construction
    try:
        reg = _legacy.get_metrics_singleton()
        if reg is None:  # legacy path failed (should be rare) -> direct new registry
            reg = _new_registry()
        return reg
    except (ImportError, AttributeError, TypeError, RuntimeError):
        # Handle missing module/method, type issues, or operation failures
        return _new_registry()


# ============================================================================
# Phase 5: Idempotent Metric Registration Helpers
# ============================================================================

def ensure_stale_metrics(metrics: Any) -> dict[str, Any]:
    """Ensure stale tracking metrics exist on the registry.
    
    Returns a dict with keys: stale_active, stale_cycles_total,
    stale_system_cycles_total, stale_consecutive_cycles, stale_system_active.
    
    Idempotent: safe to call multiple times, won't create duplicates.
    """
    if metrics is None:
        return {}
    
    result = {}
    try:
        from prometheus_client import Counter, Gauge
        
        # Per-index stale metrics
        if not hasattr(metrics, 'stale_active'):
            try:
                metrics.stale_active = Gauge(
                    'g6_stale_active',
                    'Whether index stale in current cycle (1=stale, 0=ok)',
                    ['index']
                )
            except (ValueError, AttributeError, TypeError) as e:
                logger.debug("Failed to create stale_active: %s", e)
        
        if not hasattr(metrics, 'stale_cycles_total'):
            try:
                metrics.stale_cycles_total = Counter(
                    'g6_stale_cycles_total',
                    'Count of cycles where index or system classified stale',
                    ['index', 'mode']
                )
            except (ValueError, AttributeError, TypeError) as e:
                logger.debug("Failed to create stale_cycles_total: %s", e)
        
        # System-level stale metrics
        if not hasattr(metrics, 'stale_system_cycles_total'):
            try:
                metrics.stale_system_cycles_total = Counter(
                    'g6_stale_system_cycles_total',
                    'Count of cycles where any index stale (system perspective)',
                    ['mode']
                )
            except (ValueError, AttributeError, TypeError) as e:
                logger.debug("Failed to create stale_system_cycles_total: %s", e)
        
        if not hasattr(metrics, 'stale_consecutive_cycles'):
            try:
                metrics.stale_consecutive_cycles = Gauge(
                    'g6_stale_consecutive_cycles',
                    'Consecutive stale cycles (system scope)',
                    ['mode']
                )
            except (ValueError, AttributeError, TypeError) as e:
                logger.debug("Failed to create stale_consecutive_cycles: %s", e)
        
        if not hasattr(metrics, 'stale_system_active'):
            try:
                metrics.stale_system_active = Gauge(
                    'g6_stale_system_active',
                    'Whether any index stale in current cycle (system scope)',
                    ['mode']
                )
            except (ValueError, AttributeError, TypeError) as e:
                logger.debug("Failed to create stale_system_active: %s", e)
        
        # Populate result dict
        for attr in ['stale_active', 'stale_cycles_total', 'stale_system_cycles_total',
                     'stale_consecutive_cycles', 'stale_system_active']:
            result[attr] = getattr(metrics, attr, None)
        
    except ImportError:
        logger.debug("prometheus_client not available for stale metrics")
    except Exception as e:
        logger.debug("Unexpected error ensuring stale metrics: %s", e)
    
    return result


def ensure_cycle_histograms(metrics: Any) -> dict[str, Any]:
    """Ensure cycle timing histogram/summary metrics exist.
    
    Returns dict with keys: pipeline_cycle_duration_seconds,
    pipeline_cycle_duration_summary, pipeline_enrich_duration_seconds,
    pipeline_finalize_duration_seconds.
    
    Idempotent: safe to call multiple times.
    """
    if metrics is None:
        return {}
    
    result = {}
    try:
        from prometheus_client import Histogram, Summary
        
        if not hasattr(metrics, 'pipeline_cycle_duration_seconds'):
            try:
                metrics.pipeline_cycle_duration_seconds = Histogram(
                    'g6_pipeline_cycle_duration_seconds',
                    'Pipeline cycle duration seconds',
                    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10)
                )
            except (ValueError, AttributeError, TypeError) as e:
                logger.debug("Failed to create pipeline_cycle_duration_seconds: %s", e)
        
        if not hasattr(metrics, 'pipeline_cycle_duration_summary'):
            try:
                metrics.pipeline_cycle_duration_summary = Summary(
                    'g6_pipeline_cycle_duration_summary',
                    'Pipeline cycle duration summary'
                )
            except (ValueError, AttributeError, TypeError) as e:
                logger.debug("Failed to create pipeline_cycle_duration_summary: %s", e)
        
        if not hasattr(metrics, 'pipeline_enrich_duration_seconds'):
            try:
                metrics.pipeline_enrich_duration_seconds = Histogram(
                    'g6_pipeline_enrich_duration_seconds',
                    'Per-expiry enrichment duration seconds',
                    buckets=(0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1, 2)
                )
            except (ValueError, AttributeError, TypeError) as e:
                logger.debug("Failed to create pipeline_enrich_duration_seconds: %s", e)
        
        if not hasattr(metrics, 'pipeline_finalize_duration_seconds'):
            try:
                metrics.pipeline_finalize_duration_seconds = Histogram(
                    'g6_pipeline_finalize_duration_seconds',
                    'Per-expiry finalize_expiry duration seconds',
                    buckets=(0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.25)
                )
            except (ValueError, AttributeError, TypeError) as e:
                logger.debug("Failed to create pipeline_finalize_duration_seconds: %s", e)
        
        # Populate result dict
        for attr in ['pipeline_cycle_duration_seconds', 'pipeline_cycle_duration_summary',
                     'pipeline_enrich_duration_seconds', 'pipeline_finalize_duration_seconds']:
            result[attr] = getattr(metrics, attr, None)
        
    except ImportError:
        logger.debug("prometheus_client not available for cycle histograms")
    except Exception as e:
        logger.debug("Unexpected error ensuring cycle histograms: %s", e)
    
    return result


def ensure_alert_counter(metrics: Any, category: str) -> Any:
    """Ensure alert category counter exists for the given category.
    
    Returns the counter metric or None if creation failed.
    Idempotent: safe to call multiple times for same category.
    """
    if metrics is None:
        return None
    
    metric_name = f'pipeline_alerts_{category}_total'
    
    if hasattr(metrics, metric_name):
        return getattr(metrics, metric_name)
    
    try:
        from prometheus_client import Counter
        
        counter = Counter(
            f'g6_{metric_name}',
            f'Count of pipeline cycles with occurrences for category: {category}'
        )
        setattr(metrics, metric_name, counter)
        return counter
        
    except (ImportError, ValueError, AttributeError, TypeError) as e:
        logger.debug("Failed to create alert counter %s: %s", metric_name, e)
        return None


__all__ = [
    "MetricsRegistry",
    "get_registry",
    "ensure_stale_metrics",
    "ensure_cycle_histograms",
    "ensure_alert_counter",
]
