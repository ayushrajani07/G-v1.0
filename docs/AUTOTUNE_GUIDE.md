# G6 ML Threshold Auto-Tune (48h)

This guide describes how to tune alert thresholds after collecting 48 hours of telemetry in staging.

Prerequisites:
- Prometheus loads `prometheus_rules_ml_autotune.yml` in staging only.
- Dashboards show suggestions via `g6_ml_autotune_suggestion{dimension=...}`.

Steps (after ~48h):
1. Review suggestions in Grafana:
   - Table panel (add if needed) for `g6_ml_autotune_suggestion` grouped by `dimension`.
   - Focus on: latency z yellow/red, tail-burn yellow/red, weights divergence yellow/red, completeness yellow/green.
2. Compare with current thresholds in dashboards and alerts:
   - Dash thresholds: update `phase13_observability_dashboard.json` and `phase13_ops_dashboard.json` if drift is material.
   - Alert rules: update corresponding `prometheus_alerts_ml*.yml` files.
3. Apply conservative margins:
   - Start with suggested yellow; set red ≈ 1.4–1.6× yellow unless domain requires tighter bounds.
   - For completeness, keep green near suggested and ensure yellow is not above historical 5th percentile + 0.2.
4. Roll out:
   - Commit changes, deploy to staging, observe for 24h.
   - If stable, promote to production.

Notes:
- Suggestions are derived from 48h percentiles; re-run after significant regime changes.
- Avoid frequent flips: keep changes within ±20% unless clearly justified.
