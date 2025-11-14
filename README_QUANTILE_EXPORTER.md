# Quantile TP Forecast Exporter

This document describes how to train and run the quantile regression exporter that produces p10/p50/p90 predictions for ATM Total Premium (TP).

## 1. Train the Quantile Model

Prerequisites:
- Training CSV prepared at `data/ml/training/nifty_tp_train.csv` (must contain target column `tp` and listed features).
- Config file: `configs/ml/nifty_tp_forecast_skgbr_quantile.json`.

Training options:
- Use the VS Code task "ML: Train Quantile TP Model (NIFTY)" — it will prompt you for the training CSV path.
- Or run the script directly if you prefer.
Outputs:
- `models/nifty_tp_forecast_skgbr_quantile.joblib` (all quantile models bundled)
- `models/nifty_tp_forecast_skgbr_quantile.fe.json` (feature sidecar)

## 2. Start Live Exporter

After training, start continuous exporter (task added in `.vscode/tasks.json`):
- Task label: `ML: Start Quantile Prediction Exporter (continuous)`

The exporter appends rows to `data/ml/live_predictions/NIFTY.csv` with columns:
```
timestamp,prediction,model,index,horizon,p10,p50,p90
```
`prediction` equals `p50` (median forecast).

## 3. Grafana Integration

1. Point existing Infinity data source panel to updated CSV.
2. Add new series for `p10` and `p90`.
3. Configure panel transformation to compute band fill (e.g., use `p10` as lower, `p90` as upper with area style fill).
4. Optionally overlay previous point model for comparison.

## 4. API Consumption

If `/api/ml/predictions` already serves the CSV, the additional columns will appear automatically; clients ignoring them remain unaffected.

## 5. Monitoring & Next Steps

### Prometheus Metrics (implemented)

If you pass `--port <PORT>`, the exporter starts a Prometheus metrics HTTP server and emits:

- `g6_ml_prediction_p10{index,horizon,model}` — lower quantile
- `g6_ml_prediction_p50{index,horizon,model}` — median
- `g6_ml_prediction_p90{index,horizon,model}` — upper quantile
- `g6_ml_conformal_radius{index,horizon,model}` — rolling conformal radius for target coverage
- `g6_ml_conformal_coverage_estimate{index,horizon,model}` — realized coverage over the rolling window for the current radius

Ensure Prometheus is scraping the selected port (see `prometheus.yml`, job `g6_ml`, default example includes `127.0.0.1:9208`).

Example scrape job (append under `scrape_configs` in `prometheus.yml`):

```
  - job_name: g6_ml
    scrape_interval: 15s
    static_configs:
      - targets: ["127.0.0.1:9208"]
```

### Exporter Flags (new)

- `--port INT` — Start a Prometheus server on the given port and publish metrics.
- `--coverage FLOAT` — Target coverage for conformal radius (default `0.8`, clamped to `0.5..0.99`).
- `--band-window INT` — Rolling residual window size in samples (default `600`).
- `--residual-store PATH` — Optional CSV file to persist residual history; preloaded at startup to preserve conformal state across restarts.

Conformal radius is computed from the empirical quantile of recent absolute residuals `|p50 - actual_tp|` using the specified coverage and window.
Coverage estimate is computed as the fraction of residuals within the current radius over the rolling window.

### Grafana Quick Open

- Reload dashboards: use task `Grafana: Reload + Open` (provisions dashboards and opens Grafana).
- Open conformal metrics directly: task `Grafana: Open Conformal Metrics Dashboard` (defaults to `http://127.0.0.1:3002/d/ml-conformal-metrics`).

### Next Steps

- Use diagnostics endpoint with conformal mode to compare empirical coverage.
- Extend champion selection to incorporate average pinball loss for quantile models.
- Leverage recording rules (see `prometheus_rules_ml.yml`):
	- `ml:conformal:coverage_avg_5m` / `ml:conformal:coverage_avg_15m` average coverage windows.
	- `ml:conformal:band_width` derived width (2 * radius).
	- `ml:conformal:under_coverage_15m` magnitude of shortfall vs target (0.8).
- Alerts:
	- `MLConformalUnderCoverage15m` (warning) if 15m avg coverage < 0.75 for 10m.
	- `MLConformalPersistentUnderCoverage` (critical) if 15m avg coverage < 0.70 for 30m.

---
_Last updated: 2025-11-10_
