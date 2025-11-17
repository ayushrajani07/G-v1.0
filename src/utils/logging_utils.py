"""Simplified three-tier logging for G6 Platform.

Phase 1 Implementation: 2025-11-16
- Three tiers: Terminal (clean) → Ops (JSON) → Debug (detailed)
- Environment-driven configuration
- Standardized message formats
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional

# Tier definitions
TIER_TERMINAL = "terminal"  # User-facing console
TIER_OPS = "ops"            # Operational file logs
TIER_DEBUG = "debug"        # Developer debug logs

# Format strings
FMT_TERMINAL = "%(message)s"  # Clean output only
FMT_OPS = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
FMT_DEBUG = "%(asctime)s - %(threadName)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"

# Suppressed loggers (always WARNING+)
SUPPRESSED_LOGGERS = [
    'urllib3', 'requests', 'kiteconnect.connection', 'urllib3.connectionpool'
]

def setup_logging(
    terminal_level: str = "WARNING",  # Default: show only warnings/errors
    ops_file: Optional[str] = None,   # If provided, enable Tier 2
    debug_file: Optional[str] = None, # If provided, enable Tier 3
    # Legacy compatibility
    level: Optional[str] = None,
    log_file: Optional[str] = None,
    fmt: Optional[str] = None,
) -> logging.Logger:
    """
    Configure three-tier logging.
    
    Args:
        terminal_level: Console level (WARNING=user, INFO=verbose, DEBUG=dev)
        ops_file: Path for operational JSON logs (None=disabled)
        debug_file: Path for debug logs (None=disabled)
        
        # Legacy compatibility args (deprecated):
        level: Old API, maps to terminal_level if provided
        log_file: Old API, maps to debug_file if provided
        fmt: Ignored in new implementation
    
    Env Overrides:
        G6_LOG_LEVEL: Override terminal_level
        G6_OPS_LOG: Override ops_file path
        G6_DEBUG_LOG: Override debug_file path
    
    Examples:
        # Production: Quiet terminal, ops logs only
        setup_logging(terminal_level="WARNING", ops_file="logs/ops.jsonl")
        
        # Development: Verbose terminal, debug logs
        setup_logging(terminal_level="INFO", debug_file="logs/debug.log")
        
        # Legacy compatibility
        setup_logging(level='INFO', log_file='logs/g6.log')  # Still works
    """
    # Handle legacy API
    if level is not None:
        terminal_level = level
    if log_file is not None and debug_file is None:
        debug_file = log_file
    
    # Apply env overrides
    terminal_level = os.getenv("G6_LOG_LEVEL", terminal_level).upper()
    ops_file = os.getenv("G6_OPS_LOG", ops_file)
    debug_file = os.getenv("G6_DEBUG_LOG", debug_file)
    
    # Setup root logger
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # Capture all, filter per handler
    
    # Clear existing handlers
    for h in root.handlers[:]:
        try:
            root.removeHandler(h)
            h.close()
        except Exception:
            pass

    
    # Tier 1: Terminal (clean, minimal)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(getattr(logging, terminal_level, logging.WARNING))
    console.setFormatter(logging.Formatter(FMT_TERMINAL))
    root.addHandler(console)

    
    # Tier 2: Operational logs (JSON, structured)
    if ops_file:
        try:
            os.makedirs(os.path.dirname(ops_file), exist_ok=True)
            ops_handler = logging.FileHandler(ops_file, encoding='utf-8')
            ops_handler.setLevel(logging.INFO)
            
            # Simple JSON formatter
            class JSONFormatter(logging.Formatter):
                def format(self, record):
                    import json
                    import time
                    obj = {
                        "ts": int(time.time() * 1000),
                        "level": record.levelname,
                        "logger": record.name,
                        "msg": record.getMessage(),
                    }
                    # Add context if available
                    for attr in ("index", "component", "run_id", "cycle", "success_pct", "field_coverage_pct"):
                        if hasattr(record, attr):
                            obj[attr] = getattr(record, attr)
                    if record.exc_info:
                        obj["exception"] = self.formatException(record.exc_info)
                    return json.dumps(obj)
            
            ops_handler.setFormatter(JSONFormatter())
            root.addHandler(ops_handler)
        except Exception as e:
            root.error("Failed to create ops log handler: %s", e)
    
    # Tier 3: Debug logs (full detail)
    if debug_file:
        try:
            os.makedirs(os.path.dirname(debug_file), exist_ok=True)
            debug_handler = logging.FileHandler(debug_file, encoding='utf-8')
            debug_handler.setLevel(logging.DEBUG)
            debug_handler.setFormatter(logging.Formatter(FMT_DEBUG))
            root.addHandler(debug_handler)
        except Exception as e:
            root.error("Failed to create debug log handler: %s", e)
    
    # Suppress noisy loggers
    for name in SUPPRESSED_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    return root


# Quick presets for common scenarios
def setup_production():
    """Production: Quiet terminal + ops logs."""
    return setup_logging(
        terminal_level="WARNING",
        ops_file="logs/ops.jsonl"
    )

def setup_development():
    """Development: Verbose terminal + debug logs."""
    return setup_logging(
        terminal_level="INFO",
        debug_file="logs/debug.log"
    )

def setup_ci():
    """CI/CD: Info terminal only, no files."""
    return setup_logging(terminal_level="INFO")


# Best-effort cleanup of logging handlers at interpreter exit
try:
    import atexit
    @atexit.register
    def _g6_close_logging_handlers() -> None:
        try:
            root = logging.getLogger()
            handlers = list(root.handlers[:])
        except Exception:
            handlers = []
        for h in handlers:
            try:
                h.flush()
                h.close()
            except Exception:
                pass
except Exception:
    pass

__all__ = ["setup_logging", "setup_production", "setup_development", "setup_ci"]
