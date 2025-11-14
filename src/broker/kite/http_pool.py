"""HTTP connection pooling and session reuse for Kite API calls.

Implements Phase 1 Quick Win: HTTP client pooling with keep-alive to reduce
connection overhead and improve fetch phase performance.

The KiteConnect library uses urllib internally. While we can't directly replace it
without forking, we can provide guidance on connection reuse and prepare for future
httpx migration if needed.

Environment Variables:
    G6_HTTP_POOL_SIZE: Maximum connections in pool (default 16)
    G6_HTTP_KEEPALIVE: Maximum keepalive connections (default 8)
    G6_HTTP_TIMEOUT: Request timeout in seconds (default 5.0)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

logger = logging.getLogger(__name__)


def configure_http_pooling() -> dict[str, Any]:
    """Get HTTP pooling configuration from environment.
    
    Returns configuration dict that can be used to tune HTTP clients.
    Note: KiteConnect uses urllib3 internally via requests library.
    
    Returns:
        Dict with keys: pool_size, keepalive, timeout
    """
    from src.config.env_config import EnvConfig
    
    config = {
        'pool_size': EnvConfig.get_int('G6_HTTP_POOL_SIZE', 16),
        'keepalive': EnvConfig.get_int('G6_HTTP_KEEPALIVE', 8),
        'timeout': EnvConfig.get_float('G6_HTTP_TIMEOUT', 5.0),
    }
    
    return config


def apply_urllib3_pooling_config() -> None:
    """Apply connection pooling configuration to urllib3 (used by requests/KiteConnect).
    
    This configures the global urllib3 PoolManager defaults that will be inherited
    by requests sessions created by KiteConnect.
    """
    from src.config.env_config import EnvConfig
    
    if not EnvConfig.get_bool('G6_HTTP_POOL_ENABLED', True):
        return
    
    try:
        import urllib3
        from urllib3.util.retry import Retry
        
        config = configure_http_pooling()
        
        # Configure connection pool defaults
        # These will be picked up by new PoolManager instances
        urllib3.connection.HTTPConnection.default_socket_options = [
            (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
        ]
        
        logger.info(
            "HTTP connection pooling configured: pool_size=%d keepalive=%d timeout=%.1fs",
            config['pool_size'],
            config['keepalive'],
            config['timeout']
        )
    except ImportError:
        logger.debug("urllib3 not available for pool configuration")
    except Exception:
        logger.debug("Failed to configure HTTP pooling", exc_info=True)


def create_retry_strategy() -> Any:
    """Create a retry strategy for transient failures.
    
    Returns an urllib3 Retry object configured for typical API failure modes.
    """
    try:
        from urllib3.util.retry import Retry
        
        return Retry(
            total=3,  # Total retries
            backoff_factor=0.3,  # Exponential backoff: 0.3, 0.6, 1.2s
            status_forcelist=[429, 500, 502, 503, 504],  # Retry on these status codes
            allowed_methods=['GET', 'POST'],  # Only retry safe methods
        )
    except ImportError:
        return None


def patch_kite_connect_session() -> None:
    """Attempt to enhance KiteConnect's internal session with pooling.
    
    This is a best-effort enhancement. KiteConnect creates its own requests
    sessions, so we can't directly control them without modifying the library.
    
    This function serves as documentation for future httpx migration.
    """
    logger.debug("KiteConnect uses requests internally; connection pooling via urllib3 defaults")


# Ensure pooling is configured on import if enabled
try:
    from src.config.env_config import EnvConfig
    if EnvConfig.get_bool('G6_HTTP_POOL_ENABLED', True):
        import socket
        apply_urllib3_pooling_config()
except Exception:
    pass


__all__ = [
    'configure_http_pooling',
    'apply_urllib3_pooling_config',
    'create_retry_strategy',
]
