# Master Tracking Issue: Phase 9 Performance & Observability

## Summary
Central tracker for all Phase 9 optimization, caching, metrics, load testing, and documentation alignment work. Consolidates status, dependencies, success criteria, and baseline vs target metrics.

## Objectives
- Reduce P95 forecast latency ≥30% post-caching & instrumentation.
- Improve forecast cache hit ratio ≥60% steady state; recent file window cache ≥70%.
- Add full detail forecast mode (`detail=full`) for path visualization & advanced consumers.
- Provide Prometheus metrics + validator for CI observability gates.
- Upgrade load testing to async and integrate latency/error artifact into CI.
- Harden docs so a single schema/env source of truth exists.

## Issue Inventory & Status
| ID | File | Title (Planned GH Issue) | Status | Owner | Depends On |
|----|------|--------------------------|--------|-------|------------|
| P9-1 | `ISSUE_FULL_DETAIL_MODE.md` | feat(api): add detail=full forecast response mode | NOT STARTED | Cloud Agent | — |
| P9-2 | `ISSUE_RECENT_WINDOW_FILE_CACHE.md` | feat(cache): recent window file cache (mtime + TTL) | NOT STARTED | Cloud Agent | P9-1 (optional) |
| P9-3 | `ISSUE_FORECAST_CACHE_LRU.md` | feat(cache): add LRU bound + eviction stats | NOT STARTED | Cloud Agent | — |
| P9-4 | `ISSUE_PROMETHEUS_METRICS.md` | feat(metrics): Prometheus export (latency/cache) | IN PROGRESS | Cloud Agent | P9-3 (recommended) |
| P9-5 | `ISSUE_METRICS_VALIDATOR.md` | feat(tooling): metrics validator script | IN PROGRESS | Cloud Agent | P9-4 |
| P9-6 | `ISSUE_ASYNC_LOAD_TEST_AND_CI.md` | feat(loadtest): async load test + CI artifact | IN PROGRESS | Cloud Agent | P9-4 (for metrics) |
| P9-7 | `ISSUE_DOCS_HARDENING.md` | docs: harden ensemble API & ops docs | IN PROGRESS | Cloud Agent | P9-1, P9-4 |

## Dependency Graph (Simplified)
`Full Detail Mode` → `Docs Hardening`
`Forecast Cache LRU` → `Prometheus Metrics` → `Metrics Validator`
`Recent File Cache` → (independent speedup; metrics will expose stats)
`Prometheus Metrics` + `Caches` → `Async Load Test & CI` → metrics-based gate

## Environment Variables (Current + Incoming)
| Variable | Status | Default | Purpose |
|----------|--------|---------|---------|
| `G6_FORECAST_CACHE_TTL` | ACTIVE | 30 | TTL for forecast cache entries |
| `G6_FORECAST_CACHE_MAX` | PLANNED | 500 | Max entries before LRU eviction (P9-3) |
| `G6_RECENT_FILE_CACHE_TTL` | PLANNED | 60 | TTL for recent window file cache (P9-2) |
| `G6_RECENT_FILE_CACHE_MAX_SIZE` | PLANNED | 50 | Max cached recent windows (P9-2) |
| `ENABLE_PATH_FORECAST_PROM_METRICS` | PLANNED | 0 | Enable Prometheus metrics (P9-4) |
| `DASHBOARD_API_WINDOW_STYLE` | ACTIVE | Hidden | Start script window style |
| `PATH_FORECAST_DISABLE_WEIGHTED` | OPTIONAL | 0 | Disable weighted quantiles (perf switch) |

## Metrics Baseline & Targets
| Metric | Baseline (TBD) | Target | Source |
|--------|----------------|--------|--------|
| P95 Forecast Latency (ms) | (capture before P9 merges) | ≤ 0.7 × baseline | Load test JSON |
| Forecast Cache Hit Ratio | (capture) | ≥ 60% | `/cache/stats` & Prom metrics |
| Recent File Cache Hit Ratio | n/a | ≥ 70% | `/cache/stats` & Prom metrics |
| Error Rate | (capture) | ≤ 2% | Load test JSON |
| Metrics Validator Pass | n/a | 100% required metrics present | Validator script |

## Validation Gates (CI)
1. Metrics endpoint available when flag enabled.
2. Validator ensures required metric names exist.
3. Async load test artifact includes latency percentiles & error rate.
4. Fails if error rate >2% or required metrics missing.

## Changelog & Documentation Updates
- Each issue PR must update: `PHASE9_CHANGELOG.md` and (if schema/env change) `docs/ml/ENSEMBLE_API.md`.
- Docs Hardening final PR consolidates temporary notes into definitive sections (schema, metrics, env vars).

## Risks & Mitigations
| Risk | Impact | Mitigation |
|------|--------|-----------|
| Metrics overhead raises latency | Medium | Minimal histogram buckets; benchmark before enabling by default |
| Unbounded cache growth pre-LRU | High | Implement `G6_FORECAST_CACHE_MAX` early (P9-3) |
| Stale recent window after file rotation | Low | Mtime + TTL invalidation |
| Merge conflicts in docs | Medium | Sequence doc hardening last; small isolated updates |
| Flaky load test CI | Medium | Use deterministic horizons & fixed QPS; short duration (≤10s) |

## Progress Log (Append Entries)
| Date | Issue | Status Change | Notes |
|------|-------|---------------|-------|
| 2025-11-17 | Tracker Created | INIT | Baseline capture pending |
| 2025-11-17 | P9-4 / P9-5 / P9-6 / P9-7 | DELEGATED | Cloud agent started work |

## Next Actions (Rolling)
- [ ] Capture baseline latency/error (thread load tester) and store `baseline.json`.
- [ ] Implement P9-1 (detail=full) → merge; update API docs.
- [ ] Implement P9-3 (LRU) before enabling metrics widely.
- [ ] Implement P9-2 (recent file cache) to increase hit ratios.
- [ ] Implement P9-4 (Prom metrics) & expose `/metrics`.
- [ ] Implement P9-5 (validator) & add CI step.
- [ ] Implement P9-6 (async load test) & integrate artifact gating.
- [ ] Finalize P9-7 (docs hardening) after schema & metrics stable.

## Completion Criteria
- All issue statuses = MERGED.
- Baseline vs optimized report shows ≥30% P95 latency reduction.
- Validator passes in CI; load test artifact archived.
- Docs reflect final schema, metrics, env vars without inconsistencies.

## Post-Phase Follow-Up (Phase 10 Prep)
- Evaluate drift & feature importance integration with new metrics.
- Determine need for adaptive TTL based on realized volatility.
- Plan streaming ingestion changes for real-time ML readiness (Phase 11).

---
**Maintainer:** ML Engineering Team  
**Last Updated:** 2025-11-17  
**Location:** `docs/ml/issues/ISSUE_PHASE9_MASTER_TRACKER.md`
