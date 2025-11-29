# Phase 11 Dashboard Specification

## New Panels
1. Tail Ratio (Decay p95 5m vs 30m baseline)
   - Metric: `g6_ml_residual_p95_decay:ratio_5m_30m`
   - Target line: `1 - g6_ml_target_mae_p95_improve_pct/100`
2. Tail Burn Rate
   - Metric: `g6_ml_residual_tail_burn:short_long`
   - Threshold bands: 0.05 (warning), 0.10 (critical)
3. Adaptive Retrain Signal
   - Metric: `g6_ml_retrain_signal:smooth_5m`
   - Bands: >=2 warning, >=2.5 critical
4. Trend Ratio Smoothed
   - Metric: `g6_ml_residual_trend_ratio:smooth_5m`
   - Bands: >1.10 watch, >1.25 critical
5. Weight Divergence
   - Metric: `g6_ml_ensemble_weight:divergence`
   - Expectation: >0.08 healthy differentiation; <0.05 watch for convergence
6. Regime Health Class
   - Metric: `g6_ml_residual_health:class`
   - Values: 1 good, 2 watch, 3 bad
7. Target Improvement Gauge
   - Metric: `g6_ml_target_mae_p95_improve_pct` (single value)
   - Display on Tail Ratio panel annotation.

## Panel Layout (2 columns)
Left Column:
- Tail Ratio
- Tail Burn Rate
- Trend Ratio
- Regime Health Class

Right Column:
- Adaptive Retrain Signal
- Weight Divergence
- Target Improvement Gauge (small)

## Annotations
- Tail Ratio panel: show dynamic gap: `tail_ratio - (1 - improve_target/100)`.
- Adaptive Retrain panel: tooltip listing component contributions (tail, trend, burn).

## Alert Integration
- Link each panel to corresponding alert names:
  - Tail Ratio -> MLResidualTailDecayDegraded / Critical
  - Tail Burn -> MLResidualTailBurnFastWarning / Critical
  - Adaptive Retrain -> MLAdaptiveRetrainRecommended / Critical
  - Trend Ratio -> MLResidualTrendWorseningFast / Critical

## Refresh Interval
- 30s aligned with recording rule group interval.

## Future Enhancements
- Add forecasting error distribution sparkline.
- Overlay moving quantiles for retrain signal decomposition.
- Add per-horizon selector (currently aggregate index scope).
- Add Tail Burn Acceleration panel (Phase 12) metric `g6_ml_residual_tail_burn:accel`.
- Show config diff summary counts (added/removed/changed) sourced from `/api/ml/ensemble/config_diff`.
- Integrate attribution CSV recent tail_ratio trend sparkline.
