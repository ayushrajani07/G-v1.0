# Master Tracking Issue: Phase 10 Continuous Improvement & Monitoring

**Status:** INIT  
**Start Date:** 2025-11-17  
**Scope:** Observability, drift & coverage monitoring, adaptive optimization, regime alerts.

## Objectives
1. Establish rolling accuracy & coverage visibility (MAE, P10-P90 band coverage).
2. Integrate drift & regime change detection into dashboards & alerting.
3. Prototype adaptive forecast cache TTL using volatility/regime signals.
4. Harden alert rules for latency, eviction rate, cache hit ratios.
5. Multi-index comparative performance reporting (NIFTY vs BANKNIFTY).
6. Maintain documentation freshness + metric definition integrity.

## Issue Inventory & Status
| ID | Title | Status | Owner | Depends On |
|----|-------|--------|-------|------------|
| P10-1 | feat(metrics): rolling MAE & coverage gauges | NOT STARTED | Cloud Agent | Prom export stable |
| P10-2 | feat(drift): drift detection panels + alerts | NOT STARTED | Cloud Agent | P10-1 (optional) |
| P10-3 | feat(regime): regime change weekly job + alert | NOT STARTED | Cloud Agent | P10-2 (optional) |
| P10-4 | feat(cache): adaptive TTL prototype (`G6_FORECAST_CACHE_ADAPTIVE=1`) | NOT STARTED | Cloud Agent | Baseline metrics captured |
| P10-5 | feat(loadtest): multi-index comparative mode | NOT STARTED | Cloud Agent | Phase 9 load test base |
| P10-6 | docs(alerting): alert rule definitions & dashboard README | NOT STARTED | Cloud Agent | P10-1, P10-4 |
| P10-7 | qa/validator: coverage & MAE validator for CI | NOT STARTED | Cloud Agent | P10-1 |

## Proposed Environment Variables (Phase 10)
| Variable | Default | Purpose |
|----------|---------|---------|
| `G6_FORECAST_CACHE_ADAPTIVE` | 0 | Enable adaptive TTL logic |
| `G6_FORECAST_CACHE_MIN_TTL` | 10 | Lower bound adaptive TTL (sec) |
| `G6_FORECAST_CACHE_MAX_TTL` | 60 | Upper bound adaptive TTL (sec) |
| `G6_VOLATILITY_WINDOW_MINUTES` | 30 | Window for short-term realized volatility |
| `G6_REGIME_DETECT_ENABLE` | 0 | Toggle regime change evaluation |

## Metrics Roadmap
- Rolling MAE (per index, horizon): `g6_forecast_mae{index="",horizon=""}`
- Coverage gauge (weekly window): `g6_forecast_coverage_pct{index="",horizon=""}`
- Drift score: `g6_feature_drift_score{feature=""}` (0–1 scale)
- Regime distance: `g6_regime_distance`
- Adaptive TTL current value: `g6_forecast_cache_ttl_current`

## Alert Rules (Initial Targets)
| Metric | Condition | Window | Severity |
|--------|-----------|--------|----------|
| Latency p95 | > 500ms | 5m | High |
| Eviction rate | > 2/sec | 5m | Medium |
| Cache hit ratio | < 40% | 15m | Medium |
| Coverage pct | < 70% OR > 90% | 1h | High |
| Drift score | > 0.25 sustained | 2h | Medium |
| Regime distance | Z-score > 2 | 1h | Info |

## Baseline Capture Tasks
- [ ] Record current coverage (last 7 days) for NIFTY & BANKNIFTY.
- [ ] Record current rolling MAE (last 7 days) per horizon.
- [ ] Capture volatility window stats for adaptive TTL input.

## Success Criteria
- Coverage within 75–85% weekly for primary indices.
- Rolling MAE stable within ±5% of Phase 9 baseline.
- Adaptive TTL yields ≤5% additional latency reduction without <5% hit ratio degradation.
- Drift alerts false positive <10% (manual review).
- Documentation updated (Version bump & metrics) — Already done (v1.2).

## Risks & Mitigation
| Risk | Impact | Mitigation |
|------|--------|-----------|
| Adaptive TTL oscillates | Latency variance | Apply hysteresis & min/max clamps |
| High cardinality metrics | Prom storage bloat | Limit labels to `index`, `horizon` |
| Drift over-sensitivity | Alert fatigue | Calibrate thresholds using historical distribution |
| Regime detection latency | Added request latency | Run asynchronously / scheduled |

## Progress Log
| Date | Item | Status | Notes |
|------|------|--------|-------|
| 2025-11-17 | Tracker Created | INIT | Phase 9 complete; starting baseline planning |

## Next Actions (Rolling)
- [ ] Create Phase 10 metric definitions & stubs.
- [ ] Implement rolling MAE & coverage collectors (batch job or inline update).
- [ ] Add Prometheus export for new metrics.
- [ ] Extend Grafana dashboard with MAE & coverage panels.
- [ ] Implement drift computation & panel.
- [ ] Implement regime weekly evaluation job.
- [ ] Prototype adaptive TTL flag + metrics.
- [ ] Author alert rule file & docs section.

---
**Maintainer:** ML Engineering Team  
**Last Updated:** 2025-11-17  
**Location:** `docs/ml/issues/ISSUE_PHASE10_CONTINUOUS_IMPROVEMENT.md`