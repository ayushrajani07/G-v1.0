# Phase 2 Task 2: Metrics Subsystem Migration Plan

## Executive Summary

**Discovery**: The src/metrics/ subsystem contains **~70+ environment variable accesses** across 15+ files that were not included in the original "200+ instances" estimate. This represents a **scope expansion** requiring careful planning.

**Status as of 2025-10-25**:
- **Scripts/**: 97% complete (67/69 files, ~3 instances remaining)
- **Src/ (non-metrics)**: 95% complete (50/52 files, factory.py NOW FIXED)
- **Src/metrics/**: 0% complete (0/15 files, ~70+ instances)
- **Overall Project**: ~73% complete (210/290+ instances)

**Risk Assessment**: **MEDIUM-HIGH**
- Metrics subsystem controls observability, cardinality protection, performance tuning
- Many env vars are read during module initialization (side effects)
- Complex interdependencies between gating, registration, and emission systems
- Test impact: Metrics behavior changes affect test isolation

---

## Metrics Subsystem Architecture

### File Inventory & Instance Counts

| File | Instances | Complexity | Priority | Notes |
|------|-----------|------------|----------|-------|
| `__init__.py` | 15-20 | **CRITICAL** | P0 | Module init, complex flow, side effects |
| `gating.py` | 8-10 | **HIGH** | P1 | Metric group filters, enable/disable |
| `emission_batcher.py` | 9 | **HIGH** | P1 | Batch tuning (interval, size, wait) |
| `cardinality_manager.py` | 3 | MEDIUM | P2 | Already has helper functions |
| `build_info.py` | 3 | LOW | P2 | Build version/commit/hash |
| `group_registry.py` | 1 | LOW | P3 | Banner suppression |
| `introspection_dump.py` | 2 | LOW | P3 | Dump flags |
| `metadata.py` | 1 | LOW | P3 | Helper function wrapper |
| `registration.py` | 3 | MEDIUM | P2 | Strict exception mode |
| `runtime_gates.py` | 1 | LOW | P3 | Per-expiry vol surface gate |
| `scheduler.py` | 1 | LOW | P3 | Strict exception mode |
| **TOTAL** | **47-52** | - | - | Core metrics files only |

### Additional Related Files

| File | Instances | Priority | Notes |
|------|-----------|----------|-------|
| `src/tools/token_providers/kite.py` | 5 | P2 | KITE_* credentials, login config |
| `src/observability/log_emitter.py` | 2 | P2 | G6_LOG_DEDUP_DISABLE, G6_LOG_SCHEMA_COMPAT |
| `scripts/benchmark_cycles.py` | 1 | P3 | Deprecation wrapper |
| `scripts/bench_aggregate.py` | 1 | P3 | Deprecation wrapper |
| `scripts/debug/debug_mode.py` | 1 | P3 | CONFIG_PATH override |

---

## Critical Concerns: src/metrics/__init__.py

### Why This File is High-Risk

```python
# Current structure (pseudo-code):
import os as __os

# Module-level side effects during import:
_prev_ctx = __os.getenv('G6_METRICS_IMPORT_CONTEXT')
# ... complex initialization logic ...

if __os.getenv('G6_FORCE_NEW_REGISTRY'):
    # Create new registry
    
if _is_truthy_env('G6_METRICS_EAGER_INTROSPECTION'):
    # Trigger early introspection
    
# At module exit:
if want_introspection_dump and not __os.getenv('G6_METRICS_SUPPRESS_AUTO_DUMPS'):
    # Auto-dump metrics on exit
```

**Challenges**:
1. **Module init side effects**: Env vars read during `import metrics`
2. **Aliased os import**: Uses `__os` to avoid namespace collision
3. **Complex boolean logic**: Multiple truthy checks, suppression flags
4. **atexit handlers**: Exit-time behavior controlled by env vars
5. **Test isolation**: Many tests mock `os.environ` for metrics behavior

### Migration Strategy for __init__.py

**Phase 1: Preparation (NO CODE CHANGES)**
1. Read entire file, document all env var usages
2. Map dependencies: which env vars interact?
3. Identify test files that mock metrics env vars
4. Create rollback plan

**Phase 2: Incremental Migration**
1. Add EnvConfig import ONLY (no usage changes yet)
2. Run full test suite → confirm no import-time breakage
3. Migrate simple cases first (single reads, no logic)
4. Run tests after EACH migration
5. Migrate complex cases last (nested conditions, atexit)

**Phase 3: Validation**
1. Run metrics-specific tests with coverage
2. Verify cardinality protection still works
3. Check introspection dumps generate correctly
4. Validate test isolation (no cross-test pollution)

---

## Environment Variables by Category

### 1. Metrics Gating & Filtering (gating.py)
```python
G6_ENABLE_METRIC_GROUPS       # Comma-separated allowlist
G6_DISABLE_METRIC_GROUPS      # Comma-separated blocklist
G6_METRICS_GATING_TRACE       # Boolean: log gating decisions
G6_METRICS_GROUP_FILTERS_LOG_EVERY_CALL  # Boolean: verbose logging
G6_SUPPRESS_GROUPED_METRICS_BANNER       # Boolean: hide startup banner
```

**Migration Pattern**: Boolean flags → `EnvConfig.get_bool()`, CSV lists → `EnvConfig.get_list()`

**Test Impact**: HIGH - many tests use these to control which metrics run

### 2. Emission & Batching (emission_batcher.py)
```python
G6_EMISSION_BATCH_TARGET_INTERVAL_MS  # Float: target batch interval (default 200ms)
G6_EMISSION_BATCH_MIN_SIZE            # Int: min batch size (default 50)
G6_EMISSION_BATCH_MAX_SIZE            # Int: max batch size (default 5000)
G6_EMISSION_BATCH_UNDER_UTIL_THRESHOLD  # Float: utilization threshold (default 0.3)
G6_EMISSION_BATCH_UNDER_UTIL_CONSEC   # Int: consecutive cycles (default 3)
G6_EMISSION_BATCH_DECAY_ALPHA_IDLE    # Float: decay alpha (default 0.6)
G6_EMISSION_BATCH_MAX_WAIT_MS         # Float: max wait time (default 750ms)
```

**Migration Pattern**: All numeric with defaults → `EnvConfig.get_int()` / `get_float()`

**Test Impact**: LOW - mostly performance tuning, rarely mocked in tests

### 3. Cardinality Protection (cardinality_manager.py)
```python
G6_CARDINALITY_MAX_SERIES      # Int: max series (default 200000) - ALREADY MIGRATED
G6_CARDINALITY_MIN_DISABLE_SECONDS  # Int: min disable time (default 600) - ALREADY MIGRATED
G6_CARDINALITY_REENABLE_FRACTION    # Float: reenable fraction (default 0.90) - ALREADY MIGRATED
G6_CARDINALITY_SNAPSHOT        # String: snapshot file path
```

**Status**: 3/4 migrated (orchestrator/cardinality_guard.py), 1 remains in cardinality_manager.py

**Migration Pattern**: Helper functions already exist, just delegate to EnvConfig

### 4. Build Info & Metadata (build_info.py, metadata.py)
```python
G6_BUILD_VERSION        # String: build version (default 'unknown')
G6_BUILD_COMMIT         # String: git commit hash (default 'unknown')
G6_BUILD_CONFIG_HASH    # String: config hash (default 'unknown')
```

**Migration Pattern**: Simple string reads → `EnvConfig.get_str()`

**Test Impact**: NONE - metadata only, not tested

### 5. Introspection & Dumps (__init__.py, introspection_dump.py)
```python
G6_METRICS_INTROSPECTION_DUMP    # String/Boolean: dump file path or flag
G6_METRICS_INIT_TRACE_DUMP       # String/Boolean: init trace file path
G6_METRICS_SUPPRESS_AUTO_DUMPS   # Boolean: disable auto-dumps on exit
G6_METRICS_EAGER_INTROSPECTION   # Boolean: trigger early introspection
```

**Migration Pattern**: Mixed string/boolean → needs careful analysis of usage context

**Test Impact**: MEDIUM - some tests check dump generation

### 6. Strict Mode & Exception Handling (registration.py, scheduler.py)
```python
G6_METRICS_STRICT_EXCEPTIONS  # Boolean: fail fast on metric errors (default False)
```

**Migration Pattern**: Boolean → `EnvConfig.get_bool()`

**Test Impact**: MEDIUM - error handling tests may depend on this

### 7. Feature Flags (runtime_gates.py)
```python
G6_VOL_SURFACE_PER_EXPIRY  # Boolean: '1' to enable per-expiry vol surface metrics
```

**Migration Pattern**: Exact match check → `EnvConfig.get_bool()` or `get_str() == '1'`

**Test Impact**: LOW - feature flag, rarely tested

### 8. Credential Management (tools/token_providers/kite.py)
```python
KITE_REQUEST_TOKEN    # String: manual request token override
KITE_REDIRECT_HOST    # String: OAuth callback host (default '127.0.0.1')
KITE_REDIRECT_PORT    # Int: OAuth callback port (default 5000)
KITE_REDIRECT_PATH    # String: OAuth callback path (default 'success')
KITE_LOGIN_TIMEOUT    # Int: login timeout seconds (default 180)
```

**Migration Pattern**: Mixed types → appropriate EnvConfig method per type

**Test Impact**: LOW - auth code rarely unit tested

### 9. Logging Configuration (observability/log_emitter.py)
```python
G6_LOG_DEDUP_DISABLE   # Boolean: disable log deduplication (inverted logic!)
G6_LOG_SCHEMA_COMPAT   # Boolean: enable schema compatibility mode
```

**Migration Pattern**: Inverted boolean → careful with defaults!

**Test Impact**: MEDIUM - log tests may check these

### 10. Registry Control (__init__.py)
```python
G6_FORCE_NEW_REGISTRY         # Boolean: force new registry creation
G6_METRICS_IMPORT_CONTEXT     # String: import context tracking
```

**Migration Pattern**: Boolean + string → `get_bool()` + `get_str()`

**Test Impact**: **CRITICAL** - many tests use G6_FORCE_NEW_REGISTRY for isolation

---

## Migration Sequence (Recommended Order)

### Phase 1: Low-Risk Quick Wins (2-3 hours)
**Goal**: Complete remaining scripts + simple metrics files

1. ✅ **scripts/benchmark_cycles.py** (1 instance - deprecation flag)
2. ✅ **scripts/bench_aggregate.py** (1 instance - deprecation flag)
3. ✅ **scripts/debug/debug_mode.py** (1 instance - config path)
4. ✅ **src/metrics/build_info.py** (3 instances - build metadata)
5. ✅ **src/metrics/metadata.py** (1 instance - helper wrapper)
6. ✅ **src/metrics/group_registry.py** (1 instance - banner suppression)
7. ✅ **src/metrics/runtime_gates.py** (1 instance - feature flag)
8. ✅ **src/metrics/introspection_dump.py** (2 instances - dump flags)
9. ✅ **src/metrics/scheduler.py** (1 instance - strict mode)

**Validation**: Run `pytest tests/test_metrics.py -v` after EACH file

### Phase 2: Medium-Risk Files (3-4 hours)
**Goal**: Migrate files with moderate complexity

10. ✅ **src/metrics/cardinality_manager.py** (3 instances - helper functions)
11. ✅ **src/metrics/registration.py** (3 instances - strict exception mode)
12. ✅ **src/tools/token_providers/kite.py** (5 instances - credentials)
13. ✅ **src/observability/log_emitter.py** (2 instances - **inverted boolean!**)
14. ✅ **src/metrics/emission_batcher.py** (9 instances - batch tuning)
    - Has helper function `_getenv()` that can delegate to EnvConfig
    - All numeric conversions, straightforward

**Validation**: 
- Run `pytest tests/test_metrics.py tests/test_utils.py -v`
- Check cardinality protection: `pytest tests/test_cardinality.py -v`
- Validate batching: `pytest tests/test_emission.py -v`

### Phase 3: High-Risk Files (4-6 hours)
**Goal**: Migrate complex metric gating system

15. ✅ **src/metrics/gating.py** (8-10 instances)
    - G6_ENABLE_METRIC_GROUPS, G6_DISABLE_METRIC_GROUPS (CSV lists)
    - G6_METRICS_GATING_TRACE (boolean)
    - G6_METRICS_GROUP_FILTERS_LOG_EVERY_CALL (boolean)
    - Multiple reads of same env vars in different functions
    - **Strategy**: 
      - Migrate simple boolean flags first
      - Migrate CSV list parsing last (use `EnvConfig.get_list()`)
      - Keep verbose logging to catch issues

**Validation**:
- Run full metrics test suite: `pytest tests/test_metrics*.py -v`
- Check test isolation: `pytest tests/ -k "metric" --tb=short -x`
- Validate gating logic: manually test with G6_ENABLE_METRIC_GROUPS set

### Phase 4: CRITICAL - __init__.py (6-8 hours)
**Goal**: Migrate the most complex file with maximum safety

16. ✅ **src/metrics/__init__.py** (15-20 instances)
    - **PRE-MIGRATION TASKS**:
      - [ ] Read entire file, create instance map
      - [ ] Document all env vars + their interactions
      - [ ] Identify all test files that mock metrics env
      - [ ] Create detailed rollback plan
      - [ ] Backup current file
    
    - **MIGRATION STEPS**:
      1. Add EnvConfig import only → test
      2. Migrate G6_METRICS_IMPORT_CONTEXT (simple string) → test
      3. Migrate G6_BUILD_CONFIG_HASH usage → test
      4. Migrate G6_FORCE_NEW_REGISTRY (boolean) → test carefully!
      5. Migrate introspection dump flags → test
      6. Migrate suppress flags → test
      7. Final validation: run ENTIRE test suite

**Validation Checklist for __init__.py**:
- [ ] `pytest tests/ --tb=short -x` (full suite, fail fast)
- [ ] `pytest tests/test_metrics*.py -v` (metrics-specific)
- [ ] `pytest tests/test_orchestrator.py -v` (integration)
- [ ] Manual smoke test: run orchestrator loop for 5 cycles
- [ ] Check metrics endpoint: `curl http://127.0.0.1:9108/metrics`
- [ ] Verify no import errors: `python -c "from src import metrics; print('OK')"`
- [ ] Check test isolation: run tests 3x in a row, confirm consistent results

---

## Testing Strategy

### Unit Test Validation (After Each File)
```bash
# Quick syntax check
python -m py_compile src/metrics/<file>.py

# Import validation
python -c "from src.metrics import <module>; print('OK')"

# Targeted tests
pytest tests/test_metrics.py::<specific_test> -v
```

### Integration Test Validation (After Each Phase)
```bash
# Phase 1: Low-risk
pytest tests/test_metrics.py tests/test_utils.py -v

# Phase 2: Medium-risk
pytest tests/test_metrics*.py tests/test_cardinality.py -v

# Phase 3: High-risk
pytest tests/test_metrics*.py tests/test_gating.py -v --tb=short

# Phase 4: CRITICAL
pytest tests/ --tb=short -x  # Full suite, fail fast
```

### Smoke Test (After Phase 4)
```bash
# Start metrics server
python scripts/start_metrics_server.py --port 9108 &

# Run orchestrator for 5 cycles
G6_LOOP_MAX_CYCLES=5 python scripts/run_orchestrator_loop.py

# Check metrics endpoint
curl http://127.0.0.1:9108/metrics | grep g6_

# Verify cardinality protection
curl http://127.0.0.1:9108/metrics | grep g6_cardinality

# Check batch emission stats
curl http://127.0.0.1:9108/metrics | grep g6_emission_batch
```

---

## Risk Mitigation

### High-Risk Scenarios

1. **Test Isolation Breakage**
   - **Risk**: Tests that mock `os.environ` for metrics config will break
   - **Mitigation**: 
     - EnvConfig cache may need test fixtures to clear between tests
     - Document which tests need `monkeypatch.setenv()` updates
     - Consider adding `EnvConfig.clear_cache()` method for tests

2. **Import-Time Side Effects**
   - **Risk**: Metrics __init__.py reads env vars during module import
   - **Mitigation**:
     - Add EnvConfig import first, test immediately
     - Migrate one variable at a time
     - Run import test after EACH change: `python -c "import src.metrics"`

3. **Cardinality Protection Failure**
   - **Risk**: Misconfiguration could disable cardinality limits
   - **Mitigation**:
     - Test with actual high-cardinality scenario
     - Verify G6_CARDINALITY_MAX_SERIES still enforced
     - Check logs for cardinality warnings

4. **Batch Emission Degradation**
   - **Risk**: Wrong default values could hurt performance
   - **Mitigation**:
     - Benchmark before/after migration
     - Monitor batch size distribution
     - Verify target interval still respected

5. **Gating Logic Inversion**
   - **Risk**: Enable/disable lists could swap behavior
   - **Mitigation**:
     - Unit tests for each gating scenario
     - Manual test with G6_ENABLE_METRIC_GROUPS="core,adaptive"
     - Verify metrics are actually emitted/suppressed

### Rollback Plan

**Per-File Rollback**:
```bash
# If a single file causes issues:
git checkout HEAD -- src/metrics/<file>.py
pytest tests/test_metrics.py -v  # Verify rollback works
```

**Full Metrics Rollback**:
```bash
# If multiple metrics files have issues:
git checkout HEAD -- src/metrics/
git checkout HEAD -- src/observability/log_emitter.py
git checkout HEAD -- src/tools/token_providers/kite.py
pytest tests/ --tb=short -x  # Full validation
```

**Nuclear Option**:
```bash
# If entire migration needs rollback:
git revert <migration-commit-range>
# Or restore from backup branch
```

---

## Success Criteria

### Phase 1 Complete (Scripts + Simple Metrics)
- [ ] All 13 simple files migrated (scripts + low-risk metrics)
- [ ] Zero compilation errors
- [ ] `pytest tests/test_metrics.py -v` passes 100%
- [ ] Import validation: `python -c "from src.metrics import build_info; print('OK')"`

### Phase 2 Complete (Medium-Risk Metrics)
- [ ] 5 medium-risk files migrated
- [ ] Cardinality tests pass: `pytest tests/test_cardinality.py -v`
- [ ] Emission tests pass: `pytest tests/test_emission.py -v`
- [ ] Kite auth still works: manual login test

### Phase 3 Complete (Gating System)
- [ ] gating.py fully migrated
- [ ] Gating tests pass: `pytest tests/test_gating.py -v`
- [ ] Manual gating test: verify metric groups enable/disable correctly
- [ ] No test isolation issues

### Phase 4 Complete (__init__.py)
- [ ] __init__.py fully migrated
- [ ] Full test suite passes: `pytest tests/ --tb=short -x`
- [ ] Smoke test: 5-cycle orchestrator run succeeds
- [ ] Metrics endpoint healthy: `/metrics` returns expected data
- [ ] No import errors across codebase

### Overall Migration Complete
- [ ] **100% of production code migrated** (0 os.environ.get in src/ and scripts/, excluding env_config.py)
- [ ] **All tests pass** (pytest tests/ with 100% pass rate)
- [ ] **Performance validated** (batch emission metrics show no degradation)
- [ ] **Documentation complete** (PHASE2_TASK2_COMPLETION.md written)
- [ ] **Grep verification**: `grep -r "os\.environ\.get\|os\.getenv" src/ scripts/ | grep -v "env_config.py" | grep -v "external/"` returns 0 results

---

## Estimated Effort

| Phase | Files | Instances | Time Estimate | Cumulative |
|-------|-------|-----------|---------------|------------|
| Phase 1: Quick Wins | 9 | 13 | 2-3 hours | 2-3 hours |
| Phase 2: Medium-Risk | 5 | 22 | 3-4 hours | 5-7 hours |
| Phase 3: Gating | 1 | 8-10 | 4-6 hours | 9-13 hours |
| Phase 4: __init__.py | 1 | 15-20 | 6-8 hours | 15-21 hours |
| **TOTAL** | **16** | **58-65** | **15-21 hours** | - |

**Note**: This is the REMAINING effort for metrics subsystem only. Already completed: ~210 instances across 64 files.

---

## Alternative Approach: Staged Rollout

If the full migration seems too risky, consider a **staged rollout**:

### Stage 1: Scripts Only (Already 97% Done)
- Complete 3 remaining scripts files
- Ship as Phase 2 Task 2.1 completion
- **ETA**: 30 minutes

### Stage 2: Non-Critical Metrics (Low-Risk)
- Migrate metadata, build_info, introspection_dump, scheduler
- Ship as Phase 2 Task 2.2 completion
- **ETA**: 2 hours

### Stage 3: Emission & Cardinality (Medium-Risk)
- Migrate emission_batcher, cardinality_manager, registration
- Ship as Phase 2 Task 2.3 completion
- **ETA**: 4 hours

### Stage 4: Gating System (High-Risk)
- Migrate gating.py
- Ship as Phase 2 Task 2.4 completion
- **ETA**: 6 hours

### Stage 5: Core __init__.py (CRITICAL)
- Migrate __init__.py with maximum care
- Ship as Phase 2 Task 2.5 completion (final)
- **ETA**: 8 hours

**Benefit**: Each stage is independently shippable, reducing risk of large monolithic migration.

---

## Recommendation

**Proposed Next Steps**:

1. **IMMEDIATE** (30 min): Complete remaining 3 scripts files → declare scripts/ 100% complete

2. **SHORT TERM** (2 hours): Migrate Phase 1 low-risk metrics files → get to 85% overall completion

3. **DECISION POINT**: After Phase 1, assess:
   - Test results: any unexpected failures?
   - Team velocity: comfortable proceeding?
   - Risk appetite: continue to Phase 2-4 or pause?

4. **MEDIUM TERM** (4-6 hours): If Phase 1 succeeds, continue with Phase 2-3

5. **LONG TERM** (6-8 hours): Phase 4 (__init__.py) requires dedicated focus session, ideally with:
   - Fresh mental state (start of day)
   - Full test suite passing beforehand
   - Rollback plan tested and ready
   - Time buffer for unexpected issues

**Overall Timeline**: 15-21 hours remaining effort, spread over 3-4 sessions.

---

## Open Questions

1. **EnvConfig Cache Behavior**: Does EnvConfig cache env var reads? If so, how do tests clear cache between runs?

2. **Test Fixtures**: Are there existing test fixtures that mock os.environ? Will they need updates?

3. **Metrics Registry Lifecycle**: How does G6_FORCE_NEW_REGISTRY interact with test isolation?

4. **Batch Emission Performance**: What are acceptable batch size/interval ranges? Need baselines.

5. **Cardinality Snapshot Format**: Is G6_CARDINALITY_SNAPSHOT file format stable? Need to preserve compatibility.

---

## Appendix: Quick Reference

### EnvConfig API Mapping
```python
# Boolean
os.environ.get('VAR','').lower() in ('1','true','yes','on')
→ EnvConfig.get_bool('VAR', False)

# Integer
int(os.environ.get('VAR', '100'))
→ EnvConfig.get_int('VAR', 100)

# Float
float(os.environ.get('VAR', '1.5'))
→ EnvConfig.get_float('VAR', 1.5)

# String
os.environ.get('VAR', 'default')
→ EnvConfig.get_str('VAR', 'default')

# CSV List
os.environ.get('VAR', '').split(',')
→ EnvConfig.get_list('VAR', [])

# Required (fail if missing)
os.environ['VAR']  # raises KeyError
→ EnvConfig.require('VAR')
```

### Common Pitfalls
```python
# ❌ WRONG - loses or-chain fallback
os.environ.get('VAR') or 'default'
→ EnvConfig.get_str('VAR', '')  # BREAKS!

# ✅ CORRECT
os.environ.get('VAR') or 'default'
→ EnvConfig.get_str('VAR', '') or 'default'

# ❌ WRONG - inverted logic
os.environ.get('VAR','').lower() not in ('1','true')
→ EnvConfig.get_bool('VAR', False)  # BREAKS!

# ✅ CORRECT
os.environ.get('VAR','').lower() not in ('1','true')
→ not EnvConfig.get_bool('VAR', False)
```

---

**Document Version**: 1.0  
**Created**: 2025-10-25  
**Last Updated**: 2025-10-25  
**Status**: PLANNING - Awaiting approval to proceed
