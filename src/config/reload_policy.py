"""Environment variable reload behavior policies.

Defines which G6_ variables can be changed at runtime and which require
application restart. Part of Phase 2.2c: Hot-Reload Controls (2025-11-16).

Usage:
    from src.config.reload_policy import ReloadPolicy
    
    # Check if variable requires restart
    if ReloadPolicy.is_startup_only('G6_METRICS_PORT'):
        logger.warning("G6_METRICS_PORT requires restart to take effect")
    
    # Get reload behavior
    behavior = ReloadPolicy.get_reload_behavior('G6_ADAPTIVE_CONTROLLER')
    # Returns: 'hot-reload', 'runtime', or 'startup-only'
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import ClassVar

logger = logging.getLogger(__name__)


class ReloadBehavior(Enum):
    """Reload behavior categories for environment variables."""
    
    STARTUP_ONLY = "startup-only"  # Requires restart
    RUNTIME = "runtime"  # Takes effect next cycle
    HOT_RELOAD = "hot-reload"  # Immediate effect via API


class ReloadPolicy:
    """Defines reload behavior for G6_ environment variables.
    
    Categories:
    - STARTUP_ONLY: Must be set before startup, cannot change at runtime
      Examples: ports, paths, API credentials
    
    - RUNTIME: Can be changed and takes effect on next collection cycle
      Examples: feature flags, thresholds, intervals
    
    - HOT_RELOAD: Can be changed via HTTP API, immediate effect
      Examples: adaptive controller settings, alert configurations
    """
    
    # Variables that MUST be set at startup and cannot change
    STARTUP_ONLY_VARS: ClassVar[set[str]] = {
        # Infrastructure & Ports
        'G6_METRICS_PORT',
        'G6_GRAFANA_PORT',
        'G6_CATALOG_HTTP_PORT',
        
        # Storage Paths
        'G6_CSV_BASE_DIR',
        'G6_DATA_DIR',
        'G6_ANALYTICS_DIR',
        'G6_CONFIG_PATH',
        'G6_LOG_FILE',
        
        # API Credentials
        'KITE_API_KEY',
        'KITE_API_SECRET',
        'KITE_ACCESS_TOKEN',
        
        # System Configuration
        'G6_LOG_LEVEL',  # Logger configured at startup
        'G6_COLLECTION_INTERVAL',  # Core timing
        'G6_CYCLE_INTERVAL',  # Core timing
        'G6_WEB_WORKERS',  # Process count
        
        # Architectural Settings
        'G6_USE_CSVIO_FACADE',  # Thread architecture
        'G6_CSVIO_BACKEND',  # Backend selection
        'G6_CSVIO_WRITER_THREAD',  # Threading model
        
        # Development & Debug
        'G6_DEBUG',  # Affects initialization
        'G6_FORCE_MARKET_OPEN',  # Market hours override
        'G6_STARTUP_EXPIRY_TRACE',  # Startup tracing
        'G6_STARTUP_LEGACY_PLACEHOLDERS',  # Startup behavior
    }
    
    # Variables that support hot-reload via HTTP API
    HOT_RELOAD_VARS: ClassVar[set[str]] = {
        # Adaptive Controller (via /adaptive/theme endpoint)
        'G6_ADAPTIVE_CONTROLLER',
        'G6_ADAPTIVE_MIN_DETAIL_MODE',
        'G6_ADAPTIVE_MAX_DETAIL_MODE',
        'G6_ADAPTIVE_PROMOTE_COOLDOWN',
        'G6_ADAPTIVE_DEMOTE_COOLDOWN',
        'G6_ADAPTIVE_MEMORY_TIER',
        'G6_ADAPTIVE_STRIKE_SCALING',
        'G6_ADAPTIVE_STRIKE_MIN',
        'G6_ADAPTIVE_STRIKE_MAX_ITM',
        'G6_ADAPTIVE_STRIKE_MAX_OTM',
        'G6_ADAPTIVE_STRIKE_STEP',
        'G6_ADAPTIVE_STRIKE_BREACH_THRESHOLD',
        'G6_ADAPTIVE_STRIKE_REDUCTION',
        
        # Alert Severity (via catalog HTTP)
        'G6_ADAPTIVE_ALERT_SEVERITY',
        'G6_ADAPTIVE_SEVERITY_TREND_WINDOW',
        'G6_ADAPTIVE_SEVERITY_TREND_SMOOTH',
        'G6_ADAPTIVE_SEVERITY_TREND_CRITICAL_RATIO',
        'G6_ADAPTIVE_SEVERITY_TREND_WARN_RATIO',
        'G6_ADAPTIVE_ALERT_COLOR_CRITICAL',
        'G6_ADAPTIVE_ALERT_COLOR_WARN',
        'G6_ADAPTIVE_ALERT_COLOR_INFO',
        
        # Memory Tier (runtime adjustable)
        'G6_MEMORY_TIER',
        'G6_MEMORY_TIER_OVERRIDE',
        'G6_MEMORY_TIER_TTL_MS',
        'G6_MEMORY_TIER_TTL_SEC',
        'G6_ADAPTIVE_THEME_TTL_MS',
        'G6_ADAPTIVE_THEME_TTL_SEC',
    }
    
    # All other variables are RUNTIME (take effect next cycle)
    # Examples: feature flags, thresholds, data quality settings
    
    @classmethod
    def get_reload_behavior(cls, var: str) -> ReloadBehavior:
        """Get reload behavior for a variable.
        
        Args:
            var: Variable name (e.g., 'G6_METRICS_PORT')
            
        Returns:
            ReloadBehavior enum value
        """
        if var in cls.STARTUP_ONLY_VARS:
            return ReloadBehavior.STARTUP_ONLY
        elif var in cls.HOT_RELOAD_VARS:
            return ReloadBehavior.HOT_RELOAD
        else:
            return ReloadBehavior.RUNTIME
    
    @classmethod
    def is_startup_only(cls, var: str) -> bool:
        """Check if variable requires restart to take effect.
        
        Args:
            var: Variable name
            
        Returns:
            True if variable is startup-only
        """
        return var in cls.STARTUP_ONLY_VARS
    
    @classmethod
    def is_hot_reload(cls, var: str) -> bool:
        """Check if variable supports hot-reload.
        
        Args:
            var: Variable name
            
        Returns:
            True if variable supports hot-reload
        """
        return var in cls.HOT_RELOAD_VARS
    
    @classmethod
    def is_runtime(cls, var: str) -> bool:
        """Check if variable takes effect on next cycle.
        
        Args:
            var: Variable name
            
        Returns:
            True if variable is runtime-reload
        """
        return not cls.is_startup_only(var) and not cls.is_hot_reload(var)
    
    @classmethod
    def warn_if_startup_only(cls, var: str, old_value: str | None, new_value: str) -> bool:
        """Warn if attempting to change startup-only variable at runtime.
        
        Args:
            var: Variable name
            old_value: Previous value (None if never set)
            new_value: New value
            
        Returns:
            True if warning was issued
        """
        if not cls.is_startup_only(var):
            return False
        
        if old_value is None:
            # First time setting - OK
            return False
        
        if old_value == new_value:
            # No change - OK
            return False
        
        # Changed at runtime - issue warning
        logger.warning(
            "Variable %s changed at runtime but requires restart to take effect. "
            "Old: %s, New: %s. Please restart the application.",
            var, old_value, new_value
        )
        return True
    
    @classmethod
    def get_reload_endpoint(cls, var: str) -> str | None:
        """Get HTTP endpoint for hot-reload variables.
        
        Args:
            var: Variable name
            
        Returns:
            Endpoint path or None if not hot-reloadable
        """
        if not cls.is_hot_reload(var):
            return None
        
        # Adaptive controller variables
        if var.startswith('G6_ADAPTIVE_'):
            return '/adaptive/theme'
        
        # Memory tier variables
        if 'MEMORY_TIER' in var:
            return '/adaptive/theme'
        
        return None
    
    @classmethod
    def categorize_all(cls) -> dict[str, list[str]]:
        """Categorize all variables by reload behavior.
        
        Returns:
            Dictionary with categories: startup_only, hot_reload, runtime
        """
        import os
        
        startup = []
        hot_reload = []
        runtime = []
        
        for key in os.environ:
            if not key.startswith('G6_'):
                continue
            
            behavior = cls.get_reload_behavior(key)
            if behavior == ReloadBehavior.STARTUP_ONLY:
                startup.append(key)
            elif behavior == ReloadBehavior.HOT_RELOAD:
                hot_reload.append(key)
            else:
                runtime.append(key)
        
        return {
            'startup_only': sorted(startup),
            'hot_reload': sorted(hot_reload),
            'runtime': sorted(runtime),
        }
    
    @classmethod
    def document_variable(cls, var: str) -> dict[str, str]:
        """Get documentation for a variable's reload behavior.
        
        Args:
            var: Variable name
            
        Returns:
            Dictionary with behavior, description, and endpoint (if applicable)
        """
        behavior = cls.get_reload_behavior(var)
        endpoint = cls.get_reload_endpoint(var)
        
        descriptions = {
            ReloadBehavior.STARTUP_ONLY: "Requires application restart to take effect",
            ReloadBehavior.RUNTIME: "Takes effect on next collection cycle",
            ReloadBehavior.HOT_RELOAD: "Immediate effect via HTTP API",
        }
        
        result = {
            'behavior': behavior.value,
            'description': descriptions[behavior],
        }
        
        if endpoint:
            result['endpoint'] = endpoint
        
        return result


__all__ = ['ReloadPolicy', 'ReloadBehavior']
