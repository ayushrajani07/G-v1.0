# Grafana Snippets: Drift Monitoring

These panels use the Infinity datasource to visualize drift evaluator recency and data availability.

## Required Variables
- `index`: the index symbol to visualize (e.g., `NIFTY`, `BANKNIFTY`).
- `DS_INFINITY`: UID of your installed Infinity datasource.
- `BACKEND_BASE`: base URL of the backend exposing the advisor endpoints, e.g., `http://localhost:9108` or your service URL.

## Panels
- `drift_evaluator_health.panel.json`
  - Stat panel showing `age_sec` for the last drift evaluation from `/api/ml/universal_advisor/drift_evaluator_health?indices=${index}`.
  - Turns red when `age_sec >= 600` (matches `G6_DRIFT_EVAL_STALE_SEC`).

- `drift_advice_data_status.panel.json`
  - Stat panel reading `data_insufficient` from `/api/ml/universal_advisor/drift_advice?index=${index}&detail=false`.
  - Maps `true` to "No current data" (orange) and `false` to "Data available" (green).

## Import Steps
1. Ensure the backend is reachable from Grafana and the endpoints respond.
2. Create dashboard variables:
   - `index`: type `Custom`, values `NIFTY,BANKNIFTY` (or your set).
   - `DS_INFINITY`: type `Datasource`, select `Infinity` provider.
   - `BACKEND_BASE`: type `Text`, value your backend base URL.
3. Import each JSON file as a panel:
   - Dashboard → Add panel → Code (JSON) → Paste contents → Apply.
4. Place panels and save the dashboard.

## Notes
- Panels assume Infinity v2+ datasource. Adjust field mappings if needed.
- You can duplicate `drift_evaluator_health.panel.json` for multiple indices or place it once with the `index` variable.
