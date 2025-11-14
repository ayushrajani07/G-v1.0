# Grid Eval: ANN Integration

This repo's grid evaluation pipeline now supports Approximate Nearest Neighbors (ANN) shortlisting directly.

What’s included:
- New CLI flags in `scripts/ml/path_forecast_grid_eval.py`:
  - `--use-ann` to enable ANN shortlist in retrieval and hybrid modes
  - `--ann-space` to choose the ANN metric space (`cosine`|`l2`), default is `cosine`
  - `--ann-max-candidates` to cap the number of ANN neighbors forwarded for exact scoring
  - `--ann-compare` to also run an exact (no-ANN) baseline and record latency speedup and q50 mean absolute difference (MAD)
  - `--ann-effect-tolerance` to enable an overall effectiveness score (see below); specifies the tolerated q50 MAD (in price units)
- Output columns in `eval.csv` include ANN config echo, diagnostics, and latency metrics.
- Summary CSVs group by ANN knobs to avoid mixing exact and ANN results and include averaged ANN diagnostics and latency metrics.
- The NS/All combiners (`combine_grid_eval_ns.py`, `combine_grid_eval.py`) were updated to respect ANN grouping as well.

## Quick start

Minimal one-shot run (Windows cmd):

```
set PYTHONPATH=%CD%
%CD%\.venv\Scripts\python.exe scripts\ml\path_forecast_grid_eval.py \
  --index NIFTY --expiry-tag this_week --offset 0 \
  --start 2025-11-06 --end 2025-11-06 \
  --horizons 60 --windows 60 --k 10 --modes retrieval \
  --bucket-ms 60000 --at end \
  --use-ann --ann-max-candidates 25 --ann-compare --ann-effect-tolerance 5 \
  --out results/grid/NIFTY/this_week/0/eval_ann.csv \
  --summary results/grid/NIFTY/this_week/0/summary_ann.csv
```

Discovery mode sweep:

```
set PYTHONPATH=%CD%
%CD%\.venv\Scripts\python.exe scripts\ml\path_forecast_grid_eval.py \
  --discover --indices NIFTY,BANKNIFTY --tags this_week --offsets 0 \
  --horizons 30,60 --windows 0,60,120,180 --k 10,15,20 --modes auto,hybrid,retrieval \
  --bucket-ms 60000 --at end \
  --use-ann --ann-space cosine --ann-max-candidates 50 --ann-compare --ann-effect-tolerance 5
```

After runs, you can still use the existing combiner scripts; they’ll keep ANN and non-ANN rows separate:

```
%CD%\.venv\Scripts\python.exe scripts\ml\combine_grid_eval.py
%CD%\.venv\Scripts\python.exe scripts\ml\combine_grid_eval_ns.py
```

## Columns added to eval.csv

- ann_use (0/1), ann_space, ann_max_candidates
- ann_enabled (0/1), ann_total_windows, ann_shortlisted
- latency_ms (ANN run), baseline_latency_ms (exact), ann_speedup (baseline/ANN), ann_q50_mad (|q50_ann - q50_exact| mean)
- ann_build_ms (time to build ANN index), ann_index_mem_bytes (approx Python/numpy footprint), ann_prune_ratio (shortlisted / total windows)
- ann_effectiveness (composite score; see formula below)

## Notes

- When `--ann-compare` is used, the baseline is executed immediately after the ANN run for the same combo; metrics are recorded in the same row.
- Summary CSVs now include ANN knobs in the grouping key and report average ANN diagnostics and latency.
- If you don’t pass `--use-ann`, the scripts behave like before (no ANN columns will be populated).
- Prune ratio close to 0 indicates heavy pruning (few candidates forwarded); close to 1 means little benefit from ANN shortlisting.
- Memory bytes is a heuristic (numpy array size or shallow hnswlib object size) and may under-report native index memory.

## Effectiveness score

To capture overall ANN payoff beyond raw latency, the pipeline can compute an effectiveness score when both ANN and an exact baseline are run and a tolerance is provided:

- Enable with CLI: `--ann-effect-tolerance <T>` where T is the tolerated q50 MAD in price units.
- Per-row column: `ann_effectiveness`
- In summary CSVs (both grid summary and combiners): `ann_effectiveness_avg`

Formula:

- Speedup: `ann_speedup = baseline_latency_ms / latency_ms`
- Pruning gain: `prune_gain = 1 - ann_prune_ratio` (in [0,1])
- Quality factor: `quality = 1 - clamp(ann_q50_mad / T, 0, 1)`
- Effectiveness: `ann_effectiveness = ann_speedup * prune_gain * quality`

Interpretation:

- Higher is better. It rewards faster runs (speedup), stronger pruning (lower shortlisted/total), and penalizes divergence from the exact q50 path beyond the allowed tolerance.
- If `ann_q50_mad` is small relative to T, the quality term stays near 1. If it exceeds T, the quality term drops toward 0.

Choosing a tolerance:

- Start with a small multiple of your typical 1-minute tick size, or a quantile (e.g., 75th percentile) of observed `ann_q50_mad` in your environment.
- For broader bands or noisier instruments, increase T to avoid over-penalizing harmless deviations.

When it’s computed:

- Requires `--use-ann` and `--ann-compare` (to have baseline), and `--ann-effect-tolerance`.
- If any ingredient is missing (no baseline, no prune ratio, or no tolerance), `ann_effectiveness` is omitted for that row.

Aggregations:

- The grid summary and both combiner scripts include `ann_effectiveness_avg` so you can compare configs by a single scalar.
