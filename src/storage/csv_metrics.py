"""Metrics tracking for CSV storage operations.

Handles metrics emission for CSV sink operations.
Extracted from CsvSink to separate concerns.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class CsvMetricsTracker:
    """Tracks and emits metrics for CSV storage operations."""

    def __init__(self, metrics_registry: Any | None = None):
        """
        Initialize metrics tracker.
        
        Args:
            metrics_registry: Optional metrics registry (lazy attachment supported)
        """
        self.metrics = metrics_registry
        self.logger = logger

    def attach_metrics(self, metrics_registry: Any) -> None:
        """Attach a metrics registry (deferred injection)."""
        self.metrics = metrics_registry

    def inc(self, name: str, amount: int | float = 1, labels: dict[str, Any] | None = None) -> None:
        """
        Increment a counter metric.
        
        Args:
            name: Metric attribute name (e.g., 'csv_rows_written')
            amount: Amount to increment by
            labels: Optional label dictionary for labeled metrics
        """
        if not self.metrics:
            return
        
        try:
            metric = getattr(self.metrics, name, None)
            if not metric:
                return
            
            if labels:
                # Labeled metric: metric.labels(**labels).inc(amount)
                labeled = metric.labels(**labels)
                if hasattr(labeled, 'inc'):
                    labeled.inc(amount)
            else:
                # Simple counter: metric.inc(amount)
                if hasattr(metric, 'inc'):
                    metric.inc(amount)
        except Exception as e:
            # Metrics failures should not break storage operations
            self.logger.debug("Failed to increment metric %s: %s", name, e)

    def set(self, name: str, value: int | float, labels: dict[str, Any] | None = None) -> None:
        """
        Set a gauge metric value.
        
        Args:
            name: Metric attribute name (e.g., 'csv_batch_size')
            value: Value to set
            labels: Optional label dictionary for labeled metrics
        """
        if not self.metrics:
            return
        
        try:
            metric = getattr(self.metrics, name, None)
            if not metric:
                return
            
            if labels:
                # Labeled metric: metric.labels(**labels).set(value)
                labeled = metric.labels(**labels)
                if hasattr(labeled, 'set'):
                    labeled.set(value)
            else:
                # Simple gauge: metric.set(value)
                if hasattr(metric, 'set'):
                    metric.set(value)
        except Exception as e:
            self.logger.debug("Failed to set metric %s: %s", name, e)

    def update_expiry_daily_stats(self, kind: str) -> None:
        """
        Update daily expiry statistics metric.
        
        Args:
            kind: Type of expiry event ('seen', 'written', 'quarantined', etc.)
        """
        if not self.metrics:
            return
        
        try:
            metric = getattr(self.metrics, 'csv_expiry_daily_stats', None)
            if metric and hasattr(metric, 'labels'):
                metric.labels(kind=kind).inc()
        except Exception as e:
            self.logger.debug("Failed to update expiry stats for %s: %s", kind, e)

    def record_row_written(self, index: str, expiry_code: str, offset: int) -> None:
        """Record a CSV row write operation."""
        self.inc('csv_rows_written', labels={'index': index, 'expiry': expiry_code, 'offset': str(offset)})

    def record_batch_flush(self, index: str, expiry_code: str, row_count: int) -> None:
        """Record a batch flush operation."""
        self.inc('csv_batch_flushes', labels={'index': index, 'expiry': expiry_code})
        self.set('csv_last_batch_size', row_count, labels={'index': index, 'expiry': expiry_code})

    def record_duplicate_suppressed(self, index: str, expiry_code: str) -> None:
        """Record a duplicate row suppression."""
        self.inc('csv_duplicates_suppressed', labels={'index': index, 'expiry': expiry_code})

    def record_junk_filtered(self, index: str, expiry_code: str, category: str) -> None:
        """Record a junk row filtered out."""
        self.inc('csv_junk_filtered', labels={'index': index, 'expiry': expiry_code, 'category': category})

    def record_quarantine_write(self, index: str, expiry_code: str, success: bool) -> None:
        """Record a quarantine file write attempt."""
        status = 'success' if success else 'failed'
        self.inc('csv_quarantine_writes', labels={'index': index, 'expiry': expiry_code, 'status': status})

    def record_overview_write(self, index: str) -> None:
        """Record an overview snapshot write."""
        self.inc('csv_overview_writes', labels={'index': index})

    def record_aggregation_update(self, index: str, expiry_code: str) -> None:
        """Record an aggregation state update."""
        self.inc('csv_aggregation_updates', labels={'index': index, 'expiry': expiry_code})
