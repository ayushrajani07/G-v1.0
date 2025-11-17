# Issue: Prometheus Metrics Export

## Summary
Expose critical performance & cache metrics at `/metrics` when enabled via `ENABLE_PATH_FORECAST_PROM_METRICS=1`.

## Metrics (Initial Set)
| Name | Type | Labels | Description |
|------|------|--------|-------------|
| `g6_forecast_latency_ms` | Histogram | index,horizon | Latency distribution (configure buckets) |
| `g6_forecast_cache_hits_total` | Counter | index | Forecast cache hits |
| `g6_forecast_cache_misses_total` | Counter | index | Forecast cache misses |
| `g6_recent_window_cache_hits_total` | Counter | index | Recent file cache hits |
| `g6_recent_window_cache_misses_total` | Counter | index | Recent file cache misses |
| `g6_forecast_cache_size` | Gauge | - | Current forecast cache entries |
| `g6_recent_window_cache_size` | Gauge | - | Current file cache entries |

## Requirements
- Conditional registration via env flag.
- Use `prometheus_client` (add to requirements if not present).
- Minimal bucket set (e.g., [1,5,10,25,50,100,250,500,1000]).
- Update docs with scrape example.

## Implementation Steps
1. Guard import and registry with env var.
2. Wrap timing around forecast handler for latency observation.
3. Increment hit/miss counters where decisions happen.
4. Set gauges periodically or on request (on each stats call or forecast).

## Acceptance Criteria
- `/metrics` returns all configured metrics only when flag set.
- Default run without flag has no `/metrics` route addition (or returns 404 if not integrated).
- Unit test: parse metrics output and confirm required names exist.

## Risks
Latency overhead— mitigate by limited histogram buckets.
