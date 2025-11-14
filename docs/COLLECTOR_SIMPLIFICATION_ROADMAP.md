# Collector Simplification and Reliability Roadmap

Date: 2025-11-11
Owner: Platform/Collectors
Scope: src/collectors, src/orchestrator/cycle, related helpers and modules

## Goals
- Reduce complexity and improve maintainability of the collectors stack.
- Improve runtime reliability and performance without changing external behavior.
- Establish phase-by-phase verification so each change keeps the system green.

## Guiding principles
- Prefer explicit contracts over dynamic attributes and dicts.
- Fail fast on module import errors; use crisp logging for real failures.
- Snapshot environment once per cycle; avoid repetitive parsing inside tight loops.
- Keep logging lean and consistent.

## Phases and acceptance criteria

### Phase 1: Hygiene (low-risk, quick wins)
Changes
- Add optional typed fields to `CycleContext` (collector_settings, collector_ctx).
- Normalize fallback structured entries in `unified_collectors` to use `option_count` consistently.
- Fix market gate global declaration order (done).
- Keep behavior identical; only reduce type noise and import fragility.

Verification
- Unit tests: `pytest -q` passes.
- Import test: `import src.collectors.unified_collectors; callable(run_unified_collectors) is True`.
- Orchestrator one-cycle smoke: `G6_LOOP_MAX_CYCLES=1`, verify logs show `run_unified_collectors ... callable=True` and CYCLE line emitted.

Status (2025-11-11)
- Complete and stable. No regressions observed in latest full test runs.

### Phase 2: Env snapshot (performance)
Changes
- Build a per-cycle env snapshot in `orchestrator/cycle.run_cycle` (interval, parallel flags, stale modes, etc.).
- Pass snapshot into `unified_collectors.run_unified_collectors` and downstream as needed.
- Replace hot-path EnvConfig/get_* calls with snapshot reads.

Verification
- Same as Phase 1 plus basic perf sanity: cycle duration doesn’t regress; options processed unchanged.

Status (2025-11-11)
- Implemented inside `unified_collectors` via `CycleEnvSettings.from_env()` snapshot hydration and propagation as `cycle_env`.
- Follow-up: optionally lift snapshot creation into `orchestrator/cycle` to make ownership explicit and reduce coupling.
- Observed minor inconsistencies: some modules still call `EnvConfig.get_*` directly (see scan highlights) — trackable cleanup.
 - Pipeline path: Added per-run `_env_snapshot` in `src/collectors/modules/pipeline.py::run_pipeline` capturing hot flags (REF_DEBUG, ENRICH_ASYNC, PIPELINE_PARITY_LOG, ALERTS_FLAT_COMPAT, PIPELINE_MEMORY_GAUGE, PIPELINE_INCLUDE_DIAGNOSTICS) and replaced direct reads in the inner loop. Remaining direct reads are limited to the optional benchmark helper outside the hot path.

### Phase 3: Settings unification
Changes
- Choose canonical `CollectorSettings` (src/collectors/settings.py). Export a `get_collector_settings()`.
- Deprecate `collector_settings.py` and redirect imports to canonical implementation.

Verification
- All imports resolve; no `ImportError` for settings.
- `pytest -q` green; one-cycle run stable.

Status (2025-11-11)
- In place. `unified_collectors` loads `CollectorSettings` once per cycle and wires into context. No remaining imports to deprecated modules found in the main path.

### Phase 4: Consolidate strike universe selection
Changes
- Prefer `build_strike_universe` (central policy + meta) with `compute_strike_universe` as a single deprecated fallback path.
- Remove legacy `deps['build_strikes']` usage in orchestrator pipeline path; orchestrator now attempts:
	1. `build_strike_universe` -> use `.strikes` list
	2. `compute_strike_universe` (deprecated thin wrapper; still bridges to legacy deterministic builder)
	3. Final ATM-only list `[atm]` as last-resort safety (avoids hard failure while preserving minimal downstream flow)
- Adaptive scale passthrough preserved (`G6_ADAPTIVE_SCALE_PASSTHROUGH` + `adaptive_scale_factor`).
- Error handling hardened: each stage isolated so failures do not cascade.

Verification
- CYCLE options count and strike coverage unchanged for a representative window (manual spot-check against pre-change logs).
- One-cycle smoke (`G6_LOOP_MAX_CYCLES=1` with pipeline flag) completes without new warnings.
- No increase in error logs; per-index logs still show strike counts and prefilter summaries.
- Fallback layers exercised in tests where primary builder intentionally fault-injected.

Status (2025-11-11)
- Legacy/unified path: Complete. `src/collectors/modules/index_processor.py` uses `modules.strike_universe.build_strike_universe` with robust fallback to ATM-only.
- Pipeline path: Bridge implemented. `src/collectors/modules/pipeline.py` now prefers `modules.strike_universe.build_strike_universe` with fallback to legacy `compute_strike_universe` and final ATM-only safety; metadata (step, cache_hit) passed through when available.

### Phase 5: Metrics registration and cardinality guard
Changes
- Central registry to define metrics once with stable names/labels.
- Replace scattered setattr-based lazy creation with helper methods.

Verification
- No “duplicate metric” warnings; cardinality guard no longer trips in normal operation.

Status (2025-11-11)
- Partial. Several modules still do lazy metric creation (e.g., stale metrics in `index_processor`, legacy cycle histograms). No duplicates observed in tests, but consolidation remains.
- Next: introduce a `metrics.registry` helper and migrate common counters/gauges.

### Phase 6: Logging simplification
Changes
- Default to a single CYCLE format (raw or readable). Only build PRETTY table if explicitly requested.
- Avoid repeated header output unless configured.

Implementation status
- Compact CYCLE logging is now the default: a single end-of-cycle summary line is always emitted.
- Added G6_CYCLE_VERBOSE_LOGS=1 to re-enable detailed step-by-step CYCLE lines.
- Added G6_CYCLE_PRETTY=1 to render a minimal PRETTY summary table alongside the compact line.

Verification
- Tail logs are compact; CYCLE line always present.
- No missing operator signals vs previous output.

Status (2025-11-11)
- In place in `unified_collectors` with `cycle_output` mode selection (raw | pretty | both) and style control (legacy | readable). Daily banner emission deduplicated under single-header mode.
- Follow-up: ensure pipeline mirrors the same output controls or defers to facade for consistency.

### Phase 7: Interfaces and contracts
Changes
- Introduce lightweight dataclasses/TypedDicts for index and expiry results.
- Convert internal flows to typed structures; dicts only at IO edges.

Implementation status
- Introduced TypedDicts in `src/collectors/types.py`:
	- `ExpiryResult`, `IndexResult`, and `PipelineReturn` (outer shape reference)
- Updated `src/collectors/modules/pipeline.py` to annotate internal structures with these types.
- Preserved dict return shape at IO boundaries for compatibility; used local casts where legacy helpers expect plain dicts.

Verification
- Type checking is happier; runtime behavior unchanged; tests green.

Status (2025-11-11)
- Pipeline: Using `src/collectors/types.py` contracts consistently.
- Unified path: `index_processor` defines local TypedDicts for its return struct; consider harmonizing with shared types for consistency and future static checks.

---

## Ecosystem scan highlights (Nov 2025)

- Strike universe duplication
	- Unified path uses `modules.strike_universe.build_strike_universe`; pipeline now prefers the same via an adapter, with legacy `compute_strike_universe` as fallback.
	- Status: adapter done; legacy path remains as safety net until full removal.

- Env access inconsistency
	- Mixed use of `EnvConfig.get_*`, `env_adapter.get_*`, and per-cycle snapshot (`CycleEnvSettings`).
	- Action: prefer `CycleEnvSettings` values in hot paths; gate any remaining direct reads behind adapter helpers for gradual migration.

- Expiry map construction duplication
	- Converged: both unified and pipeline now delegate to `src/collectors/helpers/expiry_map.build_expiry_map` (unified via new adapter `_build_expiry_map`).
	- Outcome: identical (map, stats) tuple across paths; duplication removed.

- Metrics lazy registration scattered
	- Several modules lazily create Prometheus objects via setattr on the metrics instance; risk of divergence.
	- Action: create `src/metrics/registry.py` with idempotent getters; migrate most-used metrics (cycle duration, stale, alert categories) first.

- Typed structures split
	- Shared `types.py` exists; `index_processor` has local TypedDicts.
	- Action: align `index_processor` to shared contracts where practical or re-export a consistent alias to avoid drift.

- Logging mode parity
	- `unified_collectors` supports raw/pretty/both; pipeline logs are independent and use phase_log.
	- Action: either delegate final cycle line emission to the facade or add the same mode flags to pipeline for operator parity.

## Next actions and acceptance criteria

1) Pipeline strike-universe bridge (Completed 2025-11-11)
- Do: Adapter added in pipeline to call `modules.strike_universe.build_strike_universe` and translate meta as needed. `compute_strike_universe` retained as fallback for one release.
- Accept: Verified no change in strike counts on samples; no new warnings; deprecation note present in code.

2) Env snapshot adherence sweep
- Do: Replace direct `EnvConfig.get_*` in hot paths of unified/pipeline with `CycleEnvSettings` fields passed down, or `env_adapter` wrappers if snapshot not available.
- Accept: Grep shows no hot-path direct `EnvConfig` calls in collectors/modules excluding the snapshot builder; perf neutral.

3) Expiry map utility convergence (Completed 2025-11-11)
- Do: Added unified adapter `_build_expiry_map` delegating to shared `helpers.expiry_map.build_expiry_map` used already by pipeline.
- Accept: Verified tests green; no change to expiry counts or snapshot summary fields.

4) Metrics registry helper
- Do: Add `src/metrics/registry.py` with idempotent getters and wire stale/system cycle metrics plus cycle duration histograms through it.
- Accept: No duplicate metric warnings; metrics names unchanged; codepaths updated in unified/pipeline and index_processor.

5) Type contracts alignment
- Do: Reuse `src/collectors/types.py` in `index_processor` or re-export its local TypedDicts from a shared module to reduce split definitions.
- Accept: Type annotations converge; no runtime behavior change; tests green.

6) Logging parity toggle in pipeline
- Do: Honor `CYCLE_OUTPUT`/`CYCLE_STYLE` flags or delegate cycle line emission to facade for a single source of truth.
- Accept: Operator sees same raw/pretty/both behavior across both paths.

## Rollback plan
- Each phase is independently revertible.
- Keep feature flags for logging mode and parallel/index processing while iterating.

## Test checklist for each phase
- Unit tests: `pytest -q`.
- Import sanity: `import src.collectors.unified_collectors`.
- Single-cycle orchestrator run with `G6_LOOP_MAX_CYCLES=1`.
- Spot-check logs: CYCLE line present, options > 0 during market hours, no new exceptions.

## Notes
- Keep market-hours gating stable; use `G6_FORCE_MARKET_OPEN=1` for off-hours testing.
- Ensure settings and env flags are documented (docs/ENV_FLAGS_TABLES.md) when unified.
