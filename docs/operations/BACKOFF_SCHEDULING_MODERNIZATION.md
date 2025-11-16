# Backoff and Scheduling Modernization

Date: 2025-11-13

This document outlines the plan to standardize sleeps, backoffs, and loop cadence across the project, reducing drift and improving observability.

## Goals
- Replace ad-hoc `time.sleep()` in core loops with monotonic scheduling to avoid wall-clock drift.
- Centralize retry backoff and per-iteration delays via helpers.
- Add optional jitter to reduce thundering-herd effects across processes.
- Keep behavior backwards-compatible and tests green.

## Principles
- Use monotonic time for cadence: schedule sleeps based on `time.monotonic()` rather than wall clock.
- Centralize sleeps:
  - Sync: `utils.backoff.sleep_ms(ms)` for millisecond sleeps and `utils.scheduler` for loop cadence.
  - Async: `await asyncio.sleep()`; no `time.sleep()` in async code.
- Make jitter opt-in via env vars; default to deterministic behavior.

## Current helpers
- `src/utils/backoff.py`
  - `backoff_delays(...)` yields bounded, optionally jittered delays in ms.
  - `sleep_ms(ms)` sleeps for milliseconds (testable indirection).
- NEW: `src/utils/scheduler.py`
  - `compute_sleep_for(start_monotonic, interval, jitter_ms=0.0)`
  - `next_deadline(prev_deadline, interval)`

## Recent changes
- Orchestrator loop (`src/orchestrator/loop.py`)
  - Uses `next_deadline()` for monotonic cadence.
  - Supports optional jitter via `G6_LOOP_JITTER_MS` (milliseconds).
  - Prefers centralized `backoff.sleep_ms(...)` for cadence sleeping (falls back to `time.sleep`).
- Orchestrator cycle (`src/orchestrator/cycle.py`)
  - Per-index stagger uses `backoff.sleep_ms()` when available.
- Storage CSV writer (`src/storage/csv_writer.py`)
  - Retry backoffs use `backoff.sleep_ms()` to centralize behavior.
- Panels integrity monitor (`src/panels/integrity_monitor.py`)
  - Failure retries now use env-driven backoff via `iter_backoff_from_env`.
  - Prefix: `G6_PANELS_INTEGRITY_BACKOFF_*` (MAX_RETRIES, BASE_MS, FACTOR, CAP_MS, JITTER_MS).

## Next candidates (priority)
- Orchestrator polling:
  - `src/orchestrator/sse.py`, `src/orchestrator/gating.py`, `src/orchestrator/catalog_http.py`
  - Replace `time.sleep(...)` with `backoff.sleep_ms()` or a cadence helper, keeping semantics.
- Metrics and background services:
  - `src/metrics/emitter.py`, `src/metrics/resource_sampling.py`, `src/health/monitor.py`, `src/panels/integrity_monitor.py`
  - Switch to scheduler/backoff helpers; expose env-configurable intervals.
- Scripts (operational, lower risk):
  - Gradual sweep; wire into the same helpers when sensible. Maintain CLI-opted intervals.

## Configuration
- `G6_LOOP_JITTER_MS` (default 0): optional jitter subtracted from per-iteration sleep in orchestrator loop.
- `G6_METRICS_SAMPLER_JITTER_MS` (default 0): jitter for metrics sampler/emitter/watchdog sleeps.
- `G6_HEALTH_MONITOR_JITTER_MS` (default 0): jitter for health monitor check sleeps.
- `G6_SSE_POLL_JITTER_MS` (default 0): jitter for /events SSE polling interval on the server side.

## Status
- Implemented
  - Loop cadence via scheduler + centralized sleep.
  - Panels integrity backoff with env-tunable parameters (`G6_PANELS_INTEGRITY_BACKOFF_*`).
  - Optional jitter: metrics sampler/emitter/watchdog (`G6_METRICS_SAMPLER_JITTER_MS`), health monitor (`G6_HEALTH_MONITOR_JITTER_MS`).
  - SSE polling jitter (`G6_SSE_POLL_JITTER_MS`).
- Candidates queued
  - Catalog HTTP readiness wait (could accept an env-driven backoff, currently fixed 50ms steps, ~1s max).
  - Metrics samplers (emitter/resource sampling) to adopt centralized sleep helpers and optional jitter.

## Observability
- Counters for retries/backoffs are already available in some modules; ensure we increment them around helper usage.
- Optional: add histograms for loop cadence deltas if needed.

## Rollout
- Phase 1 (done): Helpers + orchestrator loop/cycle + storage writer.
- Phase 2: Orchestrator polling modules and metrics samplers.
- Phase 3: Scripts sweep and optional service-specific jitters.

## Validation
- Unit tests remain green.
- Manual orchestrator run shows stable cadence and expected cycle summaries.
- No regressions in CSV write retries/backoffs.
