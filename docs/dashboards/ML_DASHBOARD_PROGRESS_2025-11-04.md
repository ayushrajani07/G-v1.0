# ML Dashboard Progress — 2025-11-04

This document summarizes the end-to-end work to make ML predictions visible and reliable in Grafana, along with key fixes and how to operate the setup.

## Highlights

- Fixed Infinity datasource base URL issue that broke absolute API URLs
- Hardened Dashboard API and data typing for Grafana ingestion
- Built two ML dashboards: a debug view and a minimal overlay
- Resolved Grafana matcher casing bug (byFrameRefID)
- Added styling and per-model series (HGB/XGB), plus LSTM model support
- Added a synthetic predictions feeder for off-hours testing

## Components and changes

### Dashboard API (/api/ml/predictions)
- Emits robust time fields:
  - `time` (ISO 8601) — primary for Grafana
  - `time_ms` (epoch milliseconds) — fallback/inspection
- Synthesizes/repairs time from `timestamp` when needed
- Preserves columns: `prediction`, `model`, `index`, `horizon`, `timestamp`
- Supports filters: `index`, `horizon`, `model`, and `tail`

### Grafana Dashboards

1) ML Predictions (debug) — `dashboards_modular/ml_predictions_debug.json` (uid `g6-ml-debug`)
- Top panel: per-model series (sk_hgb_regressor, xgb_regressor) with explicit colors, thicker lines, and points
- No-pivot panel: reference, simple transforms (convert → organize → sort → prepare)
- Raw CSV and Transformed tables: inspector panels to verify frames
- All models (static) panel: HGB, XGB, and torch_lstm_regressor together
- Fixes:
  - Matcher id corrected to `byFrameRefID` (was `byFrameRefId` → caused runtime error)
  - LSTM model id corrected to `torch_lstm_regressor`

2) ML Minimal: Index vs TP vs Model — `dashboards_modular/ml_minimal_predictions.json` (uid `g6-ml-minimal`)
- Overlays:
  - Index Price (dashed, left axis)
  - ATM Premium (bold, right axis)
  - Model predictions split into HGB and XGB with distinct colors/points
- Transform pipeline ensures:
  - `time`, `prediction`, `index_price`, `tp` typed correctly
  - Field organization and time sort for stable legends and series
- Legend simplified to one entry per series

### Styling and UX
- Consistent colors:
  - HGB: #00d1ff
  - XGB: #f2c744
  - LSTM: #a855f7
- Lines thickened (3px) and points enabled for sparse series visibility

## Synthetic predictions (off-hours)

Script: `scripts/ml/mock_predictions_feeder.py`
- Appends rows to `data/ml/live_predictions/<INDEX>.csv`
- Columns: `timestamp,prediction,model,index,horizon`
- Example usage (rotates HGB/XGB/LSTM every write):
  - Index: NIFTY, Horizon: 1, Interval: 30s

## Known gotchas & fixes

- Grafana error: `"byFrameRefId" not found` → Use `byFrameRefID` in field matcher overrides
- Time axis wrong or blank charts → Ensure `time` parsed as time, sort by `time`, and `prediction` numeric
- LSTM not visible → Use model id `torch_lstm_regressor` (not `torch_lstm`) and ensure rows exist
- Infinity Base URL → Leave Base URL empty for absolute URLs

## Operate

- Start Dashboard API with preferred ports (8003 → 9500 fallback)
- Reload Grafana dashboards via task: “Grafana: Reload Dashboard”
- Visit dashboards:
  - Debug: `/d/g6-ml-debug`
  - Minimal: `/d/g6-ml-minimal`
- Off-hours: run the mock feeder to keep points flowing

## Next steps

- Optional: parameterized “All models” panel driven by a multi-select variable
- Optional: add additional models/variations with consistent color assignments
- Optional: small table panel listing distinct models seen in last N rows
