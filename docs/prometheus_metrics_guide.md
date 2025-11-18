# Prometheus Metrics Guide

## Overview

The G6 platform exposes Prometheus metrics for path forecast endpoints to enable monitoring and observability of forecast performance and cache efficiency.

## Enabling Metrics

Metrics exposure is controlled by an environment variable:

```bash
export ENABLE_PATH_FORECAST_PROM_METRICS=1
```

When this flag is set, the `/metrics` endpoint will expose Prometheus-formatted metrics. Without this flag, the endpoint returns a 404 response.

## Metrics Endpoint

**URL:** `/metrics`  
**Method:** GET  
**Content-Type:** `text/plain; version=0.0.4`

## Available Metrics

### Forecast Latency

**Name:** `g6_forecast_latency_ms`  
**Type:** Histogram  
**Labels:**
- `index`: Index name (e.g., "NIFTY", "BANKNIFTY")
- `horizon`: Forecast horizon in minutes

**Description:** Distribution of forecast request latency in milliseconds.

**Buckets:** `[1, 5, 10, 25, 50, 100, 250, 500, 1000]`

### Forecast Cache Metrics

#### Cache Hits

**Name:** `g6_forecast_cache_hits_total`  
**Type:** Counter  
**Labels:**
- `index`: Index name

**Description:** Total number of forecast cache hits.

#### Cache Misses

**Name:** `g6_forecast_cache_misses_total`  
**Type:** Counter  
**Labels:**
- `index`: Index name

**Description:** Total number of forecast cache misses.

#### Cache Size

**Name:** `g6_forecast_cache_size`  
**Type:** Gauge  
**Labels:** None

**Description:** Current number of entries in the forecast cache.

### Recent Window Cache Metrics

#### Cache Hits

**Name:** `g6_recent_window_cache_hits_total`  
**Type:** Counter  
**Labels:**
- `index`: Index name

**Description:** Total number of recent window file cache hits.

#### Cache Misses

**Name:** `g6_recent_window_cache_misses_total`  
**Type:** Counter  
**Labels:**
- `index`: Index name

**Description:** Total number of recent window file cache misses.

#### Cache Size

**Name:** `g6_recent_window_cache_size`  
**Type:** Gauge  
**Labels:** None

**Description:** Current number of entries in the recent window file cache.

## Prometheus Scrape Configuration

Add the following to your `prometheus.yml` configuration:

```yaml
scrape_configs:
  - job_name: 'g6_forecast'
    scrape_interval: 15s
    scrape_timeout: 10s
    static_configs:
      - targets: ['localhost:8765']  # Adjust port as needed
    metrics_path: /metrics
```

## Example Queries

### Average Forecast Latency by Index

```promql
rate(g6_forecast_latency_ms_sum[5m]) / rate(g6_forecast_latency_ms_count[5m])
```

### Cache Hit Ratio

```promql
sum(rate(g6_forecast_cache_hits_total[5m])) / 
  (sum(rate(g6_forecast_cache_hits_total[5m])) + sum(rate(g6_forecast_cache_misses_total[5m])))
```

### 95th Percentile Latency

```promql
histogram_quantile(0.95, rate(g6_forecast_latency_ms_bucket[5m]))
```

### Cache Size Over Time

```promql
g6_forecast_cache_size
```

## Alerting Examples

### High Latency Alert

```yaml
- alert: HighForecastLatency
  expr: histogram_quantile(0.95, rate(g6_forecast_latency_ms_bucket[5m])) > 500
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High forecast latency detected"
    description: "95th percentile latency is {{ $value }}ms"
```

### Low Cache Hit Rate

```yaml
- alert: LowCacheHitRate
  expr: |
    sum(rate(g6_forecast_cache_hits_total[10m])) / 
    (sum(rate(g6_forecast_cache_hits_total[10m])) + sum(rate(g6_forecast_cache_misses_total[10m]))) < 0.5
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Low forecast cache hit rate"
    description: "Cache hit rate is {{ $value | humanizePercentage }}"
```

## Grafana Dashboard

Example Grafana dashboard panels:

### Latency Panel

```json
{
  "title": "Forecast Latency (95th Percentile)",
  "targets": [
    {
      "expr": "histogram_quantile(0.95, rate(g6_forecast_latency_ms_bucket[5m]))",
      "legendFormat": "p95"
    }
  ]
}
```

### Cache Hit Rate Panel

```json
{
  "title": "Forecast Cache Hit Rate",
  "targets": [
    {
      "expr": "sum(rate(g6_forecast_cache_hits_total[5m])) / (sum(rate(g6_forecast_cache_hits_total[5m])) + sum(rate(g6_forecast_cache_misses_total[5m])))",
      "legendFormat": "hit_rate"
    }
  ]
}
```

## Performance Considerations

### Latency Overhead

The metrics collection adds minimal overhead:
- Counter increments: ~1-2 microseconds
- Histogram observations: ~5-10 microseconds
- Gauge sets: ~1-2 microseconds

The limited histogram buckets (9 buckets) minimize memory overhead while providing adequate precision for latency tracking.

### Memory Usage

Each metric series consumes approximately:
- Counter: ~100 bytes
- Gauge: ~100 bytes
- Histogram: ~1-2 KB (depending on bucket count)

With typical usage (2-3 indices), total memory overhead is approximately 5-10 KB.

## Troubleshooting

### Metrics Not Available

If `/metrics` returns 404:
1. Verify `ENABLE_PATH_FORECAST_PROM_METRICS=1` is set
2. Restart the application after setting the environment variable
3. Check application logs for initialization errors

### Missing Metrics

If specific metrics are missing:
1. Trigger forecast requests to generate data
2. Verify the forecast cache is being used (cache TTL > 0)
3. Check that recent window data is available

### Scrape Errors

If Prometheus cannot scrape metrics:
1. Verify the application is running and accessible
2. Check firewall rules
3. Verify the correct port in `prometheus.yml`
4. Check application logs for request errors

## Security Considerations

The `/metrics` endpoint does not require authentication by default. In production environments, consider:

1. Restricting access via firewall rules
2. Using a reverse proxy with authentication
3. Exposing metrics on a separate port/interface
4. Using Prometheus federation for multi-tier scraping

## Integration with Ensemble API

The metrics exposed here integrate with the ML Ensemble Forecasting API. For detailed API documentation including:
- Full forecast response schemas
- Cache configuration options
- Common integration patterns
- Phase 9 feature descriptions

See **[ML Ensemble API Reference](./ml/ENSEMBLE_API.md)**.

### Quick Examples for Ensemble API

**Test metrics are being collected:**
```bash
# Make a forecast request
curl "http://localhost:9500/api/ml/ensemble/forecast?index=NIFTY&horizon=60"

# Check metrics were recorded
curl http://localhost:9500/metrics | grep g6_forecast_latency_ms
```

**Monitor cache effectiveness:**
```bash
# Check cache stats via API
curl "http://localhost:9500/api/ml/ensemble/cache/stats" | jq

# Check metrics
curl http://localhost:9500/metrics | grep -E "g6_(forecast|recent_window)_cache"
```

## Related Documentation

- [ML Ensemble API Reference](./ml/ENSEMBLE_API.md) - **Primary API documentation**
- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [G6 Environment Variables Catalog](./ENV_VARS_CATALOG.md)
