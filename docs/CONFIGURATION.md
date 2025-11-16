# G6 Platform Configuration Guide

**Status:** Phase 2.2a Complete (2025-11-16)  
**Total Variables:** 1,065+ unique G6_ environment variables  
**Audit Date:** 2025-11-16

---

## Executive Summary

The G6 Platform has evolved to use **1,065+ environment variables** for configuration. This document provides:
1. **Categorization** by type (Core/Feature/Debug/Deprecated)
2. **Reload behavior** classification (Startup-only/Runtime/Hot-reload)  
3. **Priority levels** (Required/Recommended/Optional)
4. **Best practices** for configuration management

**Key Finding:** Creating a single immutable Config dataclass is **not practical** at this scale. Instead, we maintain the existing `EnvConfig` pattern with enhanced validation and documentation.

---

## Quick Start

### Minimal Configuration
```bash
export G6_CSV_BASE_DIR="data/g6_data"
export G6_INDICES="NIFTY,BANKNIFTY"
export KITE_API_KEY="your_key"
export KITE_API_SECRET="your_secret"
```

### Recommended Production
```bash
export G6_CSV_BASE_DIR="data/g6_data"
export G6_INDICES="NIFTY,BANKNIFTY,FINNIFTY"
export G6_COLLECTION_INTERVAL=60
export G6_METRICS_ENABLED=1
export G6_METRICS_PORT=9108
export G6_ADAPTIVE_CONTROLLER=1
export G6_ENABLE_DATA_QUALITY=1
```

---

## 1. Configuration Categories

### 1.1 Core (Startup-only) - 50+ variables

**Cannot be changed at runtime** - require application restart.

#### Storage & Persistence
- `G6_CSV_BASE_DIR` - Base directory for CSV storage (default: `data`)
- `G6_DATA_DIR` - General data directory
- `G6_ANALYTICS_DIR` - Analytics output location
- `G6_CSV_BUFFER_SIZE` - Write buffer size (bytes)
- `G6_CSV_MAX_OPEN_FILES` - Max concurrent file handles

#### System Configuration
- `G6_INDICES` - Trading indices (comma-separated)
- `G6_COLLECTION_INTERVAL` - Collection cycle in seconds
- `G6_LOG_LEVEL` - Logging level (DEBUG/INFO/WARNING/ERROR)
- `G6_METRICS_PORT` - Prometheus metrics port (default: 9108)

### 1.2 Features (Runtime-reload) - 300+ variables

**Take effect on next collection cycle** - no restart needed.

#### Metrics & Monitoring
- `G6_METRICS_ENABLED` - Enable Prometheus metrics (default: `1`)
- `G6_ENABLE_METRIC_GROUPS` - Metric groups to enable (comma-separated)
- `G6_DISABLE_METRIC_GROUPS` - Metric groups to disable
- `G6_DISABLE_PER_OPTION_METRICS` - Reduce cardinality

#### Data Quality
- `G6_ENABLE_DATA_QUALITY` - Enable DQ checks
- `G6_DQ_ERROR_THRESHOLD` - Error threshold
- `G6_DQ_WARN_THRESHOLD` - Warning threshold
- `G6_CSV_PRICE_SANITY` - Price validation

#### Performance
- `G6_USE_CSVIO_FACADE` - Async CSV writer
- `G6_CSVIO_FLUSH_MS` - Flush interval (ms)
- `G6_CSV_BATCH_FLUSH` - Batch threshold

###  1.3 Adaptive (Hot-reload) - 100+ variables

**Can be changed via HTTP API** - takes effect immediately.

#### Adaptive Controller
- `G6_ADAPTIVE_CONTROLLER` - Enable adaptive system
- `G6_ADAPTIVE_MIN_DETAIL_MODE` - Min detail level
- `G6_ADAPTIVE_MAX_DETAIL_MODE` - Max detail level
- `G6_ADAPTIVE_PROMOTE_COOLDOWN` - Promotion delay (cycles)
- `G6_ADAPTIVE_DEMOTE_COOLDOWN` - Demotion delay (cycles)

#### Alert Severity
- `G6_ADAPTIVE_ALERT_SEVERITY` - Adaptive alerts
- `G6_ADAPTIVE_SEVERITY_TREND_WINDOW` - Trend window
- `G6_ADAPTIVE_ALERT_COLOR_CRITICAL` - Critical color (hex)
- `G6_ADAPTIVE_ALERT_COLOR_WARN` - Warning color (hex)

### 1.4 Debug (Dev-only) - 200+ variables

**Should NEVER be used in production.**

- `G6_DEBUG` - Debug mode
- `G6_TRACE_COLLECTORS` - Trace execution
- `G6_FORCE_MARKET_OPEN` - Override market hours
- `G6_ENABLE_PERF_TESTS` - Performance tests
- `G6_ENABLE_SLOW_TESTS` - Slow integration tests

### 1.5 Test (Test-only) - 50+ variables

- `G6_ENABLE_OPTIONAL_TESTS` - Optional tests
- `G6_ENABLE_BROKER_TESTS` - API credential tests
- `PYTEST_CURRENT_TEST` - Test detection

### 1.6 Deprecated - 15+ variables

See `DEPRECATIONS.md` for full list. Notable removals:
- ❌ `G6_ENABLE_LEGACY_LOOP` (REMOVED 2025-09-28)
- ❌ `G6_SUMMARY_REWRITE` (REMOVED 2025-10-03)
- ⚠️ `G6_SSE_ENABLED` (Deprecated, TBD)

---

## 2. Reload Behavior Matrix

| Behavior | Count | Description | Examples | How to Change |
|----------|-------|-------------|----------|---------------|
| **Startup-only** | ~25 | Requires restart | Paths, ports, API keys | Restart application |
| **Runtime** | ~900+ | Next cycle | Feature flags, thresholds | Set env var, wait for cycle |
| **Hot-reload** | ~30 | Immediate via API | Adaptive settings | HTTP POST to endpoint |
| **Debug** | ~200 | Dev/test only | Debug flags, traces | Development only |
| **Test** | ~50 | Test framework | Test gates | Test runs only |
| **Deprecated** | ~15 | Being removed | See DEPRECATIONS.md | Don't use |

### 2.1 Startup-Only Variables (Require Restart)

These variables **MUST** be set before startup and **CANNOT** be changed at runtime:

**Infrastructure & Ports:**
- `G6_METRICS_PORT` - Prometheus metrics server port
- `G6_GRAFANA_PORT` - Grafana port number
- `G6_CATALOG_HTTP_PORT` - Catalog HTTP server port

**Storage Paths:**
- `G6_CSV_BASE_DIR` - Base directory for CSV files
- `G6_DATA_DIR` - General data directory
- `G6_ANALYTICS_DIR` - Analytics output directory
- `G6_CONFIG_PATH` - Configuration file path
- `G6_LOG_FILE` - Log file location

**API Credentials:**
- `KITE_API_KEY` - Kite Connect API key
- `KITE_API_SECRET` - Kite Connect API secret
- `KITE_ACCESS_TOKEN` - Access token

**System Configuration:**
- `G6_LOG_LEVEL` - Logging level (logger configured at startup)
- `G6_COLLECTION_INTERVAL` - Core collection timing
- `G6_CYCLE_INTERVAL` - Orchestrator cycle timing
- `G6_WEB_WORKERS` - Web server process count

**Architectural Settings:**
- `G6_USE_CSVIO_FACADE` - Async CSV writer thread
- `G6_CSVIO_BACKEND` - Storage backend selection
- `G6_CSVIO_WRITER_THREAD` - Threading model

⚠️ **Warning:** If you change these variables at runtime, you will see a warning:
```
WARNING: Variable G6_METRICS_PORT changed at runtime but requires restart to take effect.
Old: 9108, New: 9109. Please restart the application.
```

### 2.2 Hot-Reload Variables (Immediate Effect)

These variables can be changed **immediately** via HTTP API endpoints:

**Adaptive Controller** (Endpoint: `/adaptive/theme`)
- `G6_ADAPTIVE_CONTROLLER` - Enable/disable adaptive system
- `G6_ADAPTIVE_MIN_DETAIL_MODE` - Minimum detail level
- `G6_ADAPTIVE_MAX_DETAIL_MODE` - Maximum detail level
- `G6_ADAPTIVE_PROMOTE_COOLDOWN` - Promotion delay (cycles)
- `G6_ADAPTIVE_DEMOTE_COOLDOWN` - Demotion delay (cycles)

**Adaptive Strikes** (Endpoint: `/adaptive/theme`)
- `G6_ADAPTIVE_STRIKE_SCALING` - Dynamic strike scaling
- `G6_ADAPTIVE_STRIKE_MIN` - Minimum strike count
- `G6_ADAPTIVE_STRIKE_MAX_ITM` - Maximum ITM strikes
- `G6_ADAPTIVE_STRIKE_MAX_OTM` - Maximum OTM strikes
- `G6_ADAPTIVE_STRIKE_STEP` - Strike step size

**Alert Severity** (Endpoint: `/adaptive/theme`)
- `G6_ADAPTIVE_ALERT_SEVERITY` - Dynamic severity adjustment
- `G6_ADAPTIVE_SEVERITY_TREND_WINDOW` - Trend analysis window
- `G6_ADAPTIVE_ALERT_COLOR_CRITICAL` - Critical alert color
- `G6_ADAPTIVE_ALERT_COLOR_WARN` - Warning alert color

**Memory Tier** (Endpoint: `/adaptive/theme`)
- `G6_MEMORY_TIER` - Current memory tier (0-3)
- `G6_MEMORY_TIER_OVERRIDE` - Override tier detection
- `G6_MEMORY_TIER_TTL_MS` - TTL in milliseconds

**Usage Example:**
```bash
# Change adaptive controller setting via HTTP
curl -X POST http://localhost:8080/adaptive/theme \
  -H "Content-Type: application/json" \
  -d '{"G6_ADAPTIVE_MIN_DETAIL_MODE": "2"}'
```

### 2.3 Runtime Variables (Next Cycle)

All other variables take effect on the **next collection cycle** (default: 60 seconds). These include:
- Feature flags (`G6_ENABLE_*`, `G6_DISABLE_*`)
- Metrics settings (`G6_METRICS_ENABLED`, `G6_ENABLE_METRIC_GROUPS`)
- Data quality settings (`G6_ENABLE_DATA_QUALITY`, `G6_DQ_*`)
- Performance tuning (`G6_CSV_BATCH_FLUSH`, `G6_CSVIO_FLUSH_MS`)
- Alert thresholds (`G6_ALERT_*`)

**Example:**
```bash
# Enable data quality checks
export G6_ENABLE_DATA_QUALITY=1
# Takes effect on next collection cycle (within ~60 seconds)
```

---

## 3. Programmatic Access

**Always use `EnvConfig` class:**

```python
from src.config.env_config import EnvConfig

# Type-safe access
interval = EnvConfig.get_int('G6_COLLECTION_INTERVAL', 60)
enabled = EnvConfig.get_bool('G6_METRICS_ENABLED', True)
path = EnvConfig.get_path('G6_CSV_BASE_DIR', 'data')
indices = EnvConfig.get_list('G6_INDICES', ['NIFTY'])

# Check if set
if EnvConfig.is_set('G6_DEBUG'):
    print("Debug enabled")

# Require (raises if missing)
api_key = EnvConfig.require('KITE_API_KEY')
```

---

## 4. Complete Variable Index

**For full alphabetical reference:** See `docs/env_dict.md` (599 lines, auto-generated)

**To search programmatically:**
```python
from src.config.env_config import EnvConfig
all_g6_vars = EnvConfig.get_all('G6_')
```

**To search codebase:**
```powershell
Get-ChildItem -Path "src" -Filter "*.py" -Recurse | Select-String -Pattern "G6_" -AllMatches
```

---

## 5. Best Practices

### ✅ DO
- Use `.env` files for local development
- Access via `EnvConfig` methods
- Document new variables in this file
- Use clear, descriptive names
- Group related variables with prefixes

### ❌ DON'T
- Hard-code configuration values
- Use `os.getenv()` directly
- Commit `.env` files with secrets
- Create variables without documentation
- Use deprecated variables

---

## 6. Future Improvements (Phase 2.2b/c)

### Planned Enhancements
1. **Validation Layer** - Warn about unknown variables at startup
2. **Typo Detection** - Suggest corrections for misspelled names
3. **Hot-reload Documentation** - Explicit list of hot-reloadable vars
4. **Startup Warnings** - Alert when startup-only vars change at runtime

### Not Planned
- ❌ Single immutable Config dataclass (impractical at 1,065+ scale)
- ❌ Complete refactoring to centralized config (too risky)
- ❌ Removing `EnvConfig` pattern (works well, keep it)

---

**Last Updated:** 2025-11-16  
**Phase:** 2.2a Complete  
**Next:** Phase 2.2b (Validation Layer)
| Debug / Introspection | G6_REFACTOR_DEBUG, G6_LATENCY_PROFILING | Developer diagnostics | Add explicit DEBUG group |
| Compatibility / Legacy | G6_ALLOW_LEGACY_*, G6_SUMMARY_LEGACY | Transitional gating | Add sunset metadata |
| Experimental / Wildcard | suffix '_' patterns (e.g., G6_BENCHMARK_) | Namespacing for sub-flags | Replace with structured composite config |

## 5. Validation Strategy
- Type coercion (int, float, bool, lists) at assembly boundary
- Ranged constraints (e.g., non-negative intervals, percentage 0-1 bounds)
- Mutual exclusivity (legacy vs new pipeline flags)
- Deprecation warnings: log once with suggested replacement
- Stale detection: if documented but unused -> mark for removal (inventory script feeds list)

## 6. Implementation Phases
1. Passive wrapper: introduce `config/loader.py` that centralizes existing reads (no behavior change)
2. Replace scattered `os.getenv` calls with `config.get("NAME")`
3. Introduce grouped dataclasses + validation harness
4. Emit `data/active_config.json` snapshot each run (for support & diff)
5. Enforce allowlist: raise on unknown `G6_` env vars (after stabilization)

## 7. Tooling & Automation
- Extend `scripts/gen_env_inventory.py` to emit JSON for CI diff -> detect new undocumented flags
- Add governance test to assert zero undocumented (with suppression window)
- Optional: script to compare two runtime snapshots -> highlight changes

## 8. Migration Considerations
| Risk | Mitigation |
|------|-----------|
| Hidden dependency on implicit defaults | Log full resolved config early |
| Unexpected type coercion changes | Dual read period with warning logs |
| Deprecation churn | Provide mapping table + removal schedule |

## 9. Immediate Actions (Phase 1 Scope)
- Create loader scaffold file (TBD) – no code changes yet in this draft
- Enumerate groups & map existing flags (derive from `env_dict.md` + auto inventory)
- Tag obviously stale / duplicate toggles for removal candidate list

---
Draft will evolve as config consolidation implementation begins.
