# Phase 9 Performance Optimization: Developer Guide

Version: 1.0  
Date: 2025-11-17  
Status: Implemented

## Overview

Phase 9 introduces performance optimizations for the ML path forecast system through intelligent caching, instrumentation, and configurable features. All features are guarded by environment flags for safe rollout and instant rollback.

## Feature Flags

### ANN Window Cache
**Flag:** `ENABLE_ANN_WINDOW_CACHE=1`  
**Purpose:** Enable in-memory caching of ANN window vectors  
**Max Size:** `ANN_WINDOW_CACHE_MAX_SIZE` (default: 100)  
**Impact:** Reduces vector processing time for repeated window configurations

### ANN Disk Cache
**Flag:** `ENABLE_ANN_DISK_CACHE=1`  
**Directory:** `ANN_CACHE_DIR` (required when enabled)  
**Purpose:** Persist ANN indices to disk for cold-start optimization  
**Impact:** ~90% reduction in ANN build time for repeat configurations

### Profiling
**Flag:** `ENABLE_PATH_FORECAST_PROFILING=1`  
**Purpose:** Enable detailed timing and logging  
**Impact:** <2% overhead when disabled, <5% when enabled

### Prometheus Metrics
**Flag:** `ENABLE_PATH_FORECAST_PROM_METRICS=1`  
**Purpose:** Export detailed Prometheus metrics  
**Impact:** Negligible overhead

### Weighted Quantile Simplification
**Flag:** `PATH_FORECAST_DISABLE_WEIGHTED=1`  
**Purpose:** Bypass weighted quantiles for faster aggregation  
**Impact:** 10-15% speedup in aggregation stage, ±2% coverage variance

## Metrics Reference

### ANN Cache Metrics

| Metric Name | Type | Description | Labels |
|------------|------|-------------|--------|
| `g6_ml_ann_cache_hit_ratio` | Gauge | Window cache hit ratio (0-1) | - |
| `g6_ml_ann_cache_size` | Gauge | Current cache size | - |
| `g6_ml_ann_cache_evictions` | Counter | Total evictions | - |
| `g6_ml_ann_disk_cache_hits` | Counter | Disk cache hits | - |
| `g6_ml_ann_disk_cache_load_ms` | Histogram | Disk load time (ms) | - |

### Stage Latency Metrics

| Metric Name | Type | Description | Labels |
|------------|------|-------------|--------|
| `g6_ml_stage_latency_seconds` | Histogram | Stage-level latency | stage, index, horizon |

**Stages:**
- `data_load`: Historical data loading
- `retrieval`: Candidate retrieval
- `ann_build`: ANN index construction
- `ann_reuse`: ANN index cache hit
- `aggregation`: Quantile aggregation
- `conformal`: Conformal calibration

## Configuration

### Modular Config Structure

Phase 9 introduces modular sub-configs for cleaner organization:

```python
from pathlib import Path
from src.path_forecast.config_structs import (
    RetrievalConfig,
    PruningConfig,
    RegimeConfig,
    AnnConfig
)

# New modular approach
pruning = PruningConfig(min_days=7, min_future=60)
regime = RegimeConfig(distance_metric="recent_l2", recent_gamma=0.95)
ann = AnnConfig(use_ann=True, ann_space="cosine", ann_max_candidates=100)

config = RetrievalConfig.from_modular(
    root=Path("/data"),
    window=90,
    k=20,
    pruning=pruning,
    regime=regime,
    ann=ann
)
```

### Backward Compatibility

Legacy flat construction still works:

```python
# Legacy approach (still supported)
config = RetrievalConfig(
    root=Path("/data"),
    window=60,
    k=15,
    min_days=5,
    distance_metric="cosine",
    use_ann=True
)

# Modular configs are auto-populated
assert config.pruning.min_days == 5
assert config.regime.distance_metric == "cosine"
```

## Usage Examples

### Example 1: Enable In-Memory Cache Only

```bash
export ENABLE_ANN_WINDOW_CACHE=1
export ANN_WINDOW_CACHE_MAX_SIZE=200
export ENABLE_PATH_FORECAST_PROM_METRICS=1

# Start your forecast service
python src/unified_main.py
```

Expected: 
- Cache hit ratio >70% after warmup
- 20-30% latency reduction for repeated requests

### Example 2: Enable Disk Cache for Cold-Start

```bash
export ENABLE_ANN_DISK_CACHE=1
export ANN_CACHE_DIR=/var/cache/g6/ann
export ENABLE_ANN_WINDOW_CACHE=1
export ENABLE_PATH_FORECAST_PROM_METRICS=1

# Ensure cache directory exists
mkdir -p /var/cache/g6/ann

# Start your forecast service
python src/unified_main.py
```

Expected:
- First run: Builds and saves ANN index
- Subsequent runs: Loads from disk (~90% faster)

### Example 3: Disable Weighted Quantiles

```bash
export PATH_FORECAST_DISABLE_WEIGHTED=1
export ENABLE_PATH_FORECAST_PROFILING=1

# Run forecast
python scripts/ml/evaluate_by_regime.py
```

Expected:
- 10-15% faster aggregation
- Coverage within ±2% of baseline

### Example 4: Parallel Grid Evaluation

```bash
# Generate default configs
python scripts/ml/grid_eval_parallel.py \\
    --generate-default-config \\
    --workers 8 \\
    --output results/eval_$(date +%Y%m%d).json \\
    --output-csv results/eval_$(date +%Y%m%d).csv

# Or use custom config
python scripts/ml/grid_eval_parallel.py \\
    --config configs/grid_eval_custom.json \\
    --workers 4 \\
    --output results/custom_eval.json
```

## Performance Benchmarking

### Baseline Measurement

```bash
# Measure baseline (all flags off)
export ENABLE_PATH_FORECAST_PROFILING=1

python scripts/ml/load_test_ensemble.py \\
    --concurrent-requests 50 \\
    --duration 300 \\
    --index NIFTY \\
    --output baseline_metrics.json
```

### Optimized Measurement

```bash
# Measure with optimizations
export ENABLE_ANN_WINDOW_CACHE=1
export ENABLE_ANN_DISK_CACHE=1
export ANN_CACHE_DIR=/var/cache/g6/ann
export ENABLE_PATH_FORECAST_PROFILING=1

python scripts/ml/load_test_ensemble.py \\
    --concurrent-requests 50 \\
    --duration 300 \\
    --index NIFTY \\
    --output optimized_metrics.json
```

### Comparing Results

```python
import json

with open("baseline_metrics.json") as f:
    baseline = json.load(f)

with open("optimized_metrics.json") as f:
    optimized = json.load(f)

p95_baseline = baseline["latency_p95"]
p95_optimized = optimized["latency_p95"]
improvement = (p95_baseline - p95_optimized) / p95_baseline * 100

print(f"P95 latency improvement: {improvement:.1f}%")
```

## Troubleshooting

### Issue: Low Cache Hit Ratio

**Symptoms:** `g6_ml_ann_cache_hit_ratio` < 0.5  
**Causes:**
- Cache too small: Increase `ANN_WINDOW_CACHE_MAX_SIZE`
- High request variance: Different windows/params between requests
- Cache not warmed up: Wait for more requests

**Solution:**
```bash
export ANN_WINDOW_CACHE_MAX_SIZE=500  # Increase from default 100
```

### Issue: Disk Cache Not Loading

**Symptoms:** Disk cache hits = 0, ANN build time not reduced  
**Causes:**
- Directory not writable: Check permissions on `ANN_CACHE_DIR`
- Version mismatch: Model ID changed
- Corrupted cache: Files damaged

**Solution:**
```bash
# Check permissions
ls -la $ANN_CACHE_DIR

# Clear cache if corrupted
rm -rf $ANN_CACHE_DIR/*

# Restart service to rebuild
```

### Issue: High Overhead from Profiling

**Symptoms:** Latency increased >5% with profiling enabled  
**Cause:** Excessive logging or metric collection

**Solution:**
```bash
# Disable profiling in production
unset ENABLE_PATH_FORECAST_PROFILING

# Keep metrics only
export ENABLE_PATH_FORECAST_PROM_METRICS=1
```

### Issue: NaN in Metrics

**Symptoms:** Prometheus shows NaN or Inf values  
**Causes:**
- Division by zero in cache stats
- Invalid forecast values

**Solution:**
- Check logs for warnings
- Verify input data quality
- Review recent code changes

## Rollback Procedures

### Complete Rollback

```bash
# Disable all Phase 9 features
unset ENABLE_ANN_WINDOW_CACHE
unset ENABLE_ANN_DISK_CACHE
unset PATH_FORECAST_DISABLE_WEIGHTED
unset ENABLE_PATH_FORECAST_PROFILING
unset ENABLE_PATH_FORECAST_PROM_METRICS

# Restart service
systemctl restart g6-forecast-service
```

**Expected:** Behavior returns to baseline (±2% latency variance acceptable)

### Selective Rollback

Disable only problematic feature:

```bash
# Disable only disk cache
unset ENABLE_ANN_DISK_CACHE

# Keep other optimizations
export ENABLE_ANN_WINDOW_CACHE=1
export ENABLE_PATH_FORECAST_PROM_METRICS=1

# Restart service
systemctl restart g6-forecast-service
```

### Validation After Rollback

```bash
# Run health check
python scripts/ml/daily_health_check.py

# Compare metrics to pre-Phase-9 baseline
python scripts/ml/compare_metrics.py \\
    --baseline baselines/phase8_metrics.json \\
    --current current_metrics.json
```

## Integration Testing

### Flag Gating Test

```python
import os
from src.path_forecast.ann_cache import get_ann_windows, put_ann_windows

# Test cache disabled by default
result = get_ann_windows("NIFTY", "this_week", "0", 60, 100, "cosine", 60, ("file1.csv",))
assert result is None

# Test cache enabled
os.environ["ENABLE_ANN_WINDOW_CACHE"] = "1"
put_ann_windows("NIFTY", "this_week", "0", 60, 100, "cosine", 60, ("file1.csv",), [[1.0]], [])
result = get_ann_windows("NIFTY", "this_week", "0", 60, 100, "cosine", 60, ("file1.csv",))
assert result is not None
```

### Disk Cache Cycle Test

```python
import tempfile
from pathlib import Path
from src.path_forecast.ann_cache import save_ann_index_to_disk, load_ann_index_from_disk

os.environ["ENABLE_ANN_DISK_CACHE"] = "1"

with tempfile.TemporaryDirectory() as tmpdir:
    os.environ["ANN_CACHE_DIR"] = tmpdir
    
    # Save
    success = save_ann_index_to_disk("NIFTY", "this_week", "0", 60, "cosine", 60, {"data": "test"}, [])
    assert success
    
    # Load
    result = load_ann_index_from_disk("NIFTY", "this_week", "0", 60, "cosine", 60)
    assert result is not None
    assert result["ann_index"]["data"] == "test"
```

## Monitoring Checklist

- [ ] `g6_ml_ann_cache_hit_ratio` > 0.7
- [ ] `g6_ml_ann_disk_cache_hits` increasing over time
- [ ] P95 latency reduced by ≥30%
- [ ] No NaN/Inf in Prometheus metrics
- [ ] Error rate unchanged from baseline
- [ ] Coverage variance within ±2%

## Ensemble API Integration

### Phase 9 Optimizations in Ensemble API

Phase 9 optimizations are automatically available through the Ensemble API when feature flags are enabled. The API provides dedicated endpoints for monitoring cache performance.

### New API Endpoints

#### Cache Metrics Endpoint

```bash
GET /api/ml/ensemble/cache_metrics
```

Returns Phase 9 cache statistics and feature flag status.

**Example Response:**
```json
{
  "timestamp": "2025-11-17T12:00:00Z",
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
    "evictions": 12,
    "hits": 450,
    "misses": 55
  },
  "disk_cache": {
    "enabled": true,
    "hits": 120,
    "misses": 8,
    "saves": 8
  }
}
```

#### Enhanced Diagnostics Endpoint

The existing diagnostics endpoint now includes cache metrics:

```bash
GET /api/ml/ensemble/diagnostics?index=NIFTY
```

Cache information is included in the `metrics` section:
```json
{
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

### Load Testing with Phase 9

The load test script now captures cache metrics:

```bash
# Run load test with Phase 9 enabled
export ENABLE_ANN_WINDOW_CACHE=1
export ENABLE_ANN_DISK_CACHE=1
export ANN_CACHE_DIR=/tmp/ann_cache

python scripts/ml/load_test_ensemble.py \
  --index NIFTY \
  --concurrent-requests 100 \
  --duration 300 \
  --output results.json
```

The output JSON includes Phase 9 cache metrics:
```json
{
  "phase9_cache_metrics": {
    "window_cache": {
      "enabled": true,
      "hit_ratio": 0.92,
      "size": 85
    },
    "disk_cache": {
      "enabled": true,
      "hits": 450
    }
  }
}
```

### Performance Comparison

To compare performance with and without Phase 9:

```bash
# Baseline (Phase 9 disabled)
unset ENABLE_ANN_WINDOW_CACHE
unset ENABLE_ANN_DISK_CACHE
python scripts/ml/load_test_ensemble.py --index NIFTY --output baseline.json

# With Phase 9 enabled
export ENABLE_ANN_WINDOW_CACHE=1
export ENABLE_ANN_DISK_CACHE=1
export ANN_CACHE_DIR=/tmp/ann_cache
python scripts/ml/load_test_ensemble.py --index NIFTY --output optimized.json

# Compare results
python -c "
import json
b = json.load(open('baseline.json'))
o = json.load(open('optimized.json'))
print(f'P95 latency improvement: {(1 - o[\"latency_ms\"][\"p95\"] / b[\"latency_ms\"][\"p95\"]) * 100:.1f}%')
print(f'Cache hit ratio: {o.get(\"phase9_cache_metrics\", {}).get(\"window_cache\", {}).get(\"hit_ratio\", 0):.2%}')
"
```

## Support

For issues or questions:
- Check logs with `ENABLE_PATH_FORECAST_PROFILING=1`
- Review Prometheus metrics
- Test cache metrics endpoint: `/api/ml/ensemble/cache_metrics`
- Consult test cases in `tests/test_phase9_*.py` and `tests/test_ensemble_api_phase9.py`
- Contact ML Engineering Team: ml-team@example.com
