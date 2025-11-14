# Universal Advisor Observability

This document describes the Prometheus/Grafana integration for the Universal Advisor.

## Metrics (exported by `scripts/advisor/universal_advisor_exporter.py`)

- `advisor_health_score{index}`: Per-index advisor health score (0-100).
- `advisor_overall_level{index,level}`: One-hot series for overall level. Levels: `ok|warn|crit|unknown`.
- `advisor_flag{index,code}`: Active finding flags (value=1 while active). Code is the finding code (bounded set).
- `advisor_composite_risk{index,type}`: Composite correlation flag (e.g., `type="ann_path"`).

Notes:
- Current engine computes a single score/level per run; the exporter assigns the same score/level to each configured index. Future iterations may provide per-index scores.

## Recording Rules (added to `prometheus_rules.yml`)

Group `advisor_health.rules`:
- `advisor_health_score_mean_15m = avg_over_time(advisor_health_score[15m]) / 100`
- `advisor_health_score_min_15m = min_over_time(advisor_health_score[15m]) / 100`
- `advisor_health_score_mean_30m = avg_over_time(advisor_health_score[30m]) / 100`
- `advisor_health_score_min_30m = min_over_time(advisor_health_score[30m]) / 100`

Composite:
- `advisor_composite_risk_mean_15m = avg_over_time(advisor_composite_risk[15m])`

These normalize health score to 0-1 ratios for easier composition with other ratio-based SLO rules.

## Alerts (added to `prometheus_alerts.yml`)

Group `advisor_health.alerts`:
- `AdvisorHealthDegraded`: Fires when `advisor_health_score_mean_15m < 0.70` for 10m.
- `AdvisorHealthCriticalLevel`: Fires when `advisor_overall_level{level="crit"} == 1` for 5m.
- `AdvisorHealthPersistentLow`: Fires when `advisor_health_score_min_30m < 0.50` for 30m.

Composite:
- `AdvisorCompositeRiskActive`: Fires when `advisor_composite_risk == 1` for 5m.

Tune thresholds after observing baseline trends.

## Prometheus Scrape

`prometheus.yml` now includes:

```
- job_name: 'advisor_health'
  static_configs:
    - targets: ['127.0.0.1:9322']
      labels:
        job: 'advisor_health'
        instance: 'advisor-universal'
```

Start the exporter locally:

- Task (recommended): add a VS Code task or use `python scripts/advisor/universal_advisor_exporter.py --port 9322 --indices NIFTY,BANKNIFTY,SENSEX`.

## Grafana Panel Suggestions

- SingleStat/TimeSeries: `advisor_health_score` per index with 15m trend.
- State panel: map `advisor_overall_level{level}` to discrete states, per index.
- Table of active flags per index: query `advisor_flag` and group by `{index,code}`.
- Annotations: Overlay advisor alerts on main dashboard.
  - Composite Risk active: `advisor_composite_risk{index=~"$index"} > 0` (red marker)
  - Critical Level: `advisor_overall_level{level="crit",index=~"$index"} == 1`
  - Add an index variable (`label_values(advisor_health_score,index)`) and set `All` to `.*` for regex matching.

Added to Advisor dashboard:
- Health Score Min 30m (stat, 0–100)
- Health Score Mean 15m (stat, 0–100)
- Index template variable to filter all panels
- Annotations for Composite Risk and Critical Level

## Grafana Provisioning

Dashboards are auto-provisioned by the stack starter (`scripts/obs_start_clean.ps1`). It stages JSON files from these locations into Grafana's provisioning path:

- `grafana/dashboards/generated/*.json`
- `dashboards_modular/*.json`
- `docs/grafana/dashboards/*.json`
- `grafana/dashboards/*.json` (non-generated, first-class dashboards)

The Universal Advisor dashboard is committed at `grafana/dashboards/advisor_unified_health.json` and will be picked up automatically on restart.

To reload dashboards:

- Run the VS Code task: “Grafana: Reload + Open” (restarts the stack and opens Grafana), or
- Execute `scripts/reload_grafana_dashboard.ps1`.

Datasource UIDs expected by provisioned dashboards:

- Prometheus: `uid = PROM`
- Infinity: `uid = INFINITY` or `G6_INFINITY`

## Dashboards

Provisioned under Grafana folder `G6 Advisor`:

### Advisor Unified Health
- Index selector (multi; All maps to regex `.*`).
- Per-Index Health Score (timeseries, 0–100).
- Worst Overall Level (stat; 5m window for crit detection).
- Composite ANN+Path Risk Active (stat 0/1).
- Health Score Min 30m (stat, 0–100).
- Health Score Mean 15m & 30m (sparklines, 0–100).
- Active Findings table with severity code filter (`codes` variable: .*, CRIT/WARN/INFO only).
- Severity counters: CRIT/WARN/INFO active totals.
- Annotations: Composite Risk active, Critical Level.
- External link: Advisor API detailed report.
- Optional panel: Top Remedies (Advisor API) via Infinity (`INFINITY`) from `/api/ml/universal_advisor?detail=true&index=${index}`.
- Drilldowns: Worst level & severity counters link to detail dashboard with pre-filtered codes.

### Advisor Detail
- Health Score timeline (0–100) for deeper inspection.
- Worst Overall Level stat (5m window).
- Composite Risk timeline (0/1).
- Active Findings table (index + code filter).
- External link: Advisor API detailed report.

Use both dashboards together: start broad in Unified Health; drill into a specific index in Detail when anomalies occur.

## Runbook

When alerts fire:
- Use `/api/ml/universal_advisor?detail=true` to fetch full report (findings, remedies).
- Prioritize remedies by `summary.actions_ordered`.
- Cross-check ANN and PathForecast panels for corroborating regressions.

## Future Enhancements

- Per-index health scoring at engine level.
- Export direct counters for finding categories (info/warn/crit counts).
- Correlate ANN effectiveness + path coverage to emit composite severity.
