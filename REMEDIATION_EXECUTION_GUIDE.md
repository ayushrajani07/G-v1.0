# Remediation Execution Guide: Precautions, Fallout & Cleanup

**Companion Document to:** ANALYSIS_ACTION_PLAN.md  
**Created:** 2025-11-15  
**Purpose:** Practical execution guide with risk mitigation, rollback procedures, and post-cleanup validation

---

## Current Baseline and Next Steps

**Baseline (2025-11-15):** Full test suite green in both parallel and serial runs (observed locally), with extensive skips as expected. Observability and pipeline hygiene are in place (metrics gauge resiliency, cardinality guard fast-path, stable shadow meta, parameterized logging).

**Immediate Next Steps:**
- Phase 1: Exception Handling Audit — storage, utils, and metrics packages completed. Exceptions narrowed in `src/utils/csv_cache.py`, `src/data_access/unified_source.py` (JSON readers), and metrics modules (`api_call.py`, `emission_batcher.py`, `fault_budget.py`, `gating.py`).
- Validate via "big diff → parallel test → serial test" cadence: parallel and serial suites both green locally after fixes.
- Prepare PR plan to remove the legacy orchestration loop (`unified_main.collection_loop`) and related flags (Phase 1 follow-up).
 - Data access audit note: attempted additional exception narrowing in `src/data_access/unified_source.py` (file watch/metrics adapter paths). This introduced regressions in metrics spec and cache stats tests under parallel runs. Changes were reverted to preserve the green baseline. Future passes will apply micro-changes with targeted tests (one guard at a time).
 - Tools hardening note: `src/tools/refresh_kite_token.py` updated to optionally load `.env`, narrow import/browse errors, and persist token updates robustly; validated with a full parallel test run remaining green.

**Quick Validation:**
```powershell
. .venv\Scripts\Activate.ps1
python -m pytest -n auto
```

Recent validation (2025-11-15):
- Narrowed exceptions in `src/utils/csv_cache.py` and JSON readers in `src/data_access/unified_source.py`.
- Metrics package big diff applied (`api_call`, `emission_batcher`, `fault_budget`, `gating`) with fixes for indentation and a thread-race in `emission_batcher`.
- Targeted tests and full suite (parallel and serial) passed locally. A transient `StatusReader` provider-name mismatch was not reproducible after fixes.

Use this guide’s checklists for execution, rollback, and validation.

---

## Phase 1 Completion Snapshot (2025-11-15)

**Scope delivered:**
- Exceptions narrowed across storage/utils and metrics without altering public APIs.
- `UnifiedDataSource` file-change detection and cache stats validated.
- `EmissionBatcher` indentation errors corrected; `_last_flush_end` initialized pre-thread start to eliminate race.
 - Orchestrator and panels: narrowed exception scopes in `src/orchestrator/hotreload.py`, `src/orchestrator/http_theme.py`, and `src/panels/factory.py` for safer failure modes without changing output shapes.

**Validation:**
- Parallel run: `python -m pytest -n auto` — green locally.
- Serial run: `python -m pytest -q` — green locally.
 - Fixed a rare parallel-only flake: `StatusReader` now prefers provider from the explicitly configured `runtime_status` file to avoid cross-test singleton contamination from panels.

**Notes:**
- Any remaining flakiness should be tracked with test-level isolation checks; none observed in the above runs.

**Next package targets (Phase 1 follow-ups / Phase 2 feeders):**
- Orchestrator + panels factory hardening (source precedence, gating hooks).
- Tools/token_manager exception surfaces and provider capability checks.
- Data access edges (logs if present) and residual broad catches.

Use this guide’s checklists for execution, rollback, and validation.

## Document Purpose

This guide provides **actionable execution procedures** for implementing the remediation plan, including:
- ⚠️ **Precautions** to take before each phase
- 🔥 **Potential fallout** scenarios and mitigation
- 🧹 **Cleanup steps** post-remediation
- 🔄 **Rollback procedures** if issues arise
- ✅ **Validation checklists** for each phase

**Read this BEFORE starting any remediation work.**

---

## Table of Contents

1. [Pre-Execution Checklist](#pre-execution-checklist)
2. [Phase 1 Execution: Critical Issues](#phase-1-execution)
3. [Phase 2 Execution: High Priority](#phase-2-execution)
4. [Phase 3 Execution: Medium Priority](#phase-3-execution)
5. [Phase 4 Execution: Long-term](#phase-4-execution)
6. [Universal Rollback Procedures](#universal-rollback-procedures)
7. [Post-Remediation Cleanup](#post-remediation-cleanup)
8. [Validation and Sign-off](#validation-and-sign-off)

---

## Pre-Execution Checklist

### ⚠️ STOP: Complete These Before Starting

**Infrastructure Preparation:**
- [ ] **Backup Strategy** - Full database and file system backup
- [ ] **Branch Protection** - Enable branch protection on main/production branches
- [ ] **CI/CD Pipeline** - Ensure all tests pass on current codebase
- [ ] **Monitoring Baseline** - Capture current error rates, performance metrics
- [ ] **Rollback Access** - Confirm ability to quickly revert deployments
- [ ] **Communication Plan** - Notify stakeholders of planned changes

**Environment Setup:**
```bash
# 1. Create dedicated remediation branch
git checkout -b remediation/phase-1-critical
git push -u origin remediation/phase-1-critical

# 2. Set up monitoring
python scripts/baseline_metrics.py --output baselines/pre-phase1.json

# 3. Verify test suite passes
pytest -q --maxfail=3

# 4. Tag current state for rollback
git tag -a pre-remediation-$(date +%Y%m%d) -m "Baseline before remediation"
git push --tags
```

**Team Readiness:**
- [ ] All team members reviewed CORE_PROJECT_ANALYSIS.md
- [ ] Phase leads assigned and acknowledged responsibilities
- [ ] Daily standup scheduled for duration of phase
- [ ] Escalation path defined (who to contact if blocked)

---

## Phase 1 Execution: Critical Issues

### 1.1 Exception Handling Remediation

#### ⚠️ Precautions

**Before Starting:**
```bash
# 1. Identify all bare exception handlers
grep -r "except Exception:" src --include="*.py" -n > audit/exceptions_baseline.txt
wc -l audit/exceptions_baseline.txt  # Should show 3,244

# 2. Create test coverage baseline
pytest --cov=src --cov-report=json -o json_report=coverage_baseline.json

# 3. Set up error monitoring alerts
# Configure Prometheus alerts for increased error rates
```

**Safety Nets:**
- Work on ONE module at a time (e.g., complete all of `src/storage/csv_sink.py` before moving to next file)
- Run tests after EACH file modification
- Keep original exception handling in comments for first iteration
- Use feature flag for gradual rollout: `G6_NEW_EXCEPTION_HANDLING=0|1`

#### 🔥 Potential Fallout Scenarios

| Scenario | Symptom | Immediate Action | Prevention |
|----------|---------|------------------|------------|
| **Silent failures become loud** | New exceptions not in code paths previously swallowed | Add specific handlers for unexpected exceptions | Comprehensive testing before deploy |
| **Stack trace noise** | Logs flooded with stack traces | Adjust logging levels, filter benign errors | Review log volume before production |
| **Retry logic breaks** | Operations fail instead of retrying | Verify retry decorators catch new specific exceptions | Test retry paths explicitly |
| **Monitoring gaps** | Metrics no longer capture errors | Update metric collectors for new exception types | Audit all `metrics.increment('error_*')` calls |

**Example Fallout Mitigation:**

```python
# BEFORE (masks errors)
try:
    write_csv(data)
except Exception:
    logger.error("CSV write failed")  # Silent failure

# AFTER (could cause alerts)
try:
    write_csv(data)
except PermissionError as e:
    logger.error(f"Permission denied: {e}", exc_info=True)
    raise  # Now raises - COULD BREAK CALLERS
except IOError as e:
    logger.error(f"I/O error: {e}", exc_info=True)
    # Retry logic needed here
    raise
except Exception as e:
    logger.critical(f"Unexpected CSV error: {e}", exc_info=True)
    raise

# MITIGATION: Add retry wrapper
@retry(on_exception=(IOError,), max_attempts=3)
def write_csv_with_retry(data):
    try:
        write_csv(data)
    except PermissionError as e:
        # Don't retry permission errors
        raise
```

#### 🧹 Cleanup Steps

**After Each Module:**
```bash
# 1. Remove commented-out old exception handlers
grep -r "# try:" src/storage --include="*.py"  # Should find none

# 2. Verify no duplicate error handling
# Check for nested try/except doing the same thing

# 3. Update documentation
# Add exceptions to module docstrings
```

**After Storage Layer Complete:**
```bash
# 1. Run integration tests
pytest tests/storage -v --count=10  # Run 10 times to catch flakiness

# 2. Compare exception counts
grep -r "except Exception:" src/storage --include="*.py" | wc -l
# Should be <50 (down from ~150)

# 3. Verify metrics still work
curl http://localhost:9108/metrics | grep csv_write

# 4. Commit checkpoint
git add src/storage
git commit -m "refactor(storage): improve exception handling specificity"
```

#### 🔄 Rollback Procedure

**If exception handling changes cause production issues:**

```bash
# IMMEDIATE (within 5 minutes):
# 1. Flip feature flag
export G6_NEW_EXCEPTION_HANDLING=0
# or set in config
systemctl restart g6-collector

# SHORT-TERM (within 1 hour):
# 2. Revert last commit
git revert HEAD
git push origin remediation/phase-1-critical

# MEDIUM-TERM (within 1 day):
# 3. Full rollback to baseline
git checkout pre-remediation-$(date +%Y%m%d)
# Cherry-pick any unrelated fixes
git cherry-pick <commit-hash>
```

**Rollback Validation:**
```bash
# Verify baseline exception count restored
grep -r "except Exception:" src/storage --include="*.py" | wc -l

# Verify tests pass
pytest tests/storage -v

# Verify metrics match baseline
python scripts/compare_metrics.py baselines/pre-phase1.json
```

---

### 1.2 Legacy Loop Removal

#### ⚠️ Precautions

**Risk Assessment:**
```bash
# 1. Find all code using legacy loop
grep -r "LEGACY_LOOP" . --include="*.py" --include="*.sh"
grep -r "collection_loop" src --include="*.py"

# 2. Identify external scripts/automation using it
# Check CI configs, cron jobs, operator runbooks

# 3. Verify new loop has feature parity
python scripts/compare_loop_features.py --legacy --new
```

**Communication:**
- **2 weeks before:** Announce removal date in team channels
- **1 week before:** Email all stakeholders with migration guide
- **Day of:** Clearly mark as breaking change in commit message

#### 🔥 Potential Fallout Scenarios

| Scenario | Symptom | Immediate Action | Prevention |
|----------|---------|------------------|------------|
| **External automation breaks** | CI jobs fail, cron scripts error | Identify and update external callers | Pre-change audit of all callers |
| **Feature gaps** | Some functionality no longer available | Document missing features, provide workarounds | Feature parity checklist |
| **Performance regression** | New loop is slower | Profile and optimize new loop | Benchmark before removal |
| **Config incompatibility** | Old config keys not recognized | Migration script for configs | Provide auto-migration tool |

**Example Fallout Mitigation:**

```python
# PROBLEM: External script uses removed flag
# OLD: export <legacy loop gating flag>=1; python -m src.unified_main

# MITIGATION: Add deprecation shim (temporary)
if os.getenv("LEGACY_LOOP"):
    logger.warning(
        "Legacy loop gating flag is deprecated and ignored. "
        "Using new orchestrator loop. "
        "Update your scripts to remove this flag."
    )
# Then run new loop normally
```

#### 🧹 Cleanup Steps

**Immediate (Same PR):**
```bash
# 1. Remove function
# Delete collection_loop() from src/unified_main.py

# 2. Remove flag handling
grep -r "LEGACY_LOOP" src --include="*.py"
# Delete all references

# 3. Remove related tests
rm tests/test_legacy_loop_gating.py
rm tests/test_deprecation_legacy_loop.py

# 4. Update docs
# Remove from README.md, env_dict.md, DEPRECATIONS.md
```

**Follow-up (Next Release):**
```bash
# 1. Remove deprecation shim (if added)
# Delete warning message for old flag

# 2. Remove from .env.example
grep -v "LEGACY_LOOP" .env.example > .env.example.new
mv .env.example.new .env.example

# 3. Update CHANGELOG.md
echo "- BREAKING: Removed legacy collection loop (legacy loop gating flags)" >> CHANGELOG.md
```

#### 🔄 Rollback Procedure

**If new loop causes production issues:**

```bash
# IMMEDIATE (Cherry-pick revert):
# 1. Find commit that removed legacy loop
git log --oneline --all --grep="legacy loop"

# 2. Revert that specific commit
git revert <commit-hash>
git push

# 3. Re-enable legacy loop in production
export <legacy loop gating flag>=1
systemctl restart g6-collector

# VALIDATION:
# Verify legacy loop is running
grep "Legacy loop enabled" /var/log/g6/collector.log
```

---

### 1.3 CSV Writer Consolidation

#### ⚠️ Precautions

**Data Integrity Protection:**
```bash
# 1. Backup all CSV data before changes
tar -czf backup_csv_$(date +%Y%m%d).tar.gz data/g6_data/

# 2. Enable CSV write audit logging
export G6_CSV_WRITE_AUDIT=1  # Log every write with checksum

# 3. Set up data integrity monitoring
# Monitor for: file corruption, incomplete writes, schema drift
```

**Testing Strategy:**
- **Unit tests:** Each CSV function tested independently
- **Integration tests:** Full write pipeline end-to-end
- **Concurrent write tests:** Multiple processes writing simultaneously
- **Failure injection:** Disk full, permission errors, crashes mid-write

#### 🔥 Potential Fallout Scenarios

| Scenario | Symptom | Immediate Action | Prevention |
|----------|---------|------------------|------------|
| **Data corruption** | Malformed CSV, missing rows | Stop writes, restore backup | Atomic writes, checksums |
| **Performance regression** | Slower write throughput | Profile new implementation | Benchmark before deploy |
| **Lock contention** | Deadlocks, timeouts | Adjust lock granularity | Stress test concurrent writes |
| **Schema mismatch** | Column count errors | Migration script for old data | Schema versioning |
| **Partial writes** | Files incomplete after crash | Implement atomic writes | Temp file + rename pattern |

**Example Fallout Mitigation:**

```python
# PROBLEM: New facade doesn't support legacy column names
# OLD CSV: time_ms, strike, iv
# NEW CSV: timestamp, strike_price, implied_volatility

# MITIGATION: Add column mapping
LEGACY_COLUMN_MAP = {
    'time_ms': 'timestamp',
    'strike': 'strike_price',
    'iv': 'implied_volatility'
}

def write_csv_with_migration(data):
    # Auto-detect if using legacy columns
    if 'time_ms' in data:
        data = {LEGACY_COLUMN_MAP.get(k, k): v for k, v in data.items()}
    
    # Write with new facade
    write_csv_atomic(data)
```

#### 🧹 Cleanup Steps

**Phase 1: Migration Complete**
```bash
# 1. Remove legacy write paths
rm src/storage/csv_writer_old.py  # If created backup
git rm src/storage/csv_writer_helper.py  # If fully replaced

# 2. Remove feature flags
grep -r "CSVIO" . --include="*.py"
# Delete all flag checks

# 3. Update all imports
# Replace: from src.storage.csv_writer import write_csv
# With: from src.storage.csvio.api import write_csv_atomic

# 4. Consolidate tests
# Merge csv_writer_test.py and csv_sink_test.py
```

**Phase 2: Validation Complete**
```bash
# 1. Remove parallel implementations
ls -la src/storage/csv*.py
# Should have only: csv_sink.py, csvio/ (directory)

# 2. Archive old CSV data (if schema changed)
mkdir -p archive/csv_legacy_format/
mv data/g6_data_old/* archive/csv_legacy_format/

# 3. Update monitoring
# Remove metrics for old write path
grep "csv_write_legacy" prometheus_rules.yml
# Delete those rules
```

#### 🔄 Rollback Procedure

**Data Recovery Procedure:**

```bash
# If data corruption detected:

# IMMEDIATE (Stop writes):
# 1. Disable CSV writing
export G6_DISABLE_CSV_WRITES=1
systemctl restart g6-collector

# 2. Assess corruption extent
python scripts/validate_csv_integrity.py --dir data/g6_data --since 2025-11-15

# SHORT-TERM (Restore data):
# 3. Restore from backup
# Only restore corrupted files to avoid data loss
tar -xzf backup_csv_20251115.tar.gz -C /tmp/
cp /tmp/data/g6_data/NIFTY/corrupted_file.csv data/g6_data/NIFTY/

# 4. Re-enable writes (CSVIO path is always-on)
export G6_DISABLE_CSV_WRITES=0
systemctl restart g6-collector

# VALIDATION:
# 5. Verify data integrity
python scripts/validate_csv_integrity.py --dir data/g6_data --all
# 6. Compare checksums
md5sum data/g6_data/**/*.csv > checksums_post_restore.txt
```

---

## Phase 2 Execution: High Priority

### 2.1 Test Infrastructure Cleanup

#### ⚠️ Precautions

**Before Modifying Tests:**
```bash
# 1. Document current test behavior
pytest tests -v --tb=no > test_baseline.txt

# 2. Identify all serial tests
grep -r "@pytest.mark.serial" tests --include="*.py" > serial_tests.txt
wc -l serial_tests.txt  # Should show ~50

# 3. Create test isolation checklist
python scripts/analyze_test_isolation.py > test_isolation_report.txt
```

**Safe Refactoring:**
- Fix **one test file at a time**
- Run test **10 times** to ensure no flakiness: `pytest -v --count=10 tests/test_file.py`
- Keep serial marker **until confirmed stable** in parallel
- Use pytest-xdist for parallel execution: `pytest -n auto`

#### 🔥 Potential Fallout Scenarios

| Scenario | Symptom | Immediate Action | Prevention |
|----------|---------|------------------|------------|
| **Flaky tests** | Random failures in CI | Revert to serial, investigate | Run many iterations before parallel |
| **Resource leaks** | Tests pass individually, fail together | Add proper teardown | Use fixtures correctly |
| **Race conditions** | Intermittent failures | Add synchronization | Avoid shared state |
| **Fixture scope issues** | Unexpected state sharing | Change to function scope | Review fixture scopes |

**Example Fallout Mitigation:**

```python
# PROBLEM: Global metrics registry causes test interference

# BAD (global state):
metrics_registry = MetricsRegistry()  # Module level

def test_a():
    metrics_registry.add("counter")
    assert metrics_registry.count() == 1

def test_b():
    # Fails if test_a ran first
    assert metrics_registry.count() == 0  

# GOOD (isolated):
@pytest.fixture
def metrics_registry():
    registry = MetricsRegistry()
    yield registry
    registry.clear()  # Cleanup

def test_a(metrics_registry):
    metrics_registry.add("counter")
    assert metrics_registry.count() == 1

def test_b(metrics_registry):
    # Always starts clean
    assert metrics_registry.count() == 0
```

#### 🧹 Cleanup Steps

**After Each Test File:**
```bash
# 1. Verify parallel execution
pytest tests/test_fixed_file.py -n 4 -v --count=5

# 2. Remove serial marker
# Delete @pytest.mark.serial from test file

# 3. Verify in full suite
pytest tests -n auto -v

# 4. Document changes
# Update test file docstring with isolation notes
```

**After All Tests Fixed:**
```bash
# 1. Remove serial marker definition
# Edit pytest.ini - remove 'serial' marker

# 2. Verify no serial tests remain
grep -r "@pytest.mark.serial" tests --include="*.py"
# Should return nothing

# 3. Update CI configuration
# Change from: pytest -v
# To: pytest -n auto -v

# 4. Remove conftest helpers for serial tests
# Remove any serial test scheduling code
```

#### 🔄 Rollback Procedure

**If parallel tests cause CI failures:**

```bash
# IMMEDIATE (restore serial execution):
# 1. Edit CI config
# Change: pytest -n auto
# Back to: pytest -v

# 2. Re-add serial marker to problematic tests
git checkout HEAD -- tests/test_problematic.py

# 3. Run CI again
git push

# INVESTIGATION:
# 4. Identify failing test
pytest tests -n auto -v --tb=short | tee failure_log.txt

# 5. Run just that test serially
pytest tests/test_problematic.py -v --count=10

# 6. Debug in isolation
pytest tests/test_problematic.py -v -s --pdb
```

---

### 2.2 Configuration Unification

#### ⚠️ Precautions

**Configuration Audit:**
```bash
# 1. Document all config loading points
grep -r "load_config\|load_and_validate_config" src --include="*.py"

# 2. Identify startup-only vs hot-reload vars
python scripts/audit_env_vars.py --categorize

# 3. Test config migration
python scripts/test_config_migration.py --dry-run
```

**Migration Safety:**
- Create **migration script** for old configs
- Support **both old and new** config formats for 1 release
- Log **deprecation warnings** for old format usage
- Provide **conversion tool**: `python scripts/migrate_config.py`

#### 🔥 Potential Fallout Scenarios

| Scenario | Symptom | Immediate Action | Prevention |
|----------|---------|------------------|------------|
| **Config not found** | App fails to start | Fallback to defaults | Validate config on startup |
| **Type mismatch** | Parsing errors | Type coercion | Schema validation |
| **Missing required keys** | KeyError at runtime | Default values | Required key checking |
| **Hot-reload broken** | Changes not applied | Remove hot-reload | Document restart required |

**Example Fallout Mitigation:**

```python
# PROBLEM: Config changed from dict to dataclass

# OLD CODE:
config = load_config()
csv_dir = config['csv']['base_dir']

# NEW CODE (could break):
config = load_config()  # Returns Config dataclass
csv_dir = config.csv.base_dir  # Attribute access

# MITIGATION: Compatibility shim (temporary)
class ConfigCompat(Config):
    def __getitem__(self, key):
        # Support old dict-style access
        logger.warning(f"Dict-style config access deprecated: config['{key}']")
        return getattr(self, key)

# Remove shim after 1 release cycle
```

#### 🧹 Cleanup Steps

**After Migration Complete:**
```bash
# 1. Remove old config loaders
rm src/config/config_loader_old.py
rm src/config/legacy_loader.py

# 2. Remove compatibility shims
grep -r "ConfigCompat\|config\['.*'\]" src --include="*.py"
# Delete compatibility code

# 3. Update all imports
# Replace: from src.config.loader_old import load_config
# With: from src.config.loader import load_config

# 4. Remove deprecated env vars
grep -r "G6_OLD_CONFIG_FORMAT" . --include="*.py"
# Delete all references
```

**Validate Migration:**
```bash
# 1. Test with old config format
cp config/old_format.json config/test.json
python -m src.unified_main --config config/test.json --run-once
# Should work with warning

# 2. Test with new config format
cp config/new_format.json config/test.json
python -m src.unified_main --config config/test.json --run-once
# Should work without warning

# 3. Remove old format support
# Delete migration shim code
```

---

## Phase 3 Execution: Medium Priority

### 3.1 Documentation Restructuring

#### ⚠️ Precautions

**Before Moving Files:**
```bash
# 1. Create backup
tar -czf docs_backup_$(date +%Y%m%d).tar.gz *.md docs/

# 2. Find all internal doc links
grep -r "\[.*\](.*.md)" . --include="*.md" > doc_links.txt

# 3. Generate link map
python scripts/map_doc_links.py > doc_link_map.json
```

**Safe Restructuring:**
- Move files **incrementally** (10-20 at a time)
- Update **all links** after each move
- Keep **redirects** in old locations temporarily
- Test **all links** after restructuring

#### 🔥 Potential Fallout Scenarios

| Scenario | Symptom | Immediate Action | Prevention |
|----------|---------|------------------|------------|
| **Broken links** | 404s in docs | Create redirects | Link validator |
| **External links broken** | External sites pointing to old URLs | GitHub redirects | Gradual migration |
| **Search broken** | Docs not findable | Update search index | Re-index after move |
| **Lost history** | Git history unclear | Use `git mv` | Never `rm` + `create` |

#### 🧹 Cleanup Steps

**After Restructuring:**
```bash
# 1. Validate all links
python scripts/validate_doc_links.py docs/

# 2. Remove redirect stubs
rm README_old.md ANALYSIS_old.md
# After 1 month grace period

# 3. Update external references
# Check GitHub wiki, external docs, READMEs

# 4. Re-index search
# If using search functionality
```

---

## Universal Rollback Procedures

### Emergency Rollback (Production Down)

**Within 5 minutes:**
```bash
# 1. Rollback to last known good deployment
kubectl rollout undo deployment/g6-collector
# or
git checkout <last-good-tag>
./deploy.sh

# 2. Verify services up
curl http://localhost:9108/health
systemctl status g6-collector

# 3. Notify stakeholders
# Post in incident channel
```

### Planned Rollback (Issues Found in Testing)

**Within 1 hour:**
```bash
# 1. Revert specific commit
git log --oneline | head -20  # Find problematic commit
git revert <commit-hash>
git push

# 2. Run full test suite
pytest tests -v

# 3. Compare metrics
python scripts/compare_metrics.py baselines/pre-change.json current

# 4. Update documentation
echo "Rolled back due to: <reason>" >> CHANGELOG.md
```

---

## Post-Remediation Cleanup

### After Each Phase

**Code Cleanup:**
```bash
# 1. Remove dead code
python scripts/find_dead_code.py > dead_code.txt
# Review and delete

# 2. Remove deprecated flags
grep -r "DEPRECATED\|TODO.*remove" src --include="*.py"
# Clean up marked items

# 3. Update CHANGELOG
echo "## Phase X Complete ($(date +%Y-%m-%d))" >> CHANGELOG.md
echo "- Removed: <list removed items>" >> CHANGELOG.md
```

**Documentation Cleanup:**
```bash
# 1. Archive old docs
mkdir -p archive/docs_phase_X/
mv *_old.md archive/docs_phase_X/

# 2. Update README
# Remove references to removed features

# 3. Update DEPRECATIONS.md
# Move completed items to "Historical" section
```

### After All Phases

**Final Cleanup:**
```bash
# 1. Remove all baseline files
rm -rf baselines/

# 2. Remove audit files
rm -rf audit/

# 3. Remove backup tags
git tag -d pre-remediation-*

# 4. Squash fixup commits
git rebase -i HEAD~50  # Interactive rebase
# Squash related commits

# 5. Final validation
pytest tests -n auto -v
python scripts/final_metrics.py > metrics_post_remediation.txt
```

---

## Validation and Sign-off

### Phase Completion Checklist

**Phase 1 (Critical):**
- [ ] Exception handling: <500 bare catches (was 3,244)
- [ ] Legacy loop removed, no references remain
- [ ] Single CSV write path, tests pass
- [ ] No production incidents for 1 week
- [ ] Performance within 5% of baseline
- [ ] **Sign-off:** Tech Lead

**Phase 2 (High Priority):**
- [ ] Zero serial tests (was 50+)
- [ ] Single config mechanism
- [ ] Zero expired deprecations (was 55+)
- [ ] CI tests run in <10 minutes
- [ ] No configuration-related incidents
- [ ] **Sign-off:** Engineering Manager

**Phase 3 (Medium Priority):**
- [ ] Documentation organized (<10 root MD files)
- [ ] Async I/O operational, performance improved
- [ ] Security audit passed
- [ ] No data integrity issues
- [ ] **Sign-off:** Product Owner

**Phase 4 (Long-term):**
- [ ] Clean architecture diagram validated
- [ ] No circular dependencies
- [ ] All facade band-aids removed
- [ ] Code review score >8/10
- [ ] **Sign-off:** Architect

### Final Sign-off

**Before declaring remediation complete:**

```bash
# 1. Run all validation scripts
./scripts/validate_remediation.sh

# 2. Generate comparison report
python scripts/compare_before_after.py \
  --before baselines/pre-remediation.json \
  --after metrics_post_remediation.txt \
  --output remediation_impact_report.pdf

# 3. Get stakeholder approval
# Circulate report for review and sign-off

# 4. Close remediation project
# Update project management tool
# Archive all remediation documentation
```

---

## Emergency Contacts

**During Remediation:**

| Role | Responsibility | Contact |
|------|----------------|---------|
| Phase Lead | Day-to-day execution | [Name, Slack, Phone] |
| Tech Lead | Technical decisions | [Name, Slack, Phone] |
| On-call Engineer | Production issues | [Rotation, PagerDuty] |
| Product Owner | Scope changes | [Name, Slack, Email] |

**Escalation Path:**
1. Phase Lead (immediate issues)
2. Tech Lead (technical blockers)
3. Engineering Manager (resource/timeline issues)
4. CTO (business impact)

---

## Appendix: Common Issues & Solutions

### Issue: "Tests pass locally, fail in CI"

**Solution:**
```bash
# 1. Check for timing issues
pytest tests -v --tb=short --durations=10

# 2. Check for resource contention
# Reduce parallelism: pytest -n 2 instead of -n auto

# 3. Check for order dependency
pytest tests --randomly-seed=12345 -v
```

### Issue: "Performance regression detected"

**Solution:**
```bash
# 1. Profile the change
python -m cProfile -o profile.stats scripts/run_cycle.py
python -m pstats profile.stats

# 2. Compare to baseline
python scripts/compare_profiles.py baseline.stats profile.stats

# 3. Optimize hot paths
# Focus on top 5 functions by cumulative time
```

### Issue: "Rollback fails"

**Solution:**
```bash
# 1. Hard reset to known good state
git fetch origin
git reset --hard origin/main

# 2. Force push (use with caution)
# Only if remediation branch isolated
git push origin remediation/phase-1 --force

# 3. Redeploy from clean state
./scripts/clean_deploy.sh
```

---

## Summary

This execution guide provides:
- ✅ Precautions for each phase
- ✅ Fallout scenarios with mitigation
- ✅ Cleanup procedures
- ✅ Rollback procedures
- ✅ Validation checklists

**Key Principles:**
1. **Incremental changes** - Small, testable steps
2. **Always have rollback** - Never deploy without escape hatch
3. **Monitor continuously** - Watch for issues in real-time
4. **Communicate clearly** - Keep stakeholders informed
5. **Validate thoroughly** - Test, test, test

**Before Starting:**
- Read entire guide
- Set up monitoring
- Create backups
- Get team alignment

**During Execution:**
- Follow procedures exactly
- Document deviations
- Escalate blockers early
- Celebrate milestones

**After Completion:**
- Clean up artifacts
- Update documentation
- Share learnings
- Archive project materials

---

**Document Version:** 1.0  
**Last Updated:** 2025-11-15  
**Next Review:** After Phase 1 completion
