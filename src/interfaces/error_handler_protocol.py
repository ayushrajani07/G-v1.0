"""
Error Handler Protocol - Interface for error handling and routing.

Breaks circular dependency between:
- src.error_handling (implementation)
- src.collectors (emits errors)
- src.metrics (tracks errors)

This protocol allows any module to declare dependency on error handling
without importing the concrete implementation.
"""

from enum import Enum
from typing import Any, Protocol, runtime_checkable


class ErrorCategory(Enum):
    """Error categories for classification."""
    API = "api"
    DATA = "data"
    PROVIDER = "provider"
    COLLECTOR = "collector"
    VALIDATION = "validation"
    STORAGE = "storage"
    CONFIGURATION = "configuration"
    UNKNOWN = "unknown"


class ErrorSeverity(Enum):
    """Error severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@runtime_checkable
class ErrorHandlerProtocol(Protocol):
    """
    Protocol for error handling and routing.
    
    Defines the contract for error handling without depending
    on the concrete implementation.
    
    Usage:
        def collect_data(error_handler: ErrorHandlerProtocol) -> None:
            try:
                # ... risky operation ...
                pass
            except Exception as e:
                error_handler.handle_error(
                    error=e,
                    category=ErrorCategory.DATA,
                    severity=ErrorSeverity.MEDIUM,
                    context={"index": "NIFTY"}
                )
    """
    
    def handle_error(
        self,
        error: Exception,
        category: ErrorCategory,
        severity: ErrorSeverity,
        context: dict[str, Any] | None = None,
        suppress: bool = True
    ) -> None:
        """
        Handle an error with categorization and routing.
        
        Args:
            error: The exception to handle
            category: Error category for classification
            severity: Error severity level
            context: Optional context dict (e.g., index, cycle, etc.)
            suppress: Whether to suppress re-raising (default True)
        """
        ...
    
    def log_error(
        self,
        message: str,
        category: ErrorCategory,
        severity: ErrorSeverity,
        context: dict[str, Any] | None = None
    ) -> None:
        """
        Log an error message without an exception.
        
        Args:
            message: Error message
            category: Error category
            severity: Error severity
            context: Optional context dict
        """
        ...
    
    def get_error_count(self, category: ErrorCategory | None = None) -> int:
        """
        Get count of errors handled.
        
        Args:
            category: Optional category filter
            
        Returns:
            Number of errors handled
        """
        ...


# Re-export enums for convenience
__all__ = ["ErrorHandlerProtocol", "ErrorCategory", "ErrorSeverity"]
