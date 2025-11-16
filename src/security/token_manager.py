"""Secure token manager with rotation and expiry tracking.

Part of Phase 3.3: Security Hardening (2025-11-16)

Provides secure management of API tokens with features:
- Token expiry tracking
- Automatic rotation support
- Secure storage (memory-only, no disk)
- Audit logging of token operations
- Integration with Kite Connect

Environment Variables:
    G6_TOKEN_ROTATION_HOURS: Hours between rotations (default: 24)
    G6_TOKEN_EXPIRY_WARN_HOURS: Warn when expiry within hours (default: 2)
    G6_ENABLE_TOKEN_ROTATION: Enable automatic rotation (default: 0)

Usage:
    from src.security.token_manager import get_token_manager
    
    manager = get_token_manager()
    
    # Store token
    manager.set_token('kite', token, expires_in_hours=24)
    
    # Get token (warns if expiring soon)
    token = manager.get_token('kite')
    
    # Check if rotation needed
    if manager.should_rotate('kite'):
        new_token = fetch_new_token()
        manager.set_token('kite', new_token, expires_in_hours=24)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from src.config.env_config import EnvConfig

logger = logging.getLogger(__name__)


@dataclass
class TokenInfo:
    """Information about a managed token."""
    token: str
    provider: str
    created_at: float
    expires_at: float | None
    last_rotated: float
    rotation_count: int


class TokenManager:
    """Manages API tokens with rotation and expiry tracking.
    
    Tokens are stored in memory only (never persisted to disk).
    Provides hooks for automatic rotation and expiry warnings.
    """
    
    def __init__(
        self,
        rotation_hours: int | None = None,
        expiry_warn_hours: int | None = None,
    ):
        """Initialize token manager.
        
        Args:
            rotation_hours: Hours between automatic rotations
            expiry_warn_hours: Warn when token expires within this many hours
        """
        self.rotation_hours = rotation_hours or EnvConfig.get_int('G6_TOKEN_ROTATION_HOURS', 24)
        self.expiry_warn_hours = expiry_warn_hours or EnvConfig.get_int('G6_TOKEN_EXPIRY_WARN_HOURS', 2)
        self.enabled = EnvConfig.get_bool('G6_ENABLE_TOKEN_ROTATION', False)
        
        self._tokens: dict[str, TokenInfo] = {}
        self._rotation_callbacks: dict[str, Callable[[str], str]] = {}
    
    def set_token(
        self,
        provider: str,
        token: str,
        expires_in_hours: int | None = None
    ) -> None:
        """Store a token for a provider.
        
        Args:
            provider: Provider name (e.g., 'kite', 'zerodha')
            token: Token value
            expires_in_hours: Token expiry time in hours (None = never expires)
        """
        now = time.time()
        expires_at = now + (expires_in_hours * 3600) if expires_in_hours is not None and expires_in_hours > 0 else None
        
        # Check if this is a rotation
        is_rotation = provider in self._tokens
        old_info = self._tokens.get(provider)
        
        self._tokens[provider] = TokenInfo(
            token=token,
            provider=provider,
            created_at=now,
            expires_at=expires_at,
            last_rotated=now,
            rotation_count=(old_info.rotation_count + 1) if old_info else 0
        )
        
        if is_rotation:
            rotation_count = self._tokens[provider].rotation_count
            logger.info(
                "Token rotated for provider: %s (rotation #%d)",
                provider,
                rotation_count,
                extra={'provider': provider, 'rotation_count': rotation_count}
            )
        else:
            logger.info(
                "Token stored for provider: %s (expires: %s)",
                provider,
                'never' if expires_at is None else datetime.fromtimestamp(expires_at).isoformat(),
                extra={'provider': provider}
            )
    
    def get_token(self, provider: str) -> str | None:
        """Get token for a provider.
        
        Logs warnings if token is expiring soon or expired.
        
        Args:
            provider: Provider name
            
        Returns:
            Token string or None if not found/expired
        """
        info = self._tokens.get(provider)
        if info is None:
            logger.warning("No token found for provider: %s", provider)
            return None
        
        now = time.time()
        
        # Check if expired
        if info.expires_at and now >= info.expires_at:
            logger.error(
                "Token expired for provider: %s (expired %s ago)",
                provider,
                timedelta(seconds=int(now - info.expires_at)),
                extra={'provider': provider}
            )
            return None
        
        # Check if expiring soon
        if info.expires_at:
            time_until_expiry = info.expires_at - now
            warn_threshold = self.expiry_warn_hours * 3600
            
            if time_until_expiry < warn_threshold:
                logger.warning(
                    "Token expiring soon for provider: %s (expires in %s)",
                    provider,
                    timedelta(seconds=int(time_until_expiry)),
                    extra={'provider': provider, 'expires_in_seconds': int(time_until_expiry)}
                )
        
        return info.token
    
    def should_rotate(self, provider: str) -> bool:
        """Check if token should be rotated.
        
        Args:
            provider: Provider name
            
        Returns:
            True if rotation is recommended
        """
        if not self.enabled:
            return False
        
        info = self._tokens.get(provider)
        if info is None:
            return False
        
        now = time.time()
        time_since_rotation = now - info.last_rotated
        rotation_threshold = self.rotation_hours * 3600
        
        return time_since_rotation >= rotation_threshold
    
    def register_rotation_callback(
        self,
        provider: str,
        callback: Callable[[str], str]
    ) -> None:
        """Register a callback to automatically rotate tokens.
        
        Args:
            provider: Provider name
            callback: Function that takes old token and returns new token
        """
        self._rotation_callbacks[provider] = callback
        logger.info("Registered rotation callback for provider: %s", provider)
    
    def rotate_token(self, provider: str) -> bool:
        """Rotate token for a provider using registered callback.
        
        Args:
            provider: Provider name
            
        Returns:
            True if rotation succeeded, False otherwise
        """
        callback = self._rotation_callbacks.get(provider)
        if callback is None:
            logger.error("No rotation callback registered for provider: %s", provider)
            return False
        
        old_info = self._tokens.get(provider)
        if old_info is None:
            logger.error("No token to rotate for provider: %s", provider)
            return False
        
        try:
            logger.info("Rotating token for provider: %s", provider)
            new_token = callback(old_info.token)
            
            # Calculate new expiry based on old token's expiry
            if old_info.expires_at:
                original_duration = old_info.expires_at - old_info.created_at
                expires_in_hours = int(original_duration / 3600)
            else:
                expires_in_hours = None
            
            self.set_token(provider, new_token, expires_in_hours)
            return True
            
        except Exception as e:
            logger.error(
                "Token rotation failed for provider: %s - %s",
                provider,
                str(e),
                exc_info=True,
                extra={'provider': provider}
            )
            return False
    
    def get_token_info(self, provider: str) -> dict | None:
        """Get token information (without exposing token value).
        
        Args:
            provider: Provider name
            
        Returns:
            Dictionary with token metadata (excludes actual token)
        """
        info = self._tokens.get(provider)
        if info is None:
            return None
        
        now = time.time()
        
        return {
            'provider': info.provider,
            'created_at': datetime.fromtimestamp(info.created_at).isoformat(),
            'expires_at': datetime.fromtimestamp(info.expires_at).isoformat() if info.expires_at else None,
            'last_rotated': datetime.fromtimestamp(info.last_rotated).isoformat(),
            'rotation_count': info.rotation_count,
            'age_hours': (now - info.created_at) / 3600,
            'expires_in_hours': (info.expires_at - now) / 3600 if info.expires_at else None,
            'is_expired': info.expires_at and now >= info.expires_at,
            'should_rotate': self.should_rotate(provider),
        }
    
    def remove_token(self, provider: str) -> bool:
        """Remove token for a provider.
        
        Args:
            provider: Provider name
            
        Returns:
            True if token was removed, False if not found
        """
        if provider in self._tokens:
            del self._tokens[provider]
            logger.info("Token removed for provider: %s", provider, extra={'provider': provider})
            return True
        return False
    
    def list_providers(self) -> list[str]:
        """List all providers with stored tokens.
        
        Returns:
            List of provider names
        """
        return list(self._tokens.keys())
    
    def clear_all(self) -> None:
        """Clear all stored tokens (use with caution)."""
        count = len(self._tokens)
        self._tokens.clear()
        logger.warning("Cleared all tokens (%d providers)", count)


# Global singleton
_manager: TokenManager | None = None


def get_token_manager() -> TokenManager:
    """Get global token manager instance.
    
    Returns:
        Global TokenManager instance
    """
    global _manager
    if _manager is None:
        _manager = TokenManager()
    return _manager


def initialize_kite_token() -> None:
    """Initialize Kite Connect token from environment (if available).
    
    This is a convenience function for application startup.
    """
    manager = get_token_manager()
    
    kite_token = EnvConfig.get_str('KITE_ACCESS_TOKEN', '')
    if kite_token:
        # Kite tokens typically last 24 hours
        manager.set_token('kite', kite_token, expires_in_hours=24)
        logger.info("Kite token initialized from environment")
    else:
        logger.debug("No KITE_ACCESS_TOKEN in environment")


__all__ = [
    'TokenManager',
    'TokenInfo',
    'get_token_manager',
    'initialize_kite_token',
]
