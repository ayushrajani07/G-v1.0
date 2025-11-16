## ANN Health Prometheus Exporter

Lightweight continuous monitoring for ANN retrieval health (speedup, prune ratio, q50 MAD, sample rows, baseline deltas, regression count). Designed to complement the daily health check by providing always-on visibility and alerting hooks.

### Metrics
Gauges (per window):
- `ann_health_speedup{index="NIFTY",window="60"}`
- `ann_health_prune_ratio{...}`
- `ann_health_q50_mad{...}`
- `ann_health_rows{...}`
- `ann_health_speedup_delta{...}` (live - baseline)
- `ann_health_prune_ratio_delta{...}`
- `ann_health_q50_mad_delta{...}`
- `ann_health_effectiveness_adjusted{...}` (falls back to raw effectiveness when adjusted missing)
- `ann_health_guard_trigger_rate{...}` (0–1)

Global:
- `ann_health_regression_total` (number of regression conditions triggered in last run)
- `ann_health_last_run_timestamp_seconds`
Recording rules:
- `ann_health_regression_active` (smoothed 0/1 over 5m):
   ```promql
   max_over_time(ann_health_regression_total[5m]) > 0
   ```

Regression conditions (counted only if `rows >= --min-rows`):
1. Speedup drop > `--speedup-min-drop` vs baseline
2. `q50_mad_avg > --mad-max`
3. `prune_ratio_avg > --prune-max`

### Baseline
Provided via `baselines/ann_daily_baseline.json`.

Supported formats:
1. Flat (single-index, legacy):
```json
{
   "retrieval_60_k10": {"speedup_avg": 0.93, "prune_ratio_avg": 0.83, "q50_mad_avg": 0.0},
   "retrieval_120_k10": {"speedup_avg": 0.89, "prune_ratio_avg": 0.87, "q50_mad_avg": 0.0}
}
```
2. Nested (multi-index):
```json
{
   "NIFTY": {
      "retrieval_60_k10": {"speedup_avg": 0.93, "prune_ratio_avg": 0.83, "q50_mad_avg": 0.0},
      "retrieval_120_k10": {"speedup_avg": 0.89, "prune_ratio_avg": 0.87, "q50_mad_avg": 0.0}
   },
   "BANKNIFTY": {
      "retrieval_60_k10": {"speedup_avg": 0.91, "prune_ratio_avg": 0.85, "q50_mad_avg": 0.0},
      "retrieval_120_k10": {"speedup_avg": 0.90, "prune_ratio_avg": 0.86, "q50_mad_avg": 0.0}
   }
}
```
The exporter auto-detects structure. Refresh operations (`--refresh-baseline-if-ok`) update only the active index branch when nested.

### Running (Continuous)
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/ml/start_ann_health_exporter.ps1 -Index NIFTY -Tag this_week -Offset 0 -DaysBack 3 -Port 9308 -Interval 300 -MinRows 5 -Verbose
```

### Single Run (Verification / CI)
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/ml/start_ann_health_exporter.ps1 -Index NIFTY -Tag this_week -Offset 0 -DaysBack 3 -Port 9308 -Interval 5 -MinRows 5 -Verbose -Once
```

### Direct Python Invocation
```powershell
$env:PYTHONPATH = "$PWD"; python scripts/ml/ann_health_exporter.py --index NIFTY --tag this_week --offset 0 --days-back 3 --baseline baselines/ann_daily_baseline.json --port 9308 --interval 300 --min-rows 5 --verbose
```

### Grafana Integration Hints
1. Add Prometheus job scrape config:
   ```yaml
   - job_name: ann_health
     scrape_interval: 30s
     static_configs:
       - targets: ['localhost:9308']
   ```
2. Panels to create:
   - Speedup vs baseline delta (line)
   - q50 MAD vs threshold (stat + sparkline)
   - Prune ratio (gauge with threshold region)
   - Regression count (alert when > 0)
3. Alert rule example:
   ```promql
   ann_health_regression_total > 0
   ```

### Grafana Dashboard (Seed)
Dashboard JSON committed at `grafana/dashboards/generated/ann_health.json` with panels:
- Regressions (stat)
- Last run timestamp
- Speedup & Speedup Δ
- q50 MAD & MAD Δ
- Prune Ratio
- Rows contributing (sample size)
- Adjusted Effectiveness (with thresholds: green>=0.05, orange>=0.02, red<0.02)
- Guard Trigger Rate (0-1)
- Regression Active (smoothed 5m flag)

Variables:
- `$index` (PromQL label_values on ann_health_speedup)
- `$window` (static: 60,120)

### Alerting
Two alert rules added in `prometheus_alerts.yml` group `ann_health.alerts`:
1. `AnnHealthRegressionDetected` – fires when `ann_health_regression_total > 0` for 2m.
2. `AnnHealthChronicRegression` – fires on persistent non-zero regression across 30m window.
3. `AnnHealthRegressionActiveSustained` – fires when smoothed flag stays active 5m.
4. `AnnHealthEffectivenessLow` – critical when regression active and 15m average adjusted effectiveness <0.02.

### Prometheus Scrape
`prometheus.yml` now includes job `ann_health` targeting default ports `9308` and optional secondary instances `9309` (BANKNIFTY) and `9310` (test/sandbox).

### Multi-index
- Run a second exporter instance (example BANKNIFTY on 9309):

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/ml/start_ann_health_exporter.ps1 -Index BANKNIFTY -Tag this_week -Offset 0 -DaysBack 3 -Port 9309 -Interval 300 -MinRows 5 -Verbose
```

- Ensure Prometheus has `127.0.0.1:9309` under job `ann_health` (already in prometheus.yml). The Grafana dashboard will pick up the second index automatically via `$index` variable.

#### SENSEX coverage
- Baseline branch `SENSEX` is included in `baselines/ann_daily_baseline.json` (seeded with placeholders). For representative thresholds, seed from a SENSEX harness run using `scripts/ml/seed_ann_baseline_from_ranking.py` once you have a `ann_ranking.csv` for SENSEX.
- Recommended exporter port: 9310. A convenient task is available: "ANN: Start Health Exporter (SENSEX 9310)"; for a quick single-run verification use "ANN: Verify Health Exporter (SENSEX one-shot)".
- Add `localhost:9310` to the Prometheus `ann_health` job targets.

### Baseline Auto-Refresh
`--refresh-baseline-if-ok` can be passed to the exporter to automatically update the baseline JSON when:
1. `regression_total == 0`
2. Each baseline key has `rows >= --min-rows`

Refresh mechanics:
- Writes to a temporary file and atomically replaces the original.
- Only updates existing keys (no new windows introduced).
- Nested baseline: only the branch for the current `--index` is updated (other indices preserved).
- Use sparingly; disable during known tuning experiments.

Example:
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/ml/start_ann_health_exporter.ps1 -Index NIFTY -Tag this_week -Offset 0 -DaysBack 3 -Port 9308 -Interval 300 -MinRows 5 -Verbose -RefreshBaselineIfOk
```

### SLO Derived Recording Rules
Added in `prometheus_rules.yml`:
- `ann_health_effectiveness_adjusted_mean_30m` – 30m moving average effectiveness.
- `ann_health_speedup_delta_mean_30m` – 30m average of speedup delta.
- `ann_health_prune_ratio_p95_30m` – 30m p95 prune ratio.
 - (New) `ann_health_effectiveness_adjusted_mean_5m` / `ann_health_effectiveness_adjusted_mean_1h` – short/long window effectiveness means.
 - (New) `ann_health_speedup_delta_mean_5m` / `ann_health_speedup_delta_mean_1h` – short/long window speedup delta means.
 - (New) `ann_health_prune_ratio_p95_2h` – longer horizon pruning pressure.

These additional windows enable burn-rate style SLO alerts comparing fast vs slow degradation trajectories.

### Extended Alerts
New alert rules (ann_health.alerts):
- `AnnHealthEffectivenessSLOBreach` – 30m mean effectiveness below 0.05 while regression active.
- `AnnHealthPruneRatioP95High` – p95 prune ratio >0.90 for 15m.
- `AnnHealthSpeedupDeltaEroded` – speedup delta 30m mean < -0.05.
 - (New) `AnnHealthEffectivenessFastBurn` – 5m <0.03 & 1h <0.05 (rapid SLO consumption) while regression active.
 - (New) `AnnHealthEffectivenessSlowBurn` – 30m <0.05 & 6h <0.06 (long-lived slow SLO burn) while regression active.
 - (New) `AnnHealthSpeedupDeltaBurn` – 5m speedup delta < -0.08 & 1h < -0.05 (performance erosion multi-window).
 - (New) `AnnHealthPruneRatioBurn` – prune p95 30m >0.92 AND 2h >0.90 (sustained high pruning across horizons).

Burn alerts provide earlier differentiated signals (fast vs slow) for targeted remediation (rollback vs retune vs refresh).

### Suggested Next Enhancements
- Dashboard stat coloring thresholds (e.g., speedup delta < -0.05 => red).
- Dedicated panel for baseline deltas aggregated (heatmap style).
- Multi-index exporter instances with combined effectiveness comparison.
 - Composite ANN health score (blend of regression_active + normalized effectiveness + speedup delta + prune p95).
 - Automated baseline refresh scheduler avoiding volatile first session hour.
 - Alert suppression gating for low-row early session windows.
 - Dashboard generator integration (automated inclusion of `ann_health.json`).

### Runbook Reference
Operational triage, remediation decision tree (refresh vs retune vs rollback), and edge cases are documented in `ANN_RUNBOOK.md`. Keep thresholds in sync when adjusting alert logic or recording rules.

### Progress Summary (Phases)
1. Harness establishment & baseline metrics
2. Exporter core (single-index) + Prometheus/Grafana integration
3. Metrics enhancements (adjusted effectiveness, guard trigger rate)
4. Multi-index baseline & exporter instances (BANKNIFTY bring-up)
5. SLO recording rules & burn-rate alert set
6. Runbook documentation & decision framework

### Roadmap (Future)
| Item | Goal |
|------|------|
| Composite health score | Single stat summarizing ANN status |
| Baseline scheduler | Safe, automated refresh windows |
| Dashboard generator integration | Remove manual seed step |
| Low-row alert suppression | Reduce false positives pre-open |
| Index data enrichment (BANKNIFTY) | Improve baseline representativeness |
| Guard heuristic tuning | Optimize trigger rate vs quality tradeoff |

All future changes should update this file and `ANN_RUNBOOK.md`.

### Extending
- Add adjusted effectiveness or guard trigger rate by parsing ranking CSV (future enhancement).
- Multi-index support: run multiple exporter instances on different ports (e.g., 9308 NIFTY, 9309 BANKNIFTY).

### Troubleshooting
- Missing baseline: exporter exits with error; ensure file path correct.
- No metrics / zeros: likely insufficient rows (< min_rows) or retrieval slice returned no data for the date window.
- Loop not exiting: use `-Once` for test runs.

### License / Notes
Internal operational tooling. Keep resource usage minimal; slice runs use retrieval-only mode with `--metrics-minimal`.