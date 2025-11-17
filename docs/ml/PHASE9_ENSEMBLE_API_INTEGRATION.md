# Phase 9 Ensemble API Integration

**Version:** 1.0  
**Date:** 2025-11-17  
**Status:** Complete

## Overview

Phase 9 performance optimizations are now fully integrated with the Ensemble API, providing:
- Real-time cache performance monitoring
- Enhanced diagnostics with cache metrics
- Load testing with cache statistics
- Easy-to-use demo and monitoring tools

## Quick Start

### 1. Enable Phase 9 Features

```bash
# Enable ANN caches
export ENABLE_ANN_WINDOW_CACHE=1
export ENABLE_ANN_DISK_CACHE=1
export ANN_CACHE_DIR=/var/cache/g6/ann

# Optional: Enable detailed metrics
export ENABLE_PATH_FORECAST_PROM_METRICS=1
```

### 2. Start the Ensemble API

```bash
python -m src.web.api.ml_ensemble --host 0.0.0.0 --port 9210
```

### 3. Check Cache Metrics

```bash
# Interactive demo
python scripts/ml/demo_phase9_api.py --host localhost --port 9210

# Or via curl
curl http://localhost:9210/api/ml/ensemble/cache_metrics | jq
```

## New API Endpoints

### Cache Metrics Endpoint

**Endpoint:** `GET /api/ml/ensemble/cache_metrics`

Returns Phase 9 cache statistics and feature flag status.

**Example Request:**
```bash
curl http://localhost:9210/api/ml/ensemble/cache_metrics
```

**Example Response:**
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

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string | ISO 8601 timestamp of response |
| `feature_flags` | object | Status of Phase 9 feature flags |
| `window_cache` | object | In-memory window cache statistics |
| `disk_cache` | object | Disk cache statistics |

**Window Cache Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | boolean | Whether window cache is enabled |
| `hit_ratio` | number | Cache hit ratio (0.0 to 1.0) |
| `size` | integer | Current number of entries |
| `hits` | integer | Total cache hits |
| `misses` | integer | Total cache misses |
| `evictions` | integer | Total LRU evictions |

**Disk Cache Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `enabled` | boolean | Whether disk cache is enabled |
| `hits` | integer | Total disk cache hits |
| `misses` | integer | Total disk cache misses |
| `saves` | integer | Total disk cache saves |

### Enhanced Diagnostics Endpoint

**Endpoint:** `GET /api/ml/ensemble/diagnostics?index=NIFTY`

The existing diagnostics endpoint now includes cache metrics.

**Example Request:**
```bash
curl "http://localhost:9210/api/ml/ensemble/diagnostics?index=NIFTY"
```

**Example Response (cache metrics highlighted):**
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
  "metrics": {
    "forecast_count_24h": 1440,
    "avg_latency_ms": 310,
    "error_rate_24h": 0.001,
    "window_cache_enabled": true,
    "window_cache_hit_ratio": 0.89,
    "disk_cache_enabled": true,
    "disk_cache_hits": 120
  }
}
```

**New Cache Metrics Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `window_cache_enabled` | boolean | Window cache status |
| `window_cache_hit_ratio` | number | Current hit ratio |
| `disk_cache_enabled` | boolean | Disk cache status |
| `disk_cache_hits` | integer | Disk cache hits |

## Load Testing with Phase 9

The load test script now automatically captures cache metrics.

### Basic Load Test

```bash
# Enable Phase 9 features
export ENABLE_ANN_WINDOW_CACHE=1
export ENABLE_ANN_DISK_CACHE=1
export ANN_CACHE_DIR=/tmp/ann_cache

# Run load test
python scripts/ml/load_test_ensemble.py \
  --index NIFTY \
  --concurrent-requests 100 \
  --duration 300 \
  --output results.json
```

### Load Test Output

The output JSON includes Phase 9 cache metrics:

```json
{
  "timestamp": "2025-11-17T12:00:00",
  "test_config": {
    "index": "NIFTY",
    "concurrent_requests": 100,
    "duration": 300
  },
  "summary": {
    "total_requests": 5000,
    "successful": 4985,
    "throughput": 16.6
  },
  "latency_ms": {
    "mean": 310,
    "p50": 280,
    "p95": 580,
    "p99": 820
  },
  "phase9_cache_metrics": {
    "window_cache": {
      "enabled": true,
      "hit_ratio": 0.92,
      "size": 85,
      "evictions": 15
    },
    "disk_cache": {
      "enabled": true,
      "hits": 450,
      "misses": 50
    }
  }
}
```

### Performance Comparison

Compare baseline vs. Phase 9 optimized performance:

```bash
# 1. Run baseline test (Phase 9 disabled)
unset ENABLE_ANN_WINDOW_CACHE
unset ENABLE_ANN_DISK_CACHE
python scripts/ml/load_test_ensemble.py \
  --index NIFTY \
  --concurrent-requests 100 \
  --duration 300 \
  --output baseline.json

# 2. Run optimized test (Phase 9 enabled)
export ENABLE_ANN_WINDOW_CACHE=1
export ENABLE_ANN_DISK_CACHE=1
export ANN_CACHE_DIR=/tmp/ann_cache
python scripts/ml/load_test_ensemble.py \
  --index NIFTY \
  --concurrent-requests 100 \
  --duration 300 \
  --output optimized.json

# 3. Compare results
python -c "
import json
b = json.load(open('baseline.json'))
o = json.load(open('optimized.json'))

print('Performance Comparison')
print('=' * 50)
print(f'P95 Latency:')
print(f'  Baseline:   {b[\"latency_ms\"][\"p95\"]:.0f}ms')
print(f'  Optimized:  {o[\"latency_ms\"][\"p95\"]:.0f}ms')
improvement = (1 - o['latency_ms']['p95'] / b['latency_ms']['p95']) * 100
print(f'  Improvement: {improvement:.1f}%')
print()

if 'phase9_cache_metrics' in o:
    print('Cache Performance:')
    wc = o['phase9_cache_metrics']['window_cache']
    dc = o['phase9_cache_metrics']['disk_cache']
    print(f'  Window Cache Hit Ratio: {wc[\"hit_ratio\"]:.2%}')
    print(f'  Disk Cache Hit Ratio:   {dc[\"hits\"]/(dc[\"hits\"]+dc[\"misses\"]):.2%}')
"
```

## Demo Script

Use the interactive demo to explore Phase 9 features:

```bash
# Formatted display
python scripts/ml/demo_phase9_api.py --host localhost --port 9210

# JSON output for automation
python scripts/ml/demo_phase9_api.py --host localhost --port 9210 --json

# Specific index
python scripts/ml/demo_phase9_api.py --index BANKNIFTY
```

**Example Output:**
```
======================================================================
  Phase 9 Feature Flags
======================================================================
  ANN Window Cache               ✓ ENABLED
  ANN Disk Cache                 ✓ ENABLED
  Profiling                      ✗ DISABLED
  Prometheus Metrics             ✓ ENABLED
  Disable Weighted Quantiles     ✗ DISABLED

======================================================================
  ANN Window Cache Statistics
======================================================================
  Status:        ENABLED
  Hit Ratio:     89.00%
  Cache Size:    85 entries
  Hits:          450
  Misses:        55
  Evictions:     12

======================================================================
  ANN Disk Cache Statistics
======================================================================
  Status:        ENABLED
  Hits:          120
  Misses:        8
  Hit Ratio:     93.75%
```

## Monitoring and Alerting

### Key Metrics to Monitor

1. **Window Cache Hit Ratio**: Should be >70%
   - Access via: `/api/ml/ensemble/cache_metrics`
   - Alert if <60% after warmup period

2. **Disk Cache Hit Ratio**: Should be >80%
   - Calculate: `hits / (hits + misses)`
   - Alert if <70% in production

3. **P95 Latency Improvement**: Should show ≥30% reduction
   - Compare with baseline measurements
   - Monitor via load test results

### Example Monitoring Script

```bash
#!/bin/bash
# monitor_phase9.sh - Simple monitoring script

API_URL="http://localhost:9210/api/ml/ensemble/cache_metrics"
WARN_THRESHOLD=0.6
CRIT_THRESHOLD=0.5

while true; do
  METRICS=$(curl -s $API_URL)
  HIT_RATIO=$(echo $METRICS | jq -r '.window_cache.hit_ratio // 0')
  
  echo "[$(date)] Window Cache Hit Ratio: $HIT_RATIO"
  
  if (( $(echo "$HIT_RATIO < $CRIT_THRESHOLD" | bc -l) )); then
    echo "CRITICAL: Cache hit ratio below $CRIT_THRESHOLD"
  elif (( $(echo "$HIT_RATIO < $WARN_THRESHOLD" | bc -l) )); then
    echo "WARNING: Cache hit ratio below $WARN_THRESHOLD"
  fi
  
  sleep 60
done
```

## Troubleshooting

### Cache Metrics Not Available

**Symptom:** Cache metrics endpoint returns `{"enabled": false}`

**Solution:**
1. Verify Phase 9 environment variables are set
2. Check that `src/path_forecast/ann_cache.py` module exists
3. Restart API server after setting environment variables

```bash
# Check environment
env | grep -E "ANN_|PATH_FORECAST"

# Set required variables
export ENABLE_ANN_WINDOW_CACHE=1
export ENABLE_ANN_DISK_CACHE=1
export ANN_CACHE_DIR=/tmp/ann_cache

# Restart server
python -m src.web.api.ml_ensemble
```

### Low Cache Hit Ratio

**Symptom:** Window cache hit ratio <60%

**Possible Causes:**
1. Cache size too small for workload
2. High variability in forecast parameters
3. Cache not warmed up yet

**Solutions:**
```bash
# Increase cache size
export ANN_WINDOW_CACHE_MAX_SIZE=200

# Allow warmup period (5-10 minutes)
# Monitor hit ratio over time

# Check cache evictions
curl http://localhost:9210/api/ml/ensemble/cache_metrics | jq '.window_cache.evictions'
```

### Disk Cache Not Saving

**Symptom:** Disk cache saves = 0 after multiple requests

**Possible Causes:**
1. `ANN_CACHE_DIR` not set or invalid
2. Directory permissions issue
3. Disk cache disabled

**Solutions:**
```bash
# Verify directory exists and is writable
mkdir -p /tmp/ann_cache
chmod 755 /tmp/ann_cache

# Set correct environment variable
export ANN_CACHE_DIR=/tmp/ann_cache

# Check disk cache status
curl http://localhost:9210/api/ml/ensemble/cache_metrics | jq '.disk_cache'
```

## Integration Tests

Run the Phase 9 integration tests:

```bash
# All Phase 9 tests (55 tests)
pytest tests/test_phase9*.py tests/test_ensemble_api_phase9.py -v

# Just API integration tests (9 tests)
pytest tests/test_ensemble_api_phase9.py -v

# With coverage
pytest tests/test_ensemble_api_phase9.py --cov=src.web.api.ml_ensemble
```

## Best Practices

1. **Always Enable Window Cache**: Minimal overhead, significant benefit
   ```bash
   export ENABLE_ANN_WINDOW_CACHE=1
   ```

2. **Enable Disk Cache for Production**: Reduces cold-start time
   ```bash
   export ENABLE_ANN_DISK_CACHE=1
   export ANN_CACHE_DIR=/var/cache/g6/ann
   ```

3. **Monitor Cache Metrics**: Check regularly via API
   ```bash
   # Add to cron or monitoring system
   */5 * * * * curl -s http://localhost:9210/api/ml/ensemble/cache_metrics >> /var/log/g6/cache_metrics.log
   ```

4. **Run Baseline Comparison**: Before and after Phase 9 deployment
   ```bash
   # Document baseline performance
   python scripts/ml/load_test_ensemble.py --index NIFTY --output baseline.json
   ```

5. **Gradual Rollout**: Enable features incrementally
   - Week 1: Metrics only
   - Week 2: Window cache
   - Week 3: Disk cache
   - Week 4: Optional weighted quantile toggle

## Related Documentation

- **Phase 9 Developer Guide**: `docs/ml/PHASE9_DEVELOPER_GUIDE.md`
- **Phase 9 Changelog**: `PHASE9_CHANGELOG.md`
- **Performance Baseline**: `docs/ml/PHASE9_PERFORMANCE_BASELINE.md`
- **Core Implementation**: `src/path_forecast/ann_cache.py`

## Support

For issues or questions:
- Review this integration guide
- Check Phase 9 Developer Guide
- Test with demo script: `scripts/ml/demo_phase9_api.py`
- Run integration tests: `pytest tests/test_ensemble_api_phase9.py -v`
- Contact: ml-team@example.com

---

**Last Updated:** 2025-11-17  
**Maintained By:** ML Engineering Team
