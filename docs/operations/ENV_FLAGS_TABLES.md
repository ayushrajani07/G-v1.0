# Runtime Environment Flags (Tables, Headers & Dedup)

This document summarizes the environment flags introduced or modified for cycle table aggregation, header deduplication, and log compaction.

## Table / Aggregation Flags

- G6_DISABLE_CYCLE_TABLES
  Disable accumulation & emission of per-cycle human tables.
  Values: 1/true/yes/on to disable. Default: off (tables enabled if module imported).

- G6_CYCLE_TABLE_GRACE_MS
  Milliseconds to defer final table flush after `cycle_status_summary` in order to capture late `option_match_stats` events. If > 0 the first call to `emit_cycle_tables` arms a deadline and returns; a subsequent invocation after the deadline performs the flush.
  Default: 0 (immediate flush).

- G6_CYCLE_TABLE_GRACE_MAX_MS
  Upper bound (ms) on how long the deferred flush can extend (safety cap). Default: same as `G6_CYCLE_TABLE_GRACE_MS`.

- G6_DISABLE_COLOR
  Disable ANSI color in coverage columns.

- G6_DEFER_CYCLE_TABLES
  Defer human table emission until orchestrator loop completion (flush via automatic call). Useful to avoid interleaving multiple partial table blocks when collectors invoked multiple times per cycle.

## Coverage Coloring Thresholds (code constants)
- Green: >= 0.90
- Yellow: >= 0.70
- Red: < 0.70

## Header / Banner Deduplication

- G6_SINGLE_HEADER_MODE
  Emit the daily banner/header exactly once centrally in `run_orchestrator_loop` and suppress all per-cycle headers in `unified_collectors`.
  Values: 1/true/yes/on to enable. Default: off.

- G6_DISABLE_REPEAT_BANNERS
  When enabled (and single header mode off) suppress repeated daily banner emission inside collectors after first appearance.

- G6_COMPACT_BANNERS
  Switch header format from multi-line framed banner to a single concise line.

- G6_DAILY_HEADER_EVERY_CYCLE
  Force banner every cycle (overrides suppression) for debugging comparisons.

## Phase Timing & Summaries

- G6_PHASE_TIMING_MERGE
  Merge per-phase timings into one consolidated `PHASE_TIMING_MERGED` line per cycle.

- G6_PHASE_TIMING_SINGLE_EMIT
  When used alongside `G6_PHASE_TIMING_MERGE=1`, suppress intermediate (per index block) merged lines and emit exactly one consolidated `PHASE_TIMING_MERGED` at the end of the cycle.

- G6_GLOBAL_PHASE_TIMING
  When enabled: suppress all `PHASE_TIMING_MERGED` emission (including single-emit) inside collectors and aggregate phase timings across *all* collector invocations for the cycle. The orchestrator emits a single `PHASE_TIMING_GLOBAL` line once per cycle. Automatically benefits from merge + single emit semantics; you do NOT need to set those flags explicitly when this is on.

- G6_AGGREGATE_GLOBAL_BANNER
  Emit aggregated legs/fails summary banner after each index block (or globally in concise mode) showing system status (GREEN/DEGRADED based on fail count).

- (Implicit) When `G6_SINGLE_HEADER_MODE=1` timing merge and single emit are auto-enabled.

## FINNIFTY Specific Logic

- (No explicit flag) Adaptive widening disabled and strike sampling normalized to multiples of 100; logic resides in code paths guarded by index symbol equality.

## Other Related Flags (contextual)

- G6_IMPORT_TRACE: Emit import trace markers for diagnosing slow module import.
- G6_ENABLE_DATA_QUALITY: Enable data quality checks (affects potential late option stats timing).
- G6_STRUCT_COMPACT: Compact structured JSON payloads (truncate long arrays, drop verbose fields) before logging.
- G6_BANNER_DEBUG: Emit DEBUG lines explaining why banners/market-open lines were suppressed.

## Interaction Notes

1. If `G6_SINGLE_HEADER_MODE` is set, `G6_DISABLE_REPEAT_BANNERS` becomes moot for header emission inside collectors (they are always suppressed).
2. Grace delay (`G6_CYCLE_TABLE_GRACE_MS`) only influences human-readable table flush, not structured JSON events.
3. Merged phase timing (`G6_PHASE_TIMING_MERGE`) coexists with raw `PHASE_TIMING` lines; disabling it restores original per-phase emission.
4. Aggregated summary (`G6_AGGREGATE_GLOBAL_BANNER`) adjusts system status: GREEN when total fails == 0 else DEGRADED.
5. `G6_GLOBAL_PHASE_TIMING` suppresses both merged and single-emit timing lines; only the orchestrator-level global line remains.
6. A curated superset reference of these flags with defaults lives in `.env.summary` for quick copying.

## Quick Examples

Single header, merged timings, compact banner, 250ms grace for tables:
```
G6_SINGLE_HEADER_MODE=1 \
G6_COMPACT_BANNERS=1 \
G6_PHASE_TIMING_MERGE=1 \
G6_CYCLE_TABLE_GRACE_MS=250 \
python scripts/run_orchestrator_loop.py --cycles 5
```

Immediate tables, colorful full banners:
```
unset G6_SINGLE_HEADER_MODE
unset G6_CYCLE_TABLE_GRACE_MS
python scripts/run_orchestrator_loop.py --cycles 1
```

(Adjust unset syntax per shell; on Windows PowerShell: `$env:G6_SINGLE_HEADER_MODE='';`.)

## Troubleshooting

- Tables missing: Verify `G6_DISABLE_CYCLE_TABLES` not set and module imported; ensure at least one `cycle_status_summary` event emitted.
- Delayed or absent table after enabling grace: A second `cycle_status_summary` (next cycle) may trigger flush if first cycle completed within grace window without subsequent emit call.
- Duplicate headers while single header mode active: Check that orchestrator script is the only entry point; external wrappers invoking collectors directly will bypass central header logic.

---
Maintainers: Update this file when introducing new G6_* flags affecting human log surface area.

## I/O & Storage Performance Flags

- G6_CSVIO_WRITER_THREAD
  Enable the asynchronous CSV writer thread with micro-batching. When active, individual row appends are queued and flushed in batches either when `G6_CSVIO_BATCH` is reached or the `G6_CSVIO_FLUSH_MS` interval elapses. Reduces per-append open/fsync overhead and smooths write latency spikes. Automatically defaults to enabled (1) when the CSVIO facade is in use; can be disabled by setting to 0/false. Safe to toggle at process start; do not disable mid-session.

- G6_CSVIO_FLUSH_MS
  Flush interval in milliseconds for the writer thread. Pending batches are written when this duration passes since last flush. Default: 500.

- G6_CSVIO_BATCH
  Maximum accumulated rows per file before forcing an immediate flush regardless of time window. Default: 2000.

- G6_PARQUET_PILOT
  Enable the Parquet pilot sink for columnar storage (write + optional periodic CSV export). When set (1/true/on) option chain snapshots are written as partitioned Parquet (date/index/expiry) providing improved write throughput and disk compression. Default: 0 (disabled). Requires `pyarrow` installed. Recommended to evaluate in isolated runs before enabling broadly.

- G6_PARQUET_INDEX / G6_PARQUET_PARTITION_BY / G6_PARQUET_COMPRESSION / G6_PARQUET_CSV_EXPORT_INTERVAL
  Tuning knobs for the Parquet pilot: target index symbol (default NIFTY), partition column list (default `date,index,expiry`), compression codec (default `snappy`), and periodic CSV export interval in seconds (default 3600). Only honored when `G6_PARQUET_PILOT=1`.
  See `scripts/dev/check_parquet_pilot.py` for a readiness/health check script.

## Ensemble Calibration & Disagreement Flags

- G6_USE_RAW_K
  Force use of the raw `recommended_k` from calibration sidecar instead of the smoothed `k_smooth` value when computing applied disagreement radius. Truthy values (1/true/on) bypass smoothing logic; falsy (unset/0/false) uses `k_smooth` when present. Falls back to raw when smoothing absent. Useful for A/B comparisons or during initial calibration windows when smoothing may lag rapid regime shifts.
  Detailed calibration & governance reference: `CALIBRATION_K_GUIDE.md`.

### Interaction Notes (New Sections)

1. When both writer thread and Parquet pilot are enabled the CSV writer thread still services legacy CSV sinks; Parquet writes are independent and not batched by the thread.
2. Disabling `G6_CSVIO_WRITER_THREAD` reverts to immediate synchronous appends; expect higher variance in per-write latency under heavy emission.
3. `G6_USE_RAW_K` only influences consensus exporter applied K when no manual override is active; overrides always take precedence until removed or auto-reverted.
4. Parquet pilot does not retro-migrate existing CSV archives; enable early in the session to capture a full trading day.

