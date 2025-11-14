# Ensemble k Operations Guide (recommended_k, k_smooth, applied_k)

Last updated: 2025-11-11

This guide explains how calibrated k flows from recommendation to production use, how to override safely, and how to observe coverage quality.

---
## Key Terms

- recommended_k: Raw calibration output minimizing coverage error over a trailing window.
- k_smooth: EMA-smoothed recommended_k for stability (controls jumpiness across runs).
- applied_k: Final k used operationally by the ensemble exporter (precedence: override > k_smooth > recommended_k).
- scaled_radius: applied_k × disagreement (effective band uses max(conformal_radius, scaled_radius)).
- effective_hit: 1 when consensus lies within the effective band; 0 otherwise.

---
## Data Flow

1) Calibration daemon writes sidecar JSON per (index, horizon):
   data/ml/live_predictions/<INDEX>_ensemble_k_calibration.json
   {
     "timestamp": 1731312345000,
     "recommended_k": 1.35,
     "k_smooth": 1.28,
     "band_radius": 42.1,
     "effective_coverage": 0.79
   }

2) Exporter reads sidecar + optional override and emits:
   data/ml/live_predictions/<INDEX>_ensemble.csv
   ...,applied_k,applied_k_source,scaled_radius,...

3) Prometheus gauges:
   - g6_ml_ensemble_applied_k{index,horizon,source}
   - g6_ml_ensemble_scaled_radius{index,horizon}
   - g6_ml_ensemble_effective_hit{index,horizon}

4) Recording rules (prometheus_rules_ml_applied_k.yml):
   - ml:ensemble:effective_cov_15m / 60m
   - ml:ensemble:applied_k_latest, ml:ensemble:scaled_radius_latest

---
## Override Mechanics

- Endpoint (POST): /api/ml/ensemble/k_override
  Body: { index, horizon, k, ttl_minutes?, actor?, reason?, classification? }
  Notes:
  - actor: freeform user identifier (email, handle)
  - reason: short description; commas will be sanitized in logs/CSV
  - classification: one of emergency | strategic | test | other (freeform accepted)
- Listing (GET): /api/ml/ensemble/k_overrides
  Columns: horizon,k,expires_ms,created_ms,actor,reason,class,source_ip,index
- Applied rows (GET CSV): /api/ml/ensemble/k_applied?index=NIFTY&horizon=60

Precedence: override > k_smooth > recommended_k.

Audit: <INDEX>_ensemble_k_overrides.log lines appended with timestamp, horizon, k, expires_ms, created_ms, and optional actor, reason, class, source_ip.

TTL: Use expires_ms to set automatic expiry; exporter prefers k_smooth after expiry.
Auto-Revert: When run with `--override-auto-revert`, the ensemble exporter monitors calibration sidecar coverage windows (`coverage_fast.value`, `coverage_slow.value`) versus the target (dynamic_target_coverage if present else static target). If both windows remain within `--override-target-tolerance` for `--override-sustain-cycles` consecutive cycles, the active override for that horizon is automatically removed (unless `--dry-run-overrides` is set). Audit lines appended to `<INDEX>_ensemble_k_overrides.log` with `AUTO_REMOVE` reason `coverage_stable` including fast/slow coverage snapshot and tolerance. TTL expiries are also logged with reason `ttl_expired`.
Forecasting Stub: Exporter emits `predicted_disagreement` (EMA forecast) and `projected_radius = max(band_radius, applied_k * predicted_disagreement)` each cycle. Prometheus gauges `g6_ml_ensemble_predicted_disagreement` and `g6_ml_ensemble_disagreement_forecast_mape` track forecast value and one-step MAPE; recording rules derive latest projection and ratios.

Adaptive integration (optional, exporter flags):
- `--use-forecast-floor`: treat `applied_k * predicted_disagreement` as an additional floor when computing the effective band for coverage checks (metrics). This can reduce under-coverage during rising disagreement regimes without changing CSV schema.
- `--inflate-k-from-forecast`: when no manual override is active, proactively inflate `applied_k` so that the current scaled radius anticipates the forecasted disagreement and conforms to the conformal `band_radius` if larger. The applied_k source label is suffixed with `+forecast` when inflation occurs.

Notes: Both options are off by default for backwards compatibility. Enable one or both based on risk appetite; start with `--use-forecast-floor` to get safer coverage without altering k selection, then consider `--inflate-k-from-forecast` once behavior is validated.

---
## Grafana Panels

- Applied k (current & timeline): shows applied vs smooth vs raw with source label.
- Scaled radius trend: monitors band inflation due to disagreement.
- Effective coverage (15m/60m): averages over window; alert bands highlighted.
- Overrides table: active horizon overrides (source: /k_overrides).

---
## Alerts

- MLAppliedKCoverageDriftFast (15m outside [0.75, 0.85], 10m for: warning)
- MLAppliedKCoverageDriftSlow (60m outside [0.76, 0.84], 30m for: info)
- MLAppliedKOverrideActiveLong (>30m continuous override presence)

---
## Operational Procedures

- Normal mode: rely on k_smooth; verify coverage panels remain within bounds.
- Temporary override: create with a clear reason and TTL; monitor coverage and remove early if stable.
- Post-spike recovery: expect k_smooth to drift down; avoid long overrides that fight smoothing.

Governance tips:
- Prefer classification=test for experiments and keep TTL small.
- Use actor consistently to enable audit trails; IP is captured automatically when available.

---
## Troubleshooting

- Coverage under target:
  - Check disagreement spike vs conformal radius; ensure exporter is using applied_k > 0 and columns present.
  - Verify calibration sidecar freshness; restart calibration daemon if stale.
  - Consider short TTL override while smoothing catches up.

- Coverage above target (bands too wide):
  - Confirm smoothing hasn’t lagged post-spike; allow EMA to decay.
  - Remove lingering overrides; check OverrideActiveLong alert and listing endpoint.

- Missing applied_k columns:
  - Ensure exporter version >= Phase 9; confirm headers include applied_k, applied_k_source, scaled_radius.

---
## Tests Reference

- test_ensemble_applied_k.py: smooth preference and override precedence
- test_weighted_ensemble_engine.py: header schema and scaled radius consistency
- test_ml_ensemble_k_endpoint.py: endpoint header correctness (recommended_k, k_smooth)

---
## Appendix: k_smooth vs recommended_k

- recommended_k: raw point estimate; responsive but noisy.
- k_smooth: EMA(m) of recommended_k; trades responsiveness for stability.
- Default choice: exporter prefers k_smooth to avoid jitter; override takes precedence when operator intervention is needed.
