"""
Errors package - Facade for error handling.

This package provides a clean interface to error handling functionality
without exposing implementation details or causing circular imports.

Usage:
    from src.errors import get_error_handler_lazy, ErrorCategory, ErrorSeverity
    
    handler = get_error_handler_lazy()
    handler.handle_error(exception, ErrorCategory.API, ErrorSeverity.HIGH)
"""

from .facade import (
    ErrorCategory,
    ErrorSeverity,
    get_error_count,
    get_error_handler_lazy,
    handle_error,
    log_error,
    reset_error_handler_lazy,
)

__all__ = [
    "get_error_handler_lazy",
    "reset_error_handler_lazy",
    "handle_error",
    "log_error",
    "get_error_count",
    "ErrorCategory",
    "ErrorSeverity",
]
