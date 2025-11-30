# Phase 13 Consolidation

Summary of metrics, panels, and acceptance gates for Phase 13 finalization.

## Metrics (Prometheus)
- `g6_ml_api_latency_anomaly{index,horizon}`: rolling z-score anomaly level
- `g6_ml_retrieval_success_ratio{index,horizon}`: successful retrievals / attempts
- `g6_ml_feature_completeness_ratio{index,horizon}`: present features / required set
- `g6_ml_tail_burn_accel{index,horizon}`: tail burn acceleration indicator

## Active Alerts
- `G6ApiLatencyAnomalySevere`: z-score > 5 for 2m (critical)
- `G6RetrievalSuccessDegradation`: success ratio < 0.6 for 5m (warning)
- `G6FeatureCompletenessLow`: completeness < 0.5 for 10m (warning)

## Panels (Dashboard)
- SSE sparkline: latency anomaly vs horizon per index
- Retrieval health band: success ratio and completeness overlay
- Drift components: tail burn acceleration, weight divergence tracker

## Acceptance Gates
- All metrics scraped across relevant indices/horizons
- Dashboard panels show live values without errors
- Alerts firing under synthetic thresholds in staging; no false positives in burn-in
- Config signing present; integrity endpoint returns manifest digest

## Notes
- Cardinality control: labels restricted to `(index,horizon)`
- Follow-up: adaptive tuner design (Phase 15) consumes latency anomaly buffer