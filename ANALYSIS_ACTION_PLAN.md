# Action Plan: Addressing Core Project Inconsistencies

**Based on:** CORE_PROJECT_ANALYSIS.md  
**Created:** 2025-11-15  
**Priority:** Immediate Action Required

---

## Current Baseline and Next Steps

**Baseline (2025-11-15):** Full test suite green in parallel (1462 passed, 539 skipped). Recent hygiene fixes improve observability and stability (resilient metrics gauge, cardinality guard fast-path, stable shadow meta, parameterized logging).

**Immediate Next Steps:**
- Kick off Phase 1: Exception Handling Audit — start with storage; tighten handlers and add targeted retries.
- Draft PR plan to remove the legacy orchestration loop and related flags.

**Quick Validation:**
```powershell
. .venv\Scripts\Activate.ps1
python -m pytest -n auto
```

---

## Executive Action Items

This document provides a concrete, prioritized action plan to address the fundamental inconsistencies and weak points identified in the core project analysis.

---

## Phase 1: Critical Issues (Weeks 1-3)

### 1.1 Exception Handling Remediation

**Goal:** Reduce bare `except Exception:` from 3,244 to <500

**Approach:**
```bash
# Step 1: Identify hotspots
grep -r "except Exception:" src --include="*.py" -n > exceptions_audit.txt

# Step 2: Prioritize by criticality
Priority Order:
1. src/storage/*.py (data integrity)
2. src/metrics/*.py (observability)
3. src/collectors/*.py (business logic)
4. src/orchestrator/*.py (system reliability)
```

**Action Items:**
- [ ] Week 1: Audit storage layer (15 files)
- [ ] Week 1-2: Audit metrics layer (50+ files)
- [ ] Week 2-3: Audit collectors (30+ files)
- [ ] Week 3: Audit orchestrator (12 files)

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

**Current State:**
- `unified_main.collection_loop` - Deprecated since 2025-09-26
- Still gated behind `G6_ENABLE_LEGACY_LOOP=1`
- Grace period expired (2+ months)

**Action Items:**
- [ ] Day 1: Run tests with legacy loop disabled to confirm stability
- [ ] Day 2: Remove `unified_main.collection_loop` function
- [ ] Day 2: Remove `G6_ENABLE_LEGACY_LOOP` flag handling
- [ ] Day 3: Remove `G6_SUPPRESS_LEGACY_LOOP_WARN` flag
- [ ] Day 3: Update all documentation references
- [ ] Day 4: Remove related tests
- [ ] Day 5: Final integration test

**Files to Modify:**
```
src/unified_main.py
src/orchestrator/loop.py
tests/test_legacy_loop_gating.py
tests/test_deprecation_legacy_loop.py
docs/env_dict.md
README.md
```

**Validation:**
```bash
# Ensure no references remain
grep -r "G6_ENABLE_LEGACY_LOOP" .
grep -r "collection_loop" src --include="*.py"
```

**Deliverable:** PR removing legacy loop with passing tests

---

### 1.3 CSV Writer Consolidation

**Goal:** Single CSV write implementation

**Current State:**
- Multiple writers: csv_sink.py, csv_writer.py, csv_batcher.py
- Facade migration incomplete (`G6_USE_CSVIO_FACADE=0` opt-out)
- Parallel implementations create data integrity risk

**Action Items:**
- [ ] Week 1: Audit all CSV write call sites
- [ ] Week 1: Verify facade covers all use cases
- [ ] Week 2: Migrate remaining direct write calls to facade
- [ ] Week 2: Remove `G6_USE_CSVIO_FACADE` flag
- [ ] Week 2: Delete legacy write implementations
- [ ] Week 3: Comprehensive integration tests
- [ ] Week 3: Performance benchmark (ensure no regression)

**Migration Checklist:**
```python
# Before:
from src.storage.csv_writer import CsvWriter
writer = CsvWriter()
writer.write_direct(path, data)

# After:
from src.storage.csvio.api import write_csv_atomic
write_csv_atomic(path, data, schema_version="v2")
```

**Deliverable:** Single CSV write path with comprehensive tests

---

## Phase 2: High Priority (Weeks 4-7)

### 2.1 Test Infrastructure Cleanup

**Goal:** Eliminate global state and simplify markers

**Problems:**
- `serial` marker indicates 50+ tests with global state
- `metrics_no_reset` suggests fixture isolation issues
- 8 different test categories with env variable gates

**Action Items:**
- [ ] Week 4: Audit all `@pytest.mark.serial` tests
- [ ] Week 4-5: Refactor tests to remove global state
- [ ] Week 5: Fix metrics registry isolation (proper fixtures)
- [ ] Week 5: Remove `metrics_no_reset` marker
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
- scripts/run_live.py (REMOVED 2025-10-01)
- scripts/terminal_dashboard.py (REMOVED 2025-10-01)
- scripts/summary_view.py (REMOVED 2025-10-03)
- G6_SUMMARY_REWRITE (REMOVED 2025-10-03)
- G6_SUMMARY_PLAIN_DIFF (REMOVED 2025-10-03)
- G6_SSE_ENABLED (REMOVED 2025-10-03)
- src.providers.kite_provider shim (REMOVED 2025-10-07)
- scripts/bench_aggregate.py (REMOVED 2025-10-05)
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
- Baseline: 3,244 bare exceptions
- Target: <500 bare exceptions
- Metric: `grep -r "except Exception:" src | wc -l`

**Legacy Code:**
- Baseline: 55+ active deprecations
- Target: 0 expired deprecations
- Metric: CI check passes

**CSV Integrity:**
- Baseline: 3+ write implementations
- Target: 1 write implementation
- Metric: Code path count

**Test Quality:**
- Baseline: 50+ serial tests
- Target: 0 serial tests
- Metric: `grep -r "@pytest.mark.serial" tests | wc -l`

**Documentation:**
- Baseline: 107 root-level markdown files
- Target: <10 root-level files, rest organized
- Metric: `ls *.md | wc -l`

### Weekly Progress Reports

Generate weekly metrics:
```bash
#!/bin/bash
# scripts/progress_metrics.sh

echo "=== Progress Metrics ==="
echo "Bare exceptions: $(grep -r 'except Exception:' src --include="*.py" | wc -l)"
echo "Serial tests: $(grep -r '@pytest.mark.serial' tests --include="*.py" | wc -l)"
echo "Root markdown files: $(ls *.md | wc -l)"
echo "Active deprecations: $(grep 'Active Deprecations' -A 100 DEPRECATIONS.md | grep '|' | wc -l)"
echo "Legacy loops: $(grep -r 'G6_ENABLE_LEGACY_LOOP' . --include="*.py" | wc -l)"
```

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

For immediate impact, start with these tasks:

1. **Morning:** Run exception audit to get baseline
2. **Afternoon:** Create PR to remove items marked "REMOVED" in DEPRECATIONS.md
3. **EOD:** Set up weekly progress metrics script

**Commands:**
```bash
# 1. Exception audit
grep -r "except Exception:" src --include="*.py" -n > exceptions_baseline.txt

# 2. Find already-removed items
grep "REMOVED" DEPRECATIONS.md

# 3. Set up metrics
cp scripts/progress_metrics.sh.template scripts/progress_metrics.sh
chmod +x scripts/progress_metrics.sh
```

---

**Next Steps:** Review this action plan with the team, adjust timelines as needed, and begin Phase 1 execution.

**End of Action Plan**
