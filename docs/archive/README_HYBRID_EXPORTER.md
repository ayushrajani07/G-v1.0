# Hybrid TP Residual Exporter

This document explains how to train and run the hybrid baseline + residual exporter for ATM Total Premium (TP).

## 1. Concept

Hybrid prediction decomposes TP into:
- Structural baseline: `baseline_tp = k * underlying * iv * sqrt(T)` (see `src/analytics/ml/baseline.py`).
- Residual ML component: model learns `tp_actual - baseline_tp` from tabular features.
Final prediction: `hybrid = baseline_tp + residual_pred`.

Benefits:
- Improved extrapolation across expiries & volatility regimes.
- Transparent split between structural drivers and learned adjustments.

## 2. Train Residual Model

Use task: `ML: Train Hybrid Residual TP Model (NIFTY)`.
Prompts for training CSV path (must contain: `tp,index_price,ce_iv,pe_iv,minutes_to_expiry` + features in config).
Outputs:
- `models/nifty_tp_forecast_hybrid_residual.joblib` — artifact with model + metadata.
- `models/nifty_tp_forecast_hybrid_residual.fe.json` — feature sidecar.

Config: `configs/ml/nifty_tp_forecast_hybrid_residual.json` controls baseline params and model hyperparameters.

## 3. Start Hybrid Exporter

Task: `ML: Start Hybrid Prediction Exporter (continuous)`.
Writes rows to `data/ml/live_predictions/NIFTY_hybrid.csv`:
```
timestamp,prediction,baseline,residual,model,index,horizon
```
`prediction` = `baseline + residual`.

## 4. Prometheus Metrics

If `--port` is provided, exporter emits gauges:
- `g6_ml_hybrid_prediction{index,horizon,model}` — final hybrid prediction.
- `g6_ml_hybrid_baseline{index,horizon,model}` — structural baseline component.
- `g6_ml_hybrid_residual{index,horizon,model}` — ML residual component.

Add scrape job (example):
```
  - job_name: g6_ml_hybrid
    scrape_interval: 15s
    static_configs:
      - targets: ["127.0.0.1:9209"]
```

Recording rules (see `prometheus_rules_ml.yml`):

- `ml:hybrid:residual_avg_15m = avg_over_time(abs(g6_ml_hybrid_residual)[15m])`
- Alert `MLHybridResidualSpike` (warning) triggers when 15m avg residual magnitude > 20 for 10m.

## 5. Grafana Integration Ideas
- Overlay hybrid prediction vs quantile p50.
- Plot baseline and residual separately for diagnostic drift (e.g., residual widening near expiry).
- Add improvement ratio panel: `(|tp - baseline| - |tp - hybrid|) / |tp - baseline|` (future diagnostics script).

Quick dashboard: `grafana/dashboards/ml_hybrid_vs_quantile.json` overlays Hybrid, p50, and Baseline with `$index`/`$horizon` variables.

## 6. Next Steps
- Integrate hybrid into diagnostics endpoint (baseline vs hybrid RMSE).
- Recording rule for residual magnitude average (e.g., `avg_over_time(g6_ml_hybrid_residual[15m])`).
- Alert if residual magnitude spikes beyond historical percentiles.

### Quick Open

- Use VS Code task `Grafana: Open Hybrid vs Quantile Dashboard` to open the overlay view.

---
_Last updated: 2025-11-10_
