"""
Error Handler Facade - Lazy singleton access for error handling.

This facade provides lazy loading of the error handler singleton,
breaking circular dependencies by deferring imports until first use.

Key Benefits:
- No circular import issues (imports happen at runtime)
- Thread-safe singleton access
- Type-safe via ErrorHandlerProtocol
- Drop-in replacement for get_error_handler()

Usage:
    # Old pattern (causes circular imports):
    from src.error_handling import get_error_handler, ErrorCategory
    handler = get_error_handler()
    
    # New pattern (no circular imports):
    from src.errors.facade import get_error_handler_lazy
    from src.interfaces import ErrorCategory, ErrorSeverity
    handler = get_error_handler_lazy()
    
    # Even better - use protocol for type hints:
    from src.interfaces import ErrorHandlerProtocol, ErrorCategory, ErrorSeverity
    from src.errors.facade import get_error_handler_lazy
    
    def my_function(error_handler: ErrorHandlerProtocol | None = None) -> None:
        handler = error_handler or get_error_handler_lazy()
        try:
            # ... risky operation ...
            pass
        except Exception as e:
            handler.handle_error(e, ErrorCategory.DATA, ErrorSeverity.MEDIUM)
"""

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.interfaces import ErrorHandlerProtocol

# Re-export enums for convenience (no circular risk)
from src.interfaces.error_handler_protocol import ErrorCategory, ErrorSeverity

# Optional imports for late import elimination (Batch 38)
try:
    from src.error_handling import get_error_handler
except ImportError:
    get_error_handler = None  # type: ignore

# Singleton state
_error_handler_instance: "ErrorHandlerProtocol | None" = None
_error_handler_lock = threading.Lock()


def get_error_handler_lazy() -> "ErrorHandlerProtocol":
    """
    Get error handler singleton with lazy initialization.
    
    This function defers importing the error handler until first call,
    breaking circular import chains. Thread-safe with double-checked locking.
    
    Returns:
        ErrorHandlerProtocol instance (error handler singleton)
        
    Example:
        handler = get_error_handler_lazy()
        
        try:
            # ... operation that might fail ...
            pass
        except Exception as e:
            handler.handle_error(
                error=e,
                category=ErrorCategory.API,
                severity=ErrorSeverity.HIGH,
                context={"index": "NIFTY"},
                suppress=True
            )
    """
    global _error_handler_instance
    
    # Fast path: already initialized
    if _error_handler_instance is not None:
        return _error_handler_instance
    
    # Slow path: need to initialize (thread-safe)
    with _error_handler_lock:
        # Double-check after acquiring lock
        if _error_handler_instance is not None:
            return _error_handler_instance
        
        # Import only when needed (breaks circular deps)
        if not get_error_handler:
            raise ImportError("get_error_handler not available")
        
        # Get handler and cast to protocol (G6ErrorHandler implements ErrorHandlerProtocol)
        handler = get_error_handler()
        _error_handler_instance = handler  # type: ignore[assignment]
        
        # Assert for type checker (guaranteed non-None after assignment above)
        assert _error_handler_instance is not None
        return _error_handler_instance


def reset_error_handler_lazy() -> None:
    """
    Reset the lazy singleton (for testing).
    
    This allows tests to reset the singleton state between test cases.
    Should not be used in production code.
    """
    global _error_handler_instance
    with _error_handler_lock:
        _error_handler_instance = None


# Convenience helpers that delegate to the singleton
def handle_error(
    error: Exception,
    category: ErrorCategory,
    severity: ErrorSeverity,
    context: dict | None = None,
    suppress: bool = True
) -> None:
    """
    Handle an error (convenience wrapper).
    
    Args:
        error: The exception to handle
        category: Error category for classification
        severity: Error severity level
        context: Optional context dict
        suppress: Whether to suppress re-raising
    """
    get_error_handler_lazy().handle_error(error, category, severity, context, suppress)


def log_error(
    message: str,
    category: ErrorCategory,
    severity: ErrorSeverity,
    context: dict | None = None
) -> None:
    """
    Log an error message without an exception (convenience wrapper).
    
    Args:
        message: Error message
        category: Error category
        severity: Error severity
        context: Optional context dict
    """
    get_error_handler_lazy().log_error(message, category, severity, context)


def get_error_count(category: ErrorCategory | None = None) -> int:
    """
    Get count of errors handled (convenience wrapper).
    
    Args:
        category: Optional category filter
        
    Returns:
        Number of errors handled
    """
    return get_error_handler_lazy().get_error_count(category)


__all__ = [
    "get_error_handler_lazy",
    "reset_error_handler_lazy",
    "handle_error",
    "log_error",
    "get_error_count",
    "ErrorCategory",
    "ErrorSeverity",
]
