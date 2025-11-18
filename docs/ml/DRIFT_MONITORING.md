# Drift Monitoring (Phase 10) – Placeholder

This document is a placeholder. Remote agent will populate with:

## Planned Content
- Overview of drift detection goals
- Feature selection & grouping (price-derived, IV, Greeks, liquidity)
- Metrics: Population Stability Index (PSI), KS test p-value, mean delta Z-score, variance ratio
- Thresholds & alert logic
- Prometheus metrics reference (`g6_feature_psi`, `g6_feature_drift_flag`, etc.)
- Endpoint schema: `/api/ml/ensemble/drift?index=...&features=...&full=1`
- Operational playbook (investigation & remediation steps)
- Baseline refresh policy (scheduled vs manual)

## Current Status
Implementation pending. Stubs added:
- Module: `src/ml/drift_monitor.py`
- Endpoint placeholder: `/api/ml/ensemble/drift` (returns 501)
- Prometheus placeholder setters in `prom_metrics.py`

## Next Steps
1. Implement baseline loader & recent window sampler
2. Calculate PSI / KS / delta metrics
3. Persist baselines under `metrics/drift_baselines/`
4. Expose gauges & finalize endpoint response schema
5. Add Grafana panels and alert rules

---
_Last updated: 2025-11-18 (placeholder)_
