# Path forecasting (new ML direction)

This repo has pivoted to a path-forecasting design focused on intraday tp (ATM premium) trajectories. The old single‑step tabular ML stack (HGB/XGB/MLP/LSTM) is deprecated and removed. This document explains the new goal, interfaces, and where the code lives now.

- Objective: At market open, emit a full-day minute-level forecast path of tp up to close. Every minute, recompute the remaining path conditioned on the latest observations and market context. Provide uncertainty bands (P10/P50/P90).
- Approach: A hybrid system (transformer prior for day-shape + retrieval-augmented residual updates) with a light, CPU-friendly live loop.

## New code layout

- Core interfaces: `src/path_forecast/`
  - `interfaces.py` — `PathForecaster` protocol (forecast_path contract)
  - `hybrid.py` — Minimal stub `HybridPathForecaster` (flat path + bands) to keep the API alive while we implement the full hybrid model
- Dashboard API:
  - `src/web/dashboard/routes/path_forecast.py` — `/api/ml/path_forecast` endpoint returning CSV in wide or long format

Note: Legacy ML modules (`src/ml_arm`, `scripts/ml`, `configs/ml`) and their docs have been removed. Any old VS Code tasks pointing to those scripts are obsolete.

## Data flow (runtime)

1) Live market CSVs: `data/g6_data/<INDEX>/<expiry_tag>/<offset>/*.csv`
2) Path forecaster ingests last W minutes + context; returns timeseries for the remaining session (quantiles included)
3) Dashboard Infinity panel queries `/api/ml/path_forecast` to render the P10/P50/P90 bands

Sketch:

  live_csv  ->  path forecaster (stub today) -> /api/ml/path_forecast (CSV)

## Endpoint

- `/api/ml/path_forecast?index=NIFTY&horizon_minutes=390&quantiles=0.1,0.5,0.9&format=wide`
  - wide: `time,q10,q50,q90`
  - long: `time,quantile,value`

Current behavior: The endpoint returns a flat path at the last observed tp with ±5% bands (stub). This is intentional while we implement the retrieval + transformer components.

## Next steps

See `docs/ML_PATH_FORECAST_STRATEGY.md` for the full plan. Immediate tasks:
- Phase 0: Retrieval-only baseline (ANN over historical windows, FE v2 stats embedding)
- Phase 1: Learned encoder + residual head
- Phase 2: Transformer prior (PatchTST/TFT) fused with retrieval via a gate

## Notes

- Old endpoints under `routes/ml.py` remain available for non-path diagnostics, but are deprecated and will be removed after the path panels land.
- Any `models/` artifacts from the previous stack are considered data leftovers and not used by the new pipeline.
