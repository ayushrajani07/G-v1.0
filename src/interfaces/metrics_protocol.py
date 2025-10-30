"""
Metrics Protocol - Interface for metrics instrumentation.

Breaks circular dependency between:
- src.metrics (implementation)
- src.collectors (users of metrics)
- src.error_handling (emits metrics)

This protocol allows any module to declare dependency on metrics
without importing the concrete implementation.
"""

from typing import Any, ContextManager, Protocol, runtime_checkable


@runtime_checkable
class MetricsProtocol(Protocol):
    """
    Protocol for metrics instrumentation.
    
    Defines the contract for emitting metrics without depending
    on the concrete MetricsRegistry implementation.
    
    Usage:
        def collect_data(metrics: MetricsProtocol) -> None:
            metrics.increment_counter("data_collected")
            with metrics.record_timer("collection_time"):
                # ... collection logic ...
                pass
    """
    
    def increment_counter(self, name: str, value: float = 1.0, labels: dict[str, Any] | None = None) -> None:
        """
        Increment a counter metric.
        
        Args:
            name: Metric name
            value: Increment value (default 1.0)
            labels: Optional label dict
        """
        ...
    
    def set_gauge(self, name: str, value: float, labels: dict[str, Any] | None = None) -> None:
        """
        Set a gauge metric to a specific value.
        
        Args:
            name: Metric name
            value: Gauge value
            labels: Optional label dict
        """
        ...
    
    def observe_histogram(self, name: str, value: float, labels: dict[str, Any] | None = None) -> None:
        """
        Record a histogram observation.
        
        Args:
            name: Metric name
            value: Observed value
            labels: Optional label dict
        """
        ...
    
    def record_timer(self, name: str, labels: dict[str, Any] | None = None) -> ContextManager[None]:
        """
        Context manager for timing operations.
        
        Args:
            name: Timer metric name
            labels: Optional label dict
            
        Returns:
            Context manager that records elapsed time on exit
            
        Usage:
            with metrics.record_timer("operation_time"):
                # ... timed operation ...
                pass
        """
        ...
    
    def safe_emit(self, name: str, value: float, labels: dict[str, Any] | None = None) -> None:
        """
        Emit a metric with error suppression.
        
        Guarantees that metric emission failures won't propagate.
        
        Args:
            name: Metric name
            value: Metric value
            labels: Optional label dict
        """
        ...


@runtime_checkable
class MetricsRegistryProtocol(Protocol):
    """
    Extended protocol for the full MetricsRegistry interface.
    
    Use this when you need registry-level operations like
    registration, not just emission.
    """
    
    def register_counter(self, name: str, help_text: str, labels: list[str] | None = None) -> Any:
        """Register a new counter metric."""
        ...
    
    def register_gauge(self, name: str, help_text: str, labels: list[str] | None = None) -> Any:
        """Register a new gauge metric."""
        ...
    
    def register_histogram(self, name: str, help_text: str, labels: list[str] | None = None, buckets: list[float] | None = None) -> Any:
        """Register a new histogram metric."""
        ...
    
    def get_metric(self, name: str) -> Any | None:
        """Get a registered metric by name."""
        ...
