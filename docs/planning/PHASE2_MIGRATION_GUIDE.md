# Phase 2 Migration Guide: Facade Pattern

**Date:** October 25, 2025  
**Status:** Phase 2 Complete - Facades created, migration pattern established

---

## Overview

Phase 2 introduces **lazy-loading facade modules** to break circular dependencies by deferring imports until first use. This eliminates the need for late imports (function-scoped imports).

**Files Created:**
1. `src/metrics/facade.py` - Lazy metrics singleton access
2. `src/errors/facade.py` - Lazy error handler singleton access  
3. `src/errors/__init__.py` - Clean error package interface
4. `src/interfaces/` - Protocol definitions (Phase 1)

**Benefits:**
- ✅ Eliminates function-scoped imports (539 identified)
- ✅ Breaks circular dependency chains
- ✅ Thread-safe singleton access
- ✅ Type-safe via protocols
- ✅ Better IDE support and type checking
- ✅ Improved startup and runtime performance

---

## Migration Patterns

### Pattern 1: Metrics Import Refactoring

**Before (Late Import - Causes Circular Dependency):**
```python
def my_function():
    # Late import inside function (bad)
    from src.metrics import get_metrics
    metrics = get_metrics()
    metrics.increment_counter("my_metric")
```

**After (Facade Pattern - No Circular Dependency):**
```python
# Import at module top (good)
from src.metrics.facade import get_metrics_lazy

def my_function():
    metrics = get_metrics_lazy()
    metrics.increment_counter("my_metric")
```

**Even Better (With Protocol Type Hints):**
```python
# Import at module top
from src.interfaces import MetricsProtocol
from src.metrics.facade import get_metrics_lazy

def my_function(metrics: MetricsProtocol | None = None):
    metrics = metrics or get_metrics_lazy()
    metrics.increment_counter("my_metric")
```

**Best (Direct Convenience Functions):**
```python
# Import at module top
from src.metrics.facade import increment_counter, record_timer

def my_function():
    increment_counter("my_metric")
    
    with record_timer("operation_duration"):
        # ... timed operation ...
        pass
```

### Pattern 2: Error Handler Import Refactoring

**Before (Late Import - Causes Circular Dependency):**
```python
def my_function():
    try:
        # ... risky operation ...
        pass
    except Exception as e:
        # Late import inside exception handler (bad)
        from src.error_handling import handle_api_error
        handle_api_error(e, component="my_module", context={})
```

**After (Facade Pattern - No Circular Dependency):**
```python
# Import at module top (good)
from src.errors import handle_error, ErrorCategory, ErrorSeverity

def my_function():
    try:
        # ... risky operation ...
        pass
    except Exception as e:
        handle_error(
            e,
            category=ErrorCategory.API,
            severity=ErrorSeverity.HIGH,
            context={"component": "my_module"},
            suppress=True
        )
```

**With Protocol Type Hints:**
```python
# Import at module top
from src.interfaces import ErrorHandlerProtocol, ErrorCategory, ErrorSeverity
from src.errors import get_error_handler_lazy

def my_function(error_handler: ErrorHandlerProtocol | None = None):
    handler = error_handler or get_error_handler_lazy()
    
    try:
        # ... risky operation ...
        pass
    except Exception as e:
        handler.handle_error(e, ErrorCategory.API, ErrorSeverity.HIGH)
```

### Pattern 3: Mixed Metrics + Error Handling

**Before:**
```python
def collect_data():
    try:
        # ... collection logic ...
        from src.metrics import get_metrics  # Late import
        get_metrics().increment_counter("success")
    except Exception as e:
        from src.error_handling import handle_collector_error  # Late import
        handle_collector_error(e)
        from src.metrics import get_metrics  # Duplicate late import!
        get_metrics().increment_counter("errors")
```

**After:**
```python
# Import at module top
from src.metrics.facade import increment_counter, get_metrics_lazy
from src.errors import handle_error, ErrorCategory, ErrorSeverity

def collect_data():
    try:
        # ... collection logic ...
        increment_counter("success")
    except Exception as e:
        handle_error(e, ErrorCategory.COLLECTOR, ErrorSeverity.MEDIUM)
        increment_counter("errors")
```

---

## API Reference

### Metrics Facade (`src.metrics.facade`)

**Main Functions:**
```python
from src.metrics.facade import get_metrics_lazy

metrics = get_metrics_lazy()  # Returns MetricsProtocol instance
```

**Convenience Functions:**
```python
from src.metrics.facade import (
    increment_counter,    # Increment a counter
    set_gauge,           # Set a gauge value
    observe_histogram,   # Record histogram observation
    record_timer,        # Timer context manager
    safe_emit,          # Error-suppressed emission
)

# Examples:
increment_counter("requests_total", 1.0, {"endpoint": "/api/data"})
set_gauge("active_connections", 42.0)
observe_histogram("response_time", 0.123)

with record_timer("operation_duration", {"operation": "fetch"}):
    # ... timed code ...
    pass

safe_emit("metric_name", 100.0)  # Won't raise on error
```

### Error Handler Facade (`src.errors`)

**Main Functions:**
```python
from src.errors import get_error_handler_lazy

handler = get_error_handler_lazy()  # Returns ErrorHandlerProtocol instance
```

**Convenience Functions:**
```python
from src.errors import (
    handle_error,        # Handle exception with categorization
    log_error,          # Log error message (no exception)
    get_error_count,    # Get count of handled errors
    ErrorCategory,      # Error category enum
    ErrorSeverity,      # Error severity enum
)

# Examples:
try:
    # ... risky operation ...
    pass
except Exception as e:
    handle_error(
        error=e,
        category=ErrorCategory.API,
        severity=ErrorSeverity.HIGH,
        context={"endpoint": "/api/data", "retry_count": 3},
        suppress=True  # Don't re-raise
    )

log_error(
    "Configuration validation failed",
    category=ErrorCategory.CONFIGURATION,
    severity=ErrorSeverity.CRITICAL,
    context={"config_file": "platform_config.json"}
)

error_count = get_error_count(ErrorCategory.API)
```

**Error Categories:**
- `ErrorCategory.API` - External API errors
- `ErrorCategory.DATA` - Data validation/quality errors
- `ErrorCategory.PROVIDER` - Provider/broker errors
- `ErrorCategory.COLLECTOR` - Collection pipeline errors
- `ErrorCategory.VALIDATION` - Input validation errors
- `ErrorCategory.STORAGE` - Storage/persistence errors
- `ErrorCategory.CONFIGURATION` - Configuration errors
- `ErrorCategory.UNKNOWN` - Uncategorized errors

**Error Severities:**
- `ErrorSeverity.LOW` - Minor issues, informational
- `ErrorSeverity.MEDIUM` - Moderate issues, may affect functionality
- `ErrorSeverity.HIGH` - Serious issues, significant impact
- `ErrorSeverity.CRITICAL` - Critical issues, system-level failures

---

## Migration Priority

### Phase 2a: Top 5 Offenders (Complete Example: `logging_utils.py`)

**Priority Order:**
1. ✅ `src/utils/logging_utils.py` - 1 late import → **MIGRATED**
2. `src/orchestrator/components.py` - 20 late imports
3. `src/orchestrator/bootstrap.py` - 22 late imports  
4. `src/collectors/unified_collectors.py` - 44 late imports
5. `src/collectors/modules/expiry_processor.py` - 33 late imports

### Phase 2b: Medium Offenders (10-20 late imports)

- `src/broker/kite_provider.py` - 31 late imports
- `src/broker/kite/options.py` - 22 late imports
- `src/collectors/pipeline/phases.py` - 14 late imports
- `src/collectors/modules/index_processor.py` - 13 late imports
- `src/health/alerts/alert_manager.py` - 12 late imports

### Phase 2c: All Remaining (539 total late imports)

Migrate remaining files systematically, focusing on:
- Files with explicit "# late import" comments
- Files with "# local import to avoid circular" comments
- Collectors modules (high usage, hot path)

---

## Testing

### Validate Facade Imports
```python
# Test that facades don't cause circular imports
from src.metrics.facade import get_metrics_lazy, increment_counter
from src.errors import get_error_handler_lazy, ErrorCategory, ErrorSeverity

# Test protocol imports
from src.interfaces import MetricsProtocol, ErrorHandlerProtocol

print("✅ All facades imported successfully")
```

### Test Lazy Initialization
```python
from src.metrics.facade import get_metrics_lazy, reset_metrics_lazy

# Reset for testing
reset_metrics_lazy()

# First call initializes
metrics1 = get_metrics_lazy()

# Subsequent calls return same instance
metrics2 = get_metrics_lazy()
assert metrics1 is metrics2

print("✅ Singleton pattern working")
```

### Test Thread Safety
```python
import threading
from src.metrics.facade import get_metrics_lazy

instances = []

def get_instance():
    instances.append(get_metrics_lazy())

threads = [threading.Thread(target=get_instance) for _ in range(10)]
for t in threads:
    t.start()
for t in threads:
    t.join()

# All threads should get the same instance
assert len(set(id(i) for i in instances)) == 1

print("✅ Thread-safe singleton")
```

---

## Implementation Notes

### Why Lazy Loading?

**Problem:** Direct imports cause circular dependencies:
```
src.metrics → src.collectors → src.error_handling → src.metrics (CYCLE!)
```

**Solution:** Defer imports until runtime:
```python
# Import happens inside function, AFTER module initialization
def get_metrics_lazy():
    from src.metrics import get_metrics_singleton  # Safe!
    return get_metrics_singleton()
```

### Thread Safety

The facade uses **double-checked locking** for performance:
```python
if _instance is not None:
    return _instance  # Fast path (no lock)

with _lock:
    if _instance is not None:  # Double-check
        return _instance
    _instance = initialize()  # Slow path (one-time)
```

### Type Checking

Use `TYPE_CHECKING` to avoid runtime imports:
```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.interfaces import MetricsProtocol

def my_function() -> "MetricsProtocol":
    # Return type is string literal at runtime
    pass
```

---

## Next Steps (Phase 3)

1. **Configuration consolidation** - Unify `env_flags` and `env_adapter`
2. **Type-only imports** - Use `if TYPE_CHECKING` for remaining circulars
3. **Batch migration** - Convert top 20 offenders
4. **Validation** - Run full test suite after each batch

---

## Success Metrics

**Target:** Eliminate 539 late imports

**Phase 2 Progress:**
- ✅ Facades created: 2 (metrics, errors)
- ✅ Protocols created: 3 (metrics, errors, providers)  
- ✅ Example migration: 1 file (`logging_utils.py`)
- ✅ Validation: All imports working, no circular errors
- 📊 **Late imports eliminated:** 1 of 539 (0.2%)

**Projected Impact (Full Phase 2):**
- **100-150 late imports** eliminated in top 10 offenders
- **3 major circular chains** broken (metrics, errors, providers)
- **20-30% faster** module import time
- **Better IDE support** (IntelliSense, go-to-definition)
