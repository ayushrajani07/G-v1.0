# ML ARM Progress & Future Plan

**Document Version:** 1.0  
**Date:** 2025-11-20  
**Status:** Planning / Transition  
**Maintainers:** ML / ARM Engineering  

---
## 1. Executive Snapshot

| Phase | Status | Core Outcomes | Impact Metrics |
|-------|--------|---------------|----------------|
| 1 Feature Engineering | Complete | 24 engineered features (lag, volatility, regime) | Established baseline feature quality |
| 2 GBRT Quantile Models | Complete | P10/P50/P90 GBRT models trained & validated | Initial coverage ~72–74% |
| 3 Ensemble Integration | Complete | Weighted GBRT + retrieval + conformal banding | Confidence adaptation + dynamic weighting |
| 4 Initial Production Deploy | Complete | FastAPI endpoints, CI smoke, basic dashboards | Live shadow validation started |
| 5 Evaluation Framework | Complete | Rolling MAE, coverage, norm error scaffolds | Weekly evaluation cadence established |
| 6 Code Cleanup & Hardening | Complete | Module consolidation, test reliability | 452 tests pass, reduced churn risk |
| 7 Model Enhancements | Complete | Expanded to 47 features, improved retrieval & conformal tuning | Coverage stable 78–82% |
| 8 Prod Stabilization (ops) | Complete | Shadow to live, forecasting cache v1, perf dashboards | Latency p95 from 410ms → 285ms (-30.5%) |
| 9 Performance & Instrumentation | Complete | File window cache, LRU cap, Prom metrics, load-test async | Forecast cache hit ratio 18% → 64%; error rate 3.2% → 1.1% |
| 10 Instrumentation (ongoing) | In Progress | Drift & regime monitoring, adaptive TTL, dynamic thresholds | Adaptive TTL early positive, target ≤5% latency gain |

**Current Health:**
- Coverage: Stable (target band 75–85%)  
- Latency: p95 ≈ 285ms (goal <250ms)  
- Cache Hit Ratio: Forecast ~64%, Recent File ~73%  
- Error Rate: ~1.1% (goal <1%)  
- Drift Alerts: Low frequency; calibration thresholds under tuning  

---
## 2. Key Achievements by Theme

### Performance
- Reduced p95 latency >30% via multi-layer caching & query normalization.
- Introduced adaptive TTL (volatility + IV driven) to avoid over-frequent recomputation.

### Reliability & Observability
- Prometheus integration for latency, cache, drift, regime, threshold chain validity.
- Grafana dashboards: Feature Importance, Distribution Shift, Dynamic Thresholds, Regime Status.
- Chain-of-trust manifests with signature validation and rollback mechanism.

### Data & Model Quality
- Feature drift monitoring (PSI, KS, mean/variance deltas) + alert classification.
- Rolling evaluation metrics: MAE, coverage %, normalized error, histograms.
- Conformal adjustments with decay & half-life diagnostics.

### Governance & Automation
- Metrics validator gating required labels in CI.
- Drift threshold governance (calibrate → validate → promote → canary history + rollback).
- Auto-tune percentiles with target violation ranges (warn 5–12%, crit 1–4%).

### Documentation & Onboarding
- Centralized post-implementation guide (`ML_ARM_NEXT_STEPS.md`).
- Individual runbooks for regime & drift triage; evaluation & calibration guides.
- Ensemble API reference expanded (config introspection, TTL study, threshold chain).

---
## 3. Current Gaps / Risks
| Category | Gap | Impact | Mitigation |
|----------|-----|--------|-----------|
| Endpoint Duplication | Two `/metrics/compare` variants remain | Confusion / divergent clients | Consolidate into unified schema (Q4) |
| Drift Threshold Calibration | Early auto-tune volatility | Possible false positives | Extend baseline window & percentile smoothing |
| Adaptive TTL Metrics | TTL not fully exposed in Prometheus | Harder optimization loop | Add gauge per index/horizon (Q4) |
| Load Test Harness Split | Mixed legacy vs current endpoints | Incomplete cache insight | Refactor harness into simple vs full modes |
| SENSEX Full Parity | Some scripts still NIFTY/BANKNIFTY only | Partial feature adoption | Sweep remaining calibration scripts (Q4) |
| Forecast Confidence Model | Simple heuristic weighting | Potential suboptimal mixing | Integrate learned meta-model (Q1) |
| Retrieval ANN Quality Guard | Basic MAD guard only | Risk of silent degradation | Add dynamic guard & decayed penalty tracking |
| Drift Baseline Currency | Manual oversight risk | Stale thresholds after regime shift | Automate baseline age alerts & auto-recalibration |

---
## 4. Near-Term Backlog (Next 4–6 Weeks)
1. Consolidate `/metrics/compare` endpoints.
2. Add Prometheus metric: `g6_forecast_adaptive_ttl_sec` (gauge by index,horizon).
3. Refactor `load_test_ensemble.py` → `load_test_ensemble_simple.py` & `load_test_ensemble_multi.py`.
4. SENSEX parity sweep: calibration, band tuning, drift baseline establishment.
5. Add tests for `/ensemble/config`, `/ttl_study`, manifest chain validation.
6. Implement forecast meta-model (feature set: recent error trend, drift severity, cache pattern) → improved weighting strategy.
7. Add regime early-warning composite metric (coverage accelerating drop + rising norm error).

---
## 5. Medium-Term Roadmap (3–6 Months)
| Theme | Objective | Milestones |
|-------|-----------|-----------|
| Latency Optimization | Sub-200ms p95 | Async retrieval pre-fetch, vector ANN index persistence, speculative cache fill |
| Adaptive Systems | Self-tuning cache & thresholds | TTL auto-adjust feedback loop, drift threshold smoothing with EWMA |
| Model Quality | Stable coverage 80 ±3% | Conformal recalibration daemon + outlier clustering integration |
| Forecast Fusion | Learned ensemble mixing | Train meta-learner (stacking / light ranker) on confidence & error residual features |
| Resilience | Automated rollback & canary | Canary comparison pipeline with daily diff & alert on penalty regression >5% |
| Data Pipelines | Live feature extraction | Replace synthetic drift samples with streaming ingestion (Kafka or scheduled ETL) |
| Bench & Regression | Continuous performance gate | Nightly perf job writes historical latency, cache, error trend artifact |

---
## 6. Long-Term Vision (6–12 Months)
- Multi-index expansion (FINNIFTY, sector indices) with dynamic feature subsets.
- Volatility-aware horizon bucketing (variable resolution time grid).
- Hybrid retrieval (ANN + learned embedding similarity via contrastive representation).
- Adaptive quantile targeting (auto widen/narrow bands to maintain coverage target mid-band).
- Drift root-cause classifier (feature importance shift attribution).
- Reliability SLA dashboard (latency, accuracy, drift MTTR, threshold promotion cadence).
- Automated retraining triggers from sustained drift & regime shifts.
- Historical simulation harness for policy changes (adaptive TTL vs static) with replay datasets.

---
## 7. Metrics Targets Summary
| Metric | Current | Target (Short) | Target (Medium) | Target (Long) |
|--------|---------|----------------|-----------------|---------------|
| p95 Latency | 285ms | <250ms | <200ms | <150ms |
| Forecast Cache Hit Ratio | 64% | ≥70% | ≥75% | ≥80% |
| Recent File Cache Hit | 73% | ≥75% | ≥80% | ≥85% |
| Coverage % (P10–P90) | 78–82% | 80±3% | 80±2% | 80±1% |
| Error Rate | 1.1% | <1% | <0.9% | <0.8% |
| Drift False Positives | TBD | <10% | <7% | <5% |
| Regime Detection Overhead | <250ms | <200ms | <150ms | <120ms |
| TTL Latency Gain | Early | 5–7% | 10–12% | 15%+ |

---
## 8. Dependency & Sequencing Notes
1. Learned meta-model requires stable rolling metrics & drift summaries → finalize consolidation first.
2. Adaptive TTL gauge exposure precedes feedback controller implementation.
3. ANN persistence depends on retrieval corpus normalization & memory profiling outcome.
4. Drift automation (baseline refresh) should follow improved false positive analytics.

---
## 9. Immediate Next Steps (Actionable)
| Order | Task | Owner | ETA |
|-------|------|-------|-----|
| 1 | Unify `/metrics/compare` implementations | ML Backend | 1 week |
| 2 | Add adaptive TTL Prometheus gauge | ML Backend | 1 week |
| 3 | Load test script refactor | Tooling | 1 week |
| 4 | SENSEX calibration & baselines | Data Ops | 2 weeks |
| 5 | Add config/TTL study/manifest tests | QA | 2 weeks |
| 6 | Meta-model feature spec doc | ML Research | 3 weeks |

---
## 10. Open Questions
- Optimal adaptive TTL weighting scaling for extreme intraday volatility spikes?
- When to decay historical percentiles in dynamic drift thresholds vs maintain fixed anchor?
- Is ANN candidate ladder sufficient or do we need reinforcement-based candidate selection?
- How to treat partial coverage improvements (latency trade) in meta-model scoring?

---
## 11. Change Log
| Version | Date | Change |
|---------|------|--------|
| 1.0 | 2025-11-20 | Initial progress + future planning document created |

---
## 12. References
- `ML_ARM_NEXT_STEPS.md`
- `ML_ARM_IMPLEMENTATION_ROADMAP.md`
- `RUNBOOK_REGIME_DRIFT.md`
- `ENSEMBLE_API.md`
- `DRIFT_MONITORING.md`
- `PHASE*_COMPLETION_SUMMARY.md`

---
**Feedback:** Please open an issue under `docs/ml` with label `planning` or contact ml-team@example.com.
