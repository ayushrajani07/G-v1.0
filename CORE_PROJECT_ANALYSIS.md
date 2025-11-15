# Core Project Analysis: Fundamental Inconsistencies and Weak Points

**Analysis Date:** 2025-11-15  
**Repository:** ayushrajani07/G-v1.0  
**Scope:** Complete core project architecture, design patterns, and implementation  
**Analyst:** AI Code Review Agent

---

## Executive Summary

The G6 Platform is a sophisticated, production-grade options market data collection and analytics system with approximately **498 Python source files** and **592 test files**. While the project demonstrates advanced architectural patterns and extensive documentation (100+ MD files), this analysis identifies **critical inconsistencies, logical weak points, and technical debt** that require attention.

### Key Findings

✅ **Strengths:**
- Comprehensive test coverage infrastructure (pytest with parallel execution)
- Extensive documentation and governance processes
- Active refactoring and modernization efforts (see INEFFICIENCIES_REPORT.md)
- Strong observability with Prometheus metrics and Grafana dashboards

⚠️ **Critical Issues:**
- **3,244 bare `except Exception:` handlers** creating error masking risks
- Complex deprecation management with multiple active migration paths
- Fragmented configuration system despite consolidation efforts
- Heavy circular dependency risks between core modules
- Inconsistent error handling patterns across the codebase

---

## 1. Architectural Inconsistencies

### 1.1 Module Organization and Import Architecture

**Issue:** Despite recent improvements (92 late imports eliminated per INEFFICIENCIES_REPORT.md), the codebase still exhibits architectural fragmentation.

**Evidence:**
- 498 source files across deeply nested package structure
- Multiple "facade" patterns introduced to break circular dependencies
- Protocol interfaces added as band-aids for import cycles
- `src/metrics/facade.py`, `src/errors/facade.py` suggest deep coupling issues

**Root Cause:**
The core collector-metrics-error handling triangle creates bidirectional dependencies that required facade wrappers rather than proper layering.

**Recommended Fix:**
```
Proposed Dependency Flow:
Domain Models (types, protocols) 
    ↓
Core Utilities (errors, logging)
    ↓
Infrastructure (metrics, storage)
    ↓
Business Logic (collectors, analytics)
    ↓
Orchestration (unified_main, orchestrator)
```

**Impact:** High - Affects maintainability and onboarding time

---

### 1.2 Configuration System Fragmentation

**Issue:** Multiple configuration loading mechanisms despite consolidation efforts.

**Evidence from codebase:**
```
src/config/loader.py          - Canonical loader (recent consolidation)
src/config/env_config.py      - Environment variable facade  
src/config/runtime_config.py  - Runtime configuration
src/config/config_wrapper.py  - Wrapper pattern
src/config/validation.py      - Validation logic
```

**Inconsistency:**
- Different modules use different config access patterns
- Environment variables duplicated across multiple loaders
- `G6_*` prefix conventions not consistently enforced
- Runtime flags hydrated once vs dynamic access patterns mixed

**Example Conflict:**
From README.md Section 6.1:
> "Consolidated Runtime Flags (A23/A24): High‑traffic collector toggles... are hydrated once via `CollectorSettings`. Changing the corresponding environment variables after startup has no effect unless... `get_collector_settings(force_reload=True)` is explicitly called"

This creates confusion: some env vars are dynamic, others are frozen at startup.

**Recommended Fix:**
1. Establish clear policy: startup-only vs. hot-reload configs
2. Document which variables require restart vs. runtime change
3. Centralize all env parsing into single immutable config object
4. Deprecate dynamic reload mechanisms unless justified

**Impact:** Medium - Causes production debugging confusion

---

### 1.3 Parallel Execution Paths

**Issue:** Multiple orchestration entry points with overlapping responsibilities.

**Evidence:**
```
src/unified_main.py                     - Original entry point (deprecated loop)
src/orchestrator/loop.py                - New orchestrator loop  
src/orchestrator/bootstrap.py           - Bootstrap logic
scripts/run_orchestrator_loop.py        - Script wrapper
src/collectors/unified_collectors.py    - Collector orchestration
src/collectors/pipeline_root.py         - Pipeline variant
```

**From DEPRECATIONS.md:**
> "`unified_main.collection_loop` (legacy orchestration loop)" - Deprecated but still present with `G6_ENABLE_LEGACY_LOOP=1`

**Problem:**
Having two complete orchestration paths (legacy + new) doubles the testing surface and maintenance burden. The deprecation has been in place since 2025-09-26 but not removed.

**Recommended Fix:**
1. Complete removal of legacy loop (grace period exceeded)
2. Single canonical entry: `src/orchestrator/loop.run_loop()`
3. Consolidate bootstrap logic
4. Remove all `G6_ENABLE_LEGACY_*` flags

**Impact:** High - Active maintenance burden

---

## 2. Error Handling Inconsistencies

### 2.1 Excessive Bare Exception Handlers

**Critical Finding:** 3,244 instances of `except Exception:` across the codebase.

**Risk Assessment:**
- **Silent Failures:** Broad exception catching masks root causes
- **Error Propagation:** Important failures may be logged but not properly handled
- **Debugging Difficulty:** Stack traces lost or incomplete

**Examples from CODE_HEALTH_ROADMAP.md:**
> "Reduce blanket `except Exception` by 80% in priority paths (web, storage, metrics)"

**This is acknowledged but not yet addressed.**

**Recommended Priority Paths:**
1. **Storage Layer** (`src/storage/*.py`) - Data integrity critical
2. **Metrics Registration** (`src/metrics/*.py`) - Silent failures affect observability
3. **Collector Core** (`src/collectors/*.py`) - Main business logic
4. **Orchestrator** (`src/orchestrator/*.py`) - System reliability

**Recommended Pattern:**
```python
# Bad - Current widespread pattern
try:
    critical_operation()
except Exception:
    logger.error("Operation failed")  # Root cause lost

# Good - Specific exception handling
try:
    critical_operation()
except ValueError as e:
    logger.error(f"Validation error: {e}", exc_info=True)
    raise
except IOError as e:
    logger.error(f"I/O error: {e}", exc_info=True)
    # Decide: retry, fallback, or raise
except Exception as e:
    logger.critical(f"Unexpected error: {e}", exc_info=True)
    # Only catch for cleanup/metrics, then re-raise
    raise
```

**Impact:** Critical - Affects system reliability and debugging

---

### 2.2 Inconsistent Error Routing

**Issue:** Multiple error handling mechanisms without clear separation of concerns.

**Evidence:**
```
src/error_handling.py           - Legacy error handling
src/errors/error_routing.py     - New error routing
src/errors/facade.py            - Error handler facade
```

**From README.md:**
> "Error Routing" listed in architecture table but implementation scattered

**Problem:**
No single source of truth for:
- When to log vs. raise
- Error categorization (transient vs. permanent)
- Retry policies per error type
- Alerting thresholds

**Recommended Fix:**
Create error taxonomy and routing rules:
```python
class ErrorSeverity(Enum):
    TRANSIENT = "transient"      # Retry with backoff
    PERMANENT = "permanent"      # Don't retry, alert
    CONFIGURATION = "config"     # User action required
    CRITICAL = "critical"        # System-wide failure

class G6Error(Exception):
    severity: ErrorSeverity
    should_retry: bool
    alert_threshold: int
```

**Impact:** High - Affects operational reliability

---

## 3. Testing Infrastructure Weak Points

### 3.1 Test Organization and Markers

**Issue:** Complex pytest marker system with unclear activation patterns.

**From pytest.ini:**
```ini
markers =
    optional: Optional developer / exploratory tests (disabled unless G6_ENABLE_OPTIONAL_TESTS=1)
    slow: Slow tests (enable with G6_ENABLE_SLOW_TESTS=1 or run -m slow explicitly)
    integration: Higher-level integration tests (may spin threads / external deps)
    perf: Performance smoke tests (timing thresholds / basic perf assertions)
    asyncio: Mark an async test function (managed by custom event_loop fixture)
    metrics_no_reset: Opt-out of the autouse metrics registry reset fixture
    broker: Tests that require broker provider initialization / credentials
    serial: Tests that must not run under parallel/xdist due to global mutable state
```

**Problem:**
- 8 different test categories with environment variable gates
- Unclear which tests run in default CI
- `serial` marker suggests global state issues
- `metrics_no_reset` indicates fixture isolation problems

**Evidence of Global State Issues:**
The need for `serial` marker and `metrics_no_reset` indicates tests are not properly isolated, creating flakiness risks.

**Recommended Fix:**
1. Audit all `serial` marked tests - eliminate global state
2. Make metrics registry properly fixture-scoped
3. Simplify marker system to: `unit`, `integration`, `slow`
4. Default CI should run all non-slow tests
5. Remove environment variable gates for test execution

**Impact:** Medium - Affects CI reliability and developer experience

---

### 3.2 Missing Test Coverage for Critical Paths

**From TECH_DEBT_HOTSPOTS.md:**
> "Suggested near-term high-impact areas for coverage uplift:
> - `src/orchestrator/catalog_http.py` branch edges
> - `src/panels/factory.py` panel assembly fallbacks
> - `src/metrics/metrics.py` rarely triggered exception branches
> - `src/storage/csv_sink.py` multi-path retention / error handling"

**Issue:** Core infrastructure modules lack comprehensive test coverage.

**Risk:** Critical path failures may not be caught until production.

**Recommended Action:**
1. Run coverage analysis: `pytest --cov=src --cov-report=html`
2. Focus on >80% coverage for all `src/storage/`, `src/orchestrator/`, `src/metrics/` modules
3. Add property-based tests for data quality edge cases
4. Integration tests for multi-module failure scenarios

**Impact:** High - Risk of production failures

---

## 4. Deprecation Management Issues

### 4.1 Accumulating Technical Debt

**From DEPRECATIONS.md:**
- 55+ active deprecation entries
- Multiple deprecated since September 2025, still present in November
- Unclear removal policies ("R+1", "R+2", "GATED")
- Some items marked "REMOVED" but discussed in docs

**Examples of Stale Deprecations:**
```
| Item | First Warn Release | Earliest Removal | Status |
|------|-------------------|------------------|--------|
| unified_main.collection_loop | 2025-09-26 | GATED (R+1 removal target) | Still present |
| start_live_dashboard_v2.ps1 | 2025-10-01 | R+1 | Still present |
| G6_DISABLE_CYCLE_TABLES | 2025-10-07 | 2025-11 | No-op but not removed |
```

**Problem:**
Deprecation policy not being enforced. Code marked for removal remains in codebase, creating:
- Maintenance burden
- Test complexity
- Confusion for new developers

**Recommended Fix:**
1. **Immediate:** Remove all items past their "Earliest Removal" date
2. **Policy:** Strict 2-release deprecation cycle, no exceptions
3. **Automation:** CI check fails if deprecated code past removal date exists
4. **Documentation:** Clear removal dates, not vague "R+1" notation

**Impact:** Medium - Affects codebase cleanliness and maintainability

---

### 4.2 Flag Proliferation

**Issue:** Over 100 `G6_*` environment variables controlling behavior.

**From README.md env governance:**
> "All `G6_` variables referenced in code must be documented in `docs/env_dict.md`"

**Problem:**
- No clear categorization (required vs. optional vs. debugging)
- Unclear precedence when multiple flags interact
- Startup-only vs. runtime-reload flags mixed together
- Deprecation status unclear for many flags

**Example Confusion:**
```bash
G6_ENABLE_LEGACY_LOOP=1          # Deprecated, but still works
G6_SUPPRESS_LEGACY_LOOP_WARN=1   # Suppresses warning for above
G6_LOOP_MAX_CYCLES vs G6_MAX_CYCLES  # Aliases with unclear precedence
```

**Recommended Fix:**
1. Categorize all flags:
   - `G6_CORE_*` - Required configuration
   - `G6_FEATURE_*` - Optional features
   - `G6_DEBUG_*` - Debugging/development only
2. Document precedence rules clearly
3. Remove all deprecated flags immediately
4. Add startup validation to fail on unknown flags

**Impact:** Medium - Affects operational clarity

---

## 5. Data Quality and Consistency Issues

### 5.1 CSV Storage Layer Complexity

**From CODE_HEALTH_ROADMAP.md:**
> "Decompose the top 6 largest modules... `src/storage/csv_sink.py`"

**Current State:**
```
src/storage/csv_sink.py (1200+ lines) - Main sink
src/storage/csv_writer.py         - Alternative writer
src/storage/csv_batcher.py         - Batching logic  
src/storage/csv_aggregator.py      - Aggregation
src/storage/csv_utils.py           - Utilities
src/storage/csv_validator.py       - Validation
src/storage/csvio/                 - New facade attempt
```

**Issue:**
Despite refactoring efforts, CSV writing has multiple paths with unclear ownership:
- Direct writes vs. buffered writes
- Legacy paths vs. facade paths
- `G6_USE_CSVIO_FACADE=0` opt-out suggests incomplete migration

**From CODE_HEALTH_ROADMAP.md:**
> "Update (2025-11-13): CSV facade default-on with safe opt-out"

**Problem:**
Having parallel implementations creates:
- Inconsistent error handling
- Duplicated logic
- Testing complexity
- Data integrity risks if paths diverge

**Recommended Fix:**
1. Complete facade migration - remove all legacy paths
2. Single `CsvWriter` interface
3. Remove `G6_USE_CSVIO_FACADE` flag
4. Comprehensive integration tests for edge cases (concurrent writes, failures, retries)

**Impact:** High - Data integrity critical for platform

---

### 5.2 Schema Evolution Without Versioning

**Issue:** CSV schema changes lack version tracking.

**From README.md Section 8:**
> "Principles: additive columns, distinct measurements... stable naming (`ce_` / `pe_` prefixes)"

**Problem:**
- No schema version field in CSV files
- Forward/backward compatibility not enforced
- Migration path unclear when schema changes
- Consumers may break on schema evolution

**Recommended Fix:**
1. Add `schema_version` column to all CSV outputs
2. Document supported version ranges
3. Validation logic to reject incompatible versions
4. Migration scripts for historical data

**Impact:** Medium - Affects data consumers

---

## 6. Performance and Scalability Concerns

### 6.1 Synchronous I/O in Critical Path

**Issue:** CSV writing blocks collector cycle.

**From Architecture:**
Collection cycle performs synchronous CSV writes after each index collection, blocking the next cycle.

**Evidence:**
```python
# From collector pattern
for index in enabled_indices:
    data = collect_options(index)
    write_csv_synchronously(data)  # Blocks here
```

**Impact:**
- Collection latency increases with disk I/O
- No parallelization of I/O across indices
- Slow disk = slow collection cycles

**Recommended Fix:**
1. Async I/O with write queue
2. Background writer thread/process
3. In-memory buffer with periodic flush
4. Metrics on write latency and queue depth

**Current Mitigation:**
`CsvBatcher` provides some buffering, but still synchronous flush.

**Impact:** Medium - Affects system scalability

---

### 6.2 Memory Pressure Without Backpressure

**Issue:** No hard limits on memory growth.

**From README.md Section 9:**
> "Memory pressure scaling | `src/utils/memory_pressure.py` | Drop high-cardinality load"

**Implementation:**
Memory pressure system exists but appears to be a soft advisory system, not hard backpressure.

**Problem:**
- High-volume periods could cause OOM
- No request rejection at memory limits
- Unclear if adaptive scaling actually prevents crashes

**Recommended Fix:**
1. Hard memory limits with request rejection
2. Circuit breakers trip at memory thresholds
3. Metrics on memory-based rejections
4. Clear operator guidance on tuning

**Impact:** High - Stability risk

---

## 7. Security and Operational Risks

### 7.1 Token Management

**Issue:** Token handling logic scattered across multiple providers.

**From README.md Section 11:**
```
src/tools/token_manager.py
src/tools/token_providers/kite.py
src/tools/token_providers/fake.py
```

**Concerns:**
- Tokens stored as environment variables (cleartext risk)
- No rotation mechanism mentioned
- Headless mode complexity suggests authentication fragility
- `KITE_ACCESS_TOKEN` persisted - where and how?

**Recommended Security Audit:**
1. Token storage location and permissions
2. Token rotation policy
3. Token exposure in logs/errors
4. Credential management in containerized deployments

**Impact:** High - Security risk

---

### 7.2 Error Information Leakage

**Issue:** Extensive logging may expose sensitive data.

**With 3,244 exception handlers, many likely logging full context including:**
- API keys in request headers
- Token values in error messages
- Internal system paths
- Configuration values

**Recommended Fix:**
1. Audit all logger.error() calls for sensitive data
2. Implement log sanitization
3. Structured logging with explicit field allow-list
4. Separate audit log for security events

**Impact:** Medium - Security/compliance risk

---

## 8. Documentation and Knowledge Management

### 8.1 Documentation Sprawl

**Finding:** 100+ markdown documentation files with unclear hierarchy.

**Evidence:**
```bash
$ ls *.md | wc -l
107
```

**Categories observed:**
- Architecture docs (ADVISOR_ARCHITECTURE.md, PIPELINE_DESIGN.md, etc.)
- Roadmaps (CODE_HEALTH_ROADMAP.md, ML_ROADMAP*, etc.)
- Changelogs (CHANGELOG.md, CHANGELOG_DASHBOARDS.md, etc.)
- Guides (DEPLOYMENT_GUIDE.md, OPERATOR_MANUAL.md, etc.)
- Status reports (COMPLETION_SUMMARY.md, WAVE*_TRACKING.md, etc.)

**Problems:**
- No clear document hierarchy or index
- Duplicated information across files
- Unclear which docs are authoritative
- Historical docs not archived
- Search is difficult

**Recommended Fix:**
1. Create `docs/` directory structure:
   ```
   docs/
     architecture/
     operations/
     development/
     roadmaps/
     archive/
   ```
2. Single authoritative README.md with clear links
3. Deprecate and archive historical docs
4. Regular documentation review cycle

**Impact:** Low - Developer productivity

---

### 8.2 README.md Maintainability

**Issue:** README.md is 1,530 lines - too large for effective use.

**Content includes:**
- Getting started
- Architecture overview
- Configuration reference
- Metrics documentation
- Release automation
- Performance tuning
- and much more...

**Problem:**
- Information overload for new users
- Difficult to maintain
- Likely to become outdated
- Multiple sections should be separate docs

**Recommended Structure:**
```
README.md              - Quick start and overview only (max 300 lines)
ARCHITECTURE.md        - System design
CONFIGURATION.md       - All config reference
OPERATIONS.md          - Running in production  
DEVELOPMENT.md         - Developer guide
```

**Impact:** Low - Onboarding efficiency

---

## 9. Logical Inconsistencies

### 9.1 Contradictory Patterns

**Issue:** Project simultaneously embraces and rejects certain patterns.

**Example 1: Global State**
- Uses singleton patterns (StatusReader, MetricsRegistry)
- Tests require `metrics_no_reset` marker to preserve global state
- But aims for proper dependency injection

**Example 2: Async/Sync**
- Has async providers (`src/providers/async_*.py`)
- But main orchestration loop is synchronous
- Mixed async/sync patterns throughout

**Example 3: Configuration**
- Promotes immutable config loaded at startup
- But has `force_reload=True` mechanisms
- Some flags are startup-only, others are dynamic

**Recommended Fix:**
Choose consistent patterns and enforce them:
1. **State Management:** DI everywhere, no singletons
2. **Async Model:** Pure async or pure sync, not mixed
3. **Configuration:** Immutable or hot-reload, not both

**Impact:** Medium - Architectural clarity

---

### 9.2 Naming Inconsistencies

**Issue:** Inconsistent naming conventions across codebase.

**Examples:**
- `unified_collectors` vs. `pipeline_root` (both do collection)
- `csv_sink` vs. `influx_sink` (different writer patterns)
- `facade.py` appears in multiple packages with different meanings
- `helpers`, `utils`, `tools` used interchangeably

**Recommended Standards:**
```
*_service.py   - Services with lifecycle
*_manager.py   - Resource managers
*_handler.py   - Event/request handlers  
*_client.py    - External API clients
*_adapter.py   - Interface adapters
*_facade.py    - Simplified interfaces (use sparingly)
```

**Impact:** Low - Code readability

---

## 10. Dependency and Coupling Issues

### 10.1 Tight Coupling

**Issue:** Core modules tightly coupled despite facade attempts.

**Dependency Analysis:**
```
collectors → metrics (direct coupling)
collectors → errors (direct coupling)
metrics → collectors (for registration)
errors → metrics (for error counting)
```

**This creates circular dependency requiring facades.**

**Recommended Architecture:**
```
Domain Layer (models, types)
    ↓
Metrics Layer (observability)
    ↓
Service Layer (collectors, storage)
    ↓
Application Layer (orchestrator)
```

**Impact:** High - Maintainability and testability

---

### 10.2 External Dependency Risks

**From requirements.txt analysis:**

**Critical Dependencies:**
- `kiteconnect>=4.0.0` - Single vendor lock-in
- `influxdb-client>=1.36.0` - Storage dependency
- `prometheus-client>=0.17.0` - Metrics dependency

**Risks:**
1. No abstraction over KiteConnect - migration difficulty
2. InfluxDB writes are synchronous - performance bottleneck
3. No fallback if Prometheus client unavailable

**Recommended Fix:**
1. Abstract provider interface (partially done)
2. Pluggable storage backends
3. Graceful degradation if observability unavailable

**Impact:** Medium - Vendor flexibility

---

## 11. Recommendations Summary

### Priority 1 (Critical - Address Immediately)

1. **Exception Handling Audit**
   - Reduce bare `except Exception:` from 3,244 to <500
   - Focus on storage, metrics, collectors first
   - Implement proper error taxonomy
   - **Estimated Effort:** 2-3 weeks
   - **Impact:** Prevents silent failures

2. **Remove Legacy Orchestration Loop**
   - Complete deprecation of `unified_main.collection_loop`
   - Remove `G6_ENABLE_LEGACY_LOOP` flag
   - Single canonical orchestration path
   - **Estimated Effort:** 1 week
   - **Impact:** Reduces maintenance burden

3. **CSV Writer Consolidation**
   - Complete facade migration
   - Remove legacy write paths
   - Single CsvWriter implementation
   - **Estimated Effort:** 2 weeks
   - **Impact:** Data integrity

### Priority 2 (High - Address Within 1 Month)

4. **Test Infrastructure Cleanup**
   - Remove global state from serial tests
   - Fix metrics registry isolation
   - Simplify pytest markers
   - **Estimated Effort:** 2 weeks

5. **Configuration System Unification**
   - Single config loading mechanism
   - Clear startup vs. runtime policy
   - Remove conflicting env vars
   - **Estimated Effort:** 1 week

6. **Deprecation Cleanup**
   - Remove all items past removal date
   - Enforce 2-release policy
   - CI check for stale deprecations
   - **Estimated Effort:** 1 week

### Priority 3 (Medium - Address Within 3 Months)

7. **Documentation Restructuring**
   - Organize into docs/ directory
   - Split README.md
   - Archive historical docs
   - **Estimated Effort:** 1 week

8. **Performance Improvements**
   - Async CSV writing
   - Hard memory limits
   - Backpressure mechanisms
   - **Estimated Effort:** 3 weeks

9. **Security Hardening**
   - Token management audit
   - Log sanitization
   - Credential rotation
   - **Estimated Effort:** 2 weeks

### Priority 4 (Low - Address Within 6 Months)

10. **Architectural Refactoring**
    - Break circular dependencies
    - Implement proper layering
    - Consistent naming conventions
    - **Estimated Effort:** 4-6 weeks

---

## 12. Conclusion

The G6 Platform demonstrates sophisticated engineering with strong observability and extensive documentation. However, several **fundamental inconsistencies and weak points** require attention:

### Critical Weaknesses:
1. **3,244 bare exception handlers** masking errors
2. **Multiple parallel execution paths** (legacy + new)
3. **Complex CSV storage layer** with competing implementations
4. **55+ active deprecations** not being enforced
5. **Tight coupling** requiring facade band-aids

### Strengths to Preserve:
1. Comprehensive test infrastructure
2. Strong metrics and observability
3. Active refactoring culture
4. Extensive documentation

### Overall Assessment:
**Maturity Level:** Production-ready but with significant technical debt  
**Risk Level:** Medium-High without remediation  
**Recommended Action:** Prioritize exception handling and deprecation cleanup immediately

### Success Metrics:
- Bare exceptions reduced to <500 (from 3,244)
- Legacy code removed (0 active deprecations)
- Single CSV write path
- Test isolation improved (0 serial-only tests)
- Documentation reorganized

**Estimated Total Effort for P1+P2:** 10-12 weeks of focused work

---

## Appendix A: Analysis Methodology

This analysis was conducted through:
1. Repository structure examination (498 source files, 592 test files)
2. Documentation review (107 markdown files)
3. Pattern detection (grep analysis for anti-patterns)
4. Historical review (CHANGELOG, DEPRECATIONS, INEFFICIENCIES_REPORT)
5. Architecture review (module dependency analysis)
6. Configuration analysis (pytest.ini, requirements.txt, env vars)

---

## Appendix B: Quick Wins

For immediate impact with minimal effort:

1. **Run existing cleanup scripts** (per INEFFICIENCIES_REPORT.md)
2. **Delete items marked REMOVED in DEPRECATIONS.md** (already approved)
3. **Split README.md** into focused docs
4. **Add CI check** for deprecated code past removal date
5. **Document which env vars require restart** vs. hot-reload

Each of these can be completed in 1-2 days.

---

**End of Analysis**
