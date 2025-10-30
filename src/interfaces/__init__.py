"""
Interfaces package for G6 Platform.

This package contains Protocol definitions and abstract interfaces
used throughout the codebase to break circular dependencies via
dependency inversion.

Key Principles:
- Protocols are import-free (only use typing and stdlib)
- No runtime dependencies on other src modules
- Can be imported anywhere without circular risk
- Enable type-checking and runtime duck-typing

Usage:
    from src.interfaces import MetricsProtocol, ErrorHandlerProtocol
    
    def my_function(metrics: MetricsProtocol) -> None:
        metrics.increment_counter("my_metric")
"""

from .metrics_protocol import MetricsProtocol
from .error_handler_protocol import ErrorHandlerProtocol
from .provider_protocol import ProviderProtocol

__all__ = [
    "MetricsProtocol",
    "ErrorHandlerProtocol",
    "ProviderProtocol",
]
