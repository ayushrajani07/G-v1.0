# Phase 10 Drift Monitoring Review & Action Plan

Date: 2025-11-18  
Status: Action Plan Generated (Pending Execution)

## 1. Context
The branch `copilot/implement-drift-monitoring` delivered the initial drift monitoring implementation (PSI, KS, mean/variance deltas, baseline persistence, evaluator thread, Prometheus gauges, alert rules, Grafana panel, multi-index load test). This document captures a structured review, identifies gaps vs original spec, and defines a prioritized roadmap with rationale to harden and operationalize drift monitoring.

## 2. Summary of Current Implementation
Implemented components:
- Core module: `src/ml/drift_monitor.py` (PSI, KS, mean_delta_zscore, var_delta, baseline persistence).
- Metrics thread: `src/web/dashboard/drift_metrics.py` (gauges + evaluator loop; env `G6_DRIFT_ENABLE`, `G6_DRIFT_EVAL_INTERVAL_SEC`).
- Alerts: `prometheus_alerts_drift.yml` (sustained, broad, critical, high PSI, low KS, mean Z-score, multi-index, stale metrics).
- Panel: `grafana/dashboards/components/drift_panel.json` (visualization of drift status).
- Tests: `tests/ml/test_drift_monitor.py` (basic coverage).
- Documentation: updated `DRIFT_MONITORING.md`, summary doc, roadmap integration updates.
- Advisor endpoint (`/api/ml/universal_advisor/drift_advice`) for classification & actions (severity derived from thresholds).

## 3. Key Gaps & Risks
| Area | Observation | Impact | Risk Level |
|------|-------------|--------|------------|
| Severity Tiers | Only single threshold per metric; no warn vs critical distinction | Lacks gradation; more false pages | Medium |
| Data Source | Distributions use synthetic random data placeholder | Metrics unreliable; alerts meaningless in prod | High |
| Metric Duplication | Placeholder drift gauges still exist in `prom_metrics.py` alongside real ones | Confusion + double cardinality | Medium |
| Variance Handling | Variance delta ratio not thresholded in alert logic | Missed volatility drift signals | Low/Med |
| Baseline Rotation | No periodic or drift-triggered refresh logic | Baseline staleness or outdated drift standards | Medium |
| Snapshot Integration | Advisor snapshot reads placeholder gauges; actual metrics in new module | Inconsistent advice output | Medium |
| Cardinality Control | No cap on number of features exposed | Prometheus performance degradation | High |
| Evaluator Efficiency | New DriftMonitor instance each cycle; re-load baseline every iteration | Unnecessary overhead | Low |
| Alert Index Hardcoding | Many rules hardcode index="NIFTY" | Multi-index scaling requires manual duplication | Medium |
| Testing Depth | Edge cases (identical distributions, low sample size) not covered | Silent errors or unstable PSI | Low/Med |

## 4. Prioritized Roadmap
Priority order based on impact (P1 highest):

### P1: Real Data Integration
- Replace synthetic random generation with actual feature extraction from existing data sources (CSV or in-memory feature store).
- Implement abstraction `FeatureLoader` with method `load_feature_series(index, feature, start, end)`.
- Reasoning: Without real data, drift metrics produce noise; gating production enablement depends on this.

### P1: Metric Registry Unification & Placeholder Removal
- Remove placeholder drift gauges from `prom_metrics.py` to avoid duplication.
- Re-export unified drift helper functions from `drift_metrics.py` (or move gauges into `prom_metrics.py` to keep single registry).
- Reasoning: Prevent cardinality explosion and operator confusion.

### P1: Severity Tier Implementation
- Introduce dual thresholds (warn/critical) via env vars: `G6_DRIFT_PSI_WARN`, `G6_DRIFT_PSI_CRIT`, etc.
- Add gauge `g6_feature_drift_severity` (0=stable,1=watch,2=actionable,3=critical) or encode severity in `drift_flag` as integer.
- Adjust alert rules to reference severity levels instead of single thresholds where possible.
- Reasoning: Enables graduated response and reduces unnecessary pager load.

### P2: Baseline Refresh & Versioning
- Add env `G6_DRIFT_BASELINE_REFRESH_DAYS` (default 30) and `G6_DRIFT_CRITICAL_ALERT_REFRESH_COUNT` (e.g. 3).
- Logic: Refresh baseline if age exceeds refresh days OR critical alert count across distinct features >= threshold.
- Maintain baseline history at `metrics/drift_baselines/history/<index>/<timestamp>.json` for audit.
- Reasoning: Ensures baseline remains representative; allows adaptation to regime shifts.

### P2: Advisor Snapshot Alignment
- Update `get_feature_drift_snapshot` to read from the unified drift gauges if placeholders removed.
- Ensure `/drift_advice` gracefully handles absence of data (return severity=stable with `data_insufficient` flag when sample size < min threshold).
- Reasoning: Consistent advice output aligned with true drift metrics.

### P2: Cardinality Control
- Env `G6_DRIFT_MAX_FEATURES` (default 30). During metric set, sort features by importance or alert probability; only expose top N.
- Provide fallback metric `g6_feature_drift_excluded_total` for excluded count.
- Reasoning: Protects Prometheus ingestion performance.

### P3: Variance Thresholding & Combined Alert Logic
- Introduce warn/critical thresholds for variance ratio (e.g. warn: >1.5 or <0.67, critical: >2.0 or <0.5).
- Incorporate variance threshold into severity classification.
- Reasoning: Captures volatility regime changes often missed by mean shift alone.

### P3: Evaluator Optimization
- Persist single `DriftMonitor` instance; maintain baseline in memory.
- Cache quantile edges per feature to eliminate repeated bin calculation overhead.
- Record evaluation duration metric `g6_drift_eval_duration_ms`.
- Reasoning: Stability & performance; baseline I/O reduction.

### P3: Alert Rule Generalization
- Parameterize index rules using recording rules per index or templating; duplicate current rules across indices automatically in generation script.
- Reasoning: Scales to multi-index without manual edits.

### P4: Advanced Robustness & False Positive Mitigation
- Implement smoothing (EWMA) for PSI and mean delta before severity classification.
- Add composite drift condition requiring 2+ metrics (e.g., PSI + KS or PSI + mean Z) for warn severity.
- Reasoning: Reduces false positives from transient spikes.

### P4: Extended Testing Coverage
- Add tests for: identical distributions (PSI ~ 0), all values equal (bin edges collapse), small sample sets (<20), heavy-tailed synthetic distributions, baseline refresh logic, cardinality cap enforcement.
- Reasoning: Prevent regression; ensure stability under edge conditions.

### P5: Operator Tooling & Reporting
- Daily drift summary script: `scripts/ml/report_drift_daily.py` output JSON (counts by severity, top critical features, baseline age).
- Grafana panel enhancements: dynamic severity color mapping, historical severity trend sparkline.
- Reasoning: Operational visibility & actionable intelligence.

## 5. Detailed Task Breakdown & Rationale
| Task | Implementation Notes | Rationale |
|------|----------------------|-----------|
| Real Data Loader | Add `feature_loader.py`; unify path & retrieval logic; fallback if missing | Replaces placeholder randomness; foundation for valid drift signals |
| Registry Unification | Remove placeholder code from `prom_metrics.py`; import gauges via single registry variable | Avoid duplicate metric families & reduce confusion |
| Severity Tiers | Extend `drift_monitor.py` to compute severity; set integer gauge; update advisor classification | Multi-level alerting reduces noise |
| Baseline Refresh | Add refresh checker in evaluator loop; version baseline (increment major on critical drift) | Keep baseline representative to reduce systematic false drift |
| Snapshot Alignment | Replace advisor snapshot ingestion with drift registry queries; remove placeholder ingestion code | Consistent data source for decision logic |
| Feature Cap | Sort feature list by (psi + |mean_z|) or predetermined importance; enforce limit | Cardinality protection & ingestion efficiency |
| Variance Thresholds | Add ratio calculation & thresholds; integrate into severity logic | Detect volatility regime transitions |
| Evaluator Optimization | Maintain persistent monitor; precompute quantile edges; measure cycle duration | Reduced CPU & improved determinism |
| Alert Generalization | Generate rules per index from template; include dynamic index variable | Scale drift monitoring as assets expand |
| False Positive Mitigation | EWMA smoothing window (e.g., alpha derived from half-life 5 cycles); composite conditions | Increased precision of alerts |
| Testing Expansion | Add synthetic fixtures & edge case tests; assert PSI ~0 when identical | Reliability & confidence in production |
| Reporting Script | Summarize daily severity counts and top alert reasons; export to Prometheus via textfile collector (optional) | Daily ops workflow integration |

## 6. Environment Variable Additions
| Variable | Default | Purpose |
|----------|---------|---------|
| `G6_DRIFT_PSI_WARN` | 0.25 | PSI warn threshold |
| `G6_DRIFT_PSI_CRIT` | 0.40 | PSI critical threshold |
| `G6_DRIFT_KS_WARN` | 0.01 | KS p-value warn |
| `G6_DRIFT_KS_CRIT` | 0.001 | KS p-value critical |
| `G6_DRIFT_MEAN_Z_WARN` | 2.0 | Mean Z warn |
| `G6_DRIFT_MEAN_Z_CRIT` | 3.0 | Mean Z critical |
| `G6_DRIFT_VAR_RATIO_WARN_HIGH` | 1.5 | Variance ratio upper warn |
| `G6_DRIFT_VAR_RATIO_WARN_LOW` | 0.67 | Variance ratio lower warn |
| `G6_DRIFT_VAR_RATIO_CRIT_HIGH` | 2.0 | Variance ratio critical high |
| `G6_DRIFT_VAR_RATIO_CRIT_LOW` | 0.5 | Variance ratio critical low |
| `G6_DRIFT_BASELINE_REFRESH_DAYS` | 30 | Days before routine baseline refresh |
| `G6_DRIFT_CRITICAL_ALERT_REFRESH_COUNT` | 3 | Critical alert count to force refresh |
| `G6_DRIFT_MAX_FEATURES` | 30 | Cardinality cap |
| `G6_DRIFT_ENABLE_SMOOTHING` | 1 | Enable EWMA smoothing |
| `G6_DRIFT_SMOOTHING_HALF_LIFE` | 5 | Half-life (cycles) for EWMA smoothing |
| `G6_DRIFT_EVAL_STALE_SEC` | 600 | Evaluator staleness threshold in seconds (age > threshold considered stale) |

## 7. Acceptance Criteria (Post-Hardening)
- Drift metrics sourced from real deployed features (no synthetic placeholder).
- Single set of drift gauges at `/metrics`; no duplicate families.
- Severity gauge present and used in updated alert rules.
- Baseline file rotated per refresh policy & versioned.
- Advisor drift advice endpoint returns consistent severity distribution matching gauges.
- Prometheus cardinality stable (< (features_cap * indices)).
- Evaluator cycle time < 200ms for 30 features.
- Dashboards reflect `data_insufficient` (neutral/no-alarm state) and evaluator recency (warn on stale per `G6_DRIFT_EVAL_STALE_SEC`).
- Tests: All new drift-related tests pass; PSI identical distribution test yields |psi| < 1e-6.
- Alert rules validated by `promtool`; warnings precisely tracked (false-positive rate <10% after first calibration week).

## 8. Rollout Strategy
1. Implement registry unification & remove placeholders (low-risk).
2. Integrate real data loader (behind `G6_DRIFT_ENABLE=0` until validated).
3. Add severity tiers & adapt advisor + alert rules (deploy to staging).
4. Baseline refresh logic + feature cap (monitor Prometheus ingestion rate).
5. Enable smoothing & composite conditions (after initial baseline established).
6. Finalize docs & training for ops (update runbooks and dashboards).

## 9. Risks & Mitigations
| Risk | Mitigation |
|------|------------|
| Excess cardinality | Enforce feature cap & severity gauge single integer; drop per-bin PSI metrics from gauges (keep only aggregate) |
| False positives early | Keep `G6_DRIFT_ENABLE=0` until baseline fully populated; run shadow drift evaluation storing dry-run outputs |
| Data loader performance | Batch read & vectorized processing; cache per-day feature values |
| Alert fatigue | Dual thresholds + composite trigger; paging only on critical severity |
| Baseline corruption | Atomic write (temp file + replace); version tracking; validation before activation |

## 10. Next Immediate Actions
1. Remove placeholder drift gauges from `prom_metrics.py` and refactor snapshot helper to use `drift_metrics` registry.  
2. Add severity tier env vars and implement severity logic (`g6_feature_drift_severity`).  
3. Introduce feature cap enforcement during metric update.  
4. Draft real data loader scaffold (feature mapping table).  
5. Add tests for identical distributions & sample insufficiency.  

## 11. Implementation Order (Sprint-Level)
| Sprint | Focus | Deliverables |
|--------|-------|--------------|
| 1 | Infrastructure Hardening | Registry unify, severity tiers, feature cap, new tests |
| 2 | Data Integration | Real loader, baseline refresh, advisor snapshot alignment |
| 3 | Alert Precision | Composite logic, smoothing, updated alert rules, performance metrics |
| 4 | Operationalization | Reporting script, docs finalization, operator training |

## 12. References
- Original Spec & Review Response (internal notes)  
- `prometheus_alerts_drift.yml` (current alert definitions)  
- `drift_monitor.py` (core computations)  
- `drift_metrics.py` (gauge exposition & thread)
- `grafana/snippets/` (Infinity panel snippets for evaluator age and data availability)

## 13. CI & Rule Generation
- Per-index alert generation: use `scripts/monitoring/generate_drift_alerts.py` with template `monitoring/templates/prometheus_alerts_drift.per_index.tmpl.yml`.
	- Example: `python scripts/monitoring/generate_drift_alerts.py --template monitoring/templates/prometheus_alerts_drift.per_index.tmpl.yml --indices NIFTY,BANKNIFTY --out prometheus_alerts_drift.generated.yml`
- CI validations:
	- `promtool-rules`: downloads promtool and validates `prometheus_alerts_drift.yml`.
	- `promtool-generated-rules`: generates per-index rules (default `INDICES=NIFTY,BANKNIFTY`) and validates the output.
	- `feature-map-validate`: checks `configs/ml/feature_map.sample.json` and `configs/ml/feature_map.prod.json` against supported transforms and schema.

---
Document generated by automation to guide Phase 10 drift monitoring hardening.
