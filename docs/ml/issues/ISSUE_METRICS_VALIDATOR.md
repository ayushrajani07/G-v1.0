# Issue: Metrics Validator Script

## Summary
Provide a script to assert required Prometheus metrics are present & emit JSON summary for CI artifact validation.

## Requirements
- Script: `scripts/ml/validate_metrics.py`.
- Arguments: `--url http://localhost:9500/metrics --required g6_forecast_latency_ms,g6_forecast_cache_hits_total` (comma list).
- Output JSON:
  ```json
  {
    "timestamp": "2025-11-17T12:34:56Z",
    "found": ["g6_forecast_latency_ms", ...],
    "missing": [],
    "latency_histogram_sample": {"count": <int>, "sum": <float>}
  }
  ```
- Exit non‑zero if any required metric missing.

## Implementation Outline
1. GET metrics text; parse lines matching required names.
2. For histogram: parse `_sum` & `_count` if present for sample output.
3. Write JSON to `--out metrics_validation.json`.

## Acceptance Criteria
- Missing metric triggers non-zero exit & CI failure.
- Works locally with metrics enabled; cleanly warns if `/metrics` unreachable.

## Risks
Prometheus format parsing complexity → Keep to simple regex matching.
