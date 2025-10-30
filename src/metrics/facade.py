"""
Metrics Facade - Lazy singleton access for metrics instrumentation.

This facade provides lazy loading of the MetricsRegistry singleton,
breaking circular dependencies by deferring imports until first use.

Key Benefits:
- No circular import issues (imports happen at runtime)
- Thread-safe singleton access
- Type-safe via MetricsProtocol
- Drop-in replacement for get_metrics_singleton()

Usage:
    # Old pattern (causes circular imports):
    from src.metrics import get_metrics_singleton
    metrics = get_metrics_singleton()
    
    # New pattern (no circular imports):
    from src.metrics.facade import get_metrics_lazy
    metrics = get_metrics_lazy()
    
    # Even better - use protocol for type hints:
    from src.interfaces import MetricsProtocol
    from src.metrics.facade import get_metrics_lazy
    
    def my_function(metrics: MetricsProtocol | None = None) -> None:
        metrics = metrics or get_metrics_lazy()
        metrics.increment_counter("my_metric")
"""

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.interfaces import MetricsProtocol

# Optional imports for late import elimination (Batch 38)
try:
    from src.metrics import get_metrics_singleton
except ImportError:
    get_metrics_singleton = None  # type: ignore

# Singleton state
_metrics_instance: "MetricsProtocol | None" = None
_metrics_lock = threading.Lock()


def get_metrics_lazy() -> "MetricsProtocol":
    """
    Get metrics singleton with lazy initialization.
    
    This function defers importing MetricsRegistry until first call,
    breaking circular import chains. Thread-safe with double-checked locking.
    
    Returns:
        MetricsProtocol instance (MetricsRegistry singleton)
        
    Example:
        metrics = get_metrics_lazy()
        metrics.increment_counter("requests_total")
        
        with metrics.record_timer("operation_duration"):
            # ... timed operation ...
            pass
    """
    global _metrics_instance
    
    # Fast path: already initialized
    if _metrics_instance is not None:
        return _metrics_instance
    
    # Slow path: need to initialize (thread-safe)
    with _metrics_lock:
        # Double-check after acquiring lock
        if _metrics_instance is not None:
            return _metrics_instance
        
        # Import only when needed (breaks circular deps)
        if not get_metrics_singleton:
            raise ImportError("get_metrics_singleton not available")
        
        # Get singleton and cast to protocol (MetricsRegistry implements MetricsProtocol)
        registry = get_metrics_singleton()
        if registry is None:
            raise RuntimeError("MetricsRegistry singleton returned None")
        _metrics_instance = registry  # type: ignore[assignment]
        
        # Assert for type checker (guaranteed non-None after assignment above)
        assert _metrics_instance is not None
        return _metrics_instance


def reset_metrics_lazy() -> None:
    """
    Reset the lazy singleton (for testing).
    
    This allows tests to reset the singleton state between test cases.
    Should not be used in production code.
    """
    global _metrics_instance
    with _metrics_lock:
        _metrics_instance = None


# Convenience helpers that delegate to the singleton
def increment_counter(name: str, value: float = 1.0, labels: dict | None = None) -> None:
    """Increment a counter (convenience wrapper)."""
    get_metrics_lazy().increment_counter(name, value, labels)


def set_gauge(name: str, value: float, labels: dict | None = None) -> None:
    """Set a gauge value (convenience wrapper)."""
    get_metrics_lazy().set_gauge(name, value, labels)


def observe_histogram(name: str, value: float, labels: dict | None = None) -> None:
    """Record a histogram observation (convenience wrapper)."""
    get_metrics_lazy().observe_histogram(name, value, labels)


def record_timer(name: str, labels: dict | None = None):
    """Get a timer context manager (convenience wrapper)."""
    return get_metrics_lazy().record_timer(name, labels)


def safe_emit(name: str, value: float, labels: dict | None = None) -> None:
    """Emit a metric with error suppression (convenience wrapper)."""
    get_metrics_lazy().safe_emit(name, value, labels)


__all__ = [
    "get_metrics_lazy",
    "reset_metrics_lazy",
    "increment_counter",
    "set_gauge",
    "observe_histogram",
    "record_timer",
    "safe_emit",
]
