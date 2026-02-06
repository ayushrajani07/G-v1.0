# Collection Cycle Performance Roadmap

Date: 2025-11-14
Owner: Orchestrator/Infra

## Objectives
- Reduce average collection cycle time during market hours by 30–50%.
- Keep tail latencies stable (99th percentile within 2x of median).
- Improve robustness: predictable cadence under provider slowdowns and local resource contention.
- Make the pipeline scalable across indices and data volume growth.

## Current Signals
- First market hour avg ~17s; last 3 hours ~33s. No change in loop interval.
- Suspects: provider fetch latency/retries, growing CSV write cost, resource contention.
- We already emit phase histograms: fetch/process/write times, and cycle-level gauges.

## Quick Wins (low effort, high impact)
- Parallel across indices (safe parallelism)
  - Run indices (NIFTY/BANKNIFTY/SENSEX/…) in parallel processes/threads.
  - Cap concurrency to cores; timebox each index to avoid overruns.
  - How to try: add `--parallel` to runner; keep per-option serial inside each index.

- CSVIO fast-path (append instead of atomic rewrite)
  - Use append mode with periodic flush; rotate hourly to keep files small.
  - Env: `G6_CSVIO_BACKEND=filesystem`, `G6_CSVIO_FLUSH_MS=500`, `G6_CSVIO_BATCH=2000`.
  - Keep atomic mode for EOD compaction only.

- HTTP client pooling + keep-alive
  - Reuse a single HTTP client (httpx/requests Session) per worker; enable HTTP/2 if available.
  - Limits: max_connections≈16, max_keepalive≈8, timeouts 2–5s, bounded retries.

- Antivirus exclusions (Windows)
  - Exclude `data/`, repo directory, and `C:\GrafanaData\` from real-time scanning.
  - Prevents per-write scanning of temp/atomic files.

- Reduce per-cycle overhead
  - Quiet steady-state logs; cache config/env; avoid per-record logging/formatting.

## Phase-Specific Strategies
- Fetch
  - Use `httpx.Client(http2=True)` with pooling; exponential backoff with jitter; cap total retry budget per cycle.
  - Prefer bulk endpoints; request only required fields; constrain concurrency per-index to reduce 429s.

- Process
  - Vectorize transforms (pandas/pyarrow); avoid Python loops/`apply`.
  - Pre-index frames; reduce repeated merges; reuse schemas.

- Write
  - Dedicated writer thread with micro-batches (250–500ms flush) to amortize fsync.
  - Append-only journal + periodic compaction to CSV/Parquet.
  - Consider Parquet datasets partitioned by date/index for high volume.

## Orchestrator Pipeline
- Overlap stages: fetch(t+1) while process/write(t) runs.
- Backpressure: bounded queues; drop non-critical tails when lagging.
- Timeboxing: per-cycle budget (e.g., 60s). If exceeded, degrade: skip low-priority symbols or reduce depth.

## Storage Strategy (medium/high effort)
- Parquet/Delta/DuckDB
  - Partition by `date/index/expiry`; append via pyarrow for faster writes/reads and smaller footprint.
  - Keep CSV compatibility via periodic export (off-hours).

- Rolling files & compaction
  - Hourly shards during market; compact to daily after close.

## Observability Enhancements
- Add `index` label to phase histograms; custom buckets: `[0.5,1,2,5,10,20,40,80]`.
- Counters: `g6_fetch_retries_total{index,reason}`, `g6_write_bytes_total`, `g6_write_rows_total`.
- Grafana: add a row comparing 15m rolling avg for fetch/process/write by index.

## System Tweaks
- Ensure SSD-backed data dirs; disable NTFS compression on `data/`.
- Separate Prometheus TSDB to a different drive if heavy.
- Use `multiprocessing` across indices (bypasses GIL for CPU-bound parts); cap to physical cores.

---

## Concrete Implementation Plan (Phased)

### Phase 0 – Diagnosis (same day)
- Add Grafana panels for:
  - `avg_fetch = increase(g6_cycle_fetch_time_seconds_sum[15m]) / increase(g6_cycle_fetch_time_seconds_count[15m])`
  - `avg_process = increase(g6_cycle_process_time_seconds_sum[15m]) / increase(g6_cycle_process_time_seconds_count[15m])`
  - `avg_write = increase(g6_cycle_write_time_seconds_sum[15m]) / increase(g6_cycle_write_time_seconds_count[15m])`
- Outcome: identify which phase doubled later in the day.

### Phase 1 – Quick Wins (1–2 days)
1) Enable safe index-parallelism
- Toggle: `--parallel` on `scripts/run_orchestrator_loop.py` during market hours.
- Guardrails: cap pool size to min(cores, indices); add per-index timeout.
- Acceptance: cycle time drops ≥25% with similar error rates.

2) CSVIO append + writer thread
- Env toggles (runtime):
  - `G6_CSVIO_BACKEND=filesystem`
  - `G6_CSVIO_FLUSH_MS=500`
  - `G6_CSVIO_BATCH=2000`
- Rotation: hourly during market; daily compaction post-market.
- Acceptance: write histogram mean halves vs atomic rewrite; no data loss.

3) HTTP session reuse & pooling
- Replace per-call clients with a shared client per worker; enable HTTP/2 where supported.
- Timeouts ≤ 5s; retries bounded; retry budget per cycle.
- Acceptance: fetch histogram mean drops; fewer long tails.

### Phase 2 – Pipelining & Timeboxing (2–4 days)
- Implement staged pipeline with small worker pools: fetch → process → writer.
- Bounded queues with backpressure; per-cycle budget (e.g., 60s) and graceful degradation.
- Acceptance: stable cadence with consistent tail latencies under load.

### Phase 3 – Columnar Storage Pilot (2–4 days)
- Pilot Parquet for one index (NIFTY) intraday with pyarrow; partition by `date/index/expiry`.
- Keep CSV compatibility via periodic export; measure write/read performance and disk usage.
- Acceptance: ≥2× faster writes on large batches; disk footprint reduced ≥50%.

### Phase 4 – Robustness Hardening (ongoing)
- Circuit breakers (error-rate/quarantine by index/symbol); bulkheads across indices.
- AV exclusions documented and enforced; separate TSDB and data disks if possible.

---

## Code Touchpoints (high-level)
- Fetch client(s): reuse pooled httpx/requests sessions; configure limits, timeouts, retries.
- Orchestrator loop: enable and timebox index-parallel execution; backpressure.
- CSV sink/CSVIO facade: append mode, writer thread, rotation & compaction utilities.
- Metrics: index-labelled histograms; write size/rows counters.
- Grafana: add panels for per-phase averages and write throughput.

## Rollback & Safety
- All changes are gated by env flags/CLI.
- Immediate rollback: unset flags or remove `--parallel`.
- Keep E2E tests/CI checks on for data integrity and timing constraints.

## “Flip It” Commands (PowerShell)

- Parallel across indices run (dev):
```
$py = (Get-Command python).Source
& $py scripts\run_orchestrator_loop.py --config config\g6_config.json --parallel
```

- CSVIO append fast-path (dev):
```
$env:G6_CSVIO_BACKEND = 'filesystem'
$env:G6_CSVIO_FLUSH_MS = '500'
$env:G6_CSVIO_BATCH = '2000'
```

- PromQL snippets (Grafana/Explore):
```
increase(g6_cycle_fetch_time_seconds_sum[15m]) / increase(g6_cycle_fetch_time_seconds_count[15m])
increase(g6_cycle_process_time_seconds_sum[15m]) / increase(g6_cycle_process_time_seconds_count[15m])
increase(g6_cycle_write_time_seconds_sum[15m]) / increase(g6_cycle_write_time_seconds_count[15m])
```

## Acceptance Criteria Summary
- Phase 1: ≥25% cycle-time reduction without increased error rates; no missed cycles.
- Phase 2: Tail p99 reduced/stable across market-day; no cascading lag.
- Phase 3: Parquet pilot demonstrates ≥2× write throughput, ≥50% size reduction.

---

## Notes
- Keep provider rate limits in mind; prefer per-index concurrency caps over global spikes.
- Reassess bucket edges for histograms after Phase 1 to tighten resolution.
