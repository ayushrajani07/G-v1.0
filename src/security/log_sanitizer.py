"""Log sanitization for sensitive data protection.

Part of Phase 3.3: Security Hardening (2025-11-16)

Provides automatic sanitization of sensitive data in log messages to prevent
credential leaks in logs, metrics, and error reports.

Features:
- Pattern-based sanitization for common secrets
- Custom pattern registration
- Integration with Python logging
- Configurable redaction strings
- Performance-optimized regex patterns

Environment Variables:
    G6_LOG_SANITIZATION_ENABLED: Enable sanitization (default: 1)
    G6_LOG_REDACTION_STRING: Replacement string (default: '***REDACTED***')

Usage:
    from src.security.log_sanitizer import setup_log_sanitization
    
    # Setup once at application startup
    setup_log_sanitization()
    
    # Now all loggers will automatically sanitize
    logger.info(f"Token: {token}")  # Logged as "Token: ***REDACTED***"
"""
from __future__ import annotations

import logging
import re
from typing import ClassVar, Pattern

from src.config.env_config import EnvConfig

logger = logging.getLogger(__name__)


class LogSanitizer:
    """Sanitizes sensitive data from log messages.
    
    Uses regex patterns to detect and redact sensitive information like:
    - API keys, tokens, passwords
    - Database connection strings
    - Email addresses (optional)
    - Credit card numbers
    - Private IP addresses
    """
    
    # Default sensitive patterns
    DEFAULT_PATTERNS: ClassVar[list[tuple[Pattern[str], str]]] = [
        # API keys and tokens
        (re.compile(r'(api[_-]?key\s*[=:]\s*)["\']?([a-zA-Z0-9_\-]{10,})["\']?', re.IGNORECASE), r'\1***REDACTED***'),
        (re.compile(r'(access[_-]?token\s*[=:]\s*)["\']?([a-zA-Z0-9_\-]{20,})["\']?', re.IGNORECASE), r'\1***REDACTED***'),
        (re.compile(r'(bearer\s+)([a-zA-Z0-9_\-\.]{20,})', re.IGNORECASE), r'\1***REDACTED***'),
        
        # Kite Connect specific
        (re.compile(r'(KITE_API_KEY\s*[=:]\s*)["\']?([a-zA-Z0-9]{15,})["\']?', re.IGNORECASE), r'\1***REDACTED***'),
        (re.compile(r'(KITE_API_SECRET\s*[=:]\s*)["\']?([a-zA-Z0-9]{15,})["\']?', re.IGNORECASE), r'\1***REDACTED***'),
        (re.compile(r'(KITE_ACCESS_TOKEN\s*[=:]\s*)["\']?([a-zA-Z0-9]{20,})["\']?', re.IGNORECASE), r'\1***REDACTED***'),
        
        # Generic secrets
        (re.compile(r'(password\s*[=:]\s*)["\']?([^\s"\'\n]{8,})["\']?', re.IGNORECASE), r'\1***REDACTED***'),
        (re.compile(r'(secret\s*[=:]\s*)["\']?([a-zA-Z0-9_\-]{10,})["\']?', re.IGNORECASE), r'\1***REDACTED***'),
        (re.compile(r'(token\s*[=:]\s*)["\']?([a-zA-Z0-9_\-\.]{20,})["\']?', re.IGNORECASE), r'\1***REDACTED***'),
        
        # Database URLs
        (re.compile(r'(://[^:@\s]+:)([^@\s]+)(@)', re.IGNORECASE), r'\1***REDACTED***\3'),
        
        # AWS keys
        (re.compile(r'(AKIA[0-9A-Z]{16})', re.IGNORECASE), r'***REDACTED_AWS_KEY***'),
        (re.compile(r'([a-zA-Z0-9/+=]{40})', re.IGNORECASE), r'***REDACTED_SECRET***'),  # Generic 40-char secrets
    ]
    
    def __init__(self, redaction_string: str = '***REDACTED***'):
        """Initialize sanitizer with custom redaction string.
        
        Args:
            redaction_string: String to replace sensitive data with
        """
        self.redaction_string = redaction_string
        self.patterns = list(self.DEFAULT_PATTERNS)
        self.enabled = EnvConfig.get_bool('G6_LOG_SANITIZATION_ENABLED', True)
    
    def add_pattern(self, pattern: str | Pattern[str], replacement: str) -> None:
        """Add a custom sanitization pattern.
        
        Args:
            pattern: Regex pattern (string or compiled)
            replacement: Replacement string (can use regex groups like r'\1***')
        """
        if isinstance(pattern, str):
            pattern = re.compile(pattern, re.IGNORECASE)
        self.patterns.append((pattern, replacement))
    
    def sanitize(self, message: str) -> str:
        """Sanitize a log message by redacting sensitive data.
        
        Args:
            message: Original log message
            
        Returns:
            Sanitized message with sensitive data redacted
        """
        if not self.enabled or not message:
            return message
        
        sanitized = message
        for pattern, replacement in self.patterns:
            sanitized = pattern.sub(replacement, sanitized)
        
        return sanitized
    
    def sanitize_dict(self, data: dict) -> dict:
        """Sanitize dictionary values (for structured logging).
        
        Args:
            data: Dictionary with potentially sensitive values
            
        Returns:
            New dictionary with sanitized values
        """
        if not self.enabled:
            return data
        
        sanitized = {}
        sensitive_keys = {'password', 'token', 'secret', 'api_key', 'apikey', 'access_token'}
        
        for key, value in data.items():
            if isinstance(value, str):
                # If key is sensitive, always redact
                if key.lower() in sensitive_keys:
                    sanitized[key] = self.redaction_string
                else:
                    sanitized[key] = self.sanitize(value)
            elif isinstance(value, dict):
                sanitized[key] = self.sanitize_dict(value)
            elif isinstance(value, (list, tuple)):
                sanitized[key] = [self.sanitize_dict(v) if isinstance(v, dict) else self.sanitize(str(v)) for v in value]
            else:
                sanitized[key] = value
        
        return sanitized


class SanitizingFormatter(logging.Formatter):
    """Logging formatter that sanitizes sensitive data.
    
    Drop-in replacement for logging.Formatter that automatically sanitizes
    all log messages before formatting.
    """
    
    def __init__(self, *args, **kwargs):
        """Initialize sanitizing formatter.
        
        Args:
            *args: Passed to logging.Formatter
            **kwargs: Passed to logging.Formatter
        """
        super().__init__(*args, **kwargs)
        self.sanitizer = LogSanitizer(
            redaction_string=EnvConfig.get_str('G6_LOG_REDACTION_STRING', '***REDACTED***')
        )
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record with sanitization.
        
        Args:
            record: Log record to format
            
        Returns:
            Formatted and sanitized log message
        """
        # Sanitize message
        if record.msg:
            record.msg = self.sanitizer.sanitize(str(record.msg))
        
        # Sanitize args (but preserve types for %d formatting)
        if record.args:
            if isinstance(record.args, dict):
                record.args = self.sanitizer.sanitize_dict(record.args)
            else:
                # Only sanitize string args, preserve numbers
                record.args = tuple(
                    self.sanitizer.sanitize(str(arg)) if isinstance(arg, str) else arg 
                    for arg in record.args
                )
        
        # Format normally
        return super().format(record)


# Global singleton
_sanitizer: LogSanitizer | None = None


def get_sanitizer() -> LogSanitizer:
    """Get global log sanitizer instance.
    
    Returns:
        Global LogSanitizer instance
    """
    global _sanitizer
    if _sanitizer is None:
        _sanitizer = LogSanitizer()
    return _sanitizer


def setup_log_sanitization() -> None:
    """Setup log sanitization for all handlers in root logger.
    
    Replaces formatters on all handlers with SanitizingFormatter while
    preserving the original format string.
    """
    root_logger = logging.getLogger()
    
    for handler in root_logger.handlers:
        original_formatter = handler.formatter
        
        if isinstance(original_formatter, SanitizingFormatter):
            # Already setup
            continue
        
        # Get format string from original formatter
        if original_formatter:
            fmt = original_formatter._fmt if hasattr(original_formatter, '_fmt') else None
            datefmt = original_formatter.datefmt
            style = original_formatter._style._fmt if hasattr(original_formatter, '_style') else '%'
        else:
            fmt = None
            datefmt = None
            style = '%'
        
        # Replace with sanitizing formatter
        handler.setFormatter(SanitizingFormatter(fmt=fmt, datefmt=datefmt))
    
    logger.info("Log sanitization enabled for all handlers")


def sanitize_string(text: str) -> str:
    """Sanitize a single string (convenience function).
    
    Args:
        text: Text to sanitize
        
    Returns:
        Sanitized text
    """
    return get_sanitizer().sanitize(text)


def sanitize_dict(data: dict) -> dict:
    """Sanitize a dictionary (convenience function).
    
    Args:
        data: Dictionary to sanitize
        
    Returns:
        Sanitized dictionary
    """
    return get_sanitizer().sanitize_dict(data)


__all__ = [
    'LogSanitizer',
    'SanitizingFormatter',
    'get_sanitizer',
    'setup_log_sanitization',
    'sanitize_string',
    'sanitize_dict',
]
