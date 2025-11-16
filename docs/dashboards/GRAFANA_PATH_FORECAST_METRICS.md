# Path Forecast Metrics Dashboard

This dashboard visualizes Prometheus metrics emitted by the path forecaster (retrieval and composite blend).

Metrics emission is optional and guarded by the environment variable:

- `ENABLE_PATH_FORECAST_PROM_METRICS=1`

## What you get

- Retrieval latency quantiles (p50/p90/p99) via Prometheus histogram buckets
- Composite latency quantiles
- Candidate day counts and ANN pruning effectiveness
- Stage timings: ANN build, exact scoring, quantile aggregation
- Composite diagnostics: prior cache hit, alpha, prior vs retained days

## Files

- Dashboard JSON: `grafana/dashboards/path_forecast_metrics.json`
 - Provisioning provider: `grafana/provisioning/dashboards/dashboard.yml` (auto-loads all dashboards in `grafana/dashboards/`)
 - Latency alert rules: `grafana/provisioning/alerting/path_forecast_latency.yml`

Import this file into Grafana (or place it under your existing dashboards provisioning path). It expects a Prometheus datasource variable named `DS_PROMETHEUS` (standard in this repo's dashboards).

## How to run locally

1) Start the Dashboard API with metrics enabled (ensures forecaster code paths execute and expose `/metrics`):

- Make sure your environment has `ENABLE_PATH_FORECAST_PROM_METRICS=1` set for the API process.
- Use the VS Code task "Dashboard API: Start on 9500 (reload)".

2) Exercise the forecaster paths so metrics get emitted:

- Use any existing flows that trigger path forecasts (e.g., Advisor/ML endpoints) or run `scripts/smoke_retrieval_metrics.py`.

3) Import the dashboard:

- Grafana → Dashboards → Import → Upload file → select `grafana/dashboards/path_forecast_metrics.json` → choose your Prometheus datasource.

If you are using the included provisioning, simply restart (or start) Grafana and it will ingest the dashboard automatically into the `G6` folder.

4) Panels should begin populating within a minute. If quantiles are empty, ensure the histogram series exist (check `pf_*_bucket` in Prometheus) and you have recent request traffic.

## Notes

- Histogram queries use 5m rate windows: adjust to your traffic profile if needed.
- ANN prune ratio is a gauge in [0,1]; thresholds are set at 0.5/0.7.
- Prior cache hit is emitted as 0/1; for hit rate over time, consider a recording rule.
- Exact metric names are defined in `src/path_forecast/metrics.py`.
- Composite metrics require the composite forecaster code path to run (e.g., the blended output).

## Alerting

Two example latency alerts are provisioned (p90 over 5m), plus health alerts for pruning and cache effectiveness:

| Alert | Metric | Threshold | For | UID |
|-------|--------|-----------|-----|-----|
| Retrieval p90 latency high | `pf_retrieval_latency_ms` (histogram quantile) | > 500 ms | 3m | `pf_retrieval_p90_latency` |
| Composite p90 latency high | `pf_composite_latency_ms` (histogram quantile) | > 800 ms | 3m | `pf_composite_p90_latency` |
| ANN prune ratio high (low pruning) | `avg_over_time(pf_ann_prune_ratio[15m])` | > 0.85 | 5m | `pf_ann_prune_ratio_high` |
| Prior cache hit rate low (warn) | `avg_over_time(pf_composite_prior_cache_hit[15m])` | < 0.50 | 10m | `pf_prior_cache_hit_rate_low_warn` |
| Prior cache hit rate low (critical) | `avg_over_time(pf_composite_prior_cache_hit[15m])` | < 0.20 | 10m | `pf_prior_cache_hit_rate_low_crit` |

Adjust thresholds by editing `grafana/provisioning/alerting/path_forecast_latency.yml` or `grafana/provisioning/alerting/path_forecast_alerts.yaml` and reloading Grafana. Consider adding recording rules if you want stabilized (down-sampled) latency series for alerting.

## Alert Routing

Routing is defined in `grafana/provisioning/alerting/contact_points.yml`:

- Base policies group by `alertname` & `severity` and send to `Console Notifications`.
- Nested routes match `component = path_forecast` for `severity = critical|high` and forward to the dedicated webhook receiver `Path Forecast Ops` (POST `/api/alerts/path_forecast`).
- File Logger receives all medium/high/critical severities for archival.

To change escalation cadence:
1. Edit the nested route `repeat_interval` values.
2. Restart Grafana (or trigger provisioning reload) for changes to apply.

Add new receivers by appending another contact point block (e.g., Slack) and adding a nested route under the severity branch with `component = path_forecast`.
