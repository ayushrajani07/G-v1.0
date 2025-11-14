# Provider–Collector Efficiency Must‑Haves

This document captures the high‑impact improvements to optimize the provider → collector pipeline. Each item includes a brief rationale and clear success criteria to validate gains.

## Must‑haves (ranked)

1) Provider HTTP pooling + gzip + batching
- What: Use a shared client with keep‑alive, connection pooling, and gzip; batch symbols/expiries per request when possible.
- Why: Slashes round‑trips and CPU spent in parsing.
- Success: p95 provider latency reduced by 30–50%; provider call count per cycle reduced by 3–10x.

2) Concurrency budgets + retry/backoff + circuit breaker
- What: Cap per‑endpoint concurrency; exponential backoff with jitter; fast‑fail circuit breaker on repeated errors.
- Why: Prevents stalls, cascading failures, and throttling bans.
- Success: Error rate stable under stress; no cycle overruns from provider stalls; breaker metrics show short, bounded open periods.

3) Async scheduler with jitter + bounded queues/backpressure
- What: Single asyncio loop; staggered starts; bounded work queue; drop/defer non‑critical work when lagging.
- Why: Eliminates thundering‑herd spikes and memory blowups.
- Success: Cycle time variance shrinks; backlog_depth stays below threshold; dropped_jobs only under intentional overload.

4) Delta‑first processing via content hashing
- What: Compute per‑expiry content hashes; skip rebuilds/metrics if unchanged; incremental coverage updates.
- Why: Cuts redundant compute and I/O when inputs didn’t change.
- Success: ≥40% cycles become “delta‑only”; skipped_full_rebuilds counter grows; CPU and I/O per cycle drop accordingly.

5) Atomic batched CSV writes (phase 1), Parquet for history (phase 2)
- What: Buffer writes and atomically replace (os.replace); keep “live” in CSV, archive history in partitioned Parquet.
- Why: Faster, safer writes on Windows; dramatically cheaper reads for history.
- Success: No partial reads; write time down; historical queries faster and smaller on disk.

6) Per‑phase latency histograms + queue/backlog/drops metrics
- What: Timers for provider, transform, storage phases; gauges for queue depth, backlog, dropped jobs.
- Why: Makes performance bottlenecks obvious and trackable.
- Success: Dashboards show tight p50/p95 across phases; regressions detected quickly.

7) Adaptive cadence (heat‑based refresh)
- What: Refresh active/near expiries more frequently; far/illiquid less; auto‑slow if previous cycle overruns.
- Why: Puts work where it matters; avoids cycles on cold contracts.
- Success: Same coverage with fewer provider calls; cycle CPU time reduced without FieldCov% regression.

8) Label cardinality governance
- What: Cap/bucket labels; pre‑register known label sets; enforce via existing cardinality guard.
- Why: Prevents Prometheus explosion and keeps memory stable.
- Success: Guard never trips in steady state; Prometheus memory flat under load.

## Near‑must (quick wins)

- Reduce logging in hot paths (lazy/structured logs; warn on deltas only).
- Precompute invariants (compiled regexes, monthly anchor policy constants).
- Use dataclasses with slots=True on hot records.

## Rollout plan (fast path)

- Week 1: Items 1, 2, and 6 (pooling/backoff + phase timers/queues).
- Week 2: Items 3 and 4 (async scheduler + delta‑first processing).
- Week 3: Item 5 phase 1 (atomic batched CSV), item 7 (adaptive cadence).
- Week 4: Item 5 phase 2 (Parquet for history), item 8 (cardinality polish).

## Next steps

Start with provider pooling/batching plus phase timers, then measure before/after on a 30–60 minute run:
- p95 provider latency
- provider calls per cycle
- per‑phase cycle times
- queue depth and dropped jobs

Enable feature flags for each enhancement to A/B test safely and roll back if needed.
