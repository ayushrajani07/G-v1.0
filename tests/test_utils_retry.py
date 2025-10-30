"""Tests for retry utilities."""
from __future__ import annotations

import os
from unittest.mock import Mock, patch

import pytest

from src.utils.exceptions import RetryError
from src.utils.retry import (
    build_retry_predicate,
    build_stop_strategy,
    build_wait_strategy,
    call_with_retry,
    retryable,
)


class TestRetryPredicates:
    """Test retry predicate building."""
    
    @patch.dict(os.environ, {}, clear=True)
    def test_build_retry_predicate_default(self):
        """Test default retry predicate."""
        predicate = build_retry_predicate()
        
        # Should retry TimeoutError and ConnectionError by default
        assert predicate(TimeoutError())
        assert predicate(ConnectionError())
        
        # Should not retry other exceptions
        assert not predicate(ValueError())
        assert not predicate(RuntimeError())
    
    @patch.dict(os.environ, {'G6_RETRY_WHITELIST': 'ValueError,RuntimeError'}, clear=True)
    def test_build_retry_predicate_whitelist(self):
        """Test retry predicate with whitelist."""
        predicate = build_retry_predicate()
        
        # Should only retry whitelisted exceptions
        assert predicate(ValueError())
        assert predicate(RuntimeError())
        
        # Should not retry non-whitelisted
        assert not predicate(TimeoutError())
        assert not predicate(KeyError())
    
    @patch.dict(os.environ, {'G6_RETRY_BLACKLIST': 'TimeoutError'}, clear=True)
    def test_build_retry_predicate_blacklist(self):
        """Test retry predicate with blacklist."""
        predicate = build_retry_predicate()
        
        # Should not retry blacklisted
        assert not predicate(TimeoutError())
        
        # Should still retry default retryables (except blacklisted)
        assert predicate(ConnectionError())
    
    @patch.dict(os.environ, {'G6_RETRY_WHITELIST': 'ValueError', 'G6_RETRY_BLACKLIST': 'ValueError'}, clear=True)
    def test_build_retry_predicate_blacklist_wins(self):
        """Test that blacklist takes precedence over whitelist."""
        predicate = build_retry_predicate()
        
        # Blacklist should override whitelist
        assert not predicate(ValueError())


class TestRetryStrategies:
    """Test retry strategy building."""
    
    def test_build_wait_strategy_default(self):
        """Test default wait strategy."""
        wait = build_wait_strategy()
        assert wait is not None
    
    @patch.dict(os.environ, {'G6_RETRY_BACKOFF': '0.5'})
    def test_build_wait_strategy_custom_backoff(self):
        """Test wait strategy with custom backoff."""
        wait = build_wait_strategy()
        assert wait is not None
    
    @patch.dict(os.environ, {'G6_RETRY_JITTER': '0'})
    def test_build_wait_strategy_no_jitter(self):
        """Test wait strategy without jitter."""
        wait = build_wait_strategy()
        assert wait is not None
    
    def test_build_stop_strategy_default(self):
        """Test default stop strategy."""
        stop = build_stop_strategy()
        assert stop is not None
    
    @patch.dict(os.environ, {'G6_RETRY_MAX_ATTEMPTS': '5'})
    def test_build_stop_strategy_custom_attempts(self):
        """Test stop strategy with custom attempts."""
        stop = build_stop_strategy()
        assert stop is not None
    
    @patch.dict(os.environ, {'G6_RETRY_MAX_SECONDS': '10'})
    def test_build_stop_strategy_custom_timeout(self):
        """Test stop strategy with custom timeout."""
        stop = build_stop_strategy()
        assert stop is not None


class TestRetryableDecorator:
    """Test retryable decorator."""
    
    def test_retryable_success_first_try(self):
        """Test retryable decorator with immediate success."""
        mock_fn = Mock(return_value=42)
        
        @retryable
        def func():
            return mock_fn()
        
        result = func()
        assert result == 42
        assert mock_fn.call_count == 1
    
    @patch.dict(os.environ, {'G6_RETRY_MAX_ATTEMPTS': '3', 'G6_RETRY_WHITELIST': 'RuntimeError', 'G6_RETRY_BACKOFF': '0.01'}, clear=True)
    def test_retryable_success_after_retries(self):
        """Test retryable decorator succeeds after retries."""
        mock_fn = Mock(side_effect=[RuntimeError(), RuntimeError(), 42])
        
        @retryable
        def func():
            return mock_fn()
        
        result = func()
        assert result == 42
        assert mock_fn.call_count == 3
    
    @patch.dict(os.environ, {'G6_RETRY_MAX_ATTEMPTS': '2', 'G6_RETRY_WHITELIST': 'RuntimeError', 'G6_RETRY_BACKOFF': '0.01'}, clear=True)
    def test_retryable_exhausts_retries(self):
        """Test retryable decorator exhausts retries."""
        mock_fn = Mock(side_effect=RuntimeError("persistent error"))
        
        @retryable
        def func():
            return mock_fn()
        
        with pytest.raises(RuntimeError, match="persistent error"):
            func()
        
        # Call count should be max attempts
        assert mock_fn.call_count >= 2
    
    @patch.dict(os.environ, {}, clear=True)
    def test_retryable_no_retry_on_non_retryable_exception(self):
        """Test retryable doesn't retry non-retryable exceptions."""
        mock_fn = Mock(side_effect=ValueError("not retryable"))
        
        @retryable
        def func():
            return mock_fn()
        
        with pytest.raises(ValueError, match="not retryable"):
            func()
        
        # Should not retry
        assert mock_fn.call_count == 1
    
    @patch.dict(os.environ, {'G6_RETRY_MAX_ATTEMPTS': '3', 'G6_RETRY_WHITELIST': 'TimeoutError', 'G6_RETRY_BACKOFF': '0.01'}, clear=True)
    def test_retryable_with_reraise_false(self):
        """Test retryable with reraise=False."""
        attempt_count = {'count': 0}
        
        @retryable(reraise=False)
        def func():
            attempt_count['count'] += 1
            if attempt_count['count'] < 3:
                raise TimeoutError()
            return "success"
        
        # Should not raise
        result = func()
        # Will eventually succeed or return None
        assert result == "success" or result is None
        assert attempt_count['count'] >= 1


class TestCallWithRetry:
    """Test call_with_retry helper."""
    
    def test_call_with_retry_success(self):
        """Test call_with_retry with immediate success."""
        mock_fn = Mock(return_value=42)
        
        result = call_with_retry(mock_fn)
        assert result == 42
        assert mock_fn.call_count == 1
    
    @patch.dict(os.environ, {'G6_RETRY_MAX_ATTEMPTS': '3', 'G6_RETRY_WHITELIST': 'TimeoutError', 'G6_RETRY_BACKOFF': '0.01'}, clear=True)
    def test_call_with_retry_success_after_retries(self):
        """Test call_with_retry succeeds after retries."""
        mock_fn = Mock(side_effect=[TimeoutError(), TimeoutError(), 42])
        
        result = call_with_retry(mock_fn)
        assert result == 42
        assert mock_fn.call_count == 3
    
    @patch.dict(os.environ, {'G6_RETRY_MAX_ATTEMPTS': '2', 'G6_RETRY_WHITELIST': 'TimeoutError', 'G6_RETRY_BACKOFF': '0.01'}, clear=True)
    def test_call_with_retry_raises_retry_error(self):
        """Test call_with_retry raises RetryError on exhaustion."""
        mock_fn = Mock(side_effect=TimeoutError("persistent"))
        
        with pytest.raises(RetryError):
            call_with_retry(mock_fn)
        
        # Should make multiple attempts
        assert mock_fn.call_count >= 2
    
    @patch.dict(os.environ, {'G6_RETRY_WHITELIST': 'ValueError'})
    def test_call_with_retry_with_args_kwargs(self):
        """Test call_with_retry with arguments."""
        mock_fn = Mock(return_value=42)
        
        result = call_with_retry(mock_fn, 1, 2, key='value')
        assert result == 42
        mock_fn.assert_called_once_with(1, 2, key='value')
    
    def test_call_with_retry_no_retry_on_non_retryable(self):
        """Test call_with_retry doesn't retry non-retryable exceptions."""
        mock_fn = Mock(side_effect=ValueError("not retryable"))
        
        with pytest.raises(RetryError):
            call_with_retry(mock_fn)
        
        # Should not retry
        assert mock_fn.call_count == 1


class TestRetryIntegration:
    """Integration tests for retry functionality."""
    
    @patch.dict(os.environ, {
        'G6_RETRY_MAX_ATTEMPTS': '3',
        'G6_RETRY_BACKOFF': '0.01',
        'G6_RETRY_MAX_SECONDS': '1',
        'G6_RETRY_WHITELIST': 'ConnectionError'
    })
    def test_retry_with_custom_config(self):
        """Test retry with custom configuration."""
        attempt_count = {'count': 0}
        
        @retryable
        def func():
            attempt_count['count'] += 1
            if attempt_count['count'] < 3:
                raise ConnectionError("transient")
            return "success"
        
        result = func()
        assert result == "success"
        assert attempt_count['count'] == 3
    
    @patch.dict(os.environ, {
        'G6_RETRY_MAX_ATTEMPTS': '2',
        'G6_RETRY_WHITELIST': 'TimeoutError',
        'G6_RETRY_BLACKLIST': 'TimeoutError',
        'G6_RETRY_BACKOFF': '0.01'
    }, clear=True)
    def test_retry_blacklist_overrides_whitelist(self):
        """Test that blacklist takes precedence in real scenario."""
        mock_fn = Mock(side_effect=TimeoutError())
        
        @retryable
        def func():
            return mock_fn()
        
        # Should not retry due to blacklist
        with pytest.raises(TimeoutError):
            func()
        
        # Should only call once (no retries)
        assert mock_fn.call_count == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
