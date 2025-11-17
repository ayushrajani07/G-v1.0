# Phase 9 – Follow-Up: Solidify Scaffolds (API Docs + Load Test)

## Summary
Finalize and extend the newly added scaffolds so they are production-ready and directly useful in PR reviews and performance validation.

## Scaffolds (Already in Repo)
- API Reference: `docs/ml/ENSEMBLE_API.md`
- Load Test Harness: `scripts/ml/load_test_ensemble.py`

## Tasks (Checklist)
- [ ] ENSEMBLE_API.md – Complete Schemas & Examples
  - [ ] Add OpenAPI excerpts for `/forecast` default and `detail=full` responses (time_grid + per-quantile arrays).
  - [ ] Include curl examples for cache endpoints and diagnostics.
  - [ ] Document environment variables (TTL, LRU max, diag flag) with realistic defaults and tuning guidance.
  - [ ] Add a “Breaking Changes” policy and versioning notes.
- [ ] Load Test Harness – Async Upgrade & Features
  - [ ] Port to `asyncio + httpx` with connection pooling; preserve CLI.
  - [ ] Add `--concurrency` flag (in addition to QPS) and warm-up period.
  - [ ] Add CSV output option (`--csv-out`) for latency samples (optional).
  - [ ] Add per-index breakdown in summary (latency p50/p95, error rate).
  - [ ] Respect `cache_bust` toggle for a no-cache pass and diff report.
  - [ ] Unit tests: basic argument parsing and a mocked run.
- [ ] Metrics Validation Script (Optional)
  - [ ] Tiny script to scrape `/metrics` and assert presence of:
        `g6_forecast_latency_ms`, `g6_forecast_cache_hits_total`, `g6_forecast_cache_misses_total`.
  - [ ] Output a small JSON with current counters for CI artifacts.
- [ ] CI Wiring
  - [ ] Add a short load test job (e.g., 10s at low QPS) running against a locally started app.
  - [ ] Archive JSON summary and metrics JSON as artifacts.
  - [ ] Ensure the job is opt-in (tag-based) to avoid noisy CI by default.

## Acceptance Criteria
- ENSEMBLE_API.md contains concrete schemas, examples runnable as-is, and clear env var guidance.
- Load test can run with `asyncio+httpx`, reports p50/p95 per-index, supports `cache_bust`, and optionally emits CSV.
- Basic tests pass for load-test tooling (args + mocked runner).
- CI job can run the short test and publish artifacts.

## Run
```
# API docs: just read; no run step.

# Load test (snapshot):
python scripts/ml/load_test_ensemble.py \
  --qps 20 --duration 15 --indices NIFTY --horizon 60 --detail snapshot

# Load test (full detail + cache bust):
python scripts/ml/load_test_ensemble.py \
  --qps 10 --duration 15 --indices NIFTY --horizon 60 --detail full --out reports/load_full.json
```

## Notes
- Do not change the default forecast response shape.
- Keep tooling dependency-light; if `httpx` is introduced, add it under `requirements-dev.txt` only.
- Avoid introducing external services; tests should run locally.
