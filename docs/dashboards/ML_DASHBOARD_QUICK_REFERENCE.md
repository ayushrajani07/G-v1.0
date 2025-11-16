# ML Dashboards — Quick Reference

Fast, skimmable notes for operating the two ML dashboards. Keep this beside your browser while testing.

---

## Dashboard Index

- ML Predictions (debug)
  - UID: `g6-ml-debug`
  - URL: `http://127.0.0.1:3002/d/g6-ml-debug`
  - File: `dashboards_modular/ml_predictions_debug.json`
  - Refresh: 15s (panel default)
  - Time: Last 12h (dashboard default)

- ML Minimal: Index vs TP vs Model
  - UID: `g6-ml-minimal`
  - URL: `http://127.0.0.1:3002/d/g6-ml-minimal`
  - File: `dashboards_modular/ml_minimal_predictions.json`
  - Refresh: 15s
  - Time: Last 6h

---

## Datasources & API

- Infinity datasource: Base URL must be empty
- Dashboard API must listen on 8003 (preferred) or 9500 fallback
  - Endpoints used:
    - `/api/ml/predictions` (CSV)
    - `/api/live_csv` (JSON)
- Time fields provided by API
  - `time` (ISO 8601) — primary for Grafana
  - `time_ms` (epoch ms) — fallback/inspection

---

## Variables

- Debug (`g6-ml-debug`)
  - `index`: NIFTY | BANKNIFTY | SENSEX | FINNIFTY
  - `tail`: 50 | 200 | 500 | 1200 | 2000
  - `models` (static): sk_hgb_regressor, xgb_regressor, torch_lstm_regressor (for future filtering)

- Minimal (`g6-ml-minimal`)
  - `index`: NIFTY | BANKNIFTY | SENSEX | FINNIFTY
  - `offset`: 0, ±100, ±200, ±300
  - `expiry`: this_week | next_week | this_month | next_month
  - `horizon`: 1 | 2 | 4 | 8

---

## Panels at a glance

- Debug: ML Predictions (top)
  - Targets (Infinity CSV):
    - HGB: `.../api/ml/predictions?index=${index}&tail=${tail}&model=sk_hgb_regressor`
    - XGB: `.../api/ml/predictions?index=${index}&tail=${tail}&model=xgb_regressor`
  - Transforms: convertFieldType (time, prediction) → organize (time,prediction) → sortBy(time asc) → prepareTimeSeries
  - Styling: HGB `#00d1ff`, XGB `#f2c744`, lineWidth=3, points on

- Debug: Predictions (no pivot)
  - Target: `.../api/ml/predictions?index=${index}&tail=${tail}`
  - Same transforms; used as a baseline sanity check

- Debug: All models (static)
  - Targets: HGB, XGB, LSTM (torch_lstm_regressor)
  - Same transforms; LSTM color `#a855f7`

- Minimal: Index vs TP vs Model
  - Targets:
    - LiveCSV (JSON): `.../api/live_csv?index=${index}&expiry_tag=${expiry}&offset=${offset}&include_vol=false&include_oi=false&include_pcr=false`
    - HGB: `.../api/ml/predictions?index=${index}&horizon=${horizon}&tail=1200&model=sk_hgb_regressor`
    - XGB: `.../api/ml/predictions?index=${index}&horizon=${horizon}&tail=1200&model=xgb_regressor`
  - Transforms: convert (time,prediction,index_price,tp) → rename (Index Price, ATM Premium) → include/order → sortBy(time) → prepareTimeSeries
  - Styling:
    - Index Price: dashed, left axis
    - ATM Premium: bold, right axis (label: Premium)
    - HGB/XGB: colored lines with points

---

## Color map

- sk_hgb_regressor: `#00d1ff`
- xgb_regressor: `#f2c744`
- torch_lstm_regressor: `#a855f7`

---

## Common operations

- Reload dashboards: VS Code task “Grafana: Reload Dashboard”
- Start Dashboard API: task “Dashboard API: Start (auto-port + reload)” (prefers 8003)
- Off-hours data: task “ML: Start Mock Predictions (HGB+XGB+LSTM)” to rotate synthetic points

---

## Troubleshooting quickies

- Error: `"byFrameRefId" not found` → Use matcher id `byFrameRefID` in overrides
- Blank charts or x-axis says "Premium": ensure `time` is parsed as time and sort by `time`; convert `index_price`, `tp`, and `prediction` to numbers
- LSTM not visible: model id must be `torch_lstm_regressor`; verify rows exist in the Raw CSV table
- Infinity URL issues: keep Base URL empty when using absolute API URLs

---

## Where to edit

- Dashboards: `dashboards_modular/*.json`
- API route: `src/web/dashboard/routes/ml.py`
- Mock feeder: `scripts/ml/mock_predictions_feeder.py`

