# Grafana JSON Trend Panels (Quick Import)

Two ways to visualize drift severity using the JSON endpoints:

1) Infinity (recommended)
- Import `grafana/dashboards/ml/ml_drift_json_per_severity_trend.json`.
- When prompted, map the `Infinity` datasource to your configured `yesoreyeram-infinity-datasource`.
- Set your API base so that the URL `http://localhost:9500/api/ml/drift/daily_reports/trend?days=${days}` resolves to your backend.
- Use the templating variables at the top to switch `index` and `days`.

2) JSON API (simpod)
- Create a panel with `simpod-json-datasource` and point it to `/api/ml/drift/daily_reports/trend?days=14`.
- Use path `per_index_severity_series.NIFTY.critical` and map fields:
  - `generated_at` as Time
  - `value` as Number
- Repeat for `actionable` and `watch`.

Backend endpoints used:
- Latest: `/api/ml/drift/daily_reports/latest`
- Trend: `/api/ml/drift/daily_reports/trend?days=14`
