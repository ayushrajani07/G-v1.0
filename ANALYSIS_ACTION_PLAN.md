# Action Plan: Addressing Core Project Inconsistencies

**Based on:** CORE_PROJECT_ANALYSIS.md  
**Created:** 2025-11-15  
**Priority:** Immediate Action Required

---

## Current Baseline and Next Steps

**Baseline (2025-11-16):** Full test suite green in parallel (1462 passed, 539 skipped). Recent hygiene fixes improve observability and stability (resilient metrics gauge, cardinality guard fast-path, stable shadow meta, parameterized logging).

**Progress Update (2025-11-16):**
- ✅ Phase 1.1 Exception Handling: **ONGOING** - Reduced from ~3,244 to 1,859 bare exceptions (43% reduction)
  - ✅ Multiple PRs merged: collectors layer, status_writer, catalog_http, expiry_processor, pipeline files
  - ✅ Storage layer: COMPLETED (8 handlers fixed)
  - 🔄 Current branch: copilot/replace-bare-exceptions-pipeline
- ✅ Phase 1.2 Legacy Loop Removal: **COMPLETED** (removed 2025-09-28, verified 2025-11-16)
- ✅ Phase 1.3 CSV Writer Consolidation: **ALREADY COMPLETE** (verified 2025-11-16 - was misconception)
- ✅ Deprecation Cleanup: Multiple items completed (scripts, env vars - see Phase 2.3 below)
- ✅ Test Infrastructure: Serial marker usage reduced to 1 test (from 50+)

**Immediate Next Steps:**
- Continue Phase 1 exception handling in remaining modules (dashboard, provider, validation)
- ✅ Legacy orchestration loop removal - **COMPLETED** (already removed 2025-09-28)

**Quick Validation:**
```powershell
. .venv\Scripts\Activate.ps1
python -m pytest -n auto
```

---

## Executive Action Items

This document provides a concrete, prioritized action plan to address the fundamental inconsistencies and weak points identified in the core project analysis.

---

## Phase 1: Critical Issues (Weeks 1-5)

### 1.1 Exception Handling Remediation

**Goal:** Reduce bare `except Exception:` from 3,244 to <500

**Status:** 🔄 IN PROGRESS - **43% Complete** (reduced to 1,859 as of 2025-11-16)

**Completed Work (Weeks 1-3):**
- ✅ Collectors layer: ~400+ handlers fixed across multiple files
- ✅ Pipeline infrastructure: All pipeline.py files updated
- ✅ Expiry processor: 53 handlers with specific exceptions
- ✅ Catalog HTTP: 65 handlers properly typed
- ✅ Status writer: 34 handlers refactored
- ✅ **Storage layer: 8 handlers fixed (COMPLETED 2025-11-16)**
- ✅ PRs merged: #11, #12, #13, #14

**Current Branch:** `copilot/replace-bare-exceptions-pipeline`

**Remaining Work by Priority:**

#### **Week 3: Storage Layer (HIGH PRIORITY - Data Integrity)**
**Status:** ✅ **COMPLETED** (2025-11-16) - Zero bare exceptions remaining!

**Completed fixes:**
- ✅ `src/storage/csv_batcher.py` - 2 handlers fixed (defensive logging)
- ✅ `src/storage/file_buffer_manager.py` - 3 handlers fixed (file close safety)
- ✅ `src/storage/parquet_sink.py` - 2 handlers fixed (PyArrow error handling)
- ✅ `src/storage/csvio/backends/filesystem.py` - 1 handler fixed (CSV write safety)

**Changes applied:**
- Replaced bare `except Exception:` with `except (OSError, RuntimeError):` for defensive logging fallbacks
- All storage layer files now use specific exception types
- Maintained critical stderr fallback for logging failures

**Action Plan (Minimal Work - Can complete in 1-2 days):**
```powershell
# Verify current count (should be 8)
(Get-ChildItem -Path "src\storage" -Filter "*.py" -Recurse | 
  Select-String -Pattern "except Exception:" -CaseSensitive).Count

# Get specific locations
Get-ChildItem -Path "src\storage" -Filter "*.py" -Recurse | 
  Select-String -Pattern "except Exception:" -CaseSensitive | 
  Select-Object Path, LineNumber

# Target exceptions to introduce:
# - IOError / OSError for file operations
# - PermissionError for access issues  
# - csv.Error for CSV-specific issues
# - ValueError / BufferError for buffer operations
```

**Storage Layer Pattern:**
```python
# Before:
try:
    with open(path, 'w') as f:
        writer.writerow(data)
except Exception as e:
    logger.error(f"Write failed: {e}")

# After:
try:
    with open(path, 'w') as f:
        writer.writerow(data)
except (IOError, OSError, PermissionError) as e:
    logger.error(f"File operation failed: {e}", exc_info=True)
    raise StorageError(f"Failed to write {path}") from e
except csv.Error as e:
    logger.error(f"CSV formatting error: {e}", exc_info=True)
    raise DataFormatError("Invalid CSV data") from e
except Exception as e:
    logger.critical(f"Unexpected storage error: {e}", exc_info=True)
    raise  # Always re-raise unexpected errors
```

#### **Week 4: Web Dashboard Layer (MEDIUM-HIGH PRIORITY)**
Files identified with many bare exceptions:
- `src/web/dashboard/core/csv_io.py` - 26 handlers
- `src/web/dashboard/core/obs.py` - 5 handlers
- `src/web/dashboard/services/forecast_core.py` - 6 handlers
- `src/web/dashboard/routes/*.py` - Multiple handlers

**Dashboard-Specific Exceptions:**
```python
# Introduce these custom exceptions:
class DashboardError(Exception): pass
class DataLoadError(DashboardError): pass
class RenderError(DashboardError): pass
class APIError(DashboardError): pass

# Pattern:
try:
    data = load_csv_for_dashboard(path)
    render_chart(data)
except FileNotFoundError as e:
    logger.warning(f"Data file missing: {path}")
    return {"error": "No data available", "status": 404}
except (IOError, PermissionError) as e:
    logger.error(f"Cannot read data: {e}")
    return {"error": "Data access error", "status": 500}
except (ValueError, KeyError) as e:
    logger.error(f"Invalid data format: {e}")
    return {"error": "Data format error", "status": 422}
```

#### **Week 5: Provider & Validation Layers**
Remaining files:
- `src/provider/*.py` - 11 handlers across multiple files
- `src/validation/preventive_validator.py` - 4 handlers

**Provider-Specific Pattern:**
```python
from src.broker.kite.exceptions import (
    KiteAuthError,
    KiteNetworkError,
    KiteRateLimitError,
    KiteDataError
)

try:
    instruments = provider.get_instruments()
except KiteAuthError as e:
    logger.error("Authentication failed", exc_info=True)
    # Re-authenticate or fail gracefully
    raise
except KiteRateLimitError as e:
    logger.warning("Rate limited, backing off")
    time.sleep(backoff_seconds)
    # Retry logic
except KiteNetworkError as e:
    logger.warning(f"Network error: {e}")
    # Implement retry with exponential backoff
except KiteDataError as e:
    logger.error(f"Invalid data from provider: {e}")
    return []  # Return empty, let coverage metrics handle
```

**Tracking & Validation:**
```powershell
# Create tracking file for each PR
$timestamp = Get-Date -Format "yyyy-MM-dd"
$count = (Get-ChildItem -Path "src" -Filter "*.py" -Recurse | 
         Select-String -Pattern "except Exception:" -CaseSensitive).Count
"$timestamp,$count" | Add-Content -Path "exceptions_progress.csv"

# Generate diff report
git diff main --stat -- "*.py" | Select-String "src/"
```

**Success Metrics:**
- Baseline: 3,244 bare exceptions (2025-11-15)
- Current: 1,859 bare exceptions (2025-11-16) - **43% reduction**
- Target: <500 bare exceptions
- Progress: 1,385 handlers fixed across 6 major areas
- ✅ Storage layer: COMPLETED (0 remaining)
- No test failures introduced
- Error handling coverage >80% in affected modules

**Revised Estimate for Remaining Work:**
- Week 3-4: Dashboard layer (40+ handlers) = ~1 week
- Week 4: Provider (11 handlers) + Validation (4 handlers) = ~3 days  
- Week 5: Final cleanup + documentation = ~2 days
- **Estimated completion:** End of Week 5 (on track!)

**Pattern to Apply:**
```python
# Replace this pattern:
try:
    operation()
except Exception as e:
    logger.error(f"Failed: {e}")

# With this:
try:
    operation()
except SpecificError as e:
    logger.error(f"Expected error: {e}", exc_info=True)
    # Handle appropriately
except Exception as e:
    logger.critical(f"Unexpected error: {e}", exc_info=True)
    raise  # Always re-raise unexpected errors
```

**Deliverable:** Exception handling audit report with metrics

---

### 1.2 Legacy Loop Removal

**Goal:** Remove deprecated orchestration loop

**Status:** ✅ **COMPLETED** (2025-09-28) - Already removed!

**Verification:**
```powershell
# Verify removal
python -m pytest tests/test_safeguard_legacy_loop_removed.py -v
# Result: PASSED - No legacy loop tokens in active code
```

**What Was Done:**
- ✅ `unified_main.collection_loop` function **REMOVED**
- ✅ `src/unified_main.py` converted to fail-fast stub
- ✅ `G6_ENABLE_LEGACY_LOOP` flag handling **REMOVED**
- ✅ `G6_SUPPRESS_LEGACY_LOOP_WARN` flag **REMOVED**
- ✅ Related tests converted to skip stubs
- ✅ Safeguard test added (`test_safeguard_legacy_loop_removed.py`)
- ✅ Documentation updated in DEPRECATIONS.md

**Files Modified (Historical):**
```
✅ src/unified_main.py - Converted to RuntimeError stub
✅ tests/test_legacy_loop_gating.py - Converted to skip stub
✅ tests/test_deprecation_legacy_loop.py - Converted to skip stub
✅ tests/test_safeguard_legacy_loop_removed.py - Added safeguard
✅ docs/DEPRECATIONS.md - Marked as removed 2025-09-28
```

**Remaining Cleanup (Optional):**
- Documentation still references the flag in historical context (docs/env_dict.md)
- These are acceptable as they explain what was removed

**Deliverable:** ✅ Legacy loop fully removed, safeguards in place

---

### 1.3 CSV Writer Consolidation

**Goal:** Single CSV write implementation

**Status:** ✅ **ALREADY COMPLETE** - Verified 2025-11-16

**Actual Current State (After Investigation):**
- ✅ Single write path: `CsvWriter` + `CsvBatcher` used by `CsvSink`
- ✅ `csvio` is an **optional async writer thread** feature, not a competing implementation
- ✅ `G6_USE_CSVIO_FACADE` flag only enables/disables async writer thread (performance feature)
- ✅ Tests verify both sync and async paths work correctly
- ✅ **No parallel implementations** - misconception in original analysis

**Architecture (Verified):**
```
CsvSink (main API)
  ├── CsvWriter (low-level I/O) ✅ Single implementation
  ├── CsvBatcher (buffering) ✅ Single implementation  
  ├── CsvAggregator (overview) ✅ Single implementation
  └── csvio/writer_thread (OPTIONAL async feature)
       └── Uses CsvWriter internally when enabled
```

**What `G6_USE_CSVIO_FACADE` Actually Does:**
- When `=1`: Enables async writer thread for improved throughput
- When `=0`: Uses synchronous writes (default, simpler)
- Both paths use the same `CsvWriter` + `CsvBatcher` underneath

**Files Inventory:**
- `src/storage/csv_sink.py` - Main API ✅
- `src/storage/csv_writer.py` - Low-level I/O ✅
- `src/storage/csv_batcher.py` - Buffering ✅
- `src/storage/csv_aggregator.py` - Overview ✅
- `src/storage/csvio/*` - Optional async thread feature ✅

**Test Coverage:**
- `test_aggregator_facade_compat.py` - Tests both sync/async ✅
- `test_batcher_facade_compat.py` - Tests both sync/async ✅
- `test_atomic_concurrency.py` - Concurrency safety ✅
- All tests pass with facade on/off ✅

**Conclusion:**
Original action plan was based on misunderstanding. The consolidation is already complete. The `G6_USE_CSVIO_FACADE` flag is not a technical debt item - it's a legitimate performance feature flag. **No action needed.**

**Optional Enhancement (Low Priority):**
Could rename `G6_USE_CSVIO_FACADE` to `G6_CSV_ASYNC_WRITES` for clarity, but current name is acceptable.

---

## Phase 2: High Priority (Weeks 4-7)

### 2.1 Test Infrastructure Cleanup

**Goal:** Eliminate global state and simplify markers

**Problems:**
- `serial` marker indicates 50+ tests with global state
- `metrics_no_reset` suggests fixture isolation issues
- 8 different test categories with env variable gates

**Action Items:**
- [x] Week 4: Audit all `@pytest.mark.serial` tests - **COMPLETED** (reduced from 50+ to 1)
- [x] Week 4-5: Refactor tests to remove global state - **COMPLETED**
- [x] Week 5: Fix metrics registry isolation (proper fixtures) - **COMPLETED**
- [x] Week 5: Remove `metrics_no_reset` marker - **COMPLETED**
- [ ] Week 6: Simplify to 3 markers: unit, integration, slow
- [ ] Week 6: Remove env variable test gates
- [ ] Week 7: Update CI configuration

**Test Isolation Pattern:**
```python
# Bad - Global state
@pytest.mark.serial
def test_metrics():
    global_registry.add_metric()
    assert global_registry.count() == 1

# Good - Fixture isolation
@pytest.fixture
def metrics_registry():
    registry = MetricsRegistry()
    yield registry
    registry.clear()

def test_metrics(metrics_registry):
    metrics_registry.add_metric()
    assert metrics_registry.count() == 1
```

**Deliverable:** All tests runnable in parallel with pytest-xdist

---

### 2.2 Configuration Unification

**Goal:** Single configuration system with clear policies

**Action Items:**
- [ ] Week 4: Document all `G6_*` variables with categories
- [ ] Week 4: Mark which are startup-only vs. runtime-reload
- [ ] Week 5: Create single `Config` class
- [ ] Week 5: Migrate all env parsing to Config.__init__
- [ ] Week 5: Remove dynamic reload mechanisms
- [ ] Week 6: Update all call sites
- [ ] Week 6: Add startup validation (fail on unknown vars)

**Config Structure:**
```python
@dataclass(frozen=True)
class G6Config:
    """Immutable configuration loaded at startup."""
    
    # Core (required)
    csv_base_dir: Path
    indices: list[str]
    
    # Features (optional)
    enable_greeks: bool = False
    enable_influx: bool = False
    
    # Debug (development only)
    debug_mode: bool = False
    trace_collectors: bool = False
    
    @classmethod
    def from_environment(cls) -> "G6Config":
        """Load once at startup. No reload."""
        ...
```

**Deliverable:** Single Config class with clear semantics

---

### 2.3 Deprecation Cleanup

**Goal:** Remove all expired deprecations

**Current State:**
- 55+ active deprecation entries
- Many past "Earliest Removal" date
- No enforcement mechanism

**Action Items:**
- Create deprecation audit script
- List all items past removal date (see DEPRECATIONS.md)
-  Remove expired items batch 1 (scripts)
-  Remove expired items batch 2 (env vars)
-  Remove expired items batch 3 (code paths)
-  Add CI check for future enforcement
-  Update deprecation policy documentation

**Immediate Removals (already approved per DEPRECATIONS.md):**
```
✅ COMPLETED:
- scripts/run_live.py (REMOVED 2025-10-01)
- scripts/terminal_dashboard.py (REMOVED 2025-10-01)
- scripts/summary_view.py (REMOVED 2025-10-03 - archived)
- G6_SUMMARY_REWRITE (REMOVED 2025-10-03)
- G6_SUMMARY_PLAIN_DIFF (REMOVED 2025-10-03)
- G6_SSE_ENABLED (REMOVED 2025-10-03 - warnings only, deprecated)
- src.providers.kite_provider shim (REMOVED 2025-10-07)
- scripts/bench_aggregate.py (REMOVED 2025-10-05 - archived)
```

**CI Enforcement:**
```python
# scripts/check_deprecations.py
def check_expired_deprecations():
    """Fail CI if code past removal date exists."""
    deprecations = load_deprecations_register()
    today = datetime.now()
    expired = [d for d in deprecations if d.removal_date < today]
    if expired:
        print(f"ERROR: {len(expired)} expired deprecations found")
        sys.exit(1)
```

**Deliverable:** Zero expired deprecations, enforced by CI

---

## Phase 3: Medium Priority (Weeks 8-11)

### 3.1 Documentation Restructuring

**Goal:** Organized, maintainable documentation

**Current State:**
- 107 markdown files in root directory
- README.md is 1,530 lines
- No clear hierarchy

**Action Items:**
- [ ] Week 8: Create docs/ directory structure
- [ ] Week 8: Categorize all existing docs
- [ ] Week 9: Split README.md into focused docs
- [ ] Week 9: Move docs to appropriate subdirectories
- [ ] Week 10: Create docs/README.md (index)
- [ ] Week 10: Archive historical/obsolete docs
- [ ] Week 11: Update all internal doc links

**New Structure:**
```
docs/
  README.md                 # Documentation index
  architecture/
    SYSTEM_DESIGN.md
    MODULE_STRUCTURE.md
    DEPENDENCY_MAP.md
  operations/
    DEPLOYMENT.md
    MONITORING.md
    TROUBLESHOOTING.md
  development/
    SETUP.md
    TESTING.md
    CONTRIBUTING.md
  reference/
    CONFIGURATION.md
    ENVIRONMENT_VARS.md
    METRICS.md
  roadmaps/
    CURRENT_QUARTER.md
    BACKLOG.md
  archive/
    [Historical docs]

README.md                   # Quick start only (max 300 lines)
```

**Deliverable:** Organized documentation with clear index

---

### 3.2 Performance Improvements

**Goal:** Async I/O and proper backpressure

**Action Items:**
- [ ] Week 8: Profile current CSV write latency
- [ ] Week 9: Implement async CSV writer with queue
- [ ] Week 9: Add write latency metrics
- [ ] Week 10: Implement hard memory limits
- [ ] Week 10: Add memory backpressure metrics
- [ ] Week 11: Integration testing under load
- [ ] Week 11: Performance benchmark comparison

**Async Writer Pattern:**
```python
class AsyncCsvWriter:
    def __init__(self, max_queue_size: int = 1000):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self.writer_task = asyncio.create_task(self._writer_loop())
    
    async def write(self, path: Path, data: dict) -> None:
        """Non-blocking write. Raises QueueFull if backpressured."""
        await self.queue.put((path, data))
    
    async def _writer_loop(self) -> None:
        """Background writer coroutine."""
        while True:
            path, data = await self.queue.get()
            await self._write_to_disk(path, data)
            self.queue.task_done()
```

**Deliverable:** Async I/O with performance metrics

---

### 3.3 Security Hardening

**Goal:** Secure token management and log sanitization

**Action Items:**
- [ ] Week 8: Audit token storage and access
- [ ] Week 9: Implement token rotation mechanism
- [ ] Week 9: Add log sanitization for sensitive data
- [ ] Week 10: Secrets management integration (consider using secret manager)
- [ ] Week 10: Security audit of all logger calls
- [ ] Week 11: Penetration testing
- [ ] Week 11: Security documentation

**Token Management Pattern:**
```python
class SecureTokenManager:
    def __init__(self):
        self._tokens: dict[str, str] = {}
        self._rotation_interval = timedelta(hours=24)
    
    def get_token(self, provider: str) -> str:
        """Get token, rotating if needed."""
        if self._should_rotate(provider):
            self._rotate_token(provider)
        return self._tokens[provider]
    
    def _rotate_token(self, provider: str) -> None:
        """Rotate token for provider."""
        new_token = self._fetch_new_token(provider)
        self._tokens[provider] = new_token
        logger.info("Token rotated", extra={"provider": provider})
```

**Log Sanitization:**
```python
class SanitizingFormatter(logging.Formatter):
    SENSITIVE_PATTERNS = [
        (r'api_key=\w+', 'api_key=***'),
        (r'token=\w+', 'token=***'),
        (r'password=\w+', 'password=***'),
    ]
    
    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        for pattern, replacement in self.SENSITIVE_PATTERNS:
            message = re.sub(pattern, replacement, message)
        return message
```

**Deliverable:** Secure credential management system

---

## Phase 4: Long-term (Weeks 12-20)

### 4.1 Architectural Refactoring

**Goal:** Proper layering without circular dependencies

**Action Items:**
-  Design layered architecture
- Extract domain models
-  Break circular dependencies
-  Migrate to new architecture
-Remove facade band-aids

**Target Architecture:**
```
┌─────────────────────────────────────┐
│     Application Layer               │
│  (orchestrator, CLI, scripts)       │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│     Service Layer                   │
│  (collectors, analytics, storage)   │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│     Infrastructure Layer            │
│  (metrics, logging, errors)         │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│     Domain Layer                    │
│  (models, types, protocols)         │
└─────────────────────────────────────┘
```

**Deliverable:** Clean layered architecture

---

## Monitoring and Success Metrics

### Key Performance Indicators

**Exception Handling:**
- Baseline: 3,244 bare exceptions (2025-11-15)
- Current: 1,859 bare exceptions (2025-11-16) - **43% reduction**
- Fixed: 1,385 handlers (Collectors + Pipeline + Status + Catalog + Expiry + **Storage**)
- Target: <500 bare exceptions
- Metric: `(Get-ChildItem -Path "src" -Filter "*.py" -Recurse | Select-String -Pattern "except Exception:" -CaseSensitive).Count`

**Legacy Code:**
- Baseline: 55+ active deprecations
- Target: 0 expired deprecations
- Metric: CI check passes

**CSV Integrity:**
- Baseline: Believed to be 3+ implementations (was misconception)
- Actual: ✅ 1 write implementation (`CsvWriter` + `CsvBatcher`)
- Status: **ALREADY ACHIEVED** - verified 2025-11-16
- Metric: Code path count

**Test Quality:**
- Baseline: 50+ serial tests
- Current: 1 serial test (2025-11-16) - **98% reduction**
- Target: 0 serial tests
- Metric: `(Select-String -Path "tests\**\*.py" -Pattern "@pytest.mark.serial" -Recurse).Count`

**Documentation:**
- Baseline: 107 root-level markdown files
- Target: <10 root-level files, rest organized
- Metric: `ls *.md | wc -l`

### Weekly Progress Reports

Generate weekly metrics:
```powershell
# scripts/progress_metrics.ps1

Write-Host "=== Progress Metrics ($(Get-Date -Format 'yyyy-MM-dd')) ==="
$bareExceptions = (Get-ChildItem -Path "src" -Filter "*.py" -Recurse | Select-String -Pattern "except Exception:" -CaseSensitive).Count
$serialTests = (Select-String -Path "tests\**\*.py" -Pattern "@pytest.mark.serial" -Recurse).Count
$rootMdFiles = (Get-ChildItem -Path "." -Filter "*.md").Count
$legacyLoopRefs = (Select-String -Path ".\**\*.py" -Pattern "G6_ENABLE_LEGACY_LOOP" -Recurse).Count

Write-Host "Bare exceptions: $bareExceptions (Target: <500)"
Write-Host "Serial tests: $serialTests (Target: 0)"
Write-Host "Root markdown files: $rootMdFiles (Target: <10)"
Write-Host "Legacy loop references: $legacyLoopRefs (Target: 0)"
```

**Latest Metrics (2025-11-16):**
- Bare exceptions: 1,859 (43% reduction from baseline 3,244) - ✅ Storage layer complete!
- Serial tests: 1 (98% reduction from baseline 50+)
- Root markdown files: ~100+ (unchanged, Phase 3 pending)
- Legacy loop: ✅ **REMOVED** (verified 2025-11-16, removed 2025-09-28)

---

## Risk Mitigation

### Rollback Strategy

For each phase:
1. **Branch Protection:** All changes via PR with review
2. **Feature Flags:** New implementations behind flags initially
3. **Incremental Rollout:** Change 10% → 50% → 100% of code
4. **Monitoring:** Watch error rates and performance metrics
5. **Rollback Plan:** Keep old code for 1 release cycle

### Testing Strategy

Before any phase:
1. **Baseline Metrics:** Capture current performance
2. **Comprehensive Tests:** 80%+ coverage for changed code
3. **Integration Tests:** Full end-to-end smoke tests
4. **Load Testing:** Verify performance under load
5. **Canary Deployment:** Test in non-production first

---

## Resource Requirements

### Team Allocation

**Phase 1 (Weeks 1-3):** 2 senior engineers full-time
- 1 focused on exception handling
- 1 focused on legacy removal and CSV consolidation

**Phase 2 (Weeks 4-7):** 2-3 engineers
- 1 on test infrastructure
- 1 on configuration
- 1 on deprecation cleanup

**Phase 3 (Weeks 8-11):** 2 engineers
- 1 on documentation and performance
- 1 on security

**Phase 4 (Weeks 12-20):** 2-3 senior engineers
- Architectural refactoring requires careful design

### Estimated Costs

- **Engineering Time:** 20 weeks × 2.5 engineers = 50 engineer-weeks
- **QA Time:** 20% of engineering time = 10 engineer-weeks
- **Infrastructure:** Minimal (existing systems)

**Total:** ~60 engineer-weeks (~3 person-months)

---

## Communication Plan

### Stakeholder Updates

**Weekly:** Progress metrics email to team
**Bi-weekly:** Demo of completed work
**Monthly:** Executive summary to leadership

### Documentation

**Real-time:** Update CHANGELOG.md for all changes
**Per Phase:** Release notes with migration guide
**Final:** Comprehensive "What Changed" guide

---

## Approval and Sign-off

This action plan requires approval from:

- [ ] Tech Lead / Architect
- [ ] Product Owner
- [ ] QA Lead
- [ ] Operations Lead

**Sign-off Date:** _______________

---

## Quick Start: Day 1 Actions

**Status:** ✅ COMPLETED

~~For immediate impact, start with these tasks:~~

1. ✅ **Morning:** Run exception audit to get baseline - COMPLETED (baseline: 3,244, current: 1,867)
2. ✅ **Afternoon:** Create PR to remove items marked "REMOVED" in DEPRECATIONS.md - COMPLETED (see CHANGELOG.md)
3. ✅ **EOD:** Set up weekly progress metrics script - Use PowerShell version above

**Commands (for ongoing monitoring):**
```powershell
# 1. Exception audit
Get-ChildItem -Path "src" -Filter "*.py" -Recurse | Select-String -Pattern "except Exception:" -CaseSensitive > exceptions_current.txt

# 2. Check deprecations status
Select-String -Path "DEPRECATIONS.md" -Pattern "REMOVED"

# 3. Run progress metrics
# See "Weekly Progress Reports" section above for the full script
```

---

**Next Steps:** Review this action plan with the team, adjust timelines as needed, and begin Phase 1 execution.

**End of Action Plan**
