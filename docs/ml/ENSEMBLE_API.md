# Ensemble API Reference

**Version:** 1.0  
**Last Updated:** 2025-11-17  
**Status:** Production

## Overview

The ML Ensemble Forecasting API provides real-time price path predictions combining multiple forecasting models (GBRT, retrieval-based, conformal prediction) with Phase 9 performance optimizations.

**Base URL:** `http://localhost:9210/api/ml/ensemble`

**Key Features:**
- Real-time ensemble forecasting with quantile predictions
- Phase 9 ANN cache metrics (window + disk cache)
- Component diagnostics and health checks
- Backward-compatible API design

---

## API Endpoints

### 1. Forecast Endpoint

**`GET /api/ml/ensemble/forecast`**

Generate ensemble forecast for a given index and time horizon.

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `index` | string | Yes | - | Index name (e.g., NIFTY, BANKNIFTY) |
| `horizon` | integer | No | 60 | Forecast horizon in minutes (> 0) |
| `detail` | string | No | snapshot | Response detail level: `snapshot` or `full` |

#### Response Schema (detail=snapshot)

**Default response** - Compact quantile summary:

```json
{
  "index": "NIFTY",
  "horizon": 60,
  "timestamp": "2025-11-17T12:34:56.789Z",
  "forecast": {
    "p10": 180.5,
    "p50": 195.3,
    "p90": 210.8,
    "band_low": 178.2,
    "band_high": 212.5
  },
  "confidence": 0.75,
  "metadata": {
    "latency_ms": 310.25,
    "components_used": ["baseline", "gbrt", "retrieval", "conformal"],
    "weights": {
      "gbrt": 0.7,
      "retrieval": 0.3
    }
  }
}
```

**Field Descriptions:**

| Field | Type | Description |
|-------|------|-------------|
| `index` | string | Index identifier |
| `horizon` | integer | Forecast horizon (minutes) |
| `timestamp` | string | ISO 8601 UTC timestamp |
| `forecast.p10` | number | 10th percentile (lower bound) |
| `forecast.p50` | number | 50th percentile (median) |
| `forecast.p90` | number | 90th percentile (upper bound) |
| `forecast.band_low` | number | Confidence band lower limit |
| `forecast.band_high` | number | Confidence band upper limit |
| `confidence` | number | Overall forecast confidence (0-1) |
| `metadata.latency_ms` | number | Request processing time |
| `metadata.components_used` | array | Active forecast components |
| `metadata.weights` | object | Component weights in ensemble |

#### Response Schema (detail=full)

**Full detail** - Time grid with per-quantile arrays:

```json
{
  "index": "NIFTY",
  "horizon": 60,
  "timestamp": "2025-11-17T12:34:56.789Z",
  "forecast": {
    "p10": 180.5,
    "p50": 195.3,
    "p90": 210.8,
    "band_low": 178.2,
    "band_high": 212.5
  },
  "time_grid": {
    "start": "2025-11-17T12:34:56.789Z",
    "end": "2025-11-17T13:34:56.789Z",
    "resolution_minutes": 5,
    "values": [
      {"offset_minutes": 0, "timestamp": "2025-11-17T12:34:56Z"},
      {"offset_minutes": 5, "timestamp": "2025-11-17T12:39:56Z"},
      {"offset_minutes": 10, "timestamp": "2025-11-17T12:44:56Z"}
    ]
  },
  "quantile_paths": {
    "p10": [175.2, 177.8, 180.5],
    "p50": [189.4, 192.1, 195.3],
    "p90": [205.3, 207.9, 210.8]
  },
  "confidence": 0.75,
  "metadata": {
    "latency_ms": 445.67,
    "components_used": ["baseline", "gbrt", "retrieval", "conformal"],
    "weights": {"gbrt": 0.7, "retrieval": 0.3},
    "retrieval_neighbors": 50,
    "conformal_coverage": 0.9
  }
}
```

**Additional Fields (detail=full):**

| Field | Type | Description |
|-------|------|-------------|
| `time_grid` | object | Time axis information |
| `time_grid.resolution_minutes` | integer | Time step resolution |
| `time_grid.values` | array | Timestamp grid points |
| `quantile_paths` | object | Per-quantile time series arrays |
| `quantile_paths.p10` | array | 10th percentile path |
| `quantile_paths.p50` | array | Median path |
| `quantile_paths.p90` | array | 90th percentile path |

#### Example Requests

**Basic forecast (snapshot):**
```bash
curl "http://localhost:9210/api/ml/ensemble/forecast?index=NIFTY&horizon=60"
```

**Full detail forecast:**
```bash
curl "http://localhost:9210/api/ml/ensemble/forecast?index=NIFTY&horizon=60&detail=full"
```

**Multiple horizons comparison:**
```bash
for horizon in 30 60 120; do
  curl "http://localhost:9210/api/ml/ensemble/forecast?index=NIFTY&horizon=$horizon" | jq
done
```

#### Error Responses

| Status | Description | Example |
|--------|-------------|---------|
| 400 | Bad Request | Missing or invalid `index` parameter |
| 404 | Not Found | No configuration for specified index |
| 500 | Internal Server Error | Forecast computation failed |

**Example Error Response:**
```json
{
  "error": "index parameter required"
}
```

---

### 2. Cache Metrics Endpoint

**`GET /api/ml/ensemble/cache_metrics`**

Retrieve Phase 9 cache performance statistics.

#### Query Parameters

None.

#### Response Schema

```json
{
  "timestamp": "2025-11-17T12:34:56.789Z",
  "feature_flags": {
    "ann_window_cache": true,
    "ann_disk_cache": true,
    "profiling": false,
    "prom_metrics": true,
    "disable_weighted": false
  },
  "window_cache": {
    "enabled": true,
    "hit_ratio": 0.89,
    "size": 85,
    "hits": 450,
    "misses": 55,
    "evictions": 12
  },
  "disk_cache": {
    "enabled": true,
    "hits": 120,
    "misses": 8,
    "saves": 8
  }
}
```

**Field Descriptions:**

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string | Response timestamp (ISO 8601) |
| `feature_flags.ann_window_cache` | boolean | ANN window cache enabled |
| `feature_flags.ann_disk_cache` | boolean | ANN disk cache enabled |
| `feature_flags.profiling` | boolean | Detailed profiling enabled |
| `feature_flags.prom_metrics` | boolean | Prometheus metrics enabled |
| `feature_flags.disable_weighted` | boolean | Weighted quantiles disabled |
| `window_cache.enabled` | boolean | Window cache status |
| `window_cache.hit_ratio` | number | Cache hit ratio (0-1) |
| `window_cache.size` | integer | Current cache entries |
| `window_cache.hits` | integer | Total cache hits |
| `window_cache.misses` | integer | Total cache misses |
| `window_cache.evictions` | integer | Total LRU evictions |
| `disk_cache.enabled` | boolean | Disk cache status |
| `disk_cache.hits` | integer | Disk cache hits |
| `disk_cache.misses` | integer | Disk cache misses |
| `disk_cache.saves` | integer | Disk cache writes |

#### Example Requests

**Get cache metrics:**
```bash
curl http://localhost:9210/api/ml/ensemble/cache_metrics | jq
```

**Monitor cache hit ratio:**
```bash
watch -n 5 'curl -s http://localhost:9210/api/ml/ensemble/cache_metrics | jq ".window_cache.hit_ratio"'
```

**Calculate disk cache hit rate:**
```bash
curl -s http://localhost:9210/api/ml/ensemble/cache_metrics | \
  jq '.disk_cache | (.hits / (.hits + .misses))'
```

---

### 3. Diagnostics Endpoint

**`GET /api/ml/ensemble/diagnostics`**

Retrieve system health and component status.

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `index` | string | Yes | - | Index name for diagnostics |

#### Response Schema

```json
{
  "index": "NIFTY",
  "status": "healthy",
  "components": {
    "baseline": true,
    "gbrt": true,
    "retrieval": true,
    "conformal": true
  },
  "weights": {
    "gbrt": 0.7,
    "retrieval": 0.3
  },
  "confidence": 0.75,
  "metrics": {
    "forecast_count_24h": 1440,
    "avg_latency_ms": 310,
    "error_rate_24h": 0.001,
    "window_cache_enabled": true,
    "window_cache_hit_ratio": 0.89,
    "disk_cache_enabled": true,
    "disk_cache_hits": 120
  },
  "model_age_days": 7.2
}
```

**Field Descriptions:**

| Field | Type | Description |
|-------|------|-------------|
| `index` | string | Index identifier |
| `status` | string | Overall health: `healthy`, `degraded`, `error` |
| `components` | object | Component availability flags |
| `weights` | object | Current ensemble weights |
| `confidence` | number | Overall confidence score (0-1) |
| `metrics.forecast_count_24h` | integer | Forecasts in last 24 hours |
| `metrics.avg_latency_ms` | number | Average request latency |
| `metrics.error_rate_24h` | number | Error rate (0-1) |
| `metrics.window_cache_enabled` | boolean | Phase 9 window cache status |
| `metrics.window_cache_hit_ratio` | number | Window cache hit ratio |
| `metrics.disk_cache_enabled` | boolean | Phase 9 disk cache status |
| `metrics.disk_cache_hits` | integer | Disk cache hits |
| `model_age_days` | number | Days since model training |

#### Example Requests

**Get diagnostics:**
```bash
curl "http://localhost:9210/api/ml/ensemble/diagnostics?index=NIFTY" | jq
```

**Check system status:**
```bash
curl -s "http://localhost:9210/api/ml/ensemble/diagnostics?index=NIFTY" | \
  jq -r '.status'
```

**Monitor cache performance:**
```bash
curl -s "http://localhost:9210/api/ml/ensemble/diagnostics?index=NIFTY" | \
  jq '.metrics | {window_hit_ratio, disk_hits}'
```

---

### 4. Health Check Endpoint

**`GET /health`**

Basic service health check (no authentication required).

#### Response Schema

```json
{
  "status": "ok",
  "timestamp": "2025-11-17T12:34:56.789Z",
  "service": "ml_ensemble_api"
}
```

#### Example Request

```bash
curl http://localhost:9210/health
```

---

## Environment Variables

Configure Phase 9 optimizations and API behavior via environment variables.

### Phase 9 Cache Configuration

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `ENABLE_ANN_WINDOW_CACHE` | boolean | 0 (disabled) | Enable in-memory ANN window cache |
| `ANN_WINDOW_CACHE_MAX_SIZE` | integer | 100 | Maximum window cache entries |
| `ENABLE_ANN_DISK_CACHE` | boolean | 0 (disabled) | Enable persistent disk cache |
| `ANN_CACHE_DIR` | path | `/tmp/ann_cache` | Disk cache directory |
| `PATH_FORECAST_DISABLE_WEIGHTED` | boolean | 0 (disabled) | Disable weighted quantiles (10-15% speedup) |

### Monitoring Configuration

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `ENABLE_PATH_FORECAST_PROFILING` | boolean | 0 (disabled) | Enable detailed stage timing logs |
| `ENABLE_PATH_FORECAST_PROM_METRICS` | boolean | 0 (disabled) | Enable Prometheus metrics export |

### API Configuration

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `ML_API_PORT` | integer | 9210 | API server port |
| `ML_API_HOST` | string | `0.0.0.0` | API server bind address |
| `DASHBOARD_API_PORT` | integer | 9500 | Dashboard integration port |

### Example Configurations

**Development (minimal cache):**
```bash
export ENABLE_ANN_WINDOW_CACHE=1
export ANN_WINDOW_CACHE_MAX_SIZE=50
export ENABLE_PATH_FORECAST_PROFILING=1
```

**Production (full optimization):**
```bash
export ENABLE_ANN_WINDOW_CACHE=1
export ANN_WINDOW_CACHE_MAX_SIZE=200
export ENABLE_ANN_DISK_CACHE=1
export ANN_CACHE_DIR=/var/cache/g6/ann
export ENABLE_PATH_FORECAST_PROM_METRICS=1
```

**Performance testing (cache disabled):**
```bash
unset ENABLE_ANN_WINDOW_CACHE
unset ENABLE_ANN_DISK_CACHE
```

### Tuning Guidance

#### Window Cache Size

- **Small workloads (<100 forecasts/day):** `ANN_WINDOW_CACHE_MAX_SIZE=50`
- **Medium workloads (100-1000 forecasts/day):** `ANN_WINDOW_CACHE_MAX_SIZE=100` (default)
- **Large workloads (>1000 forecasts/day):** `ANN_WINDOW_CACHE_MAX_SIZE=200-500`

**Monitor:** Cache hit ratio should be >70%. If evictions are frequent and hit ratio is low, increase cache size.

```bash
# Check current hit ratio
curl -s http://localhost:9210/api/ml/ensemble/cache_metrics | \
  jq '.window_cache.hit_ratio'
```

#### Disk Cache Directory

- **Development:** `/tmp/ann_cache` (default, cleared on reboot)
- **Production:** `/var/cache/g6/ann` (persistent, backed up)
- **High I/O:** SSD-backed directory for best performance

**Disk space:** Allocate ~500MB per index for cache storage.

#### Weighted Quantiles

Disabling weighted quantiles provides 10-15% aggregation speedup with <±2% coverage variance.

**When to disable:**
- Latency is critical (P95 >1s)
- Coverage variance ±2% is acceptable
- High-volume production workloads

**When to keep enabled:**
- Coverage accuracy is critical
- Development/testing environments
- Low-volume workloads

---

## Versioning and Breaking Changes

### API Version

**Current Version:** 1.0 (Stable)

### Versioning Policy

- **Major version** (e.g., 1.0 → 2.0): Breaking changes to response schemas
- **Minor version** (e.g., 1.0 → 1.1): New endpoints or optional parameters (backward compatible)
- **Patch version** (e.g., 1.0.0 → 1.0.1): Bug fixes, performance improvements

### Breaking Changes Policy

**Guaranteed for 1.0.x:**
- `forecast` endpoint response schema (snapshot mode) will not change
- Existing query parameters will remain supported
- HTTP status codes will remain consistent
- Error response format will remain stable

**May change between major versions:**
- Addition of new fields (always backward compatible)
- New optional query parameters
- Internal computation methods (transparent to API consumers)

### Deprecation Process

1. **Announcement:** 90 days before removal
2. **Warning:** Deprecation warnings in response headers
3. **Migration guide:** Provided in documentation
4. **Removal:** Only in major version increments

### Current Guarantees

✅ **Stable (1.0.x):**
- `GET /api/ml/ensemble/forecast` (snapshot response)
- `GET /api/ml/ensemble/cache_metrics`
- `GET /api/ml/ensemble/diagnostics`
- `GET /health`

⚠️ **Experimental (may change in 1.x):**
- `detail=full` response format (may add fields)
- Cache metrics structure (may add metrics)

---

## Performance Characteristics

### Expected Latency (Phase 9 Optimized)

| Scenario | P50 | P95 | P99 |
|----------|-----|-----|-----|
| Cache hit (hot) | 45ms | 120ms | 180ms |
| Cache miss (cold) | 280ms | 580ms | 820ms |
| First request | 450ms | 890ms | 1250ms |

**Phase 9 Improvements:**
- 35% P95 latency reduction with cache enabled
- 89% cold-start reduction with disk cache
- 90% cache hit ratio after warmup (5-10 minutes)

### Throughput

- **Single instance:** 50-100 requests/second
- **With caching:** Up to 200 requests/second (cache hits)
- **Recommended:** 20-50 requests/second per instance for stable P95

### Cache Warm-up

**Warm-up period:** 5-10 minutes or ~100-200 requests

**Strategies:**
1. Pre-warm with common forecasts at startup
2. Allow natural warm-up during low-traffic period
3. Load historical forecast patterns from disk cache

---

## Security and Rate Limiting

### Authentication

**Current:** None (internal service)  
**Planned (2.0):** API key authentication

### Rate Limiting

**Current:** None  
**Recommended:** Reverse proxy rate limiting (e.g., 100 req/min per client)

### Data Privacy

- No PII or sensitive data in API responses
- Forecast data is derived from public market data
- Cache metrics are operational only (no business data)

---

## Monitoring and Observability

### Prometheus Metrics

Available when `ENABLE_PATH_FORECAST_PROM_METRICS=1`:

| Metric | Type | Description |
|--------|------|-------------|
| `g6_forecast_latency_ms` | Histogram | Request latency distribution |
| `g6_forecast_cache_hits_total` | Counter | Total cache hits |
| `g6_forecast_cache_misses_total` | Counter | Total cache misses |
| `g6_ml_ann_cache_hit_ratio` | Gauge | Window cache hit ratio |
| `g6_ml_ann_cache_size` | Gauge | Current cache size |
| `g6_ml_ann_disk_cache_hits` | Counter | Disk cache hits |

**Scrape endpoint:** `http://localhost:9210/metrics`

### Log Levels

Configure via `LOG_LEVEL` environment variable:
- `DEBUG`: All operations including cache hits/misses
- `INFO`: Request/response summaries (default)
- `WARNING`: Degraded performance, high error rates
- `ERROR`: Request failures, system errors

---

## Examples and Recipes

### Load Testing

See [Load Test Documentation](./PHASE9_ENSEMBLE_API_INTEGRATION.md#load-testing-with-phase-9)

```bash
python scripts/ml/load_test_ensemble.py \
  --index NIFTY \
  --concurrent-requests 100 \
  --duration 300 \
  --output results.json
```

### Performance Comparison

```bash
# Baseline (cache disabled)
unset ENABLE_ANN_WINDOW_CACHE
python scripts/ml/load_test_ensemble.py --index NIFTY --output baseline.json

# Optimized (cache enabled)
export ENABLE_ANN_WINDOW_CACHE=1
python scripts/ml/load_test_ensemble.py --index NIFTY --output optimized.json

# Compare
python -c "
import json
b = json.load(open('baseline.json'))
o = json.load(open('optimized.json'))
improvement = (1 - o['latency_ms']['p95'] / b['latency_ms']['p95']) * 100
print(f'P95 Improvement: {improvement:.1f}%')
"
```

### Monitoring Script

```bash
#!/bin/bash
# monitor.sh - Simple health monitoring

while true; do
  STATUS=$(curl -s http://localhost:9210/health | jq -r '.status')
  HIT_RATIO=$(curl -s http://localhost:9210/api/ml/ensemble/cache_metrics | \
    jq -r '.window_cache.hit_ratio // "N/A"')
  
  echo "[$(date)] Status: $STATUS | Cache Hit Ratio: $HIT_RATIO"
  
  sleep 60
done
```

---

## Troubleshooting

### Common Issues

**1. Low cache hit ratio (<60%)**
- Increase `ANN_WINDOW_CACHE_MAX_SIZE`
- Check for high forecast parameter variability
- Allow sufficient warm-up period (5-10 minutes)

**2. High latency (P95 >1s)**
- Enable Phase 9 caches
- Check disk cache directory I/O performance
- Consider disabling weighted quantiles

**3. 404 errors**
- Verify index configuration exists in `configs/ml/`
- Check index name spelling (case-sensitive)

**4. Cache metrics unavailable**
- Verify `src/path_forecast/ann_cache.py` exists
- Check Phase 9 environment variables are set
- Restart API server after setting variables

### Debug Commands

```bash
# Check API health
curl http://localhost:9210/health

# Verify index configuration
curl "http://localhost:9210/api/ml/ensemble/diagnostics?index=NIFTY"

# Check cache status
curl http://localhost:9210/api/ml/ensemble/cache_metrics | jq

# Test forecast
curl "http://localhost:9210/api/ml/ensemble/forecast?index=NIFTY&horizon=60" | jq
```

---

## Related Documentation

- [Phase 9 Developer Guide](./PHASE9_DEVELOPER_GUIDE.md)
- [Phase 9 API Integration](./PHASE9_ENSEMBLE_API_INTEGRATION.md)
- [Performance Baseline](./PHASE9_PERFORMANCE_BASELINE.md)
- [Load Testing Guide](./PHASE9_ENSEMBLE_API_INTEGRATION.md#load-testing-with-phase-9)

---

**Document Version:** 1.0  
**Last Updated:** 2025-11-17  
**Maintained By:** ML Engineering Team  
**Contact:** ml-team@example.com
