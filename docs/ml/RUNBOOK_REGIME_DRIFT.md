# Runbook: Regime & Drift Threshold Triage

Version: 1.0  
Updated: 2025-11-19

## Purpose
Operational guide for identifying, confirming, and responding to regime change and drift threshold breaches surfaced by the ML ARM system.

## Key Signals
| Source | Metric / Field | Meaning | Action Hint |
|--------|----------------|---------|-------------|
| Manifest (`/api/ml/ensemble/regime/threshold_manifest?include_full=1`) | `relative_shifts.relative_shift_pct` | Percent change vs historical median | >15%: watch, >25%: consider rollback |
| Dynamic Thresholds (`/api/ml/ensemble/regime/dynamic_thresholds`) | `breach.drift_triggered` | Current horizon flagged | Investigate reasons list |
| Dynamic Thresholds | `latest_metrics.mae_ratio` | Short/long MAE ratio | >1.6 critical tail expansion |
| Dynamic Thresholds | `latest_metrics.norm_ratio` | Normalized error drift | >1.5 potential band compression or skew |
| Dynamic Thresholds | `latest_metrics.coverage_delta` | Short – long coverage pct points | < -15 accelerating under-coverage |
| Auto-Tune Summary | `penalty_improvement` | Recent tuning benefit | < epsilon → ignore adjustment |
| TTL Study | `g6_ttl_study_best_p95_improvement_ms` | Best p95 reduction vs baseline | Negative large magnitude indicates success |
| TTL Study | `g6_ttl_study_best_hit_ratio_delta` | Hit ratio gain | >0.05 meaningful cache efficiency improvement |

## Standard Triage Flow
1. Alert Received (Prometheus/Grafana): Identify alert rule & associated horizon/index.
2. Fetch Dynamic Snapshot:
   - `GET /api/ml/ensemble/regime/dynamic_thresholds?index=NIFTY&include_percentiles=1`
3. Confirm Breach:
   - Check `breach.drift_triggered` and supporting ratios (MAE, norm, coverage).
4. Assess Historical Context:
   - Compare current dynamic thresholds vs manifest stable thresholds (warn/crit percentiles).
5. Validate Sample Integrity:
   - Ensure `metrics/drift_samples/` recent JSON logs exist (not stale >2h).
6. Model Health Check:
   - Quick forecast sanity: call `/api/ml/ensemble/forecast?index=NIFTY&horizon=60` and inspect band width.
7. Decide Action:
   - Minor shift: monitor for next 2 cycles.
   - Persistent >2 cycles & ratios above crit: schedule recalibration (`govern_drift_thresholds.py`).
   - Erratic single-horizon spike only: review recent data ingestion anomalies.

## Common Root Causes & Remediations
| Symptom | Likely Cause | Remediation |
|---------|--------------|------------|
| MAE ratio high, norm ratio normal | Broader dispersion, band resizing needed | Increase warn/crit MAE percentiles (auto-tune) |
| Norm ratio high, coverage stable | Band narrowing | Revisit conformal calibration / widen band width logic |
| Coverage delta deeply negative | Tail under-coverage | Adjust coverage drift low percentiles or widen p10/p90 quantile bands |
| Single horizon repeatedly drifting | Horizon-specific feature degradation | Retrain horizon-specific features; inspect feature importance delta |
| All horizons drifting simultaneously | Market regime change | Trigger full recalibration + consider volatility aware TTL |
| Auto-tune converging with no improvement | Targets unrealistic | Reassess violation target bands or epsilon |
| Hit ratio deterioration with adaptive TTL | Overly short min TTL | Raise `G6_FORECAST_CACHE_ADAPTIVE_MIN` |

## Recalibration Procedure
1. Run calibration:
   ```powershell
   python scripts/ml/calibrate_drift_thresholds.py --indices NIFTY,BANKNIFTY,SENSEX --min-count 30
   ```
2. Validate stability:
   ```powershell
   python scripts/ml/validate_drift_threshold_stability.py --indices NIFTY,BANKNIFTY,SENSEX --max-shift-pct 0.15
   ```
3. Govern & Promote (with auto-tune):
   ```powershell
   python scripts/ml/govern_drift_thresholds.py --indices NIFTY,BANKNIFTY,SENSEX --apply-env --auto-tune-percentiles --auto-tune-epsilon 0.005 --json
   ```
4. Confirm manifest update:
   ```powershell
   curl http://localhost:9500/api/ml/ensemble/regime/threshold_manifest?include_full=1
   ```

## Verification Checklist After Promotion
- `relative_shifts` all <15% or justified in notes.
- `converged` false (if improvement occurred) or documented if true.
- Canary comparison does not show worse penalties than promoted set.
- Prometheus gauges updated (`g6_drift_threshold_horizons_used`).

## Rollback Criteria
Rollback if any of:
- Critical coverage under-run (coverage delta < -25 for 2 consecutive intervals).
- Relative shift ≥25% for MAE or norm warn/crit thresholds.
- Auto-tune penalty regression >10% vs previous manifest.
Command example:
```powershell
python scripts/ml/govern_drift_thresholds.py --indices NIFTY,BANKNIFTY,SENSEX --rollback-on-critical --rollback-threshold 0.25 --json
```

## TTL Study Interpretation
- Use `g6_ttl_study_p95_delta_ms` metric series: negative values = improvement.
- Prioritize scenarios with both improved p95 and non-negative hit ratio delta.
- Record improvement decisions in ops log `ops/ttl_decisions.md` (create if absent).

## Incident Logging Template
```
Date/Time (UTC):
Index/Horizons:
Alert(s):
Observed Ratios: MAE=, Norm=, Coverage Δ=
Recent Samples Count:
Auto-Tune Improvement:
Action Taken (Recalibrate / Rollback / Monitor):
Notes:
Follow-up Tasks:
```

## Automation Hooks (Future)
- Scheduled governance (daily) + Slack notification for relative shifts.
- Automatic TTL scenario run weekly and push metrics to Prometheus.
- Canary percentile drift early warning alert: p95 penalty regression >5% week-over-week.

## References
- `ML_ARM_NEXT_STEPS.md`
- `prometheus_recording_rules_ttl.yml`
- `scripts/ml/govern_drift_thresholds.py`
- `scripts/ml/ttl_impact_study.py`

---
Owned by: ML Ops / ARM Engineering
Contact: ml-ops@example.com
