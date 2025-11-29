# Collector Module Context & Debug Log Origin Analysis

**Generated:** November 21, 2025  
**File Analyzed:** `C:\Users\Asus\Desktop\g6_reorganized\logs\debug.log`  
**File Size:** 350.5 MB (350,505,377 bytes)  
**Created:** November 16, 2025 @ 10:43:47 PM  
**Last Modified:** November 21, 2025 @ 5:34:53 PM

---

## Executive Summary

The `debug.log` file originates from the **G6 Platform's three-tier logging system** configured via `src/utils/logging_utils.py`. It contains comprehensive DEBUG-level logs from all collector modules, storage operations, broker interactions, and internal pipeline operations. This log is created by the `setup_logging()` function when the system runs in **development mode** or when explicitly enabled via environment variables.

---

## Origin Trace: debug.log Creation Flow

### 1. **Entry Point: Launch Platform**
```
scripts/launch_platform.py
  ↓
src/utils/logging_utils.py::setup_logging()
  ↓
setup_development() or setup_production()
```

**Code Path:**
```python
# File: scripts/launch_platform.py (lines 45-48)
from src.utils.logging_utils import setup_logging, setup_production

if os.environ.get("G6_ENV") == "production":
    setup_production()
else:
    setup_logging(terminal_level=os.environ.get("G6_LOG_LEVEL", "INFO"))
```

### 2. **Logging Configuration: Three-Tier System**

The logging system implements three distinct tiers:

| Tier | Handler | Level | Format | Purpose |
|------|---------|-------|--------|---------|
| **1. Terminal** | StreamHandler(stdout) | WARNING/INFO/DEBUG | Clean message only | User-facing console |
| **2. Ops** | FileHandler(logs/ops.jsonl) | INFO | JSON structured | Operational monitoring |
| **3. Debug** | FileHandler(logs/debug.log) | DEBUG | Full detail | Developer debugging |

**Configuration Source:** `src/utils/logging_utils.py`

```python
# Tier 3: Debug logs (full detail) - lines 133-147
if debug_file:
    try:
        os.makedirs(os.path.dirname(debug_file), exist_ok=True)
        debug_handler = logging.FileHandler(debug_file, encoding='utf-8')
        debug_handler.setLevel(logging.DEBUG)
        debug_handler.setFormatter(logging.Formatter(FMT_DEBUG))
        root.addHandler(debug_handler)
    except Exception as e:
        root.error("Failed to create debug log handler: %s", e)
```

**Debug Format String (FMT_DEBUG):**
```python
"%(asctime)s - %(threadName)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"
```

### 3. **Environment Variables Controlling debug.log**

| Variable | Default | Effect |
|----------|---------|--------|
| `G6_DEBUG_LOG` | `logs/debug.log` | Path to debug log file |
| `G6_LOG_LEVEL` | INFO (dev) / WARNING (prod) | Terminal logging level |
| `G6_ENV` | development | Determines logging preset |

**Override Example:**
```bash
# Enable debug.log in custom location
$env:G6_DEBUG_LOG="C:\custom\path\debug.log"

# Or disable debug file entirely
$env:G6_DEBUG_LOG=""
```

### 4. **Execution Flow: Orchestrator → Collectors → Logging**

```
scripts/run_orchestrator_loop.py
  ↓
setup_development() → creates debug.log handler
  ↓
src/orchestrator/cycle.py::run_cycle()
  ↓
src/collectors/unified_collectors.py::run_unified_collectors()
  ↓
src/collectors/modules/expiry_processor.py::process_expiry()
  ↓
logger.debug(...) → writes to debug.log
```

---

## Collector Module Architecture

### Core Components

```
src/collectors/
├── unified_collectors.py          # Main entry point (2074 lines)
├── pipeline.py                    # Pipeline abstraction (332 lines)
├── providers_interface.py         # Provider facade
├── cycle_context.py               # Cycle execution context
├── settings.py                    # Collector settings
└── modules/                       # Modular components
    ├── context.py                 # CollectorContext dataclass
    ├── expiry_processor.py        # Per-expiry processing (927 lines)
    ├── expiry_pipeline.py         # Expiry pipeline phases
    ├── expiry_helpers.py          # Expiry helper functions
    ├── index_processor.py         # Index-level processing
    ├── strike_depth.py            # Strike selection logic
    ├── aggregation.py             # PCR & breadth calculations
    ├── coverage_eval.py           # Data completeness metrics
    ├── persistence_io.py          # Data persistence
    ├── metrics_updater.py         # Metrics emission
    ├── enrichment.py              # Quote enrichment
    ├── iv_estimation.py           # Implied volatility calculation
    ├── greeks_compute.py          # Options Greeks
    └── [45+ other modules]        # See full listing below
```

### Data Flow Through Collector Modules

```
┌─────────────────────────────────────────────────────────────┐
│                    COLLECTION CYCLE                          │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  1. Market Gate Check                                        │
│     └─ modules/market_gate.py                               │
│                                                               │
│  2. Index Processing (per index: NIFTY, BANKNIFTY, etc.)   │
│     ├─ modules/index_processor.py                          │
│     ├─ providers_interface.py::get_spot_quote()            │
│     └─ modules/strike_depth.py::compute_strikes()          │
│                                                               │
│  3. Expiry Processing (per expiry: this_week, next_week)   │
│     ├─ modules/expiry_processor.py::process_expiry()       │
│     ├─ Resolve expiry date                                  │
│     ├─ Fetch instruments                                    │
│     ├─ Enrich with quotes                                   │
│     ├─ modules/iv_estimation.py                            │
│     ├─ modules/greeks_compute.py                           │
│     ├─ modules/aggregation.py (PCR, breadth)              │
│     └─ modules/persistence_io.py                           │
│                                                               │
│  4. Cycle Finalization                                      │
│     ├─ modules/metrics_updater.py                          │
│     ├─ modules/status_finalize.py                          │
│     └─ modules/benchmark_bridge.py                         │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### Key Collector Modules (Complete List)

**Context & Configuration:**
- `context.py` - CollectorContext, CollectorConfig dataclasses
- `settings.py` - Collector settings management
- `collector_settings.py` - Legacy settings (deprecated path)
- `env_adapter.py` - Environment variable adapter functions

**Expiry Processing Pipeline:**
- `expiry_processor.py` - Main per-expiry processing logic
- `expiry_pipeline.py` - Pipeline phase orchestration
- `expiry_helpers.py` - Expiry helper utilities
- `expiry_finalize.py` - Expiry finalization phase
- `expiry_types.py` - Expiry type definitions
- `expiry_universe.py` - Expiry universe building

**Data Collection & Enrichment:**
- `index_processor.py` - Index-level data collection
- `enrichment.py` - Quote enrichment (sync)
- `enrichment_async.py` - Quote enrichment (async)
- `prefilter.py` - Pre-filtering logic
- `prefilter_flow.py` - Pre-filter flow orchestration

**Analytics & Calculations:**
- `iv_estimation.py` - Implied volatility estimation
- `greeks_compute.py` - Options Greeks calculation
- `aggregation.py` - PCR, breadth aggregation
- `aggregation_emitter.py` - Aggregation metrics emission
- `aggregation_overview.py` - Overview snapshot generation

**Data Quality & Validation:**
- `coverage_core.py` - Coverage assessment core
- `coverage_eval.py` - Coverage evaluation logic
- `data_quality_bridge.py` - Data quality bridge
- `data_quality_flow.py` - Data quality flow
- `preventive_validate.py` - Preventive validation
- `error_bridge.py` - Error reporting bridge

**Persistence & Storage:**
- `persistence_io.py` - Core persistence I/O
- `persist_flow.py` - Persistence flow orchestration
- `persist_result.py` - Persistence result handling
- `snapshot_core.py` - Snapshot generation core
- `snapshots.py` - Snapshot management

**Metrics & Monitoring:**
- `metrics_updater.py` - Metrics emission
- `alerts_core.py` - Alert generation
- `benchmark_bridge.py` - Benchmark artifact writing
- `status_finalize.py` - Status finalization
- `status_finalize_core.py` - Status finalization core

**Adaptive & Memory Management:**
- `adaptive_adjust.py` - Adaptive strike adjustment
- `adaptive_summary.py` - Adaptive summary
- `memory_adjust.py` - Memory adjustment
- `memory_pressure_bridge.py` - Memory pressure bridge

**Strike Selection:**
- `strike_depth.py` - Strike depth calculation
- `strike_policy.py` - Strike selection policy
- `strike_universe.py` - Strike universe building

**Synthetic Data:**
- `synthetic_fallback.py` - Synthetic data fallback
- `synthetic_quotes.py` - Synthetic quote generation

**Pipeline Components:**
- `pipeline.py` - Main pipeline abstraction
- `shadow_compare.py` - Shadow pipeline comparison
- `formatters.py` - Data formatters
- `market_gate.py` - Market hours gating

**Other Modules:**
- `struct_events_bridge.py` - Structured events bridge
- `helpers/` - Helper functions directory
- `pipeline/` - Pipeline components directory
- `scripts/` - Module-specific scripts
- `docs/` - Module documentation

---

## Recent Activity in debug.log

**Last Activity Timestamp:** November 21, 2025 @ 5:34:53 PM

**Active Components Logging:**

1. **CSV Storage Layer** (`src.storage.csv_sink`)
   - Duplicate row suppression logic
   - Writing options data for NIFTY this_week
   - 13 unique strikes, 26 total options

2. **Expiry Processor** (`src.collectors.modules.expiry_processor`)
   - Processing NIFTY expiries (this_week, next_week)
   - Successfully collected 26 options
   - Trace messages for process stages

3. **Kite Provider** (`src.broker.kite.expiry_discovery`, `src.broker.kite_provider`)
   - Expiry cache hits
   - Resolved 'next_week' → 2025-12-02
   - Instrument cache operations

4. **Status Finalization** (`src.collectors.modules.status_finalize`)
   - Error: `emit_option_match_stats()` missing 'synthetic' argument
   - Type error during metric emission

**Strike Processing:**
```
Collecting 13 strikes for NIFTY next_week:
[25750.0, 25800.0, 25850.0, 25900.0, 25950.0, 26000.0, 26050.0, 
 26100.0, 26150.0, 26200.0, 26250.0, 26300.0, 26350.0]
```

---

## Logging Categories in debug.log

### By Module/Component

| Logger Name | Purpose | Typical Messages |
|-------------|---------|------------------|
| `src.collectors.unified_collectors` | Main collector entry | Cycle start/end, index processing |
| `src.collectors.modules.expiry_processor` | Per-expiry logic | Expiry resolution, strike collection |
| `src.collectors.modules.expiry_helpers` | Expiry utilities | Instrument fetch, quote enrichment |
| `src.collectors.providers_interface` | Provider facade | Index quotes, ATM calculations |
| `src.broker.kite_provider` | Kite API wrapper | API calls, cache hits, rate limiting |
| `src.broker.kite.expiries` | Expiry resolution | Expiry rule resolution |
| `src.broker.kite.options` | Options data | Instrument lookup, cache operations |
| `src.storage.csv_sink` | CSV persistence | Write operations, duplicate handling |
| `src.collectors.modules.status_finalize` | Status generation | Metrics emission, status updates |
| `src.collectors.modules.iv_estimation` | IV calculation | Newton-Raphson solver iterations |
| `src.collectors.modules.greeks_compute` | Greeks calculation | Delta, gamma, theta, vega computation |
| `src.collectors.cycle_context` | Cycle context | Phase timing, context management |

### By Log Level in debug.log

All messages in `debug.log` are at **DEBUG** level by design. The file captures:
- Method entry/exit traces
- Cache hit/miss events
- Detailed API call parameters
- Data transformation steps
- Internal state changes
- Non-critical errors (logged but recovered)
- Performance timing details

---

## Configuration Reference

### Logging Setup Functions

**Development Mode (default):**
```python
from src.utils.logging_utils import setup_development
setup_development()
# Creates: logs/debug.log (DEBUG level, verbose)
# Terminal: INFO level (detailed)
```

**Production Mode:**
```python
from src.utils.logging_utils import setup_production
setup_production()
# Creates: logs/ops.jsonl (INFO level, JSON)
# Terminal: WARNING level (quiet)
# No debug.log created
```

**Custom Configuration:**
```python
from src.utils.logging_utils import setup_logging
setup_logging(
    terminal_level="INFO",
    ops_file="logs/ops.jsonl",
    debug_file="logs/debug.log"
)
```

### Environment Variable Complete Reference

```bash
# Logging Control
$env:G6_DEBUG_LOG="logs/debug.log"          # Enable/configure debug log (auto-rotates daily)
$env:G6_OPS_LOG="logs/ops.jsonl"            # Enable/configure ops log
$env:G6_LOG_LEVEL="INFO"                    # Terminal log level
$env:G6_ENV="development"                   # Environment preset

# Collector Behavior
$env:G6_USE_MOCK_PROVIDER="1"               # Use mock data (no API)
$env:G6_PARALLEL_INDICES="1"                # Parallel index collection
$env:G6_AUTO_SNAPSHOTS="1"                  # Enable auto snapshots
$env:G6_LOOP_MAX_CYCLES="10"                # Limit cycle count

# Debugging
$env:G6_TRACE_EXPIRY_PIPELINE="1"           # Trace expiry pipeline
$env:G6_IMPORT_TRACE="1"                    # Trace module imports
$env:G6_DEBUG_VERBOSE="1"                   # Force all loggers to DEBUG
```

**Note:** Debug logs now automatically rotate daily at midnight, keeping the last 7 days. To customize retention, modify `backupCount` in `src/utils/logging_utils.py`.

---

## Debug Log Analysis Commands

### PowerShell Commands for Log Analysis

```powershell
# Check file size and timestamps
Get-Item "C:\Users\Asus\Desktop\g6_reorganized\logs\debug.log" | 
    Format-List Name, Length, LastWriteTime, CreationTime

# View recent activity (last 50 lines)
Get-Content "logs\debug.log" -Tail 50

# Search for specific module activity
Select-String -Path "logs\debug.log" -Pattern "src.collectors.modules.expiry_processor" -Context 2

# Filter by logger name
Select-String -Path "logs\debug.log" -Pattern "src.storage.csv_sink" | 
    Select-Object -Last 20

# Find errors and exceptions
Select-String -Path "logs\debug.log" -Pattern "ERROR|Exception|Traceback" -Context 5

# Count log entries by module
(Get-Content "logs\debug.log") -match "src\.(collectors|storage|broker)" | 
    ForEach-Object { ($_ -split ' - ')[2] } | 
    Group-Object | Sort-Object Count -Descending

# Check log rotation size (if > 500MB, consider rotation)
if ((Get-Item "logs\debug.log").Length -gt 500MB) {
    Write-Host "Consider rotating debug.log (current size: $((Get-Item "logs\debug.log").Length / 1MB) MB)"
}
```

### Grep Patterns for Common Issues

```bash
# Find all ERROR level messages
grep "ERROR" logs/debug.log

# Trace a specific collection cycle
grep "CYCLE.*#123" logs/debug.log

# Find failed API calls
grep "Failed to.*API" logs/debug.log

# Check data quality issues
grep "data_quality" logs/debug.log | tail -20

# Monitor cache performance
grep "cache_hit\|cache_miss" logs/debug.log | tail -50
```

---

## Log Rotation & Maintenance

### Automatic Daily Rotation (Configured)

The debug log now **automatically rotates daily at midnight**, with intelligent cleanup:

**Rotation Behavior:**
- **Current log:** `logs/debug.log` (today's activity)
- **Rotated logs:** `logs/debug.log.2025-11-21`, `logs/debug.log.2025-11-20`, etc.
- **Retention:** Last 7 days automatically kept
- **Cleanup:** Logs older than 7 days are automatically deleted
- **Rotation time:** Midnight (00:00) local time

**Implementation Details:**
```python
# From src/utils/logging_utils.py
debug_handler = TimedRotatingFileHandler(
    debug_file,
    when='midnight',      # Rotate at midnight
    interval=1,           # Every 1 day
    backupCount=7,        # Keep last 7 days
    encoding='utf-8'
)
debug_handler.suffix = "%Y-%m-%d"  # Date format for rotated files
```

### Current File Status
- **Size:** 350.5 MB (will reset at next midnight)
- **Age:** 5 days (Nov 16 → Nov 21)
- **Growth Rate:** ~70 MB/day (high activity)
- **Next Rotation:** Tonight at midnight (00:00)

### Manual Operations (Optional)

**1. View All Debug Logs:**
```powershell
# List all debug log files
Get-ChildItem "logs\debug.log*" | Format-Table Name, Length, LastWriteTime

# Total size of all debug logs
(Get-ChildItem "logs\debug.log*" | Measure-Object -Property Length -Sum).Sum / 1MB
```

**2. Compress Old Logs (Space Saving):**
```powershell
# Compress logs older than 2 days
Get-ChildItem "logs\debug.log.20*" | 
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-2) } |
    Compress-Archive -DestinationPath "logs\archive\debug_logs_$(Get-Date -Format 'yyyyMMdd').zip"
```

**3. Force Immediate Rotation (Testing):**
```powershell
# Manually trigger rotation by renaming current log
Move-Item "logs\debug.log" "logs\debug.log.$(Get-Date -Format 'yyyy-MM-dd')"
# New debug.log will be created on next log write
```

---

## Troubleshooting: When debug.log is NOT Created

### Common Causes:

1. **Environment Variable Override:**
   ```bash
   # Check if disabled
   echo $env:G6_DEBUG_LOG
   # If empty, debug.log won't be created
   ```

2. **Production Mode Active:**
   ```bash
   echo $env:G6_ENV
   # If "production", debug.log is disabled by default
   ```

3. **Permission Issues:**
   - Check write permissions on `logs/` directory
   - Verify disk space available

4. **Early Initialization Error:**
   - Check terminal output for "Failed to create debug log handler" message

### Solutions:

```powershell
# Force debug log creation
$env:G6_DEBUG_LOG="logs/debug.log"
$env:G6_ENV="development"

# Ensure logs directory exists
New-Item -ItemType Directory -Path "logs" -Force

# Test logging setup
python -c "from src.utils.logging_utils import setup_development; setup_development(); import logging; logging.getLogger('test').debug('Test message')"
```

---

## Documentation References

**Logging System:**
- `docs/LOGGING_SIMPLIFICATION_GUIDE.md` - Complete logging documentation
- `docs/PHASE1_LOGGING_COMPLETE.md` - Phase 1 logging implementation
- `docs/PHASE3_LOGGING_COMPLETE.md` - Phase 3 logging enhancements

**Collector System:**
- `docs/COLLECTOR_SYSTEM_GUIDE.md` - Collector architecture and usage
- `.archived/docs/collector_modules.md` - Collector modularization blueprint
- `README.md` - Section 3: Architecture Snapshot

**Configuration:**
- `docs/operations/ENV_FLAGS_TABLES.md` - Environment variable reference
- `config/g6_config.json` - Runtime configuration

---

## Summary

The `debug.log` file at `C:\Users\Asus\Desktop\g6_reorganized\logs\debug.log` is:

1. **Created by:** `src/utils/logging_utils.py::setup_logging()` function
2. **Triggered by:** Running platform in development mode via `scripts/launch_platform.py` or `scripts/run_orchestrator_loop.py`
3. **Contains:** DEBUG-level logs from all collector modules, providers, storage, and analytics components
4. **Size:** 350.5 MB (high activity, recommend rotation)
5. **Current Activity:** Active NIFTY options collection cycles with strike processing
6. **Control:** Can be enabled/disabled/relocated via `G6_DEBUG_LOG` environment variable

**Primary Contributors to debug.log Volume:**
- Expiry processor module (verbose trace logging)
- CSV sink operations (duplicate suppression)
- Kite provider API calls and caching
- Quote enrichment pipeline
- Status finalization metrics

**Recommendation:** Implement log rotation at 100MB threshold to manage disk usage while preserving debugging capability.
