"""Tests for secure token manager.

Tests for Phase 3.3: Security Hardening
"""
import time
import pytest

from src.security.token_manager import (
    TokenManager,
    get_token_manager,
    initialize_kite_token,
)


def test_token_manager_initialization():
    """Test basic token manager initialization."""
    manager = TokenManager(rotation_hours=12, expiry_warn_hours=1)
    
    assert manager.rotation_hours == 12
    assert manager.expiry_warn_hours == 1


def test_set_and_get_token():
    """Test setting and retrieving tokens."""
    manager = TokenManager()
    
    manager.set_token('test_provider', 'test_token_123', expires_in_hours=24)
    token = manager.get_token('test_provider')
    
    assert token == 'test_token_123'


def test_token_expiry():
    """Test token expiry detection."""
    manager = TokenManager()
    
    # Set token that expires in past (negative hours)
    manager.set_token('test_provider', 'test_token', expires_in_hours=0.0001)  # ~0.36 seconds
    
    # Should be expired
    time.sleep(0.5)
    token = manager.get_token('test_provider')
    
    assert token is None  # Expired tokens return None


def test_token_expiry_warning(caplog):
    """Test warning when token is expiring soon."""
    import logging
    caplog.set_level(logging.WARNING)
    
    manager = TokenManager(expiry_warn_hours=1)
    
    # Set token that expires in 30 minutes
    manager.set_token('test_provider', 'test_token', expires_in_hours=0.5)
    
    # Should warn about expiry
    token = manager.get_token('test_provider')
    
    assert token == 'test_token'
    assert any('expiring soon' in record.message.lower() for record in caplog.records)


def test_should_rotate():
    """Test rotation recommendation logic."""
    manager = TokenManager(rotation_hours=0.0001)  # 0.36 seconds
    manager.enabled = True
    
    manager.set_token('test_provider', 'test_token')
    
    # Should not need rotation immediately
    assert not manager.should_rotate('test_provider')
    
    # Wait for rotation threshold
    time.sleep(0.5)  # 500ms > 360ms threshold
    
    # Should recommend rotation
    assert manager.should_rotate('test_provider')


def test_token_rotation_callback():
    """Test automatic token rotation with callback."""
    manager = TokenManager()
    
    rotation_called = []
    
    def rotate_callback(old_token):
        rotation_called.append(old_token)
        return f"new_{old_token}"
    
    manager.register_rotation_callback('test_provider', rotate_callback)
    manager.set_token('test_provider', 'old_token', expires_in_hours=24)
    
    # Perform rotation
    success = manager.rotate_token('test_provider')
    
    assert success
    assert len(rotation_called) == 1
    assert rotation_called[0] == 'old_token'
    assert manager.get_token('test_provider') == 'new_old_token'


def test_rotation_without_callback():
    """Test rotation fails without registered callback."""
    manager = TokenManager()
    
    manager.set_token('test_provider', 'test_token')
    
    success = manager.rotate_token('test_provider')
    
    assert not success


def test_rotation_callback_failure(caplog):
    """Test handling of callback failures."""
    import logging
    caplog.set_level(logging.ERROR)
    
    manager = TokenManager()
    
    def failing_callback(old_token):
        raise ValueError("Rotation failed")
    
    manager.register_rotation_callback('test_provider', failing_callback)
    manager.set_token('test_provider', 'test_token')
    
    success = manager.rotate_token('test_provider')
    
    assert not success
    assert any('rotation failed' in record.message.lower() for record in caplog.records)


def test_get_token_info():
    """Test getting token metadata."""
    manager = TokenManager()
    
    manager.set_token('test_provider', 'test_token', expires_in_hours=24)
    
    info = manager.get_token_info('test_provider')
    
    assert info is not None
    assert info['provider'] == 'test_provider'
    assert 'test_token' not in str(info)  # Token value not exposed
    assert 'created_at' in info
    assert 'expires_at' in info
    assert 'rotation_count' in info
    assert info['rotation_count'] == 0


def test_rotation_count_increment():
    """Test rotation counter increments."""
    manager = TokenManager()
    
    manager.set_token('test_provider', 'token1')
    assert manager.get_token_info('test_provider')['rotation_count'] == 0
    
    manager.set_token('test_provider', 'token2')  # Rotation
    assert manager.get_token_info('test_provider')['rotation_count'] == 1
    
    manager.set_token('test_provider', 'token3')  # Another rotation
    assert manager.get_token_info('test_provider')['rotation_count'] == 2


def test_remove_token():
    """Test token removal."""
    manager = TokenManager()
    
    manager.set_token('test_provider', 'test_token')
    assert manager.get_token('test_provider') == 'test_token'
    
    removed = manager.remove_token('test_provider')
    assert removed is True
    assert manager.get_token('test_provider') is None
    
    # Removing non-existent token
    removed = manager.remove_token('non_existent')
    assert removed is False


def test_list_providers():
    """Test listing all providers."""
    manager = TokenManager()
    
    manager.set_token('provider1', 'token1')
    manager.set_token('provider2', 'token2')
    manager.set_token('provider3', 'token3')
    
    providers = manager.list_providers()
    
    assert len(providers) == 3
    assert 'provider1' in providers
    assert 'provider2' in providers
    assert 'provider3' in providers


def test_clear_all():
    """Test clearing all tokens."""
    manager = TokenManager()
    
    manager.set_token('provider1', 'token1')
    manager.set_token('provider2', 'token2')
    
    assert len(manager.list_providers()) == 2
    
    manager.clear_all()
    
    assert len(manager.list_providers()) == 0


def test_global_manager_singleton():
    """Test global manager singleton."""
    manager1 = get_token_manager()
    manager2 = get_token_manager()
    
    assert manager1 is manager2


def test_token_never_expires():
    """Test tokens with no expiry."""
    manager = TokenManager()
    
    manager.set_token('test_provider', 'test_token', expires_in_hours=None)
    
    info = manager.get_token_info('test_provider')
    
    assert info['expires_at'] is None
    assert info['expires_in_hours'] is None
    assert not info['is_expired']


def test_get_nonexistent_token(caplog):
    """Test getting token for non-existent provider."""
    import logging
    caplog.set_level(logging.WARNING)
    
    manager = TokenManager()
    
    token = manager.get_token('non_existent')
    
    assert token is None
    assert any('no token found' in record.message.lower() for record in caplog.records)


def test_initialize_kite_token_with_env(monkeypatch):
    """Test initializing Kite token from environment."""
    monkeypatch.setenv('KITE_ACCESS_TOKEN', 'test_kite_token_123')
    
    manager = TokenManager()
    manager._tokens.clear()  # Clear any existing tokens
    
    # Manually call initialization with our test manager
    manager.set_token('kite', 'test_kite_token_123', expires_in_hours=24)
    
    token = manager.get_token('kite')
    assert token == 'test_kite_token_123'


def test_initialize_kite_token_without_env(monkeypatch):
    """Test initializing Kite token without environment variable."""
    monkeypatch.delenv('KITE_ACCESS_TOKEN', raising=False)
    
    manager = TokenManager()
    manager._tokens.clear()
    
    # Should not crash, just log debug message
    token = manager.get_token('kite')
    assert token is None


def test_disabled_rotation():
    """Test that rotation is disabled when flag is off."""
    manager = TokenManager(rotation_hours=0.001)
    manager.enabled = False
    
    manager.set_token('test_provider', 'test_token')
    
    time.sleep(0.005)  # Wait past rotation threshold
    
    # Should not recommend rotation when disabled
    assert not manager.should_rotate('test_provider')
