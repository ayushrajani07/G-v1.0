# Path forecasting (new ML direction)

This repo has pivoted to a path-forecasting design focused on intraday tp (ATM premium) trajectories. The old single‑step tabular ML stack (HGB/XGB/MLP/LSTM) is deprecated and removed. This document explains the new goal, interfaces, and where the code lives now.

- Objective: At market open, emit a full-day minute-level forecast path of tp up to close. Every minute, recompute the remaining path conditioned on the latest observations and market context. Provide uncertainty bands (P10/P50/P90).
- Approach: A hybrid system (transformer prior for day-shape + retrieval-augmented residual updates) with a light, CPU-friendly live loop.

## New code layout

- Core interfaces: `src/path_forecast/`
  - `interfaces.py` — `PathForecaster` protocol (forecast_path contract)
  - `hybrid.py` — Minimal stub `HybridPathForecaster` (flat path + bands) to keep the API alive while we implement the full hybrid model
- Dashboard API:
  - `src/web/dashboard/routes/path_forecast/` — path forecast API router package
    - Primary ribbon: `/api/ml/path_forecast_json` (JSON array for Grafana Infinity)
    - Metadata: `/api/ml/path_forecast_meta`
    - Diagnostics/stats: `/api/ml/path_diagnostics`, `/api/ml/path_stats`, `/api/ml/path_advisor`
    - Advisor flags (alerting-friendly): `/api/ml/path_advisor_flags`
    - History exports: `/api/ml/path_prediction_history` and `/api/ml/path_prediction_history_csv`
    - Realized TP series: `/api/ml/live_tp_series` (alias: `/api/ml/tp_series`)
    - Coverage history exports: `/api/ml/path_coverage_history` and `/api/ml/path_coverage_history_csv`
    - Calibration: `/api/ml/path_calibrate_now`, `/api/ml/path_calibrate` (POST), `/api/ml/path_calibration_history`
    - Grafana convenience redirect: `/api/ml/reset_defaults`

Note: Legacy ML modules (`src/ml_arm`, `scripts/ml`, `configs/ml`) and their docs have been removed. Any old VS Code tasks pointing to those scripts are obsolete.

## Data flow (runtime)

1) Live market CSVs: `data/g6_data/<INDEX>/<expiry_tag>/<offset>/*.csv`
2) Path forecaster ingests last W minutes + context; returns timeseries for the remaining session (quantiles included)
3) Dashboard Infinity panel queries `/api/ml/path_forecast_json` to render the P10/P50/P90 bands

Sketch:

  live_csv  ->  path forecaster -> /api/ml/path_forecast_json (JSON)

## Endpoint

- `/api/ml/path_forecast_json?index=NIFTY&horizon_minutes=390&mode=auto&calibrate=true`
  - Response: JSON array of rows with `plot_time` (UTC ISO Z), `plot_ms`, `q10`, `q50`, `q90` (and a best-effort `tp` overlay when available).
  - Use `plot_time` as the Grafana time field.

Current behavior: the endpoint is robust to missing/early-session data. When retrieval cannot run, it falls back to a safe stub (so dashboards stay live), and may widen a degenerate ribbon for visibility.

## Next steps

See `docs/ML_PATH_FORECAST_STRATEGY.md` for the full plan. Immediate tasks:
- Phase 0: Retrieval-only baseline (ANN over historical windows, FE v2 stats embedding)
- Phase 1: Learned encoder + residual head
- Phase 2: Transformer prior (PatchTST/TFT) fused with retrieval via a gate

## Notes

- Old endpoints under `routes/ml.py` remain available for non-path diagnostics, but are deprecated and will be removed after the path panels land.
- Any `models/` artifacts from the previous stack are considered data leftovers and not used by the new pipeline.
