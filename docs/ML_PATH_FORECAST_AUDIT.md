# ML Path Forecast Arm Audit (Phase A Kickoff)

Date: 2025-11-07

## Scope
Comprehensive review of the path forecast ML subsystem (retrieval, composite, hybrid fallback, calibration, archival, grid evaluation) to identify complexity, inefficiencies, and redundancy. This document preserves the findings prior to Phase A refactor.

## High-Impact Findings
1. Repeated TP extraction logic across multiple modules (route, retrieval, composite, grid eval, forecast_core, archival). Centralize into `extract_tp()`.
2. Duplication of window and recent sequence building ("since open" semantics) scattered. Introduce `effective_window_since_open()` and `build_recent_window()` utilities.
3. Route reimplements forecasting pipeline instead of delegating consistently to service layer; fallback drift only in route. Move logic into service (`forecast_core`) or shared utilities.
4. Retrieval forecaster rescans and reparses all historical files each call. Add caching for per-day TP sequences + query normalization; later consider ANN approximate search.
5. Grid evaluation script re-parses realized data and rebuilds windows for every parameter combination. Precompute realized map and query windows per day.
6. Band scaling/clamping duplication (route vs calibration service vs forecast_core). Consolidate into one calibration ops module.
7. Passing `root=None` into configs in `forecast_core.py` risks silent fallback; ensure explicit data root.
8. Excess broad `except Exception: pass` blocks obscure root causes. Replace with structured logging or diagnostics collection.

## Medium Priority Issues
- Simplistic quantile interpolation without NaN filtering.
- Re-centering logic may distort calibrated bands; cap shift magnitude.
- Fallback drift slope uses simple linear regression; adopt robust estimator (Theil-Sen).
- Metrics reconstruction overhead; share bucketized realized map.
- Archival frequency unthrottled; add minimum interval.
- Market hours/open/close calculations duplicated; centralize.
- Profile `force_mode` not enforced end-to-end.
- Thin test coverage of retrieval edge cases and fallback conditions.

## Lower Priority / Cleanups
- Prior median recomputed each call; cache day futures.
- Timestamp parsing repeated; normalize during CSV load.
- Raw variant reverse-scaling may accumulate precision drift.
- Scripts lack backoff/jitter on API calls.
- Diagnostics object not schema-defined; risk of drift.
- Scattered magic numbers; central constants file recommended.

## Architectural Streamlining (Phases)
Phase A: Utilities centralization + route simplification + minimal caching groundwork.
Phase B: Performance uplift (historical TP caching, candidate pruning / embeddings).
Phase C: Model quality improvements (alternative distance metrics, volatility regimes, weighted quantiles).
Phase D: Advanced indexing (ANN), vectorization, offline preprocessing.

## Phase B Kickoff (2025-11-07)
Status: Initiated

### Objectives
1. Introduce per-day TP series cache (LRU) to reduce repeated CSV parsing in retrieval/composite forecasters.
2. Add optional scan limiter (max_days_scan) to constrain historical file iteration cost.
3. Surface cache stats (entries, hits, misses, evictions) in retrieval meta for dashboard/header visibility.
4. Implement optional candidate pruning hooks (time proximity / minimum rows), default-off.

### Completed
- Implemented `src/path_forecast/cache.py` (LRU, size-capped, thread-safe) with `get_day_tp`, `invalidate_day`, `stats`.
- Integrated cache into `RetrievalPathForecaster` and `CompositePathForecaster` historical TP loads.
- Added `max_days_scan` to `RetrievalConfig`/`CompositeConfig` and cache stats emission in `last_meta`.
- Implemented candidate pruning hooks (opt-in): `min_hist_rows` and `max_time_gap_ratio` in Retrieval/Composite.
- Emitting pruning metrics in meta (`pruned_days`, `retained_days`).
- Exposed lightweight headers on `/api/ml/path_forecast_json`: `X-Retrieval-Pruned`, `X-Retrieval-Retained`, `X-Cache-*` alongside existing mode/k/window/candidates.

### Pending
- Profiling baseline: measure median retrieval latency before/after cache+pruning in staging.
- Prometheus exposure for cache/pruning counters (optional; headers exist today).
- Embedding groundwork (vector representation of windows) for future ANN.

### Risk Notes
- Cache assumes immutability of historical day CSVs; if backfills occur, need explicit invalidation path (added `invalidate_day`).
- Memory footprint manageable (<300 lists); monitor if horizon expansion increases list sizes.

---

## Phase A Concrete Tasks
- Create `src/path_forecast/common.py` with: `extract_tp`, `row_time_ms`, `effective_window_since_open`, `build_recent_window`, `build_bucketed_realized`.
- Refactor `path_forecast.py` to use utilities instead of local duplicates; keep external API stable.
- Refactor `retrieval.py` and `composite.py` to use `extract_tp` for TP series extraction.
- Remove or delegate old helper functions; mark deprecation where necessary.
- Add docstrings & type hints for shared utilities.
- (Optional) Insert TODO logging notes at major exception swallow points.

## Risk & Effort Matrix (Top 6)
| Item | Effort | Risk | Gain |
|------|--------|------|------|
| Common TP/timestamp utilities | Low | Low | High |
| Route→service consolidation | Medium | Low | Medium |
| Historical TP cache | Medium | Medium | High |
| Grid eval optimization | Medium | Low | High |
| Retrieval candidate pruning | Medium | Medium | High |
| Robust fallback drift | Low | Low | Medium |

## Initial Metrics to Track Post-Phase A
- Forecast latency (ms) median & 95p.
- Cache hit ratio for `path_forecast_json`.
- Fallback activation count per hour.
- Candidate set size median & 95p.

## Next Steps
Proceed with implementing Phase A utilities and route/forecaster refactors. Validate no API contract changes (headers, JSON shape) and maintain existing dashboard functionality.

---
End of preserved audit prior to refactor.

## Phase C Kickoff (2025-11-07)
Status: Initiated

### Objectives
1. Introduce configurable distance metrics for candidate similarity (l2, cosine, recent_l2) to explore robustness vs amplitude/scale distortions.
2. Add inverse-distance weighted quantile aggregation (optional) to reduce noise from borderline candidates.
3. Prototype volatility regime penalty (penalize candidates whose window std deviates beyond tolerance from today's window) to prefer regime-consistent paths.
4. Maintain backward compatibility (defaults preserve Phase B behavior) and surface all new knobs via meta for future profile wiring.

### Completed
- Extended `RetrievalConfig` with: `distance_metric`, `recent_gamma`, `weight_mode`, `regime_tolerance`, `regime_penalty`.
- Implemented distance functions: `_cosine_distance`, `_recent_l2_distance` (decay weighting toward recent samples).
- Added `_weighted_quantile` helper and integrated optional `inv_dist` weighting.
- Added volatility regime penalty scaling distance when relative std deviation exceeds tolerance.
- Meta fields now include: `distance_metric`, `weight_mode` ("none" when off).
- Added unit tests `tests/test_weighted_quantile.py` covering basic, skewed, and edge (empty/singleton) cases.
- Profile mapping extended: profiles in `configs/ml/path_forecast_profiles.json` now support Phase C knobs (`distance_metric`, `weight_mode`, `recent_gamma`, `regime_tolerance`, `regime_penalty`). Route applies profile overrides when query params are unset; effective values surfaced via diagnostics and headers (`X-Profile-*`).
- Regime penalized candidate counter implemented: retrieval tracks `regime_penalized` (number of candidates whose distance was scaled by regime penalty) exposed in meta and via `X-Retrieval-RegimePenalized` header; composite forecaster propagates the counter in hybrid mode for consistent observability.

### Pending / Next Candidates
- Profile/route wiring for runtime selection of distance_metric & weight_mode.
- Extended regime metrics: (boosted candidate concept TBD) only penalized count implemented; evaluate need for positive regime bonus.
- Empirical evaluation grid: latency & accuracy impact (MAE, coverage) vs baseline (store results for docs).
- Potential addition: adaptive horizon weighting (earlier vs later horizon emphasis) and mixture of metrics (ensemble distance).
- Add per-profile performance summary (latency + candidate diversity) including regime penalized proportions.

## Meta Endpoint Refactor & Tests (2025-11-08)
Status: Complete

### Changes
- Refactored `path_forecast_meta` to reuse shared helpers used by JSON route:
	- `_load_live_rows_and_context`, `_apply_profile_overrides`, `_run_forecast_pipeline`
	- Preserved response schema and profile precedence; added retrieval diagnostics passthrough.
- Exposed regime metrics consistently in meta diagnostics.

### Tests Added
- `tests/test_path_forecast_meta_endpoint.py` (unit-style via TestClient, monkeypatched helpers):
	- basic 200 path with profile overrides and diagnostics
	- fallback behavior with no live rows
	- presence of Phase C profile knobs and `regime_penalized` in diagnostics
	- 404 path when live file missing
- `tests/test_path_forecast_meta_e2e.py` (end-to-end via TestClient + temp filesystem):
	- writes historical + live CSVs under a temporary `project_root`
	- calls endpoint with `date_str`; validates diagnostics/profile fields
	- tolerant of minimal environments (accepts fallback; xfails on hard 500)

### Dependency
- Added `httpx>=0.27.0` to `requirements.txt` (required by FastAPI/Starlette TestClient)

### CI readiness
- Tests are now in place for meta endpoint and retrieval regime metrics; they rely on `httpx` which is already added to `requirements.txt`.
- Local run: `pytest -q --disable-warnings` (captures unit + e2e; the e2e test is tolerant and may xfail by design).
- Next step: add a GitHub Actions workflow to install deps, cache pip, and run tests + coverage; see "Upcoming Tasks" below.

### Follow-ups
- CI wiring for pytest and minimal data fixture seeding (optional)
- Tighten e2e to require non-fallback path by also seeding any composite prior prerequisites if needed

### Risk Notes
- Cosine distance relies on z-scored windows; if variance collapses, normalization may flatten signal (guard returns distance=1 when degenerate).
- Weighted quantiles could over-fit to single low-distance candidate; may need minimum diversity guard (e.g., require at least M distinct days before weighting).
- Regime penalty increases distance multiplicatively; extreme tolerance misconfiguration can prune too aggressively—defaults keep it disabled.

## Upcoming Tasks (Planning 2025-11-08)
The following candidate tasks are prioritized for the next iteration. They are grouped to balance robustness, performance, and feature expansion.

1. CI Pipeline Integration
	- Add GitHub Actions workflow: matrix (python 3.10/3.11), cache pip, run `pytest -q --disable-warnings --maxfail=1`, collect coverage via `pytest-cov`, upload artifact.
	- Fast fail on lint (`ruff check`, `mypy --strict` for path forecast package).
	- Optional nightly job running heavier grid evaluation with reduced parameter set.
2. Composite Prior Regression Test
	- Add test ensuring prior median computation + hybrid blending unchanged after refactors.
	- Fixture: small synthetic historical set with deterministic prior; assert hybrid vs retrieval divergence when fallback disabled.
3. Strict Calibration End-to-End Test
	- Seed calibration snapshot + band scaling history; require non-fallback pipeline; assert calibrated bands inside expected tolerance and archival side-effects (CSV append) occur.
4. JSON Route Header Parity Tests
	- Add test verifying headers: `X-Retrieval-RegimePenalized`, `X-Cache-*`, pruning metrics, profile echo, post-shift indicators align with meta diagnostics.
5. Phase D: ANN / Approximate Indexing Exploration
	- Prototype embedding of TP windows (z-scored window) stored in optional HNSW index (hnswlib) with numpy brute-force fallback.
	- Added `AnnIndex` adapter (`src/path_forecast/ann_index.py`) and retrieval integration flags: `use_ann`, `ann_space`, `ann_max_candidates`, `ann_dim`.
	- Meta diagnostics extended: `ann_enabled`, `ann_total_windows`, `ann_shortlisted`.
	- Guard rails: default `use_ann=False` preserves legacy exact scan; shortlist only refines selected neighbors with full distance metrics & regime penalty.
	- Future: evaluate latency delta and candidate quality drift (MAE/coverage).
6. Performance Profiling Harness
	- Script to run N repeated forecast calls under various profiles (distance_metric/weight_mode) capturing latency distribution and candidate counts.
7. Diversity Guard for Weighted Quantiles
	- Enforce minimum distinct day count before applying `inv_dist` weighting; fallback to unweighted quantile.
8. Regime Metrics Extension
	- Add proportion of candidates penalized and average penalty factor; potential positive selection metric for regime-aligned windows.

Rationale: CI + regression tests reduce refactor risk; calibration e2e hardens correctness; header parity ensures observability consistency; ANN & profiling target latency improvements without sacrificing accuracy.

---

