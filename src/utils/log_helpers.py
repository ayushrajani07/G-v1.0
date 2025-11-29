"""Helper functions for clean, standardized logging.

Phase 1 Implementation: 2025-11-16
Provides consistent terminal output with icons and per-index metrics.
"""
import logging
import sys
from typing import Optional, Dict, Any

# Icons for terminal output (with ASCII fallbacks for Windows)
_USE_UNICODE = (
    sys.stdout.encoding and 
    sys.stdout.encoding.lower() in ('utf-8', 'utf8') or
    sys.platform != 'win32'
)

if _USE_UNICODE:
    ICON_SUCCESS = "✓"
    ICON_WARNING = "⚠"
    ICON_ERROR = "✗"
    ICON_INFO = "ℹ"
    ICON_PROGRESS = "⟳"
else:
    # ASCII fallbacks for Windows terminals
    ICON_SUCCESS = "[OK]"
    ICON_WARNING = "[!]"
    ICON_ERROR = "[X]"
    ICON_INFO = "[i]"
    ICON_PROGRESS = "[~]"

# ANSI color codes for terminal output
class Colors:
    """ANSI color codes for terminal formatting."""
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

# Thresholds for color coding
THRESHOLD_SUCCESS_EXCELLENT = 95.0  # >= 95% = green
THRESHOLD_SUCCESS_GOOD = 80.0       # >= 80% = yellow
THRESHOLD_COVERAGE_EXCELLENT = 90.0 # >= 90% = green
THRESHOLD_COVERAGE_GOOD = 75.0      # >= 75% = yellow

def _colorize_metric(value: float, excellent_threshold: float, good_threshold: float) -> str:
    """Colorize a metric value based on thresholds.
    
    Args:
        value: Metric value (percentage)
        excellent_threshold: Threshold for green color
        good_threshold: Threshold for yellow color
    
    Returns:
        Formatted string with color codes
    """
    if value >= excellent_threshold:
        return f"{Colors.GREEN}{value:.1f}%{Colors.RESET}"
    elif value >= good_threshold:
        return f"{Colors.YELLOW}{value:.1f}%{Colors.RESET}"
    else:
        return f"{Colors.RED}{value:.1f}%{Colors.RESET}"

def log_success(logger: logging.Logger, component: str, message: str, **context):
    """Log successful operation (terminal + ops).
    
    Args:
        logger: Logger instance
        component: Component name (e.g., "COLLECTOR", "CYCLE")
        message: Success message
        **context: Additional structured context for ops logs
    
    Example:
        log_success(logger, "COLLECTOR", "NIFTY complete", 
                   strike_count=234, duration_ms=2300, success_pct=98.5)
    """
    if context:
        logger.info("%s %s: %s", ICON_SUCCESS, component, message, extra=context)
    else:
        logger.info("%s %s: %s", ICON_SUCCESS, component, message)

def log_warning(logger: logging.Logger, component: str, message: str, **context):
    """Log warning (terminal + ops).
    
    Args:
        logger: Logger instance
        component: Component name
        message: Warning message
        **context: Additional structured context
    
    Example:
        log_warning(logger, "COLLECTOR", "NIFTY partial data", 
                   strikes_missing=47, field_coverage_pct=82.3)
    """
    if context:
        logger.warning("%s %s: %s", ICON_WARNING, component, message, extra=context)
    else:
        logger.warning("%s %s: %s", ICON_WARNING, component, message)

def log_error(logger: logging.Logger, component: str, message: str, 
              exc: Optional[Exception] = None, **context):
    """Log error (terminal + ops).
    
    Args:
        logger: Logger instance
        component: Component name
        message: Error message
        exc: Optional exception for stack trace
        **context: Additional structured context
    
    Example:
        log_error(logger, "PROVIDER", "Connection timeout", 
                 exc=e, retry_count=3, provider="kite")
    """
    logger.error("%s %s: %s", ICON_ERROR, component, message, extra=context, exc_info=exc)

def log_info(logger: logging.Logger, component: str, message: str, **context):
    """Log informational message (ops only unless terminal is verbose).
    
    Args:
        logger: Logger instance
        component: Component name
        message: Info message
        **context: Additional structured context
    
    Example:
        log_info(logger, "BOOTSTRAP", "Metrics initialized", metric_count=213)
    """
    if context:
        logger.info("%s %s: %s", ICON_INFO, component, message, extra=context)
    else:
        logger.info("%s %s: %s", ICON_INFO, component, message)

def log_progress(logger: logging.Logger, component: str, message: str, **context):
    """Log progress update (ops only, not terminal unless verbose).
    
    Args:
        logger: Logger instance
        component: Component name
        message: Progress message
        **context: Additional structured context
    
    Example:
        log_progress(logger, "COLLECTOR", "Enriching batch 3/5", batch_size=50)
    """
    if context:
        logger.info("%s %s: %s", ICON_PROGRESS, component, message, extra=context)
    else:
        logger.info("%s %s: %s", ICON_PROGRESS, component, message)


def log_cycle_complete(logger: logging.Logger, 
                       duration_ms: int,
                       index_metrics: Dict[str, Dict[str, Any]]):
    """Log cycle completion with per-index metrics.
    
    Args:
        logger: Logger instance
        duration_ms: Total cycle duration in milliseconds
        index_metrics: Dict of {index_name: {success_pct, field_coverage_pct, strike_count, ...}}
    
    Example:
        log_cycle_complete(logger, 2300, {
            "NIFTY": {"success_pct": 98.5, "field_coverage_pct": 95.2, "strike_count": 234},
            "BANKNIFTY": {"success_pct": 87.3, "field_coverage_pct": 89.1, "strike_count": 187}
        })
        
    Terminal Output:
        ✓ CYCLE: Complete in 2.3s | NIFTY: 234 strikes (98.5% success, 95.2% coverage) | 
                                     BANKNIFTY: 187 strikes (87.3% success, 89.1% coverage)
    """
    # Build terminal message
    duration_s = duration_ms / 1000.0
    index_parts = []
    
    poor_indices: list[str] = []
    for index, metrics in index_metrics.items():
        success_pct = metrics.get("success_pct", 0.0)
        field_coverage_pct = metrics.get("field_coverage_pct", 0.0)
        option_count = metrics.get("strike_count", 0)  # Historical key name, actually option count
        missing_strike_cov = metrics.get("missing_strike_cov", 0)
        missing_field_cov = metrics.get("missing_field_cov", 0)
        expiries_total = metrics.get("expiries", 0)
        
        # Format with appropriate icon based on quality
        if success_pct >= THRESHOLD_SUCCESS_EXCELLENT and field_coverage_pct >= THRESHOLD_COVERAGE_EXCELLENT:
            icon = ICON_SUCCESS
        elif success_pct >= THRESHOLD_SUCCESS_GOOD and field_coverage_pct >= THRESHOLD_COVERAGE_GOOD:
            icon = ICON_WARNING
        else:
            icon = ICON_ERROR
        
        # Colorize metrics based on thresholds
        success_colored = _colorize_metric(success_pct, THRESHOLD_SUCCESS_EXCELLENT, THRESHOLD_SUCCESS_GOOD)
        coverage_colored = _colorize_metric(field_coverage_pct, THRESHOLD_COVERAGE_EXCELLENT, THRESHOLD_COVERAGE_GOOD)
        
        index_parts.append(
            "%s %s: %d options (%s success, %s coverage)" % (
                icon, index, option_count, success_colored, coverage_colored
            )
        )
        if success_pct < THRESHOLD_SUCCESS_GOOD or field_coverage_pct < THRESHOLD_COVERAGE_GOOD:
            poor_indices.append(
                f"DEBUG {index}: expiries={expiries_total} miss_strike_cov={missing_strike_cov} miss_field_cov={missing_field_cov} raw_success={success_pct:.1f}% raw_field_cov={field_coverage_pct:.1f}%"
            )
    
    # Build multi-line output with each index on its own line
    # Add IST timestamp
    from datetime import datetime, timezone, timedelta
    ist = timezone(timedelta(hours=5, minutes=30))
    timestamp = datetime.now(ist).strftime("%H:%M:%S")
    lines = ["%s CYCLE: Complete in %.1fs [%s IST]" % (ICON_SUCCESS, duration_s, timestamp)]
    lines.append("")  # Blank line after header
    lines.extend(index_parts)
    
    if poor_indices:
        lines.append("")
        lines.extend(poor_indices)
    msg = "\n".join(lines)
    
    # Log with blank line above and below for better visibility
    # Log with structured context for ops logs
    logger.info(
        "\n%s\n",
        msg,
        extra={
            "component": "cycle",
            "duration_ms": duration_ms,
            "index_count": len(index_metrics),
            **{f"{idx}_success_pct": m.get("success_pct", 0.0) for idx, m in index_metrics.items()},
            **{f"{idx}_field_coverage_pct": m.get("field_coverage_pct", 0.0) for idx, m in index_metrics.items()},
            **{f"{idx}_strike_count": m.get("strike_count", 0) for idx, m in index_metrics.items()},
            **{f"{idx}_missing_strike_cov": m.get("missing_strike_cov", 0) for idx, m in index_metrics.items()},
            **{f"{idx}_missing_field_cov": m.get("missing_field_cov", 0) for idx, m in index_metrics.items()},
            **{f"{idx}_expiries": m.get("expiries", 0) for idx, m in index_metrics.items()},
        }
    )


def log_index_complete(logger: logging.Logger, 
                       index: str,
                       strike_count: int,
                       duration_ms: int,
                       success_pct: float,
                       field_coverage_pct: float,
                       **extra_metrics):
    """Log individual index collection completion.
    
    Args:
        logger: Logger instance
        index: Index name (e.g., "NIFTY")
        strike_count: Number of option instruments collected (CE + PE across strikes)
        duration_ms: Collection duration in milliseconds
        success_pct: Success percentage (0-100)
        field_coverage_pct: Field coverage percentage (0-100)
        **extra_metrics: Additional metrics (e.g., iv_missing, oi_missing)
    
    Example:
        log_index_complete(logger, "NIFTY", 234, 1234, 98.5, 95.2, 
                          iv_missing=2, oi_missing=1)
    
    Terminal Output:
        ✓ NIFTY: 234 options in 1.2s (98.5% success, 95.2% coverage)
    """
    duration_s = duration_ms / 1000.0
    
    # Choose icon based on quality
    if success_pct >= 95.0 and field_coverage_pct >= 90.0:
        icon = ICON_SUCCESS
    elif success_pct >= 80.0 and field_coverage_pct >= 75.0:
        icon = ICON_WARNING
    else:
        icon = ICON_ERROR
    
    msg = "%d options in %.1fs (%.1f%% success, %.1f%% coverage)" % (
        strike_count, duration_s, success_pct, field_coverage_pct
    )
    
    logger.info(
        "%s %s: %s",
        icon,
        index,
        msg,
        extra={
            "component": "collector",
            "index": index,
            "strike_count": strike_count,
            "duration_ms": duration_ms,
            "success_pct": success_pct,
            "field_coverage_pct": field_coverage_pct,
            **extra_metrics
        }
    )


__all__ = [
    "log_success",
    "log_warning", 
    "log_error",
    "log_info",
    "log_progress",
    "log_cycle_complete",
    "log_index_complete",
]
