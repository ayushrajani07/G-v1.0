# Phase 10 Grafana Quickstart

This guide helps you stand up the key panels (MAE, coverage, drift) and begin rolling performance capture.

## 1) Enable metrics and start the API

On Windows PowerShell:

```powershell
# From repo root
scripts/ml/phase10_start_metrics_and_dashboard.ps1 -BindHost 127.0.0.1 -Port 9500 -WindowStyle Hidden -Indices "NIFTY,BANKNIFTY" -DriftIntervalSec 300 -EvalStaleSec 600
```

This sets:
- `ENABLE_PATH_FORECAST_PROM_METRICS=1`, `G6_ROLLING_MAE_ENABLE=1` (MAE/coverage/normalized error gauges)
- `G6_DRIFT_ENABLE=1` (drift evaluator loop)
- `G6_DRIFT_INDICES`, `G6_DRIFT_EVAL_INTERVAL_SEC`, `G6_DRIFT_EVAL_STALE_SEC`
- `BACKEND_BASE` for Infinity panels

## 2) Prometheus scrape
Ensure Prometheus scrapes the dashboard API's `/metrics` endpoint.

- Prometheus target: `http://127.0.0.1:9500/metrics`
- Validate gauges appear: `g6_forecast_mae`, `g6_forecast_coverage_pct`, `g6_feature_drift_severity`, `g6_drift_last_eval_ms`.

## 3) Import panels

- Use the Ensemble dashboards if already provisioned (`grafana/dashboards/ensemble_api*.json`).
- For drift snippets:
  - Infinity datasource UID env var: set `DS_INFINITY` in Grafana.
  - Import panels from `grafana/snippets/`:
    - `drift_evaluator_health.panel.json` (stat: evaluator age)
    - `drift_advice_data_status.panel.json` (stat: data availability)
  - Dashboard variables:
    - `index` (e.g., `NIFTY,BANKNIFTY`)
    - `DS_INFINITY` (Infinity datasource UID)
    - `BACKEND_BASE` (e.g., `http://127.0.0.1:9500`)
 - Or import the combined dashboard: `grafana/dashboards/drift_quickstart.json` (pre-wired with both panels and a severity summary table).

## 4) Verify real-time updates
- Drift evaluator age advances every `G6_DRIFT_EVAL_INTERVAL_SEC`.
- `data_insufficient` shows "No current data" until drift snapshot fills.
- MAE / coverage gauges change as forecasts are requested.

## 5) Performance & Reliability Alerts

Add Prometheus alert rules for key performance and reliability signals:

- **Drift Alerts:** `prometheus_alerts_drift.yml` (feature drift severity-based)
- **Performance Alerts:** `prometheus_alerts_performance.yml` (latency, cache, coverage, error tail)

### Performance Alert Rules

Include `prometheus_alerts_performance.yml` in your `prometheus.yml`:

```yaml
rule_files:
  - prometheus_alerts_drift.yml
  - prometheus_alerts_performance.yml
```

**Key Alerts:**
- `MLForecastLatencyP95Degraded`: P95 latency > 500ms for 10m
- `MLForecastCacheEvictionSurge`: Eviction rate > 2/sec for 10m
- `MLForecastLowCoverage`: Coverage < 70% for 15m
- `MLForecastHighNormErrorTail`: P90 normalized error > 0.15 for 10m
- `MLAdaptiveTTLTooShortPersistent`: Dynamic TTL < 15s for 30m
- `MLAdaptiveTTLTooLongHighLatency`: TTL > 55s while P95 latency > 400ms

**Configure Thresholds via Environment Variables:**
```bash
export G6_ALERT_LATENCY_P95_MS=500           # P95 latency threshold (ms)
export G6_ALERT_NORM_ERR_P90=0.15            # P90 normalized error threshold
export G6_ALERT_COVERAGE_MIN_PCT=70          # Minimum coverage percentage
export G6_ALERT_CACHE_EVICTION_RATE=2        # Max eviction rate (per sec)
export G6_ALERT_TTL_TOO_SHORT_SEC=15         # Min TTL threshold (seconds)
export G6_ALERT_TTL_TOO_LONG_SEC=55          # Max TTL threshold (seconds)
```

**Manual Verification (PromQL):**
```promql
# P95 latency for NIFTY 60m horizon (5m window)
histogram_quantile(0.95, sum(rate(g6_forecast_latency_ms_bucket{index="NIFTY",horizon="60"}[5m])) by (le))

# Cache eviction rate (5m window)
sum(rate(g6_forecast_cache_evictions_total{index="NIFTY"}[5m]))

# Current coverage for NIFTY 60m
g6_forecast_coverage_pct{index="NIFTY",horizon="60"}

# P90 normalized error (10m window)
histogram_quantile(0.90, sum(rate(g6_forecast_norm_error_hist_bucket{index="NIFTY",horizon="60"}[10m])) by (le))

# Current adaptive TTL
g6_forecast_cache_dynamic_ttl{index="NIFTY"}
```

## 6) Optional
- Generate per-index drift rules using `prometheus_alerts_drift.generated.yml`.
- Tune eval interval and staleness threshold via env vars to suit your environment.

## Import the Drift Quickstart dashboard

- File: `grafana/dashboards/drift_quickstart.json`
- Steps:
  1. In Grafana, go to Dashboards → Import.
  2. Upload the JSON file or paste its contents.
  3. Select the Infinity datasource for `DS_INFINITY` and set `BACKEND_BASE` (e.g., `http://127.0.0.1:9500`).
  4. Pick an `index` (e.g., NIFTY) and Save.
  5. Confirm panels load and refresh every 10s.
