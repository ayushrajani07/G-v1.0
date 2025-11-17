# Issue: Async Load Test + CI Integration

## Summary
Upgrade load tester to `asyncio + httpx` for higher concurrency & add CI job executing short test, archiving artifacts.

## Features
- Flags: `--qps`, `--duration`, `--concurrency`, `--indices`, `--horizon`, `--detail`, `--csv-out`, `--cache-bust-pass`, `--out`.
- Output JSON: latency p50/p95/p99, error rate, per-index breakdown, cache hit ratio sampling.
- Optional second pass with `cache_bust=1` to compare warm vs cold.

## Implementation Outline
1. Replace threads with rate-limited async tasks (token bucket or sleep pacing).
2. Collect per-request timing + status in shared lists.
3. Compute percentiles; write JSON & optional CSV.
4. If `--cache-bust-pass`, run second loop forcing bust and diff metrics.
5. Add small test using a mocked `httpx.AsyncClient`.

## CI Job (GitHub Actions / similar)
- Steps: setup Python, install minimal deps, start API (uvicorn), run test `--qps 10 --duration 10 --concurrency 5`, upload JSON artifact.
- Thresholds: fail if error rate > 2% or p95 latency > configured budget.

## Acceptance Criteria
- Async version demonstrates >2x throughput vs thread baseline locally.
- CI passes reliably under default conditions.
- Docs updated (ENSEMBLE_API or separate README section).
