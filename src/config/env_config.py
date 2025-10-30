"""Centralized environment variable access with validation and type coercion.

This module provides a single source of truth for all environment variable access
in the G6 Platform. It ensures consistent parsing, validation, and default handling.

Usage:
    from src.config.env_config import EnvConfig
    
    # Integer values
    interval = EnvConfig.get_int('G6_COLLECTION_INTERVAL', 60)
    
    # Boolean values
    enabled = EnvConfig.get_bool('G6_METRICS_ENABLED', True)
    
    # String values
    log_level = EnvConfig.get_str('G6_LOG_LEVEL', 'INFO')
    
    # Float values
    threshold = EnvConfig.get_float('G6_THRESHOLD', 0.95)
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class EnvConfig:
    """Centralized environment variable access with validation."""
    
    # Cache for parsed values to avoid repeated parsing
    _cache: dict[str, Any] = {}
    
    @classmethod
    def clear_cache(cls) -> None:
        """Clear the cache (useful for testing)."""
        cls._cache.clear()
    
    @classmethod
    def get_int(cls, key: str, default: int) -> int:
        """Get integer environment variable with validation.
        
        Args:
            key: Environment variable name
            default: Default value if not set or invalid
            
        Returns:
            Integer value or default
            
        Example:
            interval = EnvConfig.get_int('G6_COLLECTION_INTERVAL', 60)
        """
        cache_key = f"{key}:int:{default}"
        if cache_key in cls._cache:
            return cls._cache[cache_key]
        
        value_str = os.environ.get(key, str(default))
        try:
            # Handle empty string case
            if not value_str or value_str.strip() == '':
                result = default
            else:
                result = int(value_str)
            cls._cache[cache_key] = result
            return result
        except (ValueError, TypeError) as e:
            logger.warning(
                "Invalid integer value for %s='%s', using default=%s. Error: %s", key, value_str, default, e
            )
            cls._cache[cache_key] = default
            return default
    
    @classmethod
    def get_bool(cls, key: str, default: bool = False) -> bool:
        """Get boolean environment variable with consistent parsing.
        
        Truthy values: '1', 'true', 'yes', 'on' (case-insensitive)
        Falsy values: '0', 'false', 'no', 'off', empty string
        
        Args:
            key: Environment variable name
            default: Default value if not set
            
        Returns:
            Boolean value or default
            
        Example:
            enabled = EnvConfig.get_bool('G6_METRICS_ENABLED', True)
        """
        cache_key = f"{key}:bool:{default}"
        if cache_key in cls._cache:
            return cls._cache[cache_key]
        
        value_str = os.environ.get(key, '')
        if not value_str:
            cls._cache[cache_key] = default
            return default
        
        result = value_str.lower() in ('1', 'true', 'yes', 'on')
        cls._cache[cache_key] = result
        return result
    
    @classmethod
    def get_str(cls, key: str, default: str = '') -> str:
        """Get string environment variable.
        
        Args:
            key: Environment variable name
            default: Default value if not set
            
        Returns:
            String value or default
            
        Example:
            log_level = EnvConfig.get_str('G6_LOG_LEVEL', 'INFO')
        """
        cache_key = f"{key}:str:{default}"
        if cache_key in cls._cache:
            return cls._cache[cache_key]
        
        result = os.environ.get(key, default)
        cls._cache[cache_key] = result
        return result
    
    @classmethod
    def get_float(cls, key: str, default: float) -> float:
        """Get float environment variable with validation.
        
        Args:
            key: Environment variable name
            default: Default value if not set or invalid
            
        Returns:
            Float value or default
            
        Example:
            threshold = EnvConfig.get_float('G6_SUCCESS_THRESHOLD', 0.95)
        """
        cache_key = f"{key}:float:{default}"
        if cache_key in cls._cache:
            return cls._cache[cache_key]
        
        value_str = os.environ.get(key, str(default))
        try:
            # Handle empty string case
            if not value_str or value_str.strip() == '':
                result = default
            else:
                result = float(value_str)
            cls._cache[cache_key] = result
            return result
        except (ValueError, TypeError) as e:
            logger.warning(
                "Invalid float value for %s='%s', using default=%s. Error: %s", key, value_str, default, e
            )
            cls._cache[cache_key] = default
            return default
    
    @classmethod
    def get_list(cls, key: str, default: list[str] | None = None, separator: str = ',') -> list[str]:
        """Get list of strings from environment variable (comma-separated by default).
        
        Args:
            key: Environment variable name
            default: Default list if not set
            separator: String separator (default: comma)
            
        Returns:
            List of strings or default
            
        Example:
            indices = EnvConfig.get_list('G6_INDICES', ['NIFTY', 'BANKNIFTY'])
        """
        if default is None:
            default = []
        
        cache_key = f"{key}:list:{separator}:{','.join(default)}"
        if cache_key in cls._cache:
            return cls._cache[cache_key]
        
        value_str = os.environ.get(key, '')
        if not value_str or value_str.strip() == '':
            cls._cache[cache_key] = default
            return default
        
        # Split and strip whitespace
        result = [item.strip() for item in value_str.split(separator) if item.strip()]
        cls._cache[cache_key] = result
        return result
    
    @classmethod
    def get_path(cls, key: str, default: str = '') -> str:
        """Get filesystem path from environment variable.
        
        Normalizes path separators for current OS.
        
        Args:
            key: Environment variable name
            default: Default path if not set
            
        Returns:
            Normalized path string or default
            
        Example:
            data_dir = EnvConfig.get_path('G6_DATA_DIR', 'data/g6_data')
        """
        cache_key = f"{key}:path:{default}"
        if cache_key in cls._cache:
            return cls._cache[cache_key]
        
        path_str = os.environ.get(key, default)
        # Normalize path separators
        result = os.path.normpath(path_str) if path_str else default
        cls._cache[cache_key] = result
        return result
    
    @classmethod
    def is_set(cls, key: str) -> bool:
        """Check if environment variable is set (non-empty).
        
        Args:
            key: Environment variable name
            
        Returns:
            True if variable is set and non-empty
            
        Example:
            if EnvConfig.is_set('G6_DEBUG'):
                print("Debug mode enabled")
        """
        value = os.environ.get(key, '')
        return bool(value and value.strip())
    
    @classmethod
    def require(cls, key: str) -> str:
        """Get required environment variable or raise error.
        
        Args:
            key: Environment variable name
            
        Returns:
            String value
            
        Raises:
            RuntimeError: If variable is not set
            
        Example:
            api_key = EnvConfig.require('KITE_API_KEY')
        """
        value = os.environ.get(key)
        if value is None or value.strip() == '':
            raise RuntimeError(f"Required environment variable not set: {key}")
        return value
    
    @classmethod
    def get_all(cls, prefix: str = 'G6_') -> dict[str, str]:
        """Get all environment variables with given prefix.
        
        Args:
            prefix: Variable name prefix (default: 'G6_')
            
        Returns:
            Dictionary of matching variables
            
        Example:
            g6_vars = EnvConfig.get_all('G6_')
        """
        return {k: v for k, v in os.environ.items() if k.startswith(prefix)}


# Convenience functions for common patterns
def get_collection_interval() -> int:
    """Get collection interval in seconds (default: 60)."""
    return EnvConfig.get_int('G6_COLLECTION_INTERVAL', 60)


def get_metrics_port() -> int:
    """Get metrics server port (default: 9108)."""
    return EnvConfig.get_int('G6_METRICS_PORT', 9108)


def is_metrics_enabled() -> bool:
    """Check if Prometheus metrics are enabled (default: True)."""
    return EnvConfig.get_bool('G6_METRICS_ENABLED', True)


def is_debug_mode() -> bool:
    """Check if debug mode is enabled (default: False)."""
    return EnvConfig.get_bool('G6_DEBUG', False)


def get_log_level() -> str:
    """Get log level (default: INFO)."""
    return EnvConfig.get_str('G6_LOG_LEVEL', 'INFO').upper()


def get_data_dir() -> str:
    """Get base data directory (default: data)."""
    return EnvConfig.get_path('G6_DATA_DIR', 'data')


__all__ = [
    'EnvConfig',
    'get_collection_interval',
    'get_metrics_port',
    'is_metrics_enabled',
    'is_debug_mode',
    'get_log_level',
    'get_data_dir',
]
