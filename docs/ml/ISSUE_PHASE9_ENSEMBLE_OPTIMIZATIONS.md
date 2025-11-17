# Phase 9 – Immediate Optimizations (Ensemble API): file-cache, full-detail, metrics, LRU cache, load-test, docs, tests

## Summary
- Optimize the FastAPI Ensemble Forecast service to reduce latency, improve observability, and harden caching, per Phase 9 “Immediate Optimizations”.
- All work is self-contained (code + tests + docs). No dependence on local Windows process management or Grafana wiring.

## Background
- Legacy Flask service was migrated into FastAPI at port 9500 with endpoints under `/api/ml/ensemble`.
- Current state:
  - Forecast endpoint live: `/api/ml/ensemble/forecast`
  - Recent window CSV is read per request
  - In-memory TTL forecast cache exists with stats/clear endpoints
  - Diagnostics available behind `G6_DIAG_ENABLE`
- Goal now: add file-level caching, full-detail output mode, Prometheus metrics, LRU bound for forecast cache, load test harness, and API docs.

## Scope
- Code only under `src/web/dashboard/routes/ensemble.py` and closely-related modules.
- Add tests under `tests/`.
- Add docs under `docs/ml/ENSEMBLE_API.md`.
- Do not modify Windows start scripts or local ops. Do not change existing endpoint behavior by default.

## Tasks (Checklist)
- [ ] Forecast file cache
  - [ ] Implement file-level cache for recent window CSVs keyed by `(index, expiry_tag, offset, date)`, invalidated by file mtime and TTL.
  - [ ] Add env var `G6_RECENT_FILE_CACHE_TTL` (default 60).
  - [ ] Add unit tests: hit rate >90% over 50 repeated calls; verify mtime invalidation.
- [ ] Full-detail forecast output
  - [ ] Add `detail=full` query param to `/forecast`, returning:
    - `time_grid`: array of epoch ms
    - `quantiles`: object with keys for each quantile, values as arrays matching `time_grid` length
  - [ ] Keep existing default (snapshot p10/p50/p90 + bands). No breaking changes.
  - [ ] Tests: OpenAPI schema includes full detail; arrays length consistent with horizon/bucket; time monotonic increasing.
- [ ] Prometheus metrics
  - [ ] Expose counters/histograms (labels: `index`, `horizon`):
    - `g6_forecast_latency_ms` (histogram)
    - `g6_forecast_cache_hits_total`, `g6_forecast_cache_misses_total`
    - `g6_recent_file_cache_hits_total`, `g6_recent_file_cache_misses_total`
  - [ ] Tests: scrape in-process registry; verify increments after forecast calls.
- [ ] Forecast cache hardening
  - [ ] Add LRU upper bound for entries with `G6_FORECAST_CACHE_MAX` (default 500).
  - [ ] Evict oldest on insert when at capacity.
  - [ ] Tests: exceed capacity and assert bounded size + eviction occurs.
- [ ] Load test harness
  - [ ] New script: `scripts/ml/load_test_ensemble.py` (asyncio + httpx).
  - [ ] Args: `--qps`, `--duration`, `--indices`, `--horizon`, `--detail`.
  - [ ] Output: JSON summary with p50/p95 latency, error rate, cache hit ratio (via `/cache/stats`).
  - [ ] Include basic smoke run instructions in the script header.
- [ ] Documentation
  - [ ] Create `docs/ml/ENSEMBLE_API.md` documenting:
    - Endpoints, parameters, examples
    - `detail=full` response schema
    - Caching controls and cache endpoints
    - Metrics (names, labels) for Prometheus
  - [ ] Update `docs/ml/ML_ARM_NEXT_STEPS.md` to link to the new API doc (leave the existing summary section intact).
- [ ] Tests & CI
  - [ ] Extend `tests/test_ensemble_api.py` to cover:
    - `detail=full` schema and content checks
    - Prometheus metrics increments
    - File cache TTL and mtime invalidation
    - LRU bound behavior
    - OpenAPI presence of new fields
  - [ ] Ensure `pytest -q` passes locally.

## Acceptance Criteria
- File cache: mtime-sensitive; env TTL respected; >90% hit rate in repeated-call test.
- Full detail: OpenAPI updated; arrays present and sized correctly; snapshot default unchanged.
- Metrics: Counters/histogram exported; tests assert increments.
- Forecast cache: size bounded by `G6_FORECAST_CACHE_MAX`; eviction verified; no regressions to existing TTL behavior.
- Load test harness: runs and produces JSON with p50/p95/error/cache-hit stats.
- Docs: `docs/ml/ENSEMBLE_API.md` created; `ML_ARM_NEXT_STEPS.md` links added; examples runnable.
- Tests: All added tests pass locally via `pytest -q`. No breaking changes to existing tests.

## Non-Goals / Out of Scope
- Windows process/port lifecycle scripts (handled locally).
- Grafana panel updates or provisioning.
- Changing business logic of the forecaster or training workflow.
- Switching default response from snapshot to full detail.

## Branch, Labels, PR
- Branch: `feature/ensemble-phase9-optimizations`
- Labels: `area:ml`, `type:enhancement`, `priority:high`, `phase:9`
- Reviewer guidance: focus on API compatibility, test coverage, metric naming consistency.

## Environment & Defaults
- `G6_FORECAST_CACHE_TTL=30` (forecast response cache)
- `G6_FORECAST_CACHE_MAX=500` (new)
- `G6_RECENT_FILE_CACHE_TTL=60` (new)
- `G6_DIAG_ENABLE=1` (dev)

### Run
```bash
python -m uvicorn src.web.dashboard.app:app --host 0.0.0.0 --port 9500
```

### Test
```bash
python -m pytest -q
```

## Fixtures & Data
- Add a small fixture CSV (e.g., `tests/fixtures/NIFTY/this_month/0/2025-11-17.csv`) with a `tp` column and ~100 rows for recent window tests.

## Smoke Steps (for PR description)
1. Boot service; confirm OpenAPI exposes `/forecast` with `detail` param.
2. GET `/api/ml/ensemble/forecast?index=NIFTY&horizon=60&detail=full` returns arrays.
3. Call `/cache/stats` and confirm non-zero size after forecasts. Clear via `/cache/clear`.
4. Curl `/metrics` and confirm new metric families present.
