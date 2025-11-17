# Issue: Implement `detail=full` Forecast Response

## Summary
Add a rich mode to `/api/ml/ensemble/forecast` when `detail=full` (or `detail=paths`) returning a time grid and per-quantile paths in addition to snapshot fields. Preserve backward compatibility of default (snapshot) response.

## Motivation
Downstream consumers need multi-horizon trajectory curves (not just p10/p50/p90 at first bucket). Enables visualization, comparing path shapes, and computing derivatives/volatility.

## Scope
Backend (FastAPI router), tests, docs, minor Grafana panel update (optional), schema versioning note.

## Requirements
- Query parameter: `detail=full` triggers rich response.
- Response additions:
  - `time_grid`: array of epoch ms OR object `{start,end,resolution_ms,values:[...]}` (choose simplest consistent structure).
  - `quantile_paths`: object mapping canonical quantile names (p10/p50/p90 and any user-specified quantiles) to arrays of floats, same length as `time_grid`.
- Retain existing `forecast` snapshot block (p10/p50/p90 + band_low/high) for continuity.
- Ensure quantile arrays align with horizon resolution (e.g., 1‑minute or bucket config).
- Zero/empty sequences handled gracefully (return empty array, not null).

## Non-Goals
- Persisting paths to storage.
- Streaming interface.
- Changing default snapshot schema.

## Implementation Outline
1. Extend router logic after `fore.forecast_path(...)` to build `time_grid` from returned `times`.
2. Convert quantile keys (float) to stable labels: if 0.1→`p10`, etc.; keep original float as secondary map if needed.
3. Add serialization helper for building full detail block.
4. Gate addition behind `detail == 'full'` param.
5. Unit tests: snapshot mode unchanged; full mode includes arrays of correct lengths; invalid `detail` falls back to snapshot.
6. Update `docs/ml/ENSEMBLE_API.md` with new schema section + example.
7. Optional: add Grafana panel for path preview (deferred if out of scope).

## Acceptance Criteria
- Default call (no `detail`) identical to prior release.
- `detail=full` response has: `time_grid` length >= 2, `quantile_paths` arrays same length, snapshot fields still present.
- Tests asserting structure + absence of breaking fields pass.
- Docs updated and merged (no conflict markers).

## Test Plan
- Unit: call forecast with and without `detail=full` for 2 horizons (e.g., 30, 60) and verify lengths.
- Regression: ensure JSON snapshot diff for default remains stable.
- Edge: horizon=1 produces length=1 or 2 based on bucket; document behavior.

## Risks & Mitigation
| Risk | Mitigation |
|------|------------|
| Large arrays increase response size | Cap resolution (bucket_ms) or limit horizon; document expected sizes |
| Floating quantile keys cause inconsistent JSON | Normalize to `pXX` keys |
| Downstream consumers break due to new fields | Snapshot block retained; add versioning note |

## Deliverables
- Code changes in `src/web/dashboard/routes/ensemble.py`
- Tests: `tests/test_ensemble_api_full_detail.py`
- Doc update: `docs/ml/ENSEMBLE_API.md`
- Changelog entry: `PHASE9_CHANGELOG.md`

## Done Definition
All tests green; docs merged; new mode exercised manually returning plausible arrays.
