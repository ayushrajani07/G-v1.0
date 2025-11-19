# ANN Large-Slice Harness Guide

This guide explains how to run the ANN benchmarking harness and interpret the outputs.

## What it does

- Iterates index/expiry-tag/offset and (window, horizon, k) combinations over a historical date range.
- Runs `scripts/ml/path_forecast_grid_eval.py` with ANN enabled (`--use-ann --ann-compare`) and captures:
  - ann_speedup, ann_prune_ratio, ann_q50_mad, ann_build_ms, latency vs baseline
- Aggregates all rows to produce:
  - `results/ann_large/combined/ann_summary.csv` (all rows with key diagnostics)
  - `results/ann_large/combined/ann_summary.json` (global stats + recommendations)
  - `results/ann_large/combined/ann_ranking.csv` (per-combo ranking with a blended score; tunable weights)

## Quick start (PowerShell)

- Ensure the virtual environment is active and data is available for the chosen indices/date range.
- Example run (Windows):

  Optional: set `PYTHONPATH` to the repo root so Python can resolve in-repo modules.

  The harness sets `PYTHONPATH` automatically when invoking the eval script; you typically don't need to export it.

- Minimal example:

  - Indices: `NIFTY,BANKNIFTY,SENSEX`
  - Tag: `this_week`
  - Offsets: `0`
  - Date range: `2025-10-01..2025-11-06`
  - Window/Horizon/K: `60/60/15`
  - Modes: `retrieval` (default) or `auto,hybrid`

  Inside the repo folder:

  - Run via the harness directly (replace paths if needed):
    - `scripts/ml/ann_harness_large.py --indices NIFTY,BANKNIFTY,SENSEX --tags this_week --offsets 0 --start 2025-10-01 --end 2025-11-06 --windows 60 --horizons 60 --k 15 --ann-max-candidates 50 --modes retrieval,auto,hybrid --out-root results/ann_large --metrics-minimal`

  Or use your Python from `.venv`:
    - `.venv/Scripts/python.exe scripts/ml/ann_harness_large.py --indices NIFTY,BANKNIFTY,SENSEX --tags this_week --offsets 0 --start 2025-10-01 --end 2025-11-06 --windows 60 --horizons 60 --k 15 --ann-max-candidates 50 --modes retrieval,auto,hybrid --out-root results/ann_large --metrics-minimal`

Notes:
- For heavier runs, drop `--metrics-minimal` to compute full metrics, but expect longer runtimes.
- Use `--continue-on-error` to skip over missing data dates or transient errors.

## Modes

- `retrieval`: Use the current retrieval forecaster (baseline path-forecasting mode).
- `auto`: Allow the grid eval script to choose a suitable forecaster or parameters automatically (if supported by the script).
- `hybrid`: Blend retrieval with additional logic (if supported by the script).

The harness passes the requested mode(s) through `--modes <mode>` to `path_forecast_grid_eval.py`. Rows are annotated with a `mode` column so you can filter and compare per mode.

## Outputs

- Raw per-combo CSVs under `results/ann_large/raw/` with file names that include the mode:
  - `<INDEX>_<TAG>_<OFFSET>_<WIN>w_<HOR>h_k<K>_<MODE>.csv`
- Combined summary:
  - `results/ann_large/combined/ann_summary.csv`
  - `results/ann_large/combined/ann_summary.json`
- Ranking (per-combo):
  - `results/ann_large/combined/ann_ranking.csv`

## Ranking score

Each combo is summarized across all its rows and assigned a blended score (weights configurable):

- Default: `score = w_speedup*speedup_avg * (1 + w_prune*(1 - prune_ratio_avg)) - w_mad*q50_mad_avg - w_latency*latency_ms_avg`
  - Rewards speedup and pruning (lower prune ratio → higher gain)
  - Penalizes forecast deviation (q50_mad) and absolute latency
  - Tune via CLI: `--rank-w-speedup`, `--rank-w-prune`, `--rank-w-mad`, `--rank-w-latency`

Fields included per combo:
- index, expiry_tag, offset, horizon, window, k, mode
- rows, speedup_avg, prune_ratio_avg, q50_mad_avg
- latency_ms_avg, baseline_latency_ms_avg
- score (higher is better)

Use this CSV to quickly identify promising parameter sets and modes for further tuning.

## Interpreting results

- Prune ratio:
  - ~1.0 means no effective pruning (ANN shortlist equals total windows); increase historical corpus or reduce `ann_max_candidates`.
  - Target < 0.7 for meaningful pruning.
- Speedup:
  - < 1.0 indicates regressions; ≥ 1.5 starts to be meaningful.
  - Speedup often improves as the candidate corpus grows.
- q50 MAD:
  - Measures median absolute deviation between ANN and exact forecast in the core. Aim for values near 0.0.
  - If it rises, increase `ann_max_candidates` or try `--distance-metric cosine`.
- Build time:
  - If > 1s, consider persisting indices or reducing total windows per eval chunk.

### Candidate ladder (from recent runs)

Empirical results (date range ~696 rows across modes) for `ann_max_candidates`:

- 50 candidates: prune_ratio ≈ 1.00, speedup ≈ 0.93, q50_mad ≈ 0.00
- 30 candidates: prune_ratio ≈ 1.00, speedup ≈ 0.92, q50_mad ≈ 0.00
- 10 candidates: prune_ratio ≈ 0.48, speedup ≈ 0.93, q50_mad ≈ 0.65 overall
  - By mode at 10 candidates:
    - retrieval: q50_mad ≈ 0.05 (minimal quality loss)
    - auto/hybrid: q50_mad ≈ 0.95 (noticeable degradation)

Recommended ladder:
- Start at 50. If prune_ratio ~1.0, step down to 30.
- If still ~1.0, test 20 (not yet run) before jumping to 10.
- At 10, prefer `retrieval` mode unless quality guardrails are added to `auto/hybrid`.
- Consider expanding corpus (more dates/offsets) to unlock pruning without aggressive candidate cuts.

### New automation features

The harness now supports:

1. Candidate ladder automation:
  - Use `--ann-candidate-ladder 50,30,20,10` to run sequential evaluations.
  - Each candidate value writes its own directory: `<out_root>_<CANDIDATE>/combined/ann_summary.json`.
  - A consolidated CSV is written to `<out_root>/combined/ann_candidate_ladder_comparison.csv`.

2. Per-mode candidate overrides:
  - Pass `--ann-max-candidates-per-mode retrieval=10,auto=30,hybrid=30` to apply different shortlist sizes per mode.
  - Rows echo the effective `ann_max_candidates` used so you can verify overrides.

3. MAD quality guardrail:
  - Add `--ann-mad-guard <threshold>` to automatically fall back to the exact baseline path when ANN q50 MAD exceeds the threshold.
  - Requires the baseline comparison; the harness injects `--ann-compare` when guard is active.
  - Output columns: `ann_guard_triggered` (0/1) and `ann_guard_original_mad` (pre-fallback MAD).

Example (combined features):

```
python scripts/ml/ann_harness_large.py \
  --indices NIFTY,BANKNIFTY,SENSEX --tags this_week --offsets 0 \
  --start 2025-10-01 --end 2025-11-06 \
  --windows 60 --horizons 60 --k 15 \
  --modes retrieval,auto,hybrid \
  --ann-candidate-ladder 50,30,20,10 \
  --ann-max-candidates-per-mode retrieval=10,auto=30,hybrid=30 \
  --ann-mad-guard 0.5 \
  --out-root results/ann_large_adv --metrics-minimal
```

Interpretation tips with guardrail:
- If `ann_guard_triggered=1`, the final forecast path is exact (MAD neutralized) while preserving latency measurement.
- High trigger frequency for a mode suggests raising its per-mode candidate count.

4. Auto-tuner integration (optional):
  - After a ladder run, add `--auto-tune --auto-tune-target-mad 0.1 --auto-tune-min-prune 0.05`.
  - The harness will run `ann_auto_tune_candidates.py` on the generated
    `combined/ann_candidate_ladder_comparison.csv` and write a suggestion to
    `combined/ann_auto_tune.json` along with a CLI snippet in the console output.
  - Use the suggested `--ann-max-candidates-per-mode retrieval=X,auto=Y,hybrid=Z` for subsequent runs.

### Effectiveness score and per-mode defaults

To quickly compare candidate counts, compute an effectiveness score:

- effectiveness_score = speedup_avg * (1 - prune_ratio_avg) - q50_mad_avg
- Higher is better (rewards pruning + speed, penalizes MAD drift)

Recommended per-mode defaults for light pruning based on normalized runs:
- retrieval: 10
- auto: 20
- hybrid: 20

These generally maintain low MAD while producing some pruning; enable `--ann-mad-guard` for auto/hybrid when experimenting below these values.

## Tips

- Expand the date range or include more offsets to increase the candidate corpus. ANN benefits grow with scale.
- Experiment with `--ann-max-candidates` (e.g., 20, 30, 50) for a speed/quality trade-off.
- Try different modes: `retrieval,auto,hybrid` and compare in `ann_ranking.csv`.
- For stable comparisons during work hours, use `--metrics-minimal` for faster iterations.

### Caching (in-process)

- The retrieval forecaster now caches the ANN index in-process per (index, tag, offset, window, samples_today, space, dim, day_files) key.
- This avoids rebuilding the index for multiple combos on the same date in one run and reduces `ann_build_ms` significantly.
- To disable this cache (for benchmarking build time), set the environment variable `G6_DISABLE_ANN_CACHE=1` before running.

## Troubleshooting

- No rows collected: Verify the date range overlaps available data for the given index/tag/offset.
- Unexpectedly low speedup with prune_ratio ~1.0: Ensure the corpus per day is sufficiently large; ANN pruning needs volume.
- High q50 MAD: Increase candidates or adjust distance metric.
