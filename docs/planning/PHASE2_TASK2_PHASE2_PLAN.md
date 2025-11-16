# Phase 2 Task 2 - Phase 2 Migration Plan

**Status**: In Progress  
**Target**: Remaining ~50+ files in src subsystems  
**Estimated Instances**: ~150-200  
**Estimated Time**: 4-6 hours

## Migration Strategy

### Approach: Subsystem by Subsystem
1. **Utils** (remaining 3 files) - Quick wins, low risk
2. **Config** (remaining 2 files) - Medium risk
3. **Metrics** (remaining 2 files) - Medium risk
4. **Events** (4 files) - Medium complexity
5. **Data Access** (1 file) - Low risk
6. **Domain** (1 file) - Low risk
7. **Errors** (1 file) - Low risk
8. **Console** (1 file) - Low risk
9. **Lifecycle** (1 file) - Medium complexity
10. **Column Store** (1 file) - Low risk
11. **Broker** (4 files) - Medium complexity
12. **Direct Collect** (1 file) - Low risk
13. **Collectors** (~20-25 files) - Largest subsystem, save for last

## File Inventory

### 1. Utils (3 files, ~6-8 instances)
- `src/utils/expiry_service.py` (3 instances)
- `src/utils/env_flags.py` (1 instance - helper function)
- `src/utils/color_logging.py` (1 instance)

**Risk**: LOW - Simple utility functions  
**Pattern**: Mostly helper function delegation

### 2. Config (2 files, ~8-10 instances)
- `src/config/runtime_config.py` (6+ instances)
- `src/config/validation.py` (2 instances)

**Risk**: MEDIUM - Configuration loading  
**Pattern**: Mixed types (bool, int, string)

### 3. Metrics (2 files, ~8-10 instances)
- `src/metrics/cardinality_guard.py` (6 instances)
- `src/metrics/adapter.py` (1 instance)

**Risk**: MEDIUM - Cardinality governance  
**Pattern**: Snapshot paths, boolean flags, thresholds

### 4. Events (4 files, ~15-20 instances)
- `src/events/event_log.py` (6 instances)
- `src/events/event_bus.py` (4 instances)
- `src/events/adaptive_degrade.py` (2 instances - helper functions)

**Risk**: MEDIUM - Event system configuration  
**Pattern**: Logging levels, sampling rates, timeouts

### 5. Data Access (1 file, ~10 instances)
- `src/data_access/unified_source.py` (10 instances)

**Risk**: LOW - Data source configuration  
**Pattern**: URLs, paths, priorities, boolean flags

### 6. Domain (1 file, 1 instance)
- `src/domain/snapshots_cache.py` (1 instance)

**Risk**: LOW - Simple boolean flag  
**Pattern**: Standard boolean

### 7. Errors (1 file, 1 instance)
- `src/errors/error_routing.py` (1 instance)

**Risk**: LOW - Error escalation flag  
**Pattern**: Standard boolean

### 8. Console (1 file, 2 instances)
- `src/console/ws_service.py` (2 instances)

**Risk**: LOW - WebSocket service config  
**Pattern**: File path, float timeout

### 9. Lifecycle (1 file, ~8 instances)
- `src/lifecycle/job.py` (8 instances)

**Risk**: MEDIUM - Lifecycle management config  
**Pattern**: Days retention, limits, paths, compression settings

### 10. Column Store (1 file, 3 instances)
- `src/column_store/pipeline.py` (3 instances)

**Risk**: LOW - Pipeline configuration  
**Pattern**: Helper function delegation, table name

### 11. Broker (4 files, ~5-8 instances)
- `src/broker/provider_registry.py` (1 instance)
- `src/broker/kite/client.py` (1 instance)
- `src/broker/kite/provider_events.py` (2 instances)
- `src/broker/kite_instruments.py` (1 instance)

**Risk**: LOW-MEDIUM - Provider configuration  
**Pattern**: Provider selection, timeouts, paths

### 12. Direct Collect (1 file, 2 instances)
- `src/direct_collect.py` (2 instances)

**Risk**: LOW - API credentials  
**Pattern**: String env vars (KITE_API_KEY, KITE_ACCESS_TOKEN)

### 13. Collectors (20-25 files, ~80-100 instances)
**Risk**: HIGH (volume) - Largest subsystem  

**Phase 13a - Core Collectors** (5 files):
- `src/collectors/unified_collectors.py` (~15-20 instances)
- `src/collectors/collector_settings.py` (~5 instances)
- `src/collectors/enhanced_shim.py` (~2 instances)
- `src/collectors/env_adapter.py` (~5 instances - helper functions)

**Phase 13b - Collector Helpers** (3 files):
- `src/collectors/helpers/validation.py` (1 instance)
- `src/collectors/helpers/struct_events.py` (~5 instances)

**Phase 13c - Collector Modules** (4 files):
- `src/collectors/modules/benchmark_bridge.py` (~5 instances)
- `src/collectors/modules/alerts_core.py` (~8 instances)
- `src/collectors/modules/enrichment_async.py` (~3 instances)

## Execution Order (Risk-Optimized)

### Round 1: Quick Wins (Low Risk, High Confidence)
1. Utils (3 files) - Warm up
2. Domain (1 file) - Single boolean
3. Errors (1 file) - Single boolean
4. Console (1 file) - Simple config
5. Direct Collect (1 file) - Simple strings
6. Data Access (1 file) - Straightforward config

**Total Round 1**: 8 files, ~25 instances

### Round 2: Medium Complexity
7. Config (2 files) - Configuration loading
8. Metrics remaining (2 files) - Cardinality guard
9. Column Store (1 file) - Pipeline config
10. Broker (4 files) - Provider configuration

**Total Round 2**: 9 files, ~30 instances

### Round 3: Complex Subsystems
11. Lifecycle (1 file) - Retention/compression config
12. Events (4 files) - Event bus configuration

**Total Round 3**: 5 files, ~25 instances

### Round 4: Collectors (Largest Subsystem)
13. Collectors - Core (4 files)
14. Collectors - Helpers (2 files)
15. Collectors - Modules (3 files)

**Total Round 4**: ~9-12 files, ~80-100 instances

## Success Criteria

- ✅ All files compile without errors
- ✅ All modules import successfully
- ✅ Zero breaking changes
- ✅ Consistent EnvConfig usage throughout
- ✅ Helper functions updated or delegated
- ✅ Type safety maintained/improved

## Validation Plan

After each round:
1. Compile check: `python -m py_compile <files>`
2. Import check: `python -c "import <module>"`
3. Grep validation: No remaining os.getenv/os.environ.get patterns

Final validation:
1. Run full test suite
2. Integration smoke test
3. Comprehensive grep across all src files

## Notes

- **EnvConfig Exclusion**: `src/config/env_config.py` intentionally NOT migrated (it's the implementation)
- **Commented Code**: Lines starting with `#` will not be migrated
- **Environment Writes**: Any `os.environ['VAR'] = value` will be preserved (EnvConfig is read-only)

---

**Phase Lead**: GitHub Copilot  
**Start Date**: 2025-10-25  
**Estimated Completion**: 2025-10-25 (same day if continuous)
