# ML Arm Improvement Plan (November 2025)

## 1. Objectives
- Reduce latency of path forecasting (retrieval + composite) under live load.
- Lower CPU churn and file I/O for repeated intraday forecasts.
- Simplify configuration surface to improve maintainability and onboarding.
- Introduce minimal, opt-in instrumentation for guided optimization and alerting.
- Establish clear success metrics & rollback safety.

## 2. Current Pain Points (Validated)
| Area | Issue | Impact |
|------|-------|--------|
| Historical Loading | Duplicate fallback parsing in multiple modules (fixed) | Maintainability, inconsistent behavior |
| Prior Median | Recomputed every call in composite (partially fixed w/ LRU) | Unnecessary file scans |
| Distance Branching | Per-candidate metric selection branch (fixed) | Micro latency per candidate |
| ANN Index | Rebuilds z-scored windows each run, cache only index object | Startup latency; CPU for z-scoring |
| Config Sprawl | Monolithic `RetrievalConfig` / `CompositeConfig` with many optional fields | Cognitive load, misuse risk |
| Weighted Quantiles | Custom center-of-mass implementation for small K | Complexity with marginal benefit |
| Lack of Instrumentation | No timing or stage metrics | Hard to target further optimization |
| ANN Guard | MAD guard logic external to forecaster scripts | Duplication; inconsistent fallback semantics |
| Error Handling | Broad `except Exception` blocks | Masked systemic issues, debugging friction |
| Aggregation Code | Repetitive conversions / verbose safe int casts | Readability decline |

## 3. Key Metrics & Baselines (To Establish)
Before further changes we will capture (single representative run):
- Retrieval forecast end-to-end latency (ms) for typical horizon (60) with K=15.
- Composite forecast incremental overhead vs retrieval (ms).
- ANN build time (ms) and prune ratio when enabled.
- Candidate count & regime penalty fraction.
- CPU time distribution: loading, scoring, quantile aggregation (instrumentation).

## 4. Prioritized Change Sets
### Immediate (Week 1)
1. Prior Median Cache (DONE) – monitor hit ratio & memory.
2. ANN Window Vector Cache: store per-day W-length z-scored window + (mean, sd) to avoid recomputation.
3. Internalize ANN MAD Guard into `retrieval.py` with toggle param (guard threshold; update `last_meta`).
4. Instrumentation Hook: `ENABLE_PATH_FORECAST_PROFILING=1` environment flag capturing stage timings (load, ann_build, exact_scoring, quantile_agg) appended to `last_meta`.
5. Weighted Quantile Simplification: replace custom `_weighted_quantile` with simpler cumulative weight interpolation; add env flag to disable weighting entirely (`PATH_FORECAST_DISABLE_WEIGHTED=1`).

### Short Term (Weeks 2–3)
6. Config Modularization: (IN PROGRESS) Introduced sub-dataclasses: `PruningConfig`, `RegimeConfig`, `AnnConfig`; outer `RetrievalConfig` now subclasses modular `config_structs.RetrievalConfig`. Legacy flat fields remain; scripts can migrate gradually.
7. Error Handling Policy: Narrow exception catches; log unexpected failures (one-line warning with file name) when profiling enabled.
8. Composite Prior Cache Enhancement: Promote to shared module-level LRU (optional) to reuse between composite forecaster instances.
9. Unified Query Builder: Helper function returning (`query_series`, `query_z`, mean, std) used by both retrieval and composite path selection.
10. Add `safe_int` / `safe_float` helpers in `common.py` to clean aggregation code in grid eval script.

### Mid Term (Weeks 4–6)
11. Parallel Baseline + ANN Evaluation: ThreadPool (2 workers) for baseline & ANN path generation in grid eval; join, compute MAD & speedup.
12. Persistent Disk Cache (Optional): Write ANN index & window vectors to a lightweight binary file per day for warm restart speed.
13. Adaptive K Strategy: Dynamically adjust K based on candidate diversity and distance clustering (reduce work). Guard with experimental flag.
14. Streaming Forecast Mode: Maintain rolling candidate distances incrementally as new ticks arrive (avoid recomputing from scratch each call).
15. Prometheus Metrics Exporter: Expose instrumentation counters/gauges (latency, candidate counts, ann_prune_ratio) via existing metrics registry.

### Long Term / Research
16. Replace custom quantile aggregation with robust online estimation (e.g., P^2 algorithm) for rolling forecast windows.
17. Explore approximate nearest neighbors library alternatives (FAISS / HNSW) if Python ANN performance remains bottlenecked.
18. Model Ensemble Layer: Weighted blend between retrieval and composite output using learnable weights from historical validation.

## 5. Implementation Sequencing & Rollback
| Step | Change | Rollback Strategy |
|------|--------|------------------|
| 1 | ANN window vector cache | Guard by env var `DISABLE_ANN_WINDOW_CACHE`; fallback to current path |
| 2 | MAD guard internalization | Feature flag `ANN_MAD_GUARD_THRESHOLD`; disable by unset |
| 3 | Instrumentation | Flag off -> no performance overhead |
| 4 | Weighted quantile simplification | Keep original function for one release behind flag |
| 5 | Config modularization | Maintain deprecated args mapping for 2 releases |

## 6. Success Criteria
- ≥30% reduction in composite (non-ANN) median latency under typical load bursts.
- ANN build reused >70% between sequential forecasts (prune ratio stable).
- Prior cache hit ratio >60% intraday.
- Instrumentation overhead <5% added latency when enabled.
- No regression in prediction quality (coverage within ±0.01 of baseline; MAE within ±2%).

## 7. Risks & Mitigations
| Risk | Mitigation |
|------|------------|
| Cache Staleness (new day file) | Signature includes full path list; invalidated on change count delta |
| Increased Memory Footprint | Cap LRU sizes; expose memory usage in `last_meta` |
| Config Backward Compatibility | Keep legacy dataclass for one deprecation cycle with warnings |
| Instrumentation Overhead | Off by default; minimal timing granularity (perf_counter only) |
| ANN Guard Over-Fallback | Track trigger rate; auto-disable if >50% triggers over rolling window |

## 8. Required New Flags / Env Vars
- `ENABLE_PATH_FORECAST_PROFILING=1` – enable stage timings & warnings.
- `DISABLE_ANN_WINDOW_CACHE=1` – bypass new window vector cache.
- `ANN_MAD_GUARD_THRESHOLD=0.05` – example threshold.
- `PATH_FORECAST_DISABLE_WEIGHTED=1` – force unweighted quantiles.

## 9. Documentation & Communication
- Update `ML_README.md` with new flags & meta fields.
- Add a short "Performance Tuning" section referencing instrumentation and guard settings.
- Changelog entries grouped under "ML Optimization Phase".

### Profiling and Diagnostics Fields (ENABLE_PATH_FORECAST_PROFILING=1)
When the environment variable `ENABLE_PATH_FORECAST_PROFILING` is set (to any non-empty value), `retrieval.py` emits timing metrics into `last_meta`:

- `exact_scoring_ms` – time spent computing exact distances and preparing top-K futures.
- `quantile_agg_ms` – time aggregating quantiles across K futures.
- `total_ms` – end-to-end retrieval call time within the forecaster.

Additional ANN-related diagnostics are always present when ANN is enabled:

- `ann_build_ms` – time to build the ANN index (0ms on cache hits).
- `ann_index_mem_bytes` – estimated index memory footprint.
- `ann_total_windows` – number of historical windows considered for ANN.
- `ann_shortlisted` – number of files shortlisted by ANN before exact scoring.
- `ann_prune_ratio` – `ann_shortlisted / ann_total_windows` when both are > 0.

If `ANN_MAD_GUARD_THRESHOLD` is set (e.g., `0.5`), an internal MAD guard filters extreme ANN neighbors; diagnostics include:

- `ann_mad_median` – median ANN distance to the query among shortlisted windows.
- `ann_mad_mad` – median absolute deviation of those distances.
- `ann_mad_cutoff` – computed cutoff `median + threshold * MAD`.
- `ann_mad_filtered` – count of ANN candidates removed by the guard.

Weighted quantiles can be disabled globally by setting `PATH_FORECAST_DISABLE_WEIGHTED=1`. When set, quantile aggregation falls back to unweighted even if `weight_mode="inv_dist"` is configured.

### Prometheus Metrics (ENABLE_PATH_FORECAST_PROM_METRICS=1)
When `ENABLE_PATH_FORECAST_PROM_METRICS` is set (non-empty), retrieval and composite push metrics using the default Prometheus registry:

- `pf_retrieval_latency_ms` (Histogram) – observed `total_ms` per forecast call (ms buckets).
- `pf_retrieval_candidates_total` (Gauge) – count of candidate days retained after pruning.
- `pf_ann_prune_ratio` (Gauge) – shortlisted / total windows when ANN enabled.
- `pf_ann_build_ms` (Gauge) – ANN index build time (0 on cache hit).
- `pf_exact_scoring_ms` (Gauge) – exact distance scoring duration.
- `pf_quantile_agg_ms` (Gauge) – quantile aggregation duration.

Composite-specific:

- `pf_composite_latency_ms` (Histogram) – end-to-end composite forecast latency.
- `pf_composite_prior_cache_hit` (Gauge) – prior median LRU cache hit (0/1).
- `pf_composite_alpha` (Gauge) – blend weight given to retrieval median.
- `pf_composite_prior_days` (Gauge) – number of days contributing to prior (when computed).
- `pf_composite_retained_days` (Gauge) – retained days in prior after pruning.

Flags interplay:
- Profiling flag populates `exact_scoring_ms`, `quantile_agg_ms`, `total_ms`; Prometheus exposure flag publishes them.
- Disabling profiling but enabling Prom metrics will still publish candidates / ANN stats (timing gauges may remain at last values or zero if absent).

## 10. Verification Strategy
1. Baseline run scripts (unchanged) – capture metrics.
2. Apply Immediate changes sequentially; after each change, rerun forecast harness measuring latency & quality (MAE, coverage).
3. Automated check: simple pytest verifying prior cache hit increments when called twice with same context.
4. Smoke test ANN guard behavior with synthetic inflated MAD case.
5. Grafana panel additions for new Prometheus metrics (later phase).

## 11. Tracking & Reporting
- Add a lightweight progress markdown: `ML_OPTIMIZATION_PROGRESS.md` updated per completed step.
- Weekly summary of latency benchmarks vs baseline committed to repo.

---
**Next Action Proposal:** Implement ANN window vector cache (step 2) guarded by env flag, followed by adding instrumentation hook.

### Modular Config Usage Example
```python
from pathlib import Path
from src.path_forecast.config_structs import RetrievalConfig, PruningConfig, RegimeConfig, AnnConfig

cfg = RetrievalConfig.from_modular(
	root=Path("data/g6_data"),
	window=60,
	k=15,
	pruning=PruningConfig(max_days_scan=25, min_future=30),
	regime=RegimeConfig(distance_metric="recent_l2", recent_gamma=0.85, regime_tolerance=0.4),
	ann=AnnConfig(use_ann=True, ann_space="cosine", ann_max_candidates=50),
)
```
Legacy construction still works:
```python
from src.path_forecast.retrieval import RetrievalConfig
cfg = RetrievalConfig(root=Path("data/g6_data"), window=60, distance_metric="l2", use_ann=False)
```

Let me know if you want to adjust priorities (e.g., move instrumentation earlier) before proceeding.
