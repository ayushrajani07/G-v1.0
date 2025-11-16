"""Tests for log sanitization system.

Tests for Phase 3.3: Security Hardening
"""
import logging
import pytest

from src.security.log_sanitizer import (
    LogSanitizer,
    SanitizingFormatter,
    get_sanitizer,
    setup_log_sanitization,
    sanitize_string,
    sanitize_dict,
)


def test_api_key_sanitization():
    """Test API key sanitization."""
    sanitizer = LogSanitizer()
    
    message = "Using api_key=sk_live_1234567890abcdefghij for requests"
    sanitized = sanitizer.sanitize(message)
    
    assert 'sk_live_1234567890abcdefghij' not in sanitized
    assert '***REDACTED***' in sanitized
    assert 'api_key=' in sanitized


def test_kite_credentials_sanitization():
    """Test Kite Connect credential sanitization."""
    sanitizer = LogSanitizer()
    
    messages = [
        "KITE_API_KEY=abc123xyz456def789",
        "KITE_API_SECRET: secret_key_value_123",
        "KITE_ACCESS_TOKEN='long_token_value_1234567890'",
    ]
    
    for msg in messages:
        sanitized = sanitizer.sanitize(msg)
        assert 'abc123xyz456def789' not in sanitized
        assert 'secret_key_value_123' not in sanitized
        assert 'long_token_value_1234567890' not in sanitized
        assert '***REDACTED***' in sanitized


def test_bearer_token_sanitization():
    """Test Bearer token sanitization."""
    sanitizer = LogSanitizer()
    
    message = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
    sanitized = sanitizer.sanitize(message)
    
    assert 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9' not in sanitized
    assert '***REDACTED***' in sanitized


def test_password_sanitization():
    """Test password sanitization."""
    sanitizer = LogSanitizer()
    
    message = "Connecting with password=SuperSecret123! to database"
    sanitized = sanitizer.sanitize(message)
    
    assert 'SuperSecret123!' not in sanitized
    assert '***REDACTED***' in sanitized


def test_database_url_sanitization():
    """Test database URL password sanitization."""
    sanitizer = LogSanitizer()
    
    message = "DATABASE_URL=postgresql://user:password123@localhost:5432/db"
    sanitized = sanitizer.sanitize(message)
    
    assert 'password123' not in sanitized
    assert '***REDACTED***' in sanitized
    assert 'postgresql://user:' in sanitized
    assert '@localhost:5432/db' in sanitized


def test_custom_pattern():
    """Test adding custom sanitization pattern."""
    sanitizer = LogSanitizer()
    
    # Add custom pattern for SSN
    sanitizer.add_pattern(r'\b\d{3}-\d{2}-\d{4}\b', '***SSN***')
    
    message = "Customer SSN is 123-45-6789"
    sanitized = sanitizer.sanitize(message)
    
    assert '123-45-6789' not in sanitized
    assert '***SSN***' in sanitized


def test_dict_sanitization():
    """Test dictionary sanitization."""
    sanitizer = LogSanitizer()
    
    data = {
        'username': 'alice',
        'password': 'secret123',
        'api_key': 'key_12345',
        'normal_field': 'safe_value',
        'nested': {
            'token': 'nested_token_value',
            'data': 'safe_nested_value',
        }
    }
    
    sanitized = sanitizer.sanitize_dict(data)
    
    assert sanitized['username'] == 'alice'
    assert sanitized['password'] == '***REDACTED***'
    assert sanitized['api_key'] == '***REDACTED***'
    assert sanitized['normal_field'] == 'safe_value'
    assert sanitized['nested']['token'] == '***REDACTED***'
    assert sanitized['nested']['data'] == 'safe_nested_value'


def test_sanitizing_formatter():
    """Test SanitizingFormatter integration."""
    logger = logging.getLogger('test_sanitizer')
    logger.setLevel(logging.INFO)
    
    # Create handler with SanitizingFormatter
    handler = logging.StreamHandler()
    handler.setFormatter(SanitizingFormatter('%(message)s'))
    logger.addHandler(handler)
    
    # Log message with sensitive data (should not crash)
    logger.info("API key: sk_test_1234567890abcdefghij")
    
    logger.removeHandler(handler)


def test_disabled_sanitization():
    """Test that sanitization can be disabled."""
    sanitizer = LogSanitizer()
    sanitizer.enabled = False
    
    message = "password=secret123"
    sanitized = sanitizer.sanitize(message)
    
    # Should be unchanged when disabled
    assert sanitized == message


def test_global_sanitizer():
    """Test global sanitizer singleton."""
    sanitizer1 = get_sanitizer()
    sanitizer2 = get_sanitizer()
    
    assert sanitizer1 is sanitizer2


def test_convenience_functions():
    """Test convenience functions."""
    text = "api_key=secret_key_12345"
    sanitized = sanitize_string(text)
    
    assert 'secret_key_12345' not in sanitized
    assert '***REDACTED***' in sanitized
    
    data = {'password': 'secret', 'username': 'alice'}
    sanitized_dict_result = sanitize_dict(data)
    
    assert sanitized_dict_result['password'] == '***REDACTED***'
    assert sanitized_dict_result['username'] == 'alice'


def test_setup_log_sanitization():
    """Test setup function for root logger."""
    # Create a test logger
    test_logger = logging.getLogger('test_setup')
    test_logger.setLevel(logging.INFO)
    
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(message)s'))
    test_logger.addHandler(handler)
    
    # Setup sanitization
    setup_log_sanitization()
    
    # Check that root logger handlers have SanitizingFormatter
    root_logger = logging.getLogger()
    has_sanitizing_formatter = any(
        isinstance(h.formatter, SanitizingFormatter)
        for h in root_logger.handlers
    )
    
    # Cleanup
    test_logger.removeHandler(handler)


def test_empty_message():
    """Test sanitization of empty messages."""
    sanitizer = LogSanitizer()
    
    assert sanitizer.sanitize('') == ''
    assert sanitizer.sanitize(None) is None


def test_no_sensitive_data():
    """Test that normal messages are unchanged."""
    sanitizer = LogSanitizer()
    
    message = "Processing 1000 records for symbol NIFTY"
    sanitized = sanitizer.sanitize(message)
    
    assert sanitized == message


def test_multiple_patterns_in_message():
    """Test sanitization of multiple sensitive items in one message."""
    sanitizer = LogSanitizer()
    
    message = "Login with api_key=key1234567890 and password=pass4567890"
    sanitized = sanitizer.sanitize(message)
    
    assert 'key1234567890' not in sanitized
    assert 'pass4567890' not in sanitized
    assert sanitized.count('***REDACTED***') >= 2
