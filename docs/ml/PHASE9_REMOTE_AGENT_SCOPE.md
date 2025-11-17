# Phase 9 – Performance Optimization: Remote Agent Scope & Acceptance Criteria

Document version: 1.0  
Date: 2025-11-17  
Owner: ML Engineering  
Labels: phase9, performance, caching, instrumentation, configs

---

## Objectives

- Reduce end-to-end forecast P95 latency by ≥30% without degrading accuracy or coverage.
- Improve cache effectiveness (ANN reuse >70%, prior median hit >60%).
- Add detailed instrumentation to quantify stage-level latency and cache behavior.
- Keep behavior fully guarded by feature flags with instant rollback.

---

## In-Scope Deliverables (Agent)

1) ANN Window Vector Cache
- Implement in-memory cache for ANN window vectors behind `ENABLE_ANN_WINDOW_CACHE`.
- Expose Prometheus metrics: `g6_ml_ann_cache_hit_ratio`, `g6_ml_ann_cache_size`, `g6_ml_ann_cache_evictions`.
- Provide invalidation strategy on data/model change; include TTL/epoch keying.

2) ANN Disk Cache (Cold-Start Optimization)
- Optional disk-persisted ANN indices with `ENABLE_ANN_DISK_CACHE=1` and `ANN_CACHE_DIR`.
- Versioning scheme (model id + feature set + params) to avoid stale reuse.
- Metrics: `g6_ml_ann_disk_cache_hits`, `g6_ml_ann_disk_cache_load_ms`.

3) Modular Config Migration
- Implement/configure: `RetrievalConfig`, `PruningConfig`, `RegimeConfig`, `AnnConfig` (module: `src/path_forecast/config_structs.py`).
- Refactor callsites to consume the structs; no public API changes.
- Unit tests for: default values, serialization, and backward compatibility with current JSON configs.

4) Weighted Quantile Simplification (Switchable)
- Add toggle `PATH_FORECAST_DISABLE_WEIGHTED=1` to bypass weighted quantiles.
- Ensure quantile monotonicity and coverage stay within ±2% of baseline.
- Micro-benchmarks demonstrating 10–15% speedup in aggregation stage when enabled.

5) Parallel Evaluation Harness
- `scripts/ml/grid_eval_parallel.py` with `--workers N`, deterministic seeding, and CPU affinity friendly pools.
- CSV/JSON outputs with latency, accuracy, coverage per configuration row.

6) Instrumentation & Metrics
- Stage timers: data load, retrieval, ANN build/reuse, aggregation, conformal calibration.
- Prometheus histograms: `g6_ml_stage_latency_seconds{stage=...}` with P50/P95/P99.
- Cache metrics enumerated above; ensure no NaN/Inf emissions.

7) Documentation & Tests
- Developer guide: setup, flags, metrics reference, rollback guide.
- Unit tests for cache correctness, config struct, and weighted quantile toggle.
- Integration test(s) gated by flags (skip gracefully if services absent).

---

## Out of Scope (Agent)

- Changing public API endpoints or response schemas.
- Grafana dashboard authoring and Prometheus alert rule tuning (owned by ops team).
- Business logic changes beyond performance-related toggles.

---

## Environment & Flags (Contract)

- `ENABLE_ANN_WINDOW_CACHE` (0/1): Enable in-memory ANN window vector cache.
- `ENABLE_ANN_DISK_CACHE` (0/1): Enable disk persistence for ANN indices.
- `ANN_CACHE_DIR` (path): Disk cache directory when disk cache is enabled.
- `ENABLE_PATH_FORECAST_PROFILING` (0/1): Emit stage-level timing.
- `ENABLE_PATH_FORECAST_PROM_METRICS` (0/1): Expose Prometheus metrics.
- `PATH_FORECAST_DISABLE_WEIGHTED` (0/1): Bypass weighted quantile path.

Behavior with all flags off must be identical to today (bitwise-compatible outputs where practical).

---

## Acceptance Criteria

Functional
- No changes to public API: `/api/ml/ensemble/*` request/response remain compatible.
- Feature flags are discoverable via diagnostics and are safe to flip at runtime (process-level).
- All existing tests pass; new tests added for features above.

Performance
- With baseline hardware and dataset, P95 forecast latency shows ≥30% reduction when caches and instrumentation are enabled together (vs baseline with flags off).
- Cold-start improvement with disk cache: ≥90% reduction in ANN build time on repeat requests with identical config.
- Instrumentation overhead <5% when profiling enabled; <2% when disabled.

Metrics
- Prometheus exports include stage histograms and cache metrics; no NaN/Inf values; labels: `index`, `horizon`, `stage`.
- New metrics documented in a simple reference table.

Safety & Rollback
- With all flags OFF, behavior and performance match current baseline within ±2% for latency and identical forecasts (non-determinism acknowledged if live data shifts).
- Flags can be flipped independently; disabling a feature restores pre-feature behavior without restart (if feasible) or with single restart at worst.

Documentation
- README/guide section covering: flags, metrics, expected gains, troubleshooting, and how to measure impact.

Deliverables checklist (Agent must provide)
- [ ] Code + tests + minimal docs.
- [ ] Example configs demonstrating each toggle.
- [ ] Benchmark scripts or instructions to reproduce improvements.
- [ ] Short CHANGELOG for release notes.

---

## Test Plan (Agent)

Automated
- Unit: cache correctness (hit/miss/eviction), config parsing/serialization, weighted quantile monotonicity.
- Integration: stage metrics presence, flag gating behavior, ANN disk cache load/save cycle.

Manual/Scripted
- Baseline vs optimized runs with `load_test_ensemble.py` at fixed concurrency.
- Toggle sweeps to verify independence of flags and sane behavior.

Exit Gates
- All acceptance criteria satisfied.
- Performance deltas demonstrated and reported.

---

## Rollout Plan

1) Merge feature flags and instrumentation first (no caching enabled by default).  
2) Enable profiling+metrics in staging; validate dashboards and alerts.  
3) Enable in-memory ANN cache; validate hit ratios and latency improvements.  
4) Trial disk cache; validate cold-start improvement and safety.  
5) Optional: try weighted quantile toggle in staging; check coverage variance ≤ ±2%.

---

## Contacts

- ML Engineering Team: ml-team@example.com  
- On-call: ml-oncall@example.com
