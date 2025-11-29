# Phase 12 Implementation Plan (In-Progress)

## Delivered So Far
- Drift attribution persistence (`src/ml/drift_persist.py`) auto-appends CSV.
- Tail burn acceleration metric + alerts.
- Retrain trigger script (`src/ml/retrain_trigger.py`).
- Canary evaluation harness (`src/ml/canary_eval.py`).
- Config versioning history & diff endpoint (`/api/ml/ensemble/config_diff`).

## Pending
1. CI load runner integration job.
2. Dashboard updates (add acceleration + persistence insights).
3. Phase 12 final documentation.

## CI Load Runner Integration (Planned)
- Add script wrapper: `scripts/ci_load_check.py` invoking `load_runner.py` stress scenario.
- Parse JSON latency p95; fail if > target (e.g. 1200ms) or error_rate > 1%.
- Integrate in workflow (GitHub Actions job) `performance-smoke`.

## Dashboard Updates (Planned)
- Add Tail Burn Accel panel (metric `g6_ml_residual_tail_burn:accel`).
- Add retrain signals history sparkline from persisted CSV (last N points).
- Provide config diff summary panel (latest diff counts).

## Documentation Finalization
- Consolidate triggers & operational runbook for retrain.
- Add canary evaluation guidelines (minimum improvement threshold, sample size).
- Note CSV rotation procedure.

## Threshold Suggestions
- Tail burn accel warning: >0.04 sustained 10m.
- Tail burn accel critical: >0.08 sustained 5m.
- Retrain recommendation: smoothed signal >=2 average over 3 samples.
- Retrain mandatory: smoothed signal >=2.5 average over 3 samples.

## Next Steps
- Implement CI wrapper script.
- Commit and add usage docs section.
- Update dashboard spec (Phase 11 file) with new panels.
