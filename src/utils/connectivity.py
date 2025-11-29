"""Network connectivity monitoring and recovery utilities.

Provides lightweight connection health checks and recovery mechanisms to handle
internet connectivity loss and restoration during collection cycles.

Design Goals:
- Fast connectivity check (< 1s) to avoid blocking cycles
- Automatic retry with backoff for transient network issues
- Clear logging for debugging connection problems
- Minimal external dependencies

Environment Variables:
    G6_CONNECTIVITY_CHECK_ENABLED: Enable pre-cycle connectivity check (default: True)
    G6_CONNECTIVITY_CHECK_TIMEOUT: Timeout for connectivity check in seconds (default: 3)
    G6_CONNECTIVITY_CHECK_HOSTS: Comma-separated hosts to check (default: 8.8.8.8,1.1.1.1)
    G6_CONNECTIVITY_MAX_RETRIES: Max retries for failed connections (default: 3)
    G6_CONNECTIVITY_RETRY_DELAY: Delay between retries in seconds (default: 2)
"""
from __future__ import annotations

import logging
import socket
import time
from typing import Any

from src.config.env_config import EnvConfig

logger = logging.getLogger(__name__)

__all__ = [
    "check_internet_connectivity",
    "wait_for_connectivity",
    "is_connectivity_check_enabled",
]


def is_connectivity_check_enabled() -> bool:
    """Check if connectivity checking is enabled via environment."""
    return EnvConfig.get_bool('G6_CONNECTIVITY_CHECK_ENABLED', True)


def check_internet_connectivity(*, timeout: float | None = None, hosts: list[str] | None = None) -> bool:
    """Check if internet connectivity is available.

    Args:
        timeout: Connection timeout in seconds (default from env or 3s)
        hosts: List of hosts to check (default from env or ['8.8.8.8', '1.1.1.1'])

    Returns:
        True if connectivity is available, False otherwise
    """
    if timeout is None:
        timeout = float(EnvConfig.get_int('G6_CONNECTIVITY_CHECK_TIMEOUT', 3))
    
    if hosts is None:
        hosts_str = EnvConfig.get_str('G6_CONNECTIVITY_CHECK_HOSTS', '8.8.8.8,1.1.1.1')
        hosts = [h.strip() for h in hosts_str.split(',') if h.strip()]
    
    if not hosts:
        logger.warning("No connectivity check hosts configured, assuming connectivity available")
        return True
    
    # Try each host; if any succeeds, connectivity is available
    for host in hosts:
        try:
            # Use socket to check if we can reach the host on port 53 (DNS)
            # This is faster than HTTP and works with minimal dependencies
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, 53))
            sock.close()
            
            if result == 0:
                logger.debug("Connectivity check passed (host=%s)", host)
                return True
        except (socket.timeout, socket.error, OSError) as e:
            logger.debug("Connectivity check failed for host %s: %s", host, e)
            continue
        except Exception as e:
            logger.debug("Unexpected error checking connectivity to %s: %s", host, e)
            continue
    
    logger.warning("Connectivity check failed for all hosts: %s", hosts)
    return False


def wait_for_connectivity(
    *,
    max_retries: int | None = None,
    retry_delay: float | None = None,
    timeout_per_check: float | None = None,
) -> bool:
    """Wait for internet connectivity to be restored with retries.

    Args:
        max_retries: Maximum number of retry attempts (default from env or 3)
        retry_delay: Delay between retries in seconds (default from env or 2)
        timeout_per_check: Timeout for each connectivity check (default from env or 3)

    Returns:
        True if connectivity was restored, False if max retries exceeded
    """
    if max_retries is None:
        max_retries = EnvConfig.get_int('G6_CONNECTIVITY_MAX_RETRIES', 3)
    
    if retry_delay is None:
        retry_delay = float(EnvConfig.get_int('G6_CONNECTIVITY_RETRY_DELAY', 2))
    
    logger.info("Waiting for internet connectivity to be restored (max_retries=%d, retry_delay=%.1fs)", 
                max_retries, retry_delay)
    
    for attempt in range(max_retries):
        if check_internet_connectivity(timeout=timeout_per_check):
            logger.info("Internet connectivity restored after %d attempts", attempt + 1)
            return True
        
        if attempt < max_retries - 1:
            logger.warning(
                "Connectivity check failed (attempt %d/%d), retrying in %.1fs",
                attempt + 1,
                max_retries,
                retry_delay
            )
            time.sleep(retry_delay)
    
    logger.error("Failed to restore internet connectivity after %d attempts", max_retries)
    return False


def get_connectivity_status() -> dict[str, Any]:
    """Get current connectivity status as a dict for health checks.

    Returns:
        Dict with status, message, and check_enabled fields
    """
    if not is_connectivity_check_enabled():
        return {
            'status': 'disabled',
            'message': 'Connectivity checking is disabled',
            'check_enabled': False,
        }
    
    try:
        is_connected = check_internet_connectivity()
        return {
            'status': 'connected' if is_connected else 'disconnected',
            'message': 'Internet connectivity available' if is_connected else 'No internet connectivity',
            'check_enabled': True,
        }
    except Exception as e:
        logger.error("Error checking connectivity status: %s", e)
        return {
            'status': 'error',
            'message': f'Connectivity check error: {e}',
            'check_enabled': True,
        }
