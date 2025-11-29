# Phase 12 Operations Runbook

## 1. Overview
Phase 12 introduces persistence of drift attribution, tail acceleration monitoring, automated retrain triggers, and CI performance gating. This runbook defines daily, weekly, and event-driven operational procedures.

## 2. Key Paths / Endpoints
- Drift attribution CSV: `data/drift_attribution/{INDEX}_{H}.csv`
- Retrain flags: `data/retrain_flags/retrain_{INDEX}_{H}.json`
- Config history: `data/config_versions/{INDEX}.jsonl`
- API endpoints:
  - `/api/ml/ensemble/drift_attribution?index=...&horizon=...`
  - `/api/ml/ensemble/config_diff?index=...`

## 3. Metrics & Alerts
| Alert | Trigger | Action |
|-------|---------|--------|
| MLResidualTailBurnFastWarning | Accel >0.04 (10m) | Observe trend; prepare validation dataset |
| MLResidualTailBurnAccelerationCritical | Accel >0.08 (5m) | Initiate retrain checklist |
| MLAdaptiveRetrainRecommended | Retrain signal ≥2 (15m) | Stage retrain trigger script |
| MLAdaptiveRetrainCritical | Retrain signal ≥2.5 (10m) | Launch retrain workflow |

## 4. Automated Retrain Procedure
1. Alert or flag file indicates threshold met.
2. Validate canary candidate:
   - Run offline evaluation with `evaluate_canary()`; require p95 improvement ≥ target (from `g6_ml_target_mae_p95_improve_pct`).
   - Minimum sample size: 500 residual pairs.
3. If improvement confirmed:
   - Trigger `/api/ml/ensemble/retrain` with appropriate `days` window.
   - Monitor job completion, update dashboard panel.
4. Post-retrain:
   - Compare new config diff via `/api/ml/ensemble/config_diff`.
   - Record canary vs new production snapshot.

## 5. Drift Attribution Persistence Rotation (Daily 00:05 UTC)
Script logic:
```
for f in data/drift_attribution/*.csv:
  move to archive/drift_attribution/YYYYMMDD/<same name>
  create new empty file with header if future writes occur
```
Retention: keep 7 daily archives; purge older.

## 6. Config Versioning Hygiene
- No rotation required (low volume).
- Weekly audit: verify last 2 diffs expected; investigate unexpected large changed set.
- If hash mismatch without explicit deploy, treat as potential config tampering.

## 7. CI Performance Guard
- GitHub Actions job executes `scripts/ci_load_check.py`.
- Failure conditions:
  - p95 latency > 1200ms
  - error_rate > 1%
- Remediation:
  - Re-run with reduced concurrency to isolate regression.
  - Inspect recent commits touching forecasting / API / metrics.

## 8. Manual Diagnostics Checklist
When investigating drift spike:
1. Fetch live attribution JSON.
2. Review tail acceleration and burn base ratios.
3. Check config diff for recent structural changes.
4. Evaluate weight divergence; if convergence (<0.05) plus high tail acceleration, prioritize retrain.
5. Run canary evaluation if a candidate model exists.

## 9. Canary Evaluation Guidelines
- Use same residual capture window for baseline and canary.
- Accept canary if:
  - p95 improvement ≥ target improvement - 2% buffer.
  - Average residual not degraded by more than 1%.
  - No increase in outlier count (top 1% residuals).

## 10. Rollback Strategy
- If post-retrain residual tail worsens by > target + 5% absolute within 30m, revert to previous config hash.
- Use previous JSONL entry and reload forecaster.

## 11. Security & Integrity
- Config diff endpoint exposes shallow changes only; deep inspection requires manual file review.
- Optionally sign config hash with deployment key (future enhancement).

## 12. Future Enhancements
- Structured store (Parquet) for attribution queries.
- Multi-horizon labeling on acceleration metrics.
- Canary shadow mode continuous evaluation.

## 13. Quick Reference Commands (PowerShell)
```
# Run stress scenario locally
python -m src.ml.load_runner --scenario stress_high_concurrency

# Check retrain trigger manually
python -m src.ml.retrain_trigger --index NIFTY --horizon 60 --url http://localhost:9210 --samples 3

# Fetch config diff
curl http://localhost:9210/api/ml/ensemble/config_diff?index=NIFTY

# Canary eval (Python REPL example)
python - <<'PY'
from src.ml.canary_eval import evaluate_canary
import random
baseline=[100+random.random() for _ in range(600)]
canary=[100+0.95*random.random() for _ in range(600)]
actual=[100+0.9*random.random() for _ in range(600)]
print(evaluate_canary(baseline, canary, actual).to_dict())
PY
```

## 14. Ownership
- Drift / retrain alerts: ML Ops team.
- Performance CI: Platform Engineering.
- Dashboard updates: Observability.

---
This runbook should be reviewed quarterly for threshold tuning and process adjustments.
