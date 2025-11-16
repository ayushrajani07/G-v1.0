"""Environment variable validation and typo detection.

Provides startup validation for G6_ environment variables to catch typos
and unknown configurations early.

Part of Phase 2.2b: Configuration Validation Layer (2025-11-16)
"""
from __future__ import annotations

import difflib
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class G6ConfigValidator:
    """Validates G6_ environment variables at startup.
    
    Provides:
    - Detection of unknown variables (possible typos)
    - Suggestions for similar known variables
    - Categorization warnings for deprecated variables
    - Optional strict mode that fails on unknown variables
    """
    
    # Known G6_ variables (extracted from codebase)
    # This should be auto-generated periodically
    KNOWN_VARS: set[str] = {
        'G6_ADAPTIVE_ALERT_COLOR_CRITICAL',
        'G6_ADAPTIVE_ALERT_COLOR_INFO',
        'G6_ADAPTIVE_ALERT_COLOR_WARN',
        'G6_ADAPTIVE_ALERT_SEVERITY',
        'G6_ADAPTIVE_ALERT_SEVERITY_DECAY_CYCLES',
        'G6_ADAPTIVE_ALERT_SEVERITY_FORCE',
        'G6_ADAPTIVE_ALERT_SEVERITY_MIN_STREAK',
        'G6_ADAPTIVE_CONTROLLER',
        'G6_ADAPTIVE_DEMOTE_COOLDOWN',
        'G6_ADAPTIVE_MAX_DETAIL_MODE',
        'G6_ADAPTIVE_MEMORY_TIER',
        'G6_ADAPTIVE_MIN_DETAIL_MODE',
        'G6_ADAPTIVE_PROMOTE_COOLDOWN',
        'G6_ADAPTIVE_SEVERITY_TREND_CRITICAL_RATIO',
        'G6_ADAPTIVE_SEVERITY_TREND_SMOOTH',
        'G6_ADAPTIVE_SEVERITY_TREND_WARN_RATIO',
        'G6_ADAPTIVE_SEVERITY_TREND_WINDOW',
        'G6_ADAPTIVE_STRIKE_BREACH_THRESHOLD',
        'G6_ADAPTIVE_STRIKE_MAX_ITM',
        'G6_ADAPTIVE_STRIKE_MAX_OTM',
        'G6_ADAPTIVE_STRIKE_MIN',
        'G6_ADAPTIVE_STRIKE_REDUCTION',
        'G6_ADAPTIVE_STRIKE_SCALING',
        'G6_ADAPTIVE_STRIKE_STEP',
        'G6_ADAPTIVE_THEME_TTL_MS',
        'G6_ADAPTIVE_THEME_TTL_SEC',
        'G6_ALERTS',
        'G6_ALERT_FIELD_COV_MIN',
        'G6_ALERT_STRIKE_COV_MIN',
        'G6_ANALYTICS_DIR',
        'G6_AUTO_SNAPSHOTS',
        'G6_BENCHMARK_DUMP',
        'G6_CALENDAR_HOLIDAYS_JSON',
        'G6_CARDINALITY_MAX_SERIES',
        'G6_CATALOG_HTTP',
        'G6_CATALOG_HTTP_DISABLE',
        'G6_CATALOG_HTTP_HOTRELOAD',
        'G6_CATALOG_HTTP_PORT',
        'G6_CATALOG_TS',
        'G6_COLLECTION_INTERVAL',
        'G6_CONCISE_LOGS',
        'G6_CONFIG_PATH',
        'G6_CORS_ALL',
        'G6_CSV_BASE_DIR',
        'G6_CSV_BATCH_FLUSH',
        'G6_CSV_BUFFER_SIZE',
        'G6_CSV_JUNK_DEBUG',
        'G6_CSV_JUNK_ENABLE',
        'G6_CSV_VERBOSE',
        'G6_CSVIO_BACKEND',
        'G6_CSVIO_BATCH',
        'G6_CSVIO_FLUSH_MS',
        'G6_CSVIO_WRITER_THREAD',
        'G6_CYCLE_INTERVAL',
        'G6_DASHBOARD_CORE_REFRESH_SEC',
        'G6_DASHBOARD_DEBUG',
        'G6_DASHBOARD_SECONDARY_REFRESH_SEC',
        'G6_DATA_DIR',
        'G6_DEBUG',
        'G6_DETAIL_MODE_BAND_ATM_WINDOW',
        'G6_DISABLE_AUTOUSE_METRICS_RESET',
        'G6_DISABLE_METRIC_GROUPS',
        'G6_EGRESS_FROZEN',
        'G6_ENABLE_DATA_QUALITY',
        'G6_ENABLE_METRIC_GROUPS',
        'G6_ENABLE_OPTIONAL_TESTS',
        'G6_ENABLE_PERF_TESTS',
        'G6_ENABLE_SLOW_TESTS',
        'G6_ESTIMATE_IV',
        'G6_FORCE_MARKET_OPEN',
        'G6_GRAFANA_PORT',
        'G6_HEALTH_OVERVIEW_MAX_AGE_SEC',
        'G6_LIVE_API_MAX_CONCURRENCY',
        'G6_LOG_FILE',
        'G6_LOG_LEVEL',
        'G6_LOOP_MAX_CYCLES',
        'G6_MAX_CYCLES',
        'G6_MEMORY_LEVEL1_MB',
        'G6_MEMORY_LEVEL2_MB',
        'G6_MEMORY_LEVEL3_MB',
        'G6_MEMORY_TIER',
        'G6_MEMORY_TIER_OVERRIDE',
        'G6_MEMORY_TIER_TTL_MS',
        'G6_MEMORY_TIER_TTL_SEC',
        'G6_METRICS_ENABLED',
        'G6_METRICS_ENDPOINT',
        'G6_METRICS_PORT',
        'G6_OVERVIEW_INTERVAL_SECONDS',
        'G6_PANEL_DIFF_FULL_INTERVAL',
        'G6_PANEL_DIFF_MAX_KEYS',
        'G6_PANEL_DIFF_NEST_DEPTH',
        'G6_PANEL_DIFFS',
        'G6_PROJECT_ROOT',
        'G6_PYTEST_CURRENT_TEST',
        'G6_RIBBON_ABS_FLOOR',
        'G6_STARTUP_EXPIRY_TRACE',
        'G6_STARTUP_LEGACY_PLACEHOLDERS',
        'G6_SUPPRESS_LEGACY_WARNINGS',
        'G6_USE_CSVIO_FACADE',
        'G6_WEB_WORKERS',
        'PYTEST_CURRENT_TEST',
    }
    
    # Deprecated variables (removed or scheduled for removal)
    DEPRECATED_VARS: dict[str, str] = {
        'G6_ENABLE_LEGACY_LOOP': 'REMOVED 2025-09-28 - Use orchestrator directly',
        'G6_SUPPRESS_LEGACY_LOOP_WARN': 'REMOVED 2025-09-28',
        'G6_SUMMARY_REWRITE': 'REMOVED 2025-10-03 - New summary always active',
        'G6_SUMMARY_PLAIN_DIFF': 'REMOVED 2025-10-03',
        'G6_SSE_ENABLED': 'Deprecated - SSE always enabled',
    }
    
    @classmethod
    def validate_startup(cls, *, strict: bool = False, warn_only: bool = True) -> list[str]:
        """Validate all G6_ environment variables at startup.
        
        Args:
            strict: If True, raise RuntimeError on unknown variables
            warn_only: If True, only log warnings (default behavior)
            
        Returns:
            List of warning messages
            
        Raises:
            RuntimeError: If strict=True and unknown variables found
        """
        warnings: list[str] = []
        unknown_vars: list[str] = []
        deprecated_vars: list[tuple[str, str]] = []
        
        # Check all G6_ variables in environment
        for key in os.environ:
            if not key.startswith('G6_'):
                continue
                
            # Check if deprecated
            if key in cls.DEPRECATED_VARS:
                deprecated_vars.append((key, cls.DEPRECATED_VARS[key]))
                continue
                
            # Check if unknown
            if key not in cls.KNOWN_VARS:
                unknown_vars.append(key)
        
        # Report deprecated variables
        for var, reason in deprecated_vars:
            msg = f"Deprecated variable in use: {var} - {reason}"
            warnings.append(msg)
            logger.warning(msg)
        
        # Report unknown variables with suggestions
        for var in unknown_vars:
            suggestions = cls._suggest_similar(var)
            if suggestions:
                msg = f"Unknown G6_ variable: {var} - Did you mean: {', '.join(suggestions[:3])}?"
            else:
                msg = f"Unknown G6_ variable: {var} - No similar known variables found"
            
            warnings.append(msg)
            if warn_only:
                logger.warning(msg)
            else:
                logger.error(msg)
        
        # Strict mode enforcement
        if strict and (unknown_vars or deprecated_vars):
            error_msg = f"Configuration validation failed: {len(unknown_vars)} unknown, {len(deprecated_vars)} deprecated"
            raise RuntimeError(error_msg)
        
        # Summary
        if warnings:
            logger.info(
                "Configuration validation: %d warnings (%d unknown, %d deprecated)",
                len(warnings),
                len(unknown_vars),
                len(deprecated_vars)
            )
        else:
            logger.debug("Configuration validation: All G6_ variables are known")
        
        return warnings
    
    @classmethod
    def _suggest_similar(cls, var: str, max_suggestions: int = 3, cutoff: float = 0.6) -> list[str]:
        """Suggest similar known variables using fuzzy matching.
        
        Args:
            var: Variable name to find suggestions for
            max_suggestions: Maximum number of suggestions to return
            cutoff: Similarity threshold (0.0-1.0)
            
        Returns:
            List of similar variable names
        """
        matches = difflib.get_close_matches(var, cls.KNOWN_VARS, n=max_suggestions, cutoff=cutoff)
        return matches
    
    @classmethod
    def is_known(cls, var: str) -> bool:
        """Check if a variable is in the known set.
        
        Args:
            var: Variable name to check
            
        Returns:
            True if variable is known
        """
        return var in cls.KNOWN_VARS
    
    @classmethod
    def is_deprecated(cls, var: str) -> bool:
        """Check if a variable is deprecated.
        
        Args:
            var: Variable name to check
            
        Returns:
            True if variable is deprecated
        """
        return var in cls.DEPRECATED_VARS
    
    @classmethod
    def get_all_g6_vars(cls) -> dict[str, str]:
        """Get all G6_ variables from environment.
        
        Returns:
            Dictionary of G6_ variable names and values
        """
        return {k: v for k, v in os.environ.items() if k.startswith('G6_')}
    
    @classmethod
    def categorize_vars(cls) -> dict[str, list[str]]:
        """Categorize all G6_ variables in environment.
        
        Returns:
            Dictionary with categories: known, unknown, deprecated
        """
        known = []
        unknown = []
        deprecated = []
        
        for key in os.environ:
            if not key.startswith('G6_'):
                continue
            
            if key in cls.DEPRECATED_VARS:
                deprecated.append(key)
            elif key in cls.KNOWN_VARS:
                known.append(key)
            else:
                unknown.append(key)
        
        return {
            'known': sorted(known),
            'unknown': sorted(unknown),
            'deprecated': sorted(deprecated),
        }


__all__ = ['G6ConfigValidator']
