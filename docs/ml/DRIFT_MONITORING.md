# Drift Monitoring (Phase 10)

## Overview
Drift monitoring quantifies distribution shifts between a historical baseline and recent feature observations. It helps decide when to refresh baselines, retrain models, or investigate data quality issues.

## Implemented Metrics
| Metric | Gauge | Description |
|--------|-------|-------------|
| Population Stability Index (PSI) | `g6_feature_psi` | Binned quantile divergence; higher => more shift |
| KS p-value | `g6_feature_ks_pvalue` | Two-sample Kolmogorov–Smirnov test p-value |
| Mean Delta | `g6_feature_mean_delta` | Recent mean minus baseline mean |
| Variance Ratio | `g6_feature_var_ratio` | Recent variance / baseline variance |
| Severity | `g6_feature_drift_severity` | Encoded severity (0 stable,1 watch,2 actionable,3 critical) |
| Baseline Age | `g6_drift_baseline_age_days` | Days since baseline saved |
| Critical Feature Count | `g6_drift_critical_feature_count` | Number of features at critical severity per index |
| Last Eval Timestamp | `g6_drift_last_eval_ms` | Last evaluation (epoch ms) per index |

## Severity Classification Logic
Severity escalates based on thresholds (environment configurable):

- Watch: Any metric crosses its warn threshold (e.g., PSI >= `G6_DRIFT_PSI_WARN`).
- Actionable: Watch plus corroboration (PSI warn AND (KS warn OR mean Z warn)).
- Critical: Any metric crosses critical threshold (e.g., PSI >= `G6_DRIFT_PSI_CRIT`, KS p-value <= `G6_DRIFT_KS_CRIT`, |mean Z| >= `G6_DRIFT_MEAN_Z_CRIT`, variance ratio outside critical bounds).

Environment Variables (selected):
```
G6_DRIFT_PSI_WARN=0.25
G6_DRIFT_PSI_CRIT=0.40
G6_DRIFT_KS_WARN=0.01
G6_DRIFT_KS_CRIT=0.001
G6_DRIFT_MEAN_Z_WARN=2.0
G6_DRIFT_MEAN_Z_CRIT=3.0
G6_DRIFT_VAR_RATIO_WARN_HIGH=1.5
G6_DRIFT_VAR_RATIO_WARN_LOW=0.67
G6_DRIFT_VAR_RATIO_CRIT_HIGH=2.0
G6_DRIFT_VAR_RATIO_CRIT_LOW=0.5
G6_DRIFT_BASELINE_REFRESH_DAYS=30
G6_DRIFT_CRITICAL_ALERT_REFRESH_COUNT=3
G6_DRIFT_MAX_FEATURES=30
```

## Baseline Refresh Policy
Baseline automatically refreshes when:
1. Age (days) >= `G6_DRIFT_BASELINE_REFRESH_DAYS`, OR
2. Number of critical features >= `G6_DRIFT_CRITICAL_ALERT_REFRESH_COUNT`.

Refresh is atomic (temp file replace), increments `version` in baseline JSON. Age exposed via `g6_drift_baseline_age_days`.

## Prometheus Alert Rules (Severity-Based)
Stored in `prometheus_alerts_drift.yml` using severity gauge:
- `MLFeatureDriftCritical`: Any feature severity = 3.
- `MLFeatureDriftActionablePersistent`: Actionable repeats >=3 times in 15m.
- `MLBroadCriticalDrift`: >5 critical features sustained.
- `MLDriftSeveritySpike`: Rapid increase in critical count.
- `MLStaleDriftEvaluation`: Evaluator stale (>10m no update).
- `MLAcceleratedBaselineRefresh`: Critical count threshold reached pre-refresh.
- `MLMultiIndexCriticalDrift`: Multiple indices with >3 critical features.

## Advisor Integration
Endpoint `/api/ml/universal_advisor/drift_advice` now reads `g6_feature_drift_severity` directly. Fallback classification used only if severity gauge absent. Provides per-feature actions:
- Critical: alert & consider retraining / baseline refresh.
- Actionable: investigate pipeline & validate recent data.
- Watch: monitor next cycles.

Note on data_insufficient
- The advice payload includes `data_insufficient: true` when no drift snapshot is available (e.g., evaluator not yet run or metrics disabled).
- Dashboards should reflect this by:
	- Showing a neutral badge or info state (e.g., “No current data”)
	- Avoiding red/amber status until real data arrives
	- Optionally displaying the evaluator recency (see Evaluator Health below)

## Data Flow
1. `DriftMonitor` loads baseline (or creates if missing).
2. Evaluator thread computes recent window, metrics, severity.
3. Gauges updated; baseline refresh may occur.
4. Advisor aggregates severity snapshot for decision support.
5. Alerts fire based on severity and aggregate conditions.

## Evaluator Health (Recency)
Gauge `g6_drift_last_eval_ms{index}` records the last evaluator timestamp (ms since epoch) per index. An advisor endpoint exposes an age calculation and a boolean `stale` using a threshold (default 600 seconds). Suggested dashboard usage:
- Show a stat “Last drift eval age” per index
- Color as warning when `stale=true`
- Link to evaluator logs when stale persists

## Feature Mapping & Transforms
Drift uses a configurable feature map to bind logical feature names to CSV columns and simple transforms.

- Env var: `G6_DRIFT_FEATURE_MAP_JSON` (optional). If unset, a built-in default is used.
- Sample: `configs/ml/feature_map.sample.json`

Spec format (per feature):
```
{
	"<feature_name>": {
		"csv_col": "<column_in_csv>",
		"importance": <int for ordering>,
		"transform": "identity|log1p|abs"
	}
}
```

Notes:
- `importance` orders default exposure; lower = earlier.
- `transform` applies to values before statistics are computed (e.g., `tp_log` uses `log1p` of `tp`).
- The runtime feature cap still prioritizes by `psi + |mean_z|`; `importance` can act as a tiebreaker by placing key features earlier.

Quick start (local):
```
export G6_DRIFT_FEATURE_MAP_JSON=configs/ml/feature_map.sample.json
export G6_DRIFT_INDICES=NIFTY,BANKNIFTY
python scripts/ml/report_drift_daily.py --output reports/drift/daily_$(date +%F).json --trend-days 14
```

## Next Hardening Items
- Multi-day baseline aggregation.
- EWMA smoothing of metrics to reduce transient noise.
- Feature importance weighting for exposure cap (`G6_DRIFT_MAX_FEATURES`).

## Operational Playbook (Condensed)
| Severity | Action |
|----------|--------|
| Watch | Observe; confirm no data gaps |
| Actionable | Investigate feature pipeline & anomalies |
| Critical | Baseline refresh review; potential retrain; raise alert |

## References
- `src/ml/drift_monitor.py`
- `src/ml/feature_loader.py`
- `src/web/dashboard/drift_metrics.py`
- `prometheus_alerts_drift.yml`
- Advisor endpoint implementation

---
_Last updated: 2025-11-18_
