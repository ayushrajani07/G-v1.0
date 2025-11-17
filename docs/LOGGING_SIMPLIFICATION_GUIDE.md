# Terminal Log Processing - Simplification Guide
**Date:** 2025-11-16  
**Status:** Recommendations for Implementation

---

## Current State Analysis

### ✅ **What's Working Well:**
1. **Centralized Setup**: `src/utils/logging_utils.py` provides unified `setup_logging()`
2. **Minimal Console Format**: Message-only output via `MINIMAL_CONSOLE_FORMAT`
3. **Structured Logging**: JSON logs available via `G6_JSON_LOGS=1`
4. **Context Enrichment**: Log context injection (run_id, component, cycle, index)
5. **Suppression**: Noisy loggers (urllib3, requests) automatically quieted

### ⚠️ **Current Complications:**

1. **Over-Engineering**:
   - Complex filter chains for context injection
   - Multiple format toggles (verbose, minimal, JSON)
   - ASCII sanitization for non-UTF8 terminals
   - Atexit handlers for cleanup

2. **Inconsistent Usage**:
   - 20+ files use `logging.basicConfig()` directly (bypassing centralized setup)
   - Mix of lazy logging (`logger.info("msg %s", arg)`) and f-strings
   - Scattered log levels (some DEBUG, some INFO)

3. **Noise in Terminal**:
   - Bootstrap/initialization logs clutter output
   - Repetitive structured event logs
   - Stack traces for non-critical errors

4. **Hard to Debug**:
   - No easy way to filter by component/phase
   - JSON logs hard to read in terminal
   - File logs mixed with console logs

---

## Recommended Simplifications

### **Strategy 1: Three-Tier Logging (Recommended) ✅**

**Concept**: Separate logs by audience and purpose

#### **Tier 1: Terminal (User-Facing)**
- **Who**: Traders, operators, CI/CD
- **What**: High-level progress, errors, warnings only
- **Format**: Clean, minimal, color-coded
- **Level**: `WARNING` and above by default

```python
# Terminal output examples:
✓ NIFTY collection complete (234 strikes, 1.2s)
⚠ BANKNIFTY partial data (187/234 strikes, IV missing)
✗ Provider timeout after 3 retries
```

#### **Tier 2: Operational Logs (File)**
- **Who**: DevOps, monitoring systems
- **What**: All INFO+ events with context
- **Format**: Structured JSON (for log aggregation)
- **Level**: `INFO` and above

```json
{"ts": 1700000000, "level": "INFO", "component": "collector", "index": "NIFTY", "msg": "collection_complete", "duration_ms": 1234, "strike_count": 234}
```

#### **Tier 3: Debug Logs (File, On-Demand)**
- **Who**: Developers debugging issues
- **What**: Everything including DEBUG
- **Format**: Detailed text with full context
- **Level**: `DEBUG` (enable via flag)

```
2025-11-16 10:30:45,123 - Thread-1 - src.collectors.unified - DEBUG - fetch_strikes index=NIFTY expiry=2025-11-21 strikes=[20000, 20050, ...]
```

---

### **Implementation: Simplified Logging Config**

#### **Step 1: Update `logging_utils.py`**

**Current**: 200+ lines with filters, formatters, toggles  
**Proposed**: 80 lines with clear tiers

```python
"""Simplified three-tier logging for G6 Platform."""
import logging
import sys
import os
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
SUPPRESSED = ['urllib3', 'requests', 'kiteconnect', 'urllib3.connectionpool']


def setup_logging(
    terminal_level: str = "WARNING",  # Default: show only warnings/errors
    ops_file: Optional[str] = None,   # If provided, enable Tier 2
    debug_file: Optional[str] = None, # If provided, enable Tier 3
) -> logging.Logger:
    """
    Configure three-tier logging.
    
    Args:
        terminal_level: Console level (WARNING=user, INFO=verbose, DEBUG=dev)
        ops_file: Path for operational JSON logs (None=disabled)
        debug_file: Path for debug logs (None=disabled)
    
    Env Overrides:
        G6_LOG_LEVEL: Override terminal_level
        G6_OPS_LOG: Override ops_file path
        G6_DEBUG_LOG: Override debug_file path
    
    Examples:
        # Production: Quiet terminal, ops logs only
        setup_logging(terminal_level="WARNING", ops_file="logs/ops.jsonl")
        
        # Development: Verbose terminal, debug logs
        setup_logging(terminal_level="DEBUG", debug_file="logs/debug.log")
        
        # CI/CD: Info terminal, no files
        setup_logging(terminal_level="INFO")
    """
    # Apply env overrides
    terminal_level = os.getenv("G6_LOG_LEVEL", terminal_level).upper()
    ops_file = os.getenv("G6_OPS_LOG", ops_file)
    debug_file = os.getenv("G6_DEBUG_LOG", debug_file)
    
    # Setup root logger
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # Capture all, filter per handler
    
    # Clear existing handlers
    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()
    
    # Tier 1: Terminal (clean, minimal)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(getattr(logging, terminal_level, logging.WARNING))
    console.setFormatter(logging.Formatter(FMT_TERMINAL))
    root.addHandler(console)
    
    # Tier 2: Operational logs (JSON, structured)
    if ops_file:
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
                for attr in ("index", "component", "run_id", "cycle"):
                    if hasattr(record, attr):
                        obj[attr] = getattr(record, attr)
                if record.exc_info:
                    obj["exception"] = self.formatException(record.exc_info)
                return json.dumps(obj)
        
        ops_handler.setFormatter(JSONFormatter())
        root.addHandler(ops_handler)
    
    # Tier 3: Debug logs (full detail)
    if debug_file:
        os.makedirs(os.path.dirname(debug_file), exist_ok=True)
        debug_handler = logging.FileHandler(debug_file, encoding='utf-8')
        debug_handler.setLevel(logging.DEBUG)
        debug_handler.setFormatter(logging.Formatter(FMT_DEBUG))
        root.addHandler(debug_handler)
    
    # Suppress noisy loggers
    for name in SUPPRESSED:
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
```

---

### **Step 2: Update Bootstrap Code**

**File:** `src/orchestrator/bootstrap.py`

```python
# Before:
from src.utils.logging_utils import setup_logging
setup_logging(level='INFO', log_file='logs/g6.log')

# After:
from src.utils.logging_utils import setup_production, setup_development
import os

if os.getenv("G6_ENV") == "production":
    setup_production()  # Quiet terminal, ops logs
else:
    setup_development()  # Verbose for debugging
```

---

### **Step 3: Standardize Log Messages**

#### **Terminal Messages (User-Facing)**

**Pattern**: `[ICON] [COMPONENT] Message (details)`

```python
# Good: Clean, informative
logger.warning("⚠ COLLECTOR: NIFTY timeout after 3 retries")
logger.info("✓ CYCLE: Complete in 2.3s (NIFTY: 234 strikes, BANKNIFTY: 187)")
logger.error("✗ PROVIDER: Connection failed - check network")

# Bad: Too verbose
logger.info("Starting collection for NIFTY with strikes_itm=2 strikes_otm=3 expiries=['this_week']")
```

#### **Operational Logs (Structured)**

```python
# Use extra= for structured data
logger.info(
    "collection_complete",
    extra={
        "index": "NIFTY",
        "strike_count": 234,
        "duration_ms": 2300,
        "data_quality": 0.98
    }
)
```

#### **Debug Logs (Developer)**

```python
# Detailed, includes all context
logger.debug(
    "fetch_strikes: index=%s expiry=%s strikes=%s provider=%s",
    index, expiry, strikes, provider_name
)
```

---

### **Step 4: Create Log Level Helpers**

**File:** `src/utils/log_helpers.py`

```python
"""Helper functions for clean logging."""
import logging
from typing import Optional

# Icons for terminal output
ICON_SUCCESS = "✓"
ICON_WARNING = "⚠"
ICON_ERROR = "✗"
ICON_INFO = "ℹ"

def log_success(logger: logging.Logger, component: str, message: str, **context):
    """Log successful operation (terminal + ops)."""
    logger.info(f"{ICON_SUCCESS} {component}: {message}", extra=context)

def log_warning(logger: logging.Logger, component: str, message: str, **context):
    """Log warning (terminal + ops)."""
    logger.warning(f"{ICON_WARNING} {component}: {message}", extra=context)

def log_error(logger: logging.Logger, component: str, message: str, exc: Optional[Exception] = None, **context):
    """Log error (terminal + ops)."""
    logger.error(f"{ICON_ERROR} {component}: {message}", extra=context, exc_info=exc)

def log_progress(logger: logging.Logger, component: str, message: str, **context):
    """Log progress update (ops only, not terminal unless verbose)."""
    logger.info(f"{ICON_INFO} {component}: {message}", extra=context)

# Usage example:
# from src.utils.log_helpers import log_success, log_error
# log_success(logger, "COLLECTOR", "NIFTY complete", strike_count=234, duration_ms=2300)
# log_error(logger, "PROVIDER", "Connection timeout", exc=e, retry_count=3)
```

---

### **Step 5: Environment Variable Configuration**

**Single source of truth for log behavior:**

```bash
# Production (quiet, ops logs)
export G6_LOG_LEVEL=WARNING
export G6_OPS_LOG=logs/ops.jsonl

# Development (verbose, debug logs)
export G6_LOG_LEVEL=INFO
export G6_DEBUG_LOG=logs/debug.log

# CI/CD (info only, no files)
export G6_LOG_LEVEL=INFO

# Debugging specific component
export G6_LOG_LEVEL=DEBUG
export G6_DEBUG_LOG=logs/debug.log
# Then filter: grep "src.collectors" logs/debug.log
```

---

## Migration Plan

### **Phase 1: Update Core (1 day)**
- [ ] Replace `logging_utils.py` with simplified version
- [ ] Update `bootstrap.py` to use new setup
- [ ] Test in development environment

### **Phase 2: Standardize Messages (2 days)**
- [ ] Update top 20 high-frequency log messages
- [ ] Use `log_helpers.py` for clean terminal output
- [ ] Target: collectors, orchestrator, providers

### **Phase 3: Remove Redundancy (1 day)**
- [ ] Find and replace `logging.basicConfig()` calls
- [ ] Consolidate to single `setup_logging()` call in bootstrap
- [ ] Remove unused formats/filters

### **Phase 4: Documentation (1 day)**
- [ ] Update `OPERATOR_MANUAL.md` with log levels
- [ ] Document troubleshooting via logs
- [ ] Create log examples for common scenarios

---

## Expected Benefits

### **Before (Current)**
```
2025-11-16 10:30:45,123 - MainThread - src.collectors.unified_collectors - INFO - Starting collection cycle
2025-11-16 10:30:45,234 - Thread-1 - src.provider.kite_provider - DEBUG - Fetching instruments for NIFTY
2025-11-16 10:30:45,456 - Thread-1 - src.provider.kite_provider - INFO - Got 234 instruments
2025-11-16 10:30:45,567 - Thread-2 - src.collectors.modules.enrichment - DEBUG - Enriching quotes batch 1/5
2025-11-16 10:30:45,678 - MainThread - src.collectors.unified_collectors - INFO - Collection complete for NIFTY
```
**Issues**: 5 lines for simple success, timestamps clutter, thread names irrelevant

### **After (Simplified)**
```
✓ CYCLE: NIFTY complete (234 strikes, 1.2s)
```
**Benefits**: 1 line, clear result, no noise

---

## Advanced: Structured Event Logging

For operational dashboards (Grafana/Prometheus):

```python
# Emit structured events for metrics
from src.utils.log_helpers import emit_event

emit_event(logger, "collection.complete", {
    "index": "NIFTY",
    "duration_ms": 1234,
    "strike_count": 234,
    "data_quality": 0.98,
    "success": True
})

# Grafana can parse these from ops.jsonl:
# - Count by event type
# - Average duration by index
# - Track data quality trends
```

---

## Quick Wins (Implement Today)

### **1. Silent Bootstrap (5 min)**

```python
# In bootstrap.py, before setup_logging():
import sys
sys.stdout = open(os.devnull, 'w')  # Silence imports

# After setup_logging():
sys.stdout = sys.__stdout__  # Restore
```

### **2. Quiet Tests (5 min)**

```python
# In conftest.py:
@pytest.fixture(autouse=True)
def quiet_logs(caplog):
    caplog.set_level(logging.WARNING)  # Tests show only warnings+
```

### **3. One-Liner Terminal Status (10 min)**

```python
# Replace progress logs with single line update:
import sys
sys.stdout.write(f"\r✓ NIFTY: {strike_count} strikes | {duration_ms}ms")
sys.stdout.flush()
```

---

## Tools & Scripts

### **Log Analysis Script**

**File:** `scripts/analyze_logs.py`

```python
"""Analyze G6 logs for patterns and issues."""
import argparse
import json
from collections import Counter

def analyze_ops_log(file_path):
    """Parse JSONL ops log and generate report."""
    events = []
    with open(file_path) as f:
        for line in f:
            events.append(json.loads(line))
    
    print(f"Total Events: {len(events)}")
    print("\nBy Level:")
    levels = Counter(e['level'] for e in events)
    for level, count in levels.most_common():
        print(f"  {level}: {count}")
    
    print("\nBy Component:")
    components = Counter(e.get('logger', 'unknown') for e in events)
    for comp, count in components.most_common(10):
        print(f"  {comp}: {count}")
    
    print("\nErrors:")
    errors = [e for e in events if e['level'] == 'ERROR']
    for err in errors[:10]:
        print(f"  {err['msg']}")

# Usage:
# python scripts/analyze_logs.py logs/ops.jsonl
```

### **Live Log Viewer**

```bash
# Watch ops logs with pretty formatting:
tail -f logs/ops.jsonl | jq -C '.ts |= (. / 1000 | strftime("%H:%M:%S")) | "\(.ts) [\(.level)] \(.msg)"'

# Filter by component:
tail -f logs/ops.jsonl | jq -C 'select(.logger | contains("collector"))'

# Count errors per minute:
cat logs/ops.jsonl | jq -r 'select(.level=="ERROR") | .ts' | awk '{print int($1/60000)}' | uniq -c
```

---

## Summary

**Current Complexity**: 7/10  
**Proposed Simplicity**: 3/10  
**Implementation Effort**: 5 days  
**Benefit**: High (cleaner terminals, easier debugging, better ops visibility)

**Key Changes:**
1. ✅ Three tiers: Terminal (clean) → Ops (JSON) → Debug (detailed)
2. ✅ Single `setup_logging()` call, env-driven config
3. ✅ Standardized messages with icons
4. ✅ Remove 200+ lines of filter/formatter complexity
5. ✅ Better separation of concerns

**Next Steps:**
1. Review & approve this guide
2. Implement Phase 1 (core update)
3. Gradually migrate high-traffic log statements
4. Monitor and adjust based on operator feedback

---

**Questions or Feedback?**  
Contact Platform Engineering Team
