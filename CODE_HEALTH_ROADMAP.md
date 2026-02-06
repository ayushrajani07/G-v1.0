# Code Health and Modernization Roadmap

Updated: 2025-11-13
Repo: v1.1 (ayushrajani07)

This roadmap turns the audit findings into a concrete, staged plan to reduce complexity, eliminate redundancy, improve reliability, and standardize practices across the codebase.

## Objectives and KPIs

- Reliability
  - Reduce blanket `except Exception` by 80% in priority paths (web, storage, metrics).
  - Introduce a minimal error taxonomy and central error handling utilities.
- Maintainability
  - Decompose the top 6 largest modules; reduce per-file size by 30–50% with single-responsibility helpers.
  - Consolidate CSV I/O into a single abstraction; retire duplicate writers/paths.
- Observability
  - Replace ad-hoc `print()` with structured logging in priority services.
  - Add basic metrics (error counts, retries, backoffs) to storage and web routes.
- Performance
  - Replace blocking `time.sleep()` in async/event loops or critical paths with non-blocking waits/backoff.
- CI Quality Gates
  - Ensure core test suite runs green locally and in CI.
  - Add lightweight complexity and lint gates (ruff + optional radon/xenon) with pragmatic thresholds.

Success looks like: “Run full pytest” passes reliably, reduced incident rate from hidden blanket exceptions, clearer logs, less duplicated CSV code, and easier navigation through decomposed modules.

## Workstreams and Deliverables

1) Environment and Tooling Enablement
- Deliverables
  - Workspace interpreter selected and `src/` importable without ad-hoc path hacks
  - Optional: Add `.env.example` (PYTHONPATH or install-in-editable mode)
  - Confirm tasks for tests/lint run locally
- Actions
  - Select Python interpreter in VS Code; verify `pytest -q` succeeds or fails deterministically
  - Option A: Use editable install (pyproject + `pip install -e .`)
  - Option B: Configure PYTHONPATH to include `src/`
- Acceptance criteria
  - Import scans show internal modules resolved; tests run without import errors

2) Complexity Pass on Hotspots
- Scope (by size/complexity)
  - `src/web/dashboard/routes/path_forecast/` (router package; formerly `path_forecast.py`)
  - `src/storage/csv_sink.py`
  - `src/web/dashboard/routes/ml.py`
  - `src/collectors/unified_collectors.py`
  - `src/metrics/metrics.py`
  - `src/orchestrator/cycle.py`
- Deliverables
  - Cyclomatic complexity and function length/nesting snapshot (report saved in `reports/complexity_*.md`)
  - Extraction plan per file (helpers/services, contracts, tests to add)
- Actions
  - Use radon/xenon locally or linters’ complexity checks to flag worst functions
  - Identify seams for extraction; create TODOs with owners
- Acceptance criteria
  - Documented extraction plan for each hotspot; at least 2 functions refactored per module in Phase 2

3) CSV I/O Consolidation
- Rationale
  - Similar responsibilities spread across `csv_sink.py`, `csv_writer_helper.py`, `csv_writer.py`, `csv_batcher.py` with numerous “mirror legacy logic” paths
- Design principles (important)
  - Unify the public API, not the implementation. Keep the current smaller modules (lock/retry, schema/header, legacy mapping, buffering/batching) as separate, testable units.
  - Introduce a thin facade (e.g., `csvio.writer`) that orchestrates these components and exposes one stable contract to callers.
  - Allow backends/strategies (filesystem direct write, buffered batcher, atomic temp rename) to be plugged via dependency injection; default stays current filesystem behavior.
  - Preserve seams for testing and maintainability; avoid re-creating a monolith. The goal is consistency and single source of policy, not collapsing modules.
- Deliverables
  - One authoritative “CSV Writer” API/facade with:
    - Append-one/append-many with schema enforcement
    - File locking + retry/backoff (configurable, jittered)
    - Atomic writes where applicable
    - Optional header management and legacy-to-modern field mapping
    - Metrics hooks (attempts, retries, failures)
  - Migration guide and module deprecations list
- Contract (minimal)
  - Inputs: file path, row(s) dict-like, header policy, legacy mapping policy
  - Outputs: success bool or raised typed error
  - Errors: `CsvWriteError`, `CsvSchemaError`, `CsvRetryExhausted`
- Edge cases
  - Concurrent writers, partial headers, legacy timestamp vs `time`/`time_ms`, line breaks, file rotation
- Acceptance criteria
  - Storage modules call the unified writer; duplicate helpers removed/tombstoned
  - Tests cover happy-path + concurrency/retry + legacy field mapping

Update (2026-01-25): CSVIO consolidation (flag retired)
- CSV writes are centralized via `src.storage.csvio.api` (CSVIO) through `src.storage.csv_writer.CsvWriter`.
- Legacy inline write paths in storage modules were removed.
- Backend selection remains via env `G6_CSVIO_BACKEND`:
  - `filesystem` (default)
  - `atomic` — atomic temp-file strategy (safer on Windows lock errors)
- Optional writer thread is controlled by `G6_CSVIO_WRITER_THREAD=1` (default off).
- Backend selection via env `G6_CSVIO_BACKEND`:
  - `filesystem` (default) — uses `CsvWriterHelper` directly
  - `atomic` — atomic temp-file strategy (safer on Windows lock errors)
- Tests covering the facade and atomic backend exist under `tests/storage/`.

Update (2025-11-13): ML exporters routed via facade (predictions + residuals)
- Quantile exporter `scripts/ml/quantile_predict_exporter.py` now appends predictions and (optional) residuals using the CSVIO facade with a safe direct-write fallback. Headers are supplied only on new files to avoid duplication; atomic backend can be enabled via `G6_CSVIO_BACKEND=atomic`.
- Hybrid residual exporter `scripts/ml/hybrid_predict_exporter.py` now appends hybrid predictions (baseline, residual, model, index, horizon) through the facade with the same safe fallback behavior.
- Move stats archiver `scripts/ml/move_stats_archiver.py` now archives diagnostics snapshots via the facade (per index/horizon CSV) with a safe fallback.
- Benefits: atomic appends on Windows, consistent header policy, and centralized metrics/locking when enabled.
- Validation: Quick pytest run PASS after changes; no behavioral drift in CLI UX (stdout messages unchanged).

Update (2025-11-14): Forecast archiver exception hygiene & logging
- Refactored `scripts/ml/forecast_archiver.py` to replace ad-hoc `print()` calls with structured logging (`logger.info`/`logger.debug`).
- Added optional backoff-aware sleep helper `_sleep_s` leveraging `src.utils.backoff.sleep_ms` when available; falls back to `time.sleep` otherwise for consistency with other exporters.
- Narrowed KeyboardInterrupt handling at script entry to emit a clean structured termination message and exit with code 0.
- Network request failures now logged at debug (non-fatal) instead of silent broad suppression; retains loop resilience while increasing observability for intermittent issues.
- Result: aligns with roadmap logging and exception hygiene goals without altering functional behavior or CLI flags (`--quiet`). Quick test suite remains PASS.

Update (2025-11-14): Move stats archiver logging & exception hygiene
- Refactored `scripts/ml/move_stats_archiver.py` to use structured logging (start, per-fetch warnings, debug for empty responses, fatal loop errors) instead of `sys.stderr.write` prints.
- Added optional backoff-aware sleep `_sleep_s` (leverages `src.utils.backoff.sleep_ms` when available) for consistency with other ML scripts; preserves previous interval semantics.
- Narrowed exception scope: network fetch errors logged at warning level and skipped without breaking the loop; rare fallback write failures logged at error level with file path context.
- Added clean KeyboardInterrupt handling (info-level termination message).
- Maintains CSV facade usage for atomic appends; header logic unchanged; quick pytest run PASS post-change.

Update (2025-11-14): Quantile exporter logging & exception hygiene
- Refactored `scripts/ml/quantile_predict_exporter.py` to replace `print()` and `sys.stderr.write` with structured logging (`logger.info`/`logger.warning`/`logger.debug`).
- Added Prometheus counters (when port provided) for loop errors, residual append failures, and metrics export failures: `g6_ml_quantile_exporter_loop_errors_total`, `g6_ml_quantile_exporter_residual_errors_total`, `g6_ml_quantile_exporter_metrics_errors_total`.
- Implemented debug-level logging for facade fallback paths (prediction/residual appends) without elevating normal success noise.
- Preserved CSVIO facade append semantics with safe direct-write fallback; residual store preloading unchanged.
- Introduced structured metrics server start log (`metrics server started`) instead of stdout print; failure to init metrics now logged at debug with error context.
- Narrowed broad exceptions to specific metrics and append contexts while keeping loop resilience; KeyboardInterrupt still exits cleanly.
- Tests (core-only and full) PASS after refactor; no CLI flag changes.

Update (2025-11-14): Hybrid exporter logging & exception hygiene
- Refactored `scripts/ml/hybrid_predict_exporter.py` to use structured logging throughout and a backoff-aware `_sleep_s` helper.
- Replaced `print()` and `sys.stderr.write` with `logger.info`/`logger.warning` and debug logs for fallback write paths.
- Added Prometheus counters (when port provided) for loop errors and metrics export failures: `g6_ml_hybrid_exporter_loop_errors_total`, `g6_ml_hybrid_exporter_metrics_errors_total`.
- Maintains CSVIO facade usage with safe direct-append fallback; only fallback events are logged at debug to avoid noise.
- Metrics server startup now logged structurally; init failures logged at debug with context.
- Tests (core-only and full) PASS; CLI flags unchanged and functional behavior preserved.

Update (2025-11-14): Ensemble exporter logging & exception hygiene
- Refactored `scripts/ml/ensemble_consensus_exporter.py` to add structured logging and optional Prometheus counters for loop and metrics errors.
- Replaced stdout/stderr prints with `logger.info` and `logger.warning`; metrics server startup now logged structurally, and export failures are counted and logged at debug.
- Preserved write path semantics (extended header handling for ZZZTEST vs normal indices); sleep remains backoff-aware via `_sleep_s`.
- Tests (core-only and full) PASS after change; no CLI flag changes.

Update (2025-11-14): csv_sink write-path instrumentation split
- Goal: reduce complexity in `csv_sink` by separating logging/metrics from raw I/O operations.
- Implemented small, behavior-preserving helpers in `CsvSink`:
  - `_write_csv_row(filepath, row, header) -> bool` and `_write_csv_rows(filepath, rows, header) -> bool` perform only the write via existing facade/legacy paths.
  - `_instrument_write(filepath, count)` centralizes debug logging and `csv_records_written` metric increments.
- Refactored callers:
  - `_handle_duplicate_write_or_buffer` now delegates I/O to `_write_csv_row` and emits instrumentation via `_instrument_write` on success.
  - `_maybe_flush_batch` legacy flush path now uses `_write_csv_rows` + `_instrument_write`, removing inline logs/metrics from the loop.
- No behavior drift: messages and counters remain identical; header alignment and facade behavior unchanged.
- Validation: Core-only and full pytest runs PASS.

## Progress snapshot (2025-11-14)

- What we've shipped so far
  - CSV facade `storage.csvio.api` enabled by default and used by `csv_sink` for append-one/append-many with a safe legacy fallback.
  - Migrated ML exporters (quantile, hybrid, ensemble) and archivers (forecast, move_stats) to structured logging, narrowed exception scopes, and Prometheus counters where applicable.
  - Atomic CSV backend instrumentation added (lock waits, wait time, acquire failures) and tunables exposed via env vars.
  - Extracted several helpers from `src/storage/csv_sink.py` (schema, expiry handling, debug snapshot, VIX resolution, PCR, open/close caches) to reduce function-level complexity.
  - Small complexity extraction: split instrumentation from raw I/O in `csv_sink` by adding `_write_csv_row`/_`write_csv_rows` and `_instrument_write` helpers; callers refactored to use them.
  - Tests: core-only and full pytest runs PASS after these refactors.

- Quick validation notes
  - Core-only tests (parallel non-serial): PASS
  - Full test suite: PASS
  - No functional CLI changes for exporters or archivers; header and facade behaviors preserved.

## Potential future enhancements (short list)

- Short-term (next sprint)
  - Extract a small adapter around `CsvBatcher.maybe_flush_batch` to return flush counts so instrumentation can be unified for batcher-driven writes.
  - Add a focused unit/integration test harness for the `csvio` atomic backend to validate concurrent appends and lock-retry behavior on Windows.
  - Introduce a minimal error taxonomy for CSV writes (e.g., CsvWriteError, CsvRetryExhausted, CsvSchemaError) and surface them from the facade for clearer handling in callers.
  - Expand mypy checks to include `src/storage` and the csvio facade (incremental, file-by-file baseline) and add CI gating for the focused subset.

- Medium-term (3–6 weeks)
  - Implement a lightweight complexity budget check (radon/xenon) in CI for hotspot files (start with `csv_sink.py`, `routes/path_forecast/_router.py`) and add gradual enforcement.
  - Consolidate CSV writer backends into an explicit strategy registry so tests can inject a deterministic in-memory writer for faster unit tests.
  - Add Prometheus histograms for write latency and retries per-backend to support dashboarding and alerting.

- Longer-term (quarterly goals)
  - Replace remaining broad `except Exception` handlers in priority modules with targeted exceptions and instrument counts for deferred refactors.
  - Finish the CSV I/O facade contract described in the roadmap (typed errors, success boolean vs exceptions) and migrate remaining helpers off legacy inline paths.
  - Gradually raise ruff/mypy/complexity gates in CI with a staged rollout plan and small PR quotas to avoid churn.

These items aim to keep changes incremental, test-backed, and low-risk while improving observability and maintainability.

VS Code helpers (added): quick CSVIO toggles for core-only tests
- CSVIO: Core pytest (facade OFF, legacy)
- CSVIO: Core pytest (facade ON, filesystem)
- CSVIO: Core pytest (facade ON, atomic)

Each task sets `G6_CSVIO_BACKEND` (and related tuning) for the run. Use these to compare filesystem vs atomic behavior without changing your shell environment.

Lock metrics and tuning (2025-11-13)
- Atomic backend now emits lightweight lock metrics via Prometheus:
  - `csvio_lock_waits_total{kind="atomic_fs"}` — number of times a write had to wait for a lock
  - `csvio_lock_wait_time_ms_total` — total milliseconds spent waiting across lock acquisitions
  - `csvio_lock_acquire_failures_total` — retries exhausted while attempting to acquire the lock
- Tuning environment variables (optional):
  - `G6_CSV_LOCK_RETRIES` (default 50)
  - `G6_CSV_LOCK_BACKOFF_MS` (default 100 ms, exponential factor 1.3, capped 2000 ms)
- Notes:
  - Metrics are best-effort and no-op if the metrics subsystem isn’t initialized.
  - Windows-friendly: the atomic backend uses a lock file and temp-file replace strategy to avoid sharing violations.

Runtime status change detection consistency (2025-11-13)
- UnifiedDataSource now refreshes runtime status even when a cached value exists if the file changed, bringing behavior in line with panel reads.
- Effects:
  - Cache stats reflect a miss+read on file modification regardless of cache presence.
  - Event notifications are published consistently when changes are detected.
- This preserves the fast path (cache hit) when there’s no change and honors the file polling interval unless explicitly set to 0.0 (always stat).

Quality gates snapshot (2025-11-13)
- Build: PASS
- Tests: PASS (core-only and full)
- Lint/Typecheck: unchanged in this step; ruff and mypy tasks remain available.

4) Exception Hygiene and Error Policy
- Deliverables
  - Error taxonomy for web/storage/metrics (3–5 core exception types per domain)
  - Replace blanket `except Exception` in priority paths with targeted exceptions
  - Central helper for “log-and-raise” with context (request id, file path)
- Actions
  - Start with web routes, storage writer, metrics init
  - Add Prometheus counters for handled error types
- Acceptance criteria
  - 80% reduction of blanket `except Exception` in selected modules
  - Error logs gain consistent structure and labels

5) Logging Standardization
# Deliverables
  - Replace `print()` with structured logging
  - One logger factory used across modules (hooking existing `utils/output.py` where appropriate)
  - Log levels policy and minimal correlation fields
# Actions
  - Introduce `logger = get_logger(__name__)` pattern; wire console/file settings via env
  - Swap prints in web routes/metrics/storage first; then long tail
# Acceptance criteria
  - No prints in the prioritized modules; logs are parseable and consistent

Status update (2025-11-12): Completed for metrics; extended to web routes (initial)
- src/metrics/metrics.py: init and provider-mode traces routed to logging (info)
- src/metrics/gating.py: gating traces now logged at debug behind G6_METRICS_GATING_TRACE
- src/metrics/__init__.py: import tracer (_imp) uses logging.debug when G6_METRICS_IMPORT_TRACE=1
- src/web/dashboard/routes/ml.py: replaced debug prints with logger.info/debug
- src/web/dashboard/routes/system.py: replaced alert print blocks with logger.info multi-line blocks
- src/web/dashboard/app.py: replaced advisor-router import/include prints with logger.error/info
- Behavior unchanged; output now respects logging configuration and avoids stdout spam

### Latest stability fixes (2025-11-12)

- Startup summaries dedupe under parallel/serial runs
  - Ensured `collector.settings.summary` emits exactly once per process:
    - `get_collector_settings(force_reload=True)` no longer resets the one-shot guard.
    - Guard made robust against tests deleting the sentinel.
    - Deprecated module `src.collector.settings` now aliases the canonical `src.collectors.settings` module so tests manipulating module globals affect the real implementation.
  - Marked the startup summaries integration test as serial in the suite harness to avoid duplicate emissions from multi-worker import sequences.
- Expiry remediation summary determinism
  - Under pytest, when `G6_EXPIRY_SUMMARY_INTERVAL_SEC <= 1`, the CSV sink emits `expiry_quarantine_summary` immediately after updates to avoid timing flakiness.
- Two-phase pytest runner is green
  - Parallel phase: `-n auto -m 'not serial'` PASS
  - Serial phase: `-m serial` PASS
  - Harness hygiene: per-test clearing of metrics group gating env prevents registry surface drift; explicit path precedence in `StatusReader` fixed.
  - Quality gates summary for this session: Build PASS, Lint/Typecheck N/A (unchanged), Tests PASS (two-phase).

### Phase 2: complexity-driven extractions (2025-11-12)

- Target: `src/storage/csv_sink.py` (hotspot per complexity report)
  - Extracted a small, behavior-preserving helper `_build_misclass_quarantine_record` from
    `_handle_expiry_misclassification` to isolate record-construction concerns and reduce cyclomatic complexity.
  - Purpose: enable focused unit testing without I/O and make the misclassification policy branch easier to read.
  - Tests added: `tests/storage/test_csv_sink_helpers.py` covering structure, typing, and fallback conversions.
  - Validation: Full pytest quick run PASS; no behavior changes to write flows.
  - Additionally extracted `_reorder_time_columns` from the per-strike write loop to centralize schema adjustments
    for new files. This keeps the loop lean and improves testability.
  - Tests added: validations for new vs existing file schemas to ensure columns are moved only when desired.

  - Extracted `_is_preopen_and_quarantine` from `write_options_data` to encapsulate pre-open gating and quarantine
    side-effects. This reduces branching in the top-level write path and makes the policy easier to test. Added
    tests covering quarantine writes and allow-preopen bypass behavior.

  - Extracted `_nearest_price_for_type` (CE/PE ATM price selection) from an inline closure in `write_options_data`.
    This is a pure helper and keeps the main function concise. Added unit tests for basic and edge cases.

  - Extracted `_write_debug_snapshot` that writes the per-cycle debug JSON payload, reducing I/O noise in
    `write_options_data` and centralizing the snapshot contract. Behavior preserved, error handling unchanged.

  - Extracted `_update_open_prices` to initialize/update index and TP open values in a small helper. Covered with
    unit tests for pre-open, within-window updates, and next-day rollover.

  - Extracted `_compute_pcr` to encapsulate PCR calculation with defensive handling for malformed inputs; added
    unit tests for standard and edge cases (zero CE OI, invalid values).

  - Schema Assertions Layer now covered by focused tests via `_validate_schema` helper: drops invalid strikes,
    nulls legs with missing/incorrect `instrument_type`, and surfaces labeled issues. This keeps the main
    write flow lean while guarding behavior with unit tests.

  - Extracted `allowed-expiry` enforcement into helpers `_is_expiry_disallowed` and `_log_disallowed_expiry`,
    replacing the inline block and fixing a subtle isinstance bug (now checks the allowed set type correctly).
    Added tests covering set/list/tuple membership and non-configured behavior.

  - Extracted `_resolve_index_price` to centralize the fallback order for index price resolution
    (provided value → per-index defaults → metadata override). Added unit tests to lock behavior.

  - Extracted `_compute_day_width` to encapsulate the OHLC day-width calculation with defensive
    casting and fallbacks. Added tests for basic and edge cases (missing fields, non-numeric values).

  - Extracted `_resolve_vix` to unify VIX lookup order (extra → cache → external) and ensure cache
    updates on success. Added tests to verify precedence and caching behavior.

  - Introduced `_build_return_metrics` to standardize early-return payloads (pre-open and invalid-expiry
    paths), reducing branching duplication in `write_options_data`. Added tests to lock payload structure
    and flag handling.

Next candidates (from report):
- `csv_sink.write_options_data` and `_append_many_csv_rows` (split logging/metrics/IO concerns)
- `metrics.__init__` and `metrics.prune_groups` (extract config loading and filtering steps)

### Phase 2: continued extractions (2025-11-13)

- Expected-expiry advisory emission wrapper
  - Added `_emit_expected_expiry_advisory(index, seen, missing)` and refactored
    `_advise_missing_expiries` to delegate emission. This centralizes logging format/level
    and keeps the advisory logic focused on state tracking. Behavior preserved; exceptions swallowed as before.
- Consolidated change calculations (TP and Index)
  - Added `_compute_change_metrics(current, prev_close, open_value) -> (net, day, net_pct, day_pct)`
    with defensive zero-division handling. Replaced duplicate inline arithmetic in `_prepare_option_row`
    for both TP and index. This reduces duplication and clarifies intent.
- Tests added/updated
  - `tests/storage/test_csv_sink_helpers.py`: `test_compute_change_metrics_basic_and_edge` covers
    normal and edge cases (None/zero baselines) for percentage calculations.
- Validation
  - Quick core tests (parallel, non-ML) PASS after changes; no behavior drift observed in csv_sink flows.

### Dependency split and test runner updates (2025-11-13)

- Dependency files finalized and documented
  - requirements.core.txt, requirements.api.txt, requirements.monitoring.txt, requirements.ml.txt, requirements-all.txt, requirements.lock.txt
  - New DEPENDENCIES.md explains install paths and lock usage; Torch handled via a dedicated task.
  - Legacy requirements.txt replaced with a thin shim that delegates to requirements-all.txt and includes a deprecation notice.
- VS Code tasks added for dependency management
  - Deps: Install core/API/Monitoring/ML/all/lock
  - Dev: Install test deps
  - Deps: Refresh lock from venv (pip freeze -> requirements.lock.txt)
- Two-phase pytest convenience
  - Added compound task: "Pytest: Fast all (two-phase)" that runs:
    1) Pytest: Fast parallel (not serial)
    2) Pytest: Serial only

### Parity hash determinism + Windows runner reliability (2025-11-13)

- Parity hash determinism
  - Implemented canonicalization in `src/collectors/pipeline/shadow.py::_compute_parity_hash`: sort the full `strikes` list and take a sorted head of 5 before hashing.
  - Removed temporary xfail from `tests/test_shadow_hash_determinism.py`; the test now enforces order-invariant hashing directly.
  - Outcome: stabilized parity hash behavior and removed a source of intermittent XPASS noise.

- Windows-friendly core-only pytest tasks
  - Added a verbose capture task to aid diagnosis: "Run pytest (core only, verbose+capture)". Fixed PowerShell quoting (marker expression and file path) so the command parses correctly and preserves pytest's exit code.
  - Added a shell-agnostic script runner: `scripts/dev/run_core_pytest.py` and task "Run pytest (core only, capture via script)" to eliminate PowerShell quoting pitfalls entirely and write output to `pytest_core_out.txt` deterministically.
  - Outcome: eliminated spurious exit code 1 reports; core-only and full test runs are green with reliable exit codes on Windows.

### Metrics logging reliability (2025-11-13)

- Structured group filters event
  - Emitted `metrics.group_filters.loaded` once per facade import/reload to ensure deterministic presence without log spam.
- Dump/suppression markers on env changes
  - Reworked emission to use environment snapshots; markers are (re)emitted when `G6_METRICS_SUPPRESS_AUTO_DUMPS`, `G6_METRICS_INTROSPECTION_DUMP`, or `G6_METRICS_INIT_TRACE_DUMP` change.
  - Suppressed path emits: `metrics.dumps.suppressed`, `METRICS_INTROSPECTION: 0`, `METRICS_INIT_TRACE: 0 steps`.
  - Unsuppressed with dumps requested emits: `METRICS_INTROSPECTION: N` and/or `METRICS_INIT_TRACE: M steps`.
- Outcome: dump suppression and group-filter log tests pass reliably across reloads and reused registries.

### Adaptive scaling passthrough guard (2025-11-13)

- Passthrough now requires an explicit `adaptive_scale_factor` in `ctx.flags`.
- If absent, passthrough is treated as disabled for the call (returns `None`), preventing env-only leakage into tests.

6) Backoff and Sleep Modernization
- Deliverables
  - Central backoff utility (leverage `utils/retry.py`), with jitter and policy controls
  - Replace `time.sleep()` in loops with non-blocking waits where required (`asyncio.sleep` or scheduler)
- Actions
  - Audit occurrences; annotate context (threaded vs async vs CLI)
  - Swap to retry/backoff helper; or move periodic work to schedulers
- Acceptance criteria
  - 100% conversion in priority services; no blocking sleeps in async paths

7) Decompose Large Modules
- Deliverables
  - Extract cohesive helpers/services from the 6 hotspots
  - Add narrow contracts and unit tests for extracted pieces
- Actions
  - Identify seams: I/O boundaries, pure transforms, request adapters
  - Move logic to `services/` or `lib/`-style modules under `src/`
- Acceptance criteria
  - 30–50% size reduction per module; improved test coverage on extracted code

8) Deprecations and Legacy Removal
- Deliverables
  - Catalog of deprecated modules/paths (e.g., `utils/circuit_breaker.py`, `providers/kite_provider.py`, HTML-deprecated blocks in `web/dashboard/app.py`)
  - Removal or gating behind env flags with metrics to measure usage before removal
- Actions
  - Stage 1: Warn and collect usage metrics
  - Stage 2: Remove or tombstone with clear migration message
- Acceptance criteria
  - Deprecated code paths either removed or gated; no stray references remain

9) CI/Lint/Type/Test Gates
- Deliverables
  - “Core pytest” and “full pytest” tasks green in CI
  - Ruff (style + import + complexity rules) and mypy (targeted modules) in CI
  - Optional radon/xenon with lenient thresholds initially
- Actions
  - Add configs and tasks; fix top offenders iteratively
- Acceptance criteria
  - CI is stable; PRs gated on tests + lint; complexity budgets enforced gradually

### Lint gates configuration (2025-11-13)

- Added Ruff configuration at repo root: `.ruff.toml`
  - Line length 120, Python 3.12, rules enabled: E,F,W,I,B,UP,SIM
  - Excludes heavy/non-source directories (data, dashboards, models, results, build)
  - Per-file test ignores kept minimal; start lenient and tighten later
- VS Code tasks already available:
  - "Lint: Ruff check" — runs ruff check on src, scripts, tests
  - "Lint: Ruff fix" — applies safe autofixes
  - "Typecheck: mypy (src)" — optional targeted type checks
- Recommended flow for contributors:
  1) Run "Lint: Ruff check" locally and review suggestions
  2) Optionally run "Lint: Ruff fix" to auto-apply low-risk fixes
  3) Run "Pytest: Fast all (two-phase)" to validate
  4) Only after green, consider enabling stricter rules per-module

Update (2025-11-13): mypy baseline enabled
- mypy config present at repo root (`mypy.ini`) and aligned to Python 3.12
- Excludes legacy `src/utils/circuit_breaker.py` (deprecated path) to avoid parse errors
- Focus subset (dashboard core, utils, error_handling) is clean locally
- Use the task "Typecheck: mypy (src)" to run on the repo; for a quicker loop you can run:
  - dashboard core only: `python -m mypy src/web/dashboard/core`
  - utils + handler: `python -m mypy src/utils src/error_handling.py`

10) Observability Enhancements
- Deliverables
  - Metrics for key operations: CSV writes (attempts/retries/failures), web route latency/error labels, backoff counters
  - Dashboards panels augmented if needed
- Actions
  - Add Prometheus counters/histograms around writer and route handlers
- Acceptance criteria
  - Panels show error trends and latencies; alerts can be dialed in later

### Exception hygiene diagnostics and Grafana (2025-11-13)

This session wired centralized, low-noise error handling across high-traffic optional I/O paths and exposed a lightweight diagnostics surface for quick inspection and dashboards.

- Central handler reference
  - `src/error_handling.py` provides `get_error_handler()`, `ErrorCategory`, `ErrorSeverity`, and the structured `ErrorInfo` that downstream tools consume.

- Recent errors diagnostics API
  - Endpoint: `GET /api/errors/recent`
  - Query params:
    - `count` (int, 1..200): maximum records to return
    - `category` (optional): one of the names from `ErrorCategory`
    - `severity` (optional): one of the names from `ErrorSeverity`
  - Response shape:
    - JSON object `{ "count": N, "errors": [ErrorInfo, ...] }`
    - Use the `errors` array for table panels; `count` echoes the returned size (capped).
  - Local dev: start the Dashboard API on 9500 via the task "Dashboard API: Start on 9500 (reload)" or the multi-port task; the endpoint will be available at `http://127.0.0.1:9500/api/errors/recent`.

- Grafana panel (Infinity datasource)
  - Import the ready-made panel JSON: `dashboards/grafana/errors_recent_panel.json`.
  - Configure Infinity datasource mode to JSON and point the URL to `http://127.0.0.1:9500/api/errors/recent?count=50`.
  - Root selector / JSONPath: `$.errors` (since the API returns `{count, errors}`).
  - Suggested columns: `time`, `category`, `severity`, `message`, and a compact `context` subset (e.g., `path`, `index`, `file`).
  - Suggested refresh: 10–30s, no alerting by default (this panel is for situational awareness and hygiene verification).

- Quality gates (status): Build PASS, Lint/Typecheck N/A (no code changes), Tests PASS (core-only unchanged).

## Phased Timeline (Indicative)

- Phase 0 (Days 0–2): Enablement
  - Select interpreter; make `src/` importable; run core tests; capture baseline complexity report
- Phase 1 (Week 1): Quick Wins
  - Replace prints in web/storage/metrics with logger; remove a handful of blanket exceptions with targeted types
  - Start CSV writer design; agree contract and tests
- Phase 2 (Weeks 2–3): CSV and Exceptions
  - Implement unified CSV writer; migrate `csv_sink.py` and `csv_writer_helper.py`
  - Add retry/backoff utility usages; remove blocking sleeps in affected code
  - Continue trimming blanket exceptions in top modules
- Phase 3 (Weeks 4–5): Decomposition and Deprecations
  - Extract services from `routes/path_forecast/_router.py`, `ml.py`, `metrics.py`, `cycle.py`
  - Stage deprecations removal (warn, measure, remove)
- Phase 4 (Week 6+): Hardening and CI Gates
  - Add/raise lint and complexity thresholds; expand type coverage
  - Stabilize dashboards/alerts for error/backoff metrics

## Risks and Mitigations

- Risk: Behavior drift during CSV consolidation
  - Mitigation: Golden master tests and side-by-side write verification on a controlled subset
- Risk: Hidden reliance on deprecated paths
  - Mitigation: Instrument usage; keep temporary flags before removal
- Risk: Async vs thread contexts in sleep/backoff swaps
  - Mitigation: Audit context explicitly; add small adapters for sync/async

## Validation Plan

- Unit tests: happy path + retries + schema issues for CSV writer
- Integration tests: web route error propagation and structured logs; metrics exposure sanity checks
- CI tasks: run “Run pytest (core only, no-ML)” and full test tasks; add ruff and optional radon checks
- Dashboards: add panels for writer retries and route error rates; watch for regressions after rollouts

## Module Priorities (Initial)

1. `src/storage/csv_sink.py` (consolidate writer logic)
2. `src/web/dashboard/routes/path_forecast/` (decompose, logging, exceptions)
3. `src/web/dashboard/routes/ml.py` (decompose, logging)
4. `src/metrics/metrics.py` (logging, exception policy, decomposition)
5. `src/orchestrator/cycle.py` (sleep/backoff, logging, exceptions)
6. `src/collectors/unified_collectors.py` (side-effects cleanup, logging)

## Definition of Done per Stream

- CSV I/O: Single writer abstraction used by all storage modules; duplicate helpers retired; tests green
- Exceptions: Blanket `except Exception` largely eliminated in priority code; typed errors; structured logs
- Logging: No prints in priority modules; logger factory adopted consistently
- Sleeps: All blocking sleeps replaced where needed; backoff utility centralizes policy
- Decomposition: Module size reduced; extracted units tested; complexity budgets met
- Deprecations: Cataloged and removed/gated; no references left
- CI Gates: Tests + lint + basic complexity checks in CI; docs updated

## References

- Hotspot files by size (initial sample):
  - `src/web/dashboard/routes/path_forecast/_router.py`, `src/storage/csv_sink.py`, `src/web/dashboard/routes/ml.py`, `src/collectors/unified_collectors.py`, `src/metrics/metrics.py`, `src/orchestrator/cycle.py`
- Noted smells:
  - Broad exception handlers; print() usage; time.sleep(); duplicate CSV writing logic; pervasive open()
- Existing utilities to reuse:
  - `src/utils/output.py` (structured/atomic output), `src/utils/retry.py` (backoff), Prometheus metrics modules

- Efficiency must-haves (separate doc): see `EFFICIENCY_MUST_HAVES.md` for a ranked, high-impact optimization plan (provider pooling/batching, async scheduler with jitter/backpressure, delta-first processing, atomic batched CSV writes, per-phase latency metrics, adaptive cadence, and cardinality governance).

---

Ownership, sequencing, and scoping can be adjusted per sprint capacity. Start with Phase 0 immediately and gate each subsequent phase on tests staying green and metrics indicating stability.
