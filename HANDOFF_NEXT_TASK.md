# Handoff: Next Task (Post path_forecast refactor)

Date: 2026-02-05
Branch: `restore/pre_phase3_1`

## Context
- `src/web/dashboard/routes/path_forecast.py` legacy monolith has been decomposed into the package `src/web/dashboard/routes/path_forecast/`.
- Tests are green (full serial + quick runs).
- Docs updated to reflect the new package layout and implemented endpoints.

## Objective (next)
Continue the originally intended *Phase 0/1* objectives around correctness + maintainability of the path forecast router, specifically:

1) Ensure API contract stability and remove any remaining stale references to the removed monolith.
2) Consolidate any remaining duplicated request parsing / archive reading patterns across handler modules.
3) Improve observability/diagnostics consistency across endpoints (headers + meta fields).

If the “initially defined objectives” refer to a different scope, adjust this section accordingly.

## High-value targets
### A) Endpoint docs vs implementation drift
- Confirm that docs match actual endpoints in `src/web/dashboard/routes/path_forecast/_router.py`.
- Ensure no stale `/api/ml/path_forecast` references remain (that endpoint is not implemented in this repo state).

### B) Handler consolidation (reduce copy/paste)
Look for repeated patterns across these modules:
- `src/web/dashboard/routes/path_forecast/_prediction_history_handler.py`
- `src/web/dashboard/routes/path_forecast/_stats_handler.py`
- `src/web/dashboard/routes/path_forecast/_coverage_history_handler.py`
- `src/web/dashboard/routes/path_forecast/_diagnostics_handler.py`

Common seams worth extracting:
- bands archive row iteration + horizon filtering
- quantile column detection + parsing
- “now/cutoff/window” computation and bucketing

### C) Observability consistency
- Align response shapes and error behavior for “missing live_csv / missing archive” scenarios.
- Ensure headers/diagnostic fields are consistent between:
  - `/api/ml/path_forecast_json`
  - `/api/ml/path_forecast_meta`
  - `/api/ml/path_diagnostics`, `/api/ml/path_stats`

## Suggested work plan
1) Search for any remaining monolith references:
   - `path_forecast.py` references in docs/scripts/tests.
2) Identify 2–3 duplicated helper patterns in the handler modules and extract into a shared helper module under:
   - `src/web/dashboard/routes/path_forecast/_bands_archive.py` (already exists) or a new `*_util.py` within the package.
3) Add/adjust unit tests for extracted helpers (keep them pure).

## Commands
- Full tests: `python -m pytest -v --tb=short`
- Quick tests: `python -m pytest -q --tb=no`

VS Code tasks available:
- `Pytest: Serial (Default)`
- `Pytest: Quick (No Output)`

## Acceptance checks
- `Pytest: Serial (Default)` passes.
- No new API route regressions (at least `tests/test_path_forecast_meta_e2e.py` + web route tests pass).
- No docs referencing `/api/ml/path_forecast` unless explicitly labeled “proposed/legacy”.

## Notes / Known constraints
- Some docs are intentionally historical; prefer annotating with “legacy at the time” rather than deleting.
- Do not expand scope into unrelated subsystems (storage/metrics/orchestrator) unless a direct dependency blocks work.
