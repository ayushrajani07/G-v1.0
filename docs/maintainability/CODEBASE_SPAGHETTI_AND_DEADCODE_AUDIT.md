# Codebase Audit: Spaghetti Hotspots & Nonviable Code

Date: 2026-02-03

---

## Progress Since This Audit (As of 2026-02-06)

This section is a **handover snapshot** for another local agent.

### Shipped / Landed on this branch

- **Path Forecast route split completed**
  - `src/web/dashboard/routes/path_forecast.py` (historical god-file) has been decomposed into `src/web/dashboard/routes/path_forecast/`.
  - FastAPI wiring lives in `src/web/dashboard/routes/path_forecast/_router.py`; logic is extracted into focused modules such as:
    - `_pipeline.py` (forecast execution + robust fallbacks)
    - `_profiles.py` (profile overrides and effective knob resolution)
    - `_json_ribbon.py` (output shaping / ribbon widening safety)
    - `_tp_series_handler.py`, `_prediction_history_handler.py`, `_stats_handler.py` (endpoint implementations)

- **ML routes split completed**
  - The historical `src/web/dashboard/routes/ml.py` god-file has been decomposed into the `src/web/dashboard/routes/ml/` package.
  - FastAPI wiring lives in `src/web/dashboard/routes/ml/_router.py`; endpoint logic is now in focused handler modules:
    - `predictions.py`, `ensemble.py`, `diagnostics.py`, `delta.py`, `correlations.py`, `model_matrix.py`, `move_stats.py`
  - Shared helpers used across handlers are centralized in `src/web/dashboard/routes/ml/_common.py`.
  - Back-compat router wiring lives in `src/web/dashboard/routes/ml_legacy.py` (trimmed to router wiring only; no endpoint logic remains).

- **Tests added for new helpers / stability**
  - Added unit tests for date/now/index normalization helpers and CSV time parsing.
  - Added targeted tests for orchestrator resilience and storage utilities.

- **Safer best-effort behavior in diagnostics helpers**
  - Diagnostics-style helpers that should not crash the main loop were hardened to return `None` on unexpected errors (instead of re-raising).

- **Env access modernization in touched paths**
  - Several code paths migrated from raw `os.environ.get(...)` reads to `EnvConfig` getters for consistent parsing and caching behavior.

- **Repo health**
  - Test suite is collecting and runs cleanly on this branch (many tests are intentionally skipped; that is expected).

### Still high-risk / remaining work

- **ML routes are still duplicated across entrypoints**
  - `src/web/dashboard/app.py` still defines ML endpoints directly (historical), while the modular handlers now live in `src/web/dashboard/routes/ml/`.
  - Recommended next step: pick a single source of truth (preferably `routes/ml/`) and migrate `app.py` to `include_router(...)`, then delete duplicate route bodies.

- **Storage hotspot remains**
  - `src/storage/csv_sink.py` is still the top coverage-risk hotspot; extraction of pure row-shaping utilities + tests is the highest-leverage next step.

- **Collector pipeline still has compatibility complexity**
  - Several pipeline entrypoints now accept legacy positional args for `metrics`/`influx_sink`. This reduced breakage, but a longer-term cleanup should:
    - standardize call signatures across `run_unified_collectors`, module pipeline, and orchestrator cycle
    - remove positional-arg shims after a deprecation window

### Suggested next PR-sized tasks

1. Migrate ML endpoints out of `src/web/dashboard/app.py` to `src/web/dashboard/routes/ml/` router(s) and delete duplicate endpoint bodies.
2. Extract pure CSV row-building utilities from `src/storage/csv_sink.py` into small modules and add 10–20 focused unit tests.
3. Reduce catch-all exceptions in the remaining top 3 hotspots and route errors through the centralized error handler where appropriate.

This repository grew quickly with heavy AI-agent assistance and partial, evolving architecture. The goal of this audit is to identify:

1. **Spaghetti hotspots**: large, low-cohesion files/modules with high exception-suppression, type-ignores, and mixed responsibilities.
2. **Nonviable / inoperative code**: tombstones (intentional hard-removals), dead scripts, and code paths that cannot run (missing deps, removed shims, syntax/parse issues).

This is a **triage document**: it prioritizes where refactors will pay off and which code should be removed, moved, or re-scoped.

---

## 1) Ground Truth Inputs (Generated Artifacts)

These files were generated from the current workspace and are the factual basis for the rankings below:

- artifacts/maintainability/module_stats.md
- artifacts/maintainability/file_hotspots.md
- artifacts/maintainability/coverage_hotspots.txt
- docs/dead_code.md
- tools/dead_code_report.json

If you re-run on a new branch/state, treat this report as stale and regenerate the artifacts first.

---

## 2) Highest-Risk Spaghetti Hotspots (Start Here)

The following files combine one or more of:
- **Very high LOC** (hard to reason about / review)
- **High `except Exception` counts** (error swallowing / control-flow soup)
- **Many `type: ignore`** (type system bypass; often correlates with unclear interfaces)
- **Low test coverage** (from coverage risk rankings)

### A. Web API “God Files”

From artifacts/maintainability/file_hotspots.md:

- src/web/dashboard/routes/path_forecast.py (historical: ~3319 LOC; pre-refactor)
  - Update (2026-02-05): decomposed into `src/web/dashboard/routes/path_forecast/` package (router: `_router.py`, logic in handler modules)
- src/web/dashboard/routes/ml.py (historical: 2775 LOC, 147 catch-all exceptions)
  - Update (2026-02-06): replaced by `src/web/dashboard/routes/ml/` handler package + `src/web/dashboard/routes/ml_legacy.py` (compat router; now thin wiring-only)
- src/web/dashboard/app.py (1154 LOC, 53 catch-all exceptions)

**Why these are likely spaghetti**
- Route modules are simultaneously: request parsing, caching, domain orchestration, storage interaction, and error routing.
- High catch-all exception density strongly suggests “keep the server alive at any cost” patterns, which drift into silent failure.

**Recommended refactor shape**
- Split per-domain routers into smaller files (e.g., `routes/path_forecast/*.py`), with a strict separation:
  - request/response DTOs
  - services (domain logic)
  - adapters (storage/FS/network)
- Replace broad `except Exception` blocks with centralized error categorization (there is already an error-handling layer available).

### B. Storage & Persistence

From artifacts/maintainability/file_hotspots.md and coverage_hotspots.txt:

- src/storage/csv_sink.py (2912 LOC, 53 catch-all exceptions; **Rank #1** in coverage risk)
- src/storage/influx_sink.py (coverage risk hotspot)

**Why this is risky**
- This code is on the core data path; failures silently degrade correctness.
- Large file + legacy compatibility layers suggest multiple generations of behavior coexisting.

**Recommended refactor shape**
- Extract “CSV schema + row building” into small, pure functions with unit tests.
- Extract I/O backends (already partially present under `src/storage/csvio/`) and converge remaining legacy inline paths into those backends.

### C. Collectors / Pipeline Core

From artifacts/maintainability/file_hotspots.md and coverage_hotspots.txt:

- src/collectors/unified_collectors.py (1991 LOC; coverage risk hotspot)
- src/collectors/modules/index_processor.py (1025 LOC, 69 catch-all exceptions)
- src/collectors/pipeline/executor.py (744 LOC, 58 catch-all exceptions; coverage risk hotspot)

**Why this is risky**
- This is the core orchestration layer; spaghetti here creates cascading complexity everywhere else.

**Recommended refactor shape**
- Make the per-cycle pipeline explicit as a sequence of typed phases with a single error/reporting strategy.
- Reduce `except Exception` blocks by moving best-effort logic into narrow helpers.

### D. Metrics Registry / Typing Debt

From artifacts/maintainability/file_hotspots.md:

- src/metrics/metrics.py (1719 LOC, **139** `type: ignore`)

**Why this is risky**
- The registry is cross-cutting and imported everywhere; type-ignore heavy code tends to hide implicit contracts.

**Recommended refactor shape**
- Stabilize a small public API: registry creation, registration, and emission.
- Move domain-specific metrics into dedicated modules (already partially done) and enforce import direction via CI checks.

---

## 3) Test Coverage “Risk Hotspots” (Under-Tested + Large)

From artifacts/maintainability/coverage_hotspots.txt (risk = uncovered_lines * log(total_lines)):

Top examples:
- storage/csv_sink.py
- collectors/unified_collectors.py
- utils/output.py
- orchestrator/catalog_http.py
- orchestrator/cycle.py

**Interpretation**
- These files are either not executed by tests or contain large uncovered regions.
- Refactors here should be paired with targeted tests first (even a small harness helps).

---

## 4) Nonviable / Inoperative Code (and Why)

### A. Tombstones / Hard-Removed Shims (Intentional Nonviable)

These files are designed to **fail fast** if imported, to prevent silent divergence:

- src/unified_main.py → raises RuntimeError on import (legacy entrypoint removed)
- src/providers/kite_provider.py → raises ImportError (deprecated shim removed)
- src/summary/unified/snapshot.py → tombstone stub (legacy assembler removed)

**Action**
- Keep tombstones only if you still expect external callers.
- Otherwise, delete after a deprecation window and update docs to remove references.

### B. Optional-Dependency “Hard Fail” Paths

Several modules raise RuntimeError if optional deps are missing (e.g., pandas/plotly/sklearn). This is not inherently wrong, but it creates *runtime surprise*.

**Action**
- Ensure optional features are behind explicit flags and have clear error messages at the entrypoint (not deep inside helpers).

### C. Dead/Unused Code Candidates (Vulture)

Vulture scan currently reports:

- Total findings: **691**
- Types (count): attribute 50, class 23, function 151, method 173, variable 287, ...

See full list:
- docs/dead_code.md
- tools/dead_code_report.json

**Interpretation**
- This list is a *candidate set*, not proof. Dynamic imports, plugin patterns, and reflection can cause false positives.
- However, **691** is high enough to justify a cleanup project: either remove, move to `archive/`, or add targeted allowlisting with justification.

**Recommended process**
1. Triage by *package criticality* (start with scripts/ utilities first).
2. Delete obvious unused local-only scripts.
3. For `src/` findings, confirm reachability from `scripts/run_orchestrator_loop.py` and `scripts/summary/app.py` flows.

---

## 5) Architectural Smells Worth Calling Out

These patterns create long-term “spaghetti pressure” even if each file individually looks fine:

- **Dual namespaces**: both `src/provider` and `src/providers` exist (plus `src/broker/*`). This increases import ambiguity and migration churn.
- **Legacy compatibility embedded in core paths** (many “mirror legacy behavior” comments) increases branching and test matrix size.
- **Catch-all exception normalization**: heavy `except Exception` usage is a sign that errors are being handled by *continuing*, rather than being classified, surfaced, and acted on.

---

## 6) Immediate Next Steps (Recommended)

If the goal is to quickly reduce spaghetti and remove nonviable code without destabilizing production paths:

1. **Split the biggest route modules** (`routes/path_forecast/` package, `routes/ml/` package + `routes/ml_legacy.py`) into submodules.
  - Update (2026-02-07): ML is split into `routes/ml/`; `ml_legacy.py` is wiring-only; remaining work is de-duplicating `app.py` route bodies.
2. **Put tests around CSV persistence** (even 10–20 focused tests around row-shaping + I/O invariants).
3. **Reduce broad exception handling** in collector pipeline hotspots; adopt a consistent error taxonomy.
4. **Run dead-code triage**: remove clearly unused scripts and consolidate duplicate script copies.
5. **Update docs to match reality**: `src/unified_main.py` is removed and should not be presented as an entrypoint.

---

## 7) Concrete Implementation Roadmap (Phased, PR-Sized)

This roadmap is designed to be *safe* (small PRs, measurable outcomes) and to reduce risk while paying down complexity.

### Guiding Constraints (Non-Negotiables)

- **No behavior change without tests** in core persistence + cycle orchestration paths.
- **Prefer extraction over rewrite**: move code behind stable interfaces first; only then simplify.
- **Keep endpoint compatibility** for Grafana routes (paths + response shape) unless versioned.
- **Every phase has a “stop point”** where the system remains shippable.

### Success Metrics (Track Every Phase)

- Coverage hotspot risk decreases for the top 5 files (see artifacts/maintainability/coverage_hotspots.txt).
- Reduce catch-all exception density in the worst offenders (web routes + collectors).
- Reduce typing bypass counts in metrics registry hotspots.
- Reduce vulture findings over time with a controlled baseline.

---

### Phase 0 — Baseline, Guardrails, and “Make Refactors Safe” (1–3 PRs)

**Goal:** make the repo resilient to change and create measurement feedback.

PR0.1 — Codify maintainability artifacts as regeneratable
- Add a short doc section (or Make/PS1 script) that runs:
  - scripts/maintainability_audit.py
  - scripts/coverage_hotspots.py
  - python -m scripts.cleanup.dead_code_scan
- Store outputs in artifacts/maintainability/ (already used) and ensure paths are stable.

PR0.2 — Dead-code scan: establish a baseline allowlist + budget
- Decide policy:
  - Option A (recommended): baseline allowlist = current findings; CI fails only on *new* items.
  - Option B: no baseline; CI fails immediately (high friction right now given 691 items).
- Implement baseline generation via `python -m scripts.cleanup.dead_code_scan --update-baseline`.
- Set `G6_DEAD_CODE_BUDGET` (start high, then ratchet down).

Acceptance Criteria
- You can run the three audit scripts locally and get deterministic outputs.
- CI (or local gates) can fail on *new* dead-code regressions.

Stop Point
- No runtime behavior changed.

---

### Phase 1 — Web Routes: Split the God Files Without Breaking Grafana (3–6 PRs)

Targets
- src/web/dashboard/routes/path_forecast.py (historical; now decomposed into `src/web/dashboard/routes/path_forecast/`)
- src/web/dashboard/routes/ml.py (historical; now decomposed into `src/web/dashboard/routes/ml/` + `src/web/dashboard/routes/ml_legacy.py`)
- src/web/dashboard/app.py (1154 LOC)

Strategy
- Convert “one giant router module” into a *package* with clear layers:
  - `routes/path_forecast/router.py` (FastAPI wiring only)
  - `routes/path_forecast/schemas.py` (request/response DTOs)
  - `routes/path_forecast/service.py` (domain orchestration)
  - `routes/path_forecast/storage.py` (CSV/FS adapters)
  - `routes/path_forecast/cache.py` (cache helpers)

PR1.1 — Mechanical split: move pure helpers + constants
- Move pure functions and constants into new modules.
- Keep original endpoints in place by importing from the new modules.

PR1.2 — Add contract tests for a small set of endpoints
- Add tests that validate:
  - response JSON keys exist
  - status codes on expected inputs
  - caching behavior isn’t catastrophically broken
- Focus on 3–5 critical endpoints only (don’t aim for full coverage upfront).

PR1.3+ — Reduce exception soup by centralizing error handling
- Replace repeated `except Exception` blocks with:
  - a single wrapper per endpoint, OR
  - centralized service-layer error categorization (using existing error-handling patterns).

Acceptance Criteria
- Endpoints remain identical for the selected contract tests.
- Route modules shrink meaningfully (LOC and exception counts decrease).

Stop Point
- Router works; internals are split, but behavior preserved.

---

### Phase 2 — Storage CSV Sink: Extract Pure Logic + Tests First (4–8 PRs)

Target
- src/storage/csv_sink.py (highest coverage risk)

Strategy
1. Identify “pure” logic: row-building, timestamp rounding, schema assertions, PCR helpers, junk filtering decisions.
2. Extract those into small modules (or functions) with focused tests.
3. Only after tests exist, simplify legacy compatibility branches.

PR2.1 — Extract pure row-building helpers
- Create a module like `src/storage/csv_rows.py` (or similar) containing pure functions.
- Add unit tests with representative minimal inputs.

PR2.2 — Consolidate I/O pathways into existing csvio backends
- Where csv_sink has inline legacy I/O, redirect toward `src/storage/csvio/` backends.

PR2.3 — Add invariants tests (“does not break files”)
- Tests for:
  - header consistency
  - column alignment
  - idempotent gzip behavior (if applicable)
  - no double-write for same logical row in same cycle

Acceptance Criteria
- Coverage hotspot risk for csv_sink decreases.
- No schema regressions in existing tests.

Stop Point
- csv_sink still exists, but core logic is test-covered and extracted.

---

### Phase 3 — Collectors & Cycle Orchestration: Make the Pipeline Explicit (3–6 PRs)

Targets
- src/collectors/unified_collectors.py
- src/collectors/modules/index_processor.py
- src/collectors/pipeline/executor.py

Strategy
- Introduce a small typed “phase result” model (success/failure + diagnostics).
- Replace scattered `except Exception: pass` patterns with structured outcomes and a small number of choke points.

PR3.1 — Define a shared phase result + diagnostics container
- Use dataclasses / TypedDicts to standardize returns.

PR3.2 — Refactor one index pipeline path end-to-end
- Pick one index flow and make it use the phase model.
- Add tests for the phase ordering and error bubbling.

PR3.3 — Reduce catch-all exceptions in hotspots
- Replace broad handlers with narrower exceptions or consolidated reporting.

Acceptance Criteria
- Reduced exception density in these collector hotspots.
- Improved debug visibility (errors categorized, not swallowed).

Stop Point
- Collector still runs; pipeline is clearer and testable.

---

### Phase 4 — Metrics Registry: Reduce `type: ignore` and Stabilize Interfaces (2–5 PRs)

Target
- src/metrics/metrics.py

Strategy
- Identify the true minimal public surface (register, emit, group gating, metadata dump).
- Add protocols / typed wrappers to reduce `type: ignore` count.

PR4.1 — Define minimal protocols for metric objects used across modules
- Replace “duck-typed” access patterns with explicit protocols.

PR4.2 — Move domain-specific families out of the registry core
- Keep registry core as wiring only.

Acceptance Criteria
- Drop `type: ignore` count substantially in metrics/metrics.py.
- No import-direction violations (keep existing deep-import governance checks green).

Stop Point
- Registry is stable; types are improved incrementally.

---

### Phase 5 — Dead Code & Script Consolidation: Delete With Confidence (ongoing, 1–2 PRs/week)

Targets
- scripts/ (many vulture findings)
- duplicates under src/*/scripts/ (if any are legacy copies)

Strategy
- Prefer deleting unused scripts over allowlisting them.
- For “maybe used” items, add a short justification in tools/dead_code_allowlist.json.

Recommended cadence
- Each PR removes a small, obvious set (e.g., 10–30 items) with tests passing.

Acceptance Criteria
- Vulture findings trend down over time.
- No operational workflows lose their entrypoints (document replacements).

---

### Suggested Execution Order (Practical)

1) Phase 0 (guardrails)
2) Phase 1 (web route splitting) + minimal contract tests
3) Phase 2 (csv_sink extraction + tests)
4) Phase 3 (collector pipeline explicitness)
5) Phase 4 (metrics types)
6) Phase 5 (dead code cleanup ongoing)

---

### “First 2 Weeks” Concrete Backlog (If You Want an Immediate Sprint Plan)

- Week 1
  - PR0.1: add a single script/doc to regenerate audits
  - PR0.2: baseline dead-code allowlist + budget
  - PR1.1: split src/web/dashboard/routes/path_forecast.py into package modules (mechanical move only)

- Week 2
  - PR1.2: add 3–5 endpoint contract tests for path_forecast
  - PR2.1: extract pure helpers from src/storage/csv_sink.py into src/storage/csv_sink_compat_utils.py (daily open tracking, net/day changes, prev-close selection/parsing) + add focused unit tests

