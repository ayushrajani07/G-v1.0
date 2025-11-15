"""Cycle phase timing metrics for performance monitoring.

Provides histogram metrics for tracking fetch, process, and write phase durations
per index to enable performance diagnosis and optimization per the Cycle Performance
Roadmap.

These metrics support Grafana panels showing:
  - avg_fetch = increase(g6_cycle_fetch_time_seconds_sum[15m]) / increase(g6_cycle_fetch_time_seconds_count[15m])
  - avg_process = increase(g6_cycle_process_time_seconds_sum[15m]) / increase(g6_cycle_process_time_seconds_count[15m])
  - avg_write = increase(g6_cycle_write_time_seconds_sum[15m]) / increase(g6_cycle_write_time_seconds_count[15m])
"""
from __future__ import annotations

import logging
import time  # Needed for __exit__ timing; was missing causing NameError
from typing import TYPE_CHECKING

from prometheus_client import Histogram

if TYPE_CHECKING:
    from prometheus_client import CollectorRegistry

logger = logging.getLogger(__name__)

# Custom buckets tuned for typical cycle phases: [0.5,1,2,5,10,20,40,80]
# These align with the roadmap's observability enhancements
_PHASE_BUCKETS = [0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 40.0, 80.0]


def create_phase_timing_metrics(registry: CollectorRegistry | None = None) -> dict[str, Histogram]:
    """Create and register cycle phase timing histogram metrics.
    
    Returns a dict with keys: 'fetch', 'process', 'write' containing Histogram instances.
    Each histogram tracks duration in seconds with an 'index' label for per-index tracking.
    
    Args:
        registry: Optional Prometheus registry (uses default if None)
    
    Returns:
        Dictionary mapping phase names to Histogram metrics
    """
    kwargs = {}
    if registry is not None:
        kwargs['registry'] = registry
    
    metrics = {}
    
    try:
        metrics['fetch'] = Histogram(
            'g6_cycle_fetch_time_seconds',
            'Time spent in fetch phase per cycle',
            labelnames=['index'],
            buckets=_PHASE_BUCKETS,
            **kwargs
        )
    except Exception as e:
        logger.debug("Failed to create fetch phase histogram: %s", e)
    
    try:
        metrics['process'] = Histogram(
            'g6_cycle_process_time_seconds',
            'Time spent in process phase per cycle',
            labelnames=['index'],
            buckets=_PHASE_BUCKETS,
            **kwargs
        )
    except Exception as e:
        logger.debug("Failed to create process phase histogram: %s", e)
    
    try:
        metrics['write'] = Histogram(
            'g6_cycle_write_time_seconds',
            'Time spent in write phase per cycle',
            labelnames=['index'],
            buckets=_PHASE_BUCKETS,
            **kwargs
        )
    except Exception as e:
        logger.debug("Failed to create write phase histogram: %s", e)
    
    # Additional counters for retries and throughput per roadmap
    try:
        from prometheus_client import Counter
        metrics['fetch_retries'] = Counter(
            'g6_fetch_retries_total',
            'Total fetch retries by index and reason',
            labelnames=['index', 'reason'],
            **kwargs
        )
    except Exception as e:
        logger.debug("Failed to create fetch_retries counter: %s", e)
    
    try:
        from prometheus_client import Counter
        metrics['write_bytes'] = Counter(
            'g6_write_bytes_total',
            'Total bytes written to storage',
            labelnames=['index'],
            **kwargs
        )
    except Exception as e:
        logger.debug("Failed to create write_bytes counter: %s", e)
    
    try:
        from prometheus_client import Counter
        metrics['write_rows'] = Counter(
            'g6_write_rows_total',
            'Total rows written to storage',
            labelnames=['index'],
            **kwargs
        )
    except Exception as e:
        logger.debug("Failed to create write_rows counter: %s", e)
    
    return metrics


class PhaseTimer:
    """Context manager for timing a cycle phase and recording to histogram.
    
    Example:
        with PhaseTimer(metrics['fetch'], index='NIFTY'):
            # fetch operations
            pass
    """
    
    def __init__(self, histogram: Histogram | None, index: str = 'unknown'):
        self.histogram = histogram
        self.index = index
        self._start = None
    
    def __enter__(self):
        # Local start capture (module-level import ensures availability in __exit__)
        self._start = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._start is not None and self.histogram is not None:
            duration = time.time() - self._start
            try:
                self.histogram.labels(index=self.index).observe(duration)
            except Exception:
                pass
        return False


__all__ = ['create_phase_timing_metrics', 'PhaseTimer', '_PHASE_BUCKETS']
