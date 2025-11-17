# Ensemble API Reference

**Version:** 1.1  
**Last Updated:** 2025-11-17  
**Status:** Production

## Overview

The ML Ensemble Forecasting API provides real-time price path predictions combining multiple forecasting models (GBRT, retrieval-based, conformal prediction) with Phase 9 performance optimizations.

**Base URL:** `http://localhost:9500/api/ml/ensemble`

**Key Features:**
- Real-time ensemble forecasting with quantile predictions
- Full detail mode with time grid and quantile paths
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
| `horizon` | integer | No | 60 | Forecast horizon in minutes (1-720) |
| `quantiles` | string | No | "0.1,0.5,0.9" | Comma-separated quantiles |
| `underlying` | float | No | 0.0 | Current underlying level (optional, inferred if 0) |
| `avg_iv` | float | No | 0.2 | Average implied volatility proxy |
| `minutes_to_expiry` | float | No | 375.0 | Minutes remaining to expiry |
| `recent_window_size` | int | No | 60 | Number of recent TP rows (0-200) |
| `cache_bust` | int | No | 0 | Set to 1 to bypass cache |
| `detail` | string | No | - | Response detail level: `full` for time grid and paths |

#### Response Schema (detail=snapshot, default)

**Default response** - Compact quantile summary:

```json
{
  "index": "NIFTY",
  "horizon": 60,
  "timestamp": "1700226896789",
  "forecast": {
    "p10": 180.5,
    "p50": 195.3,
    "p90": 210.8,
    "band_low": 178.2,
    "band_high": 212.5
  },
  "confidence": 0.75,
  "metadata": {
    "latency_ms": 6.8,
    "components_used": ["baseline", "gbrt", "retrieval", "conformal"],
    "weights": {"gbrt": 0.70, "retrieval": 0.30},
    "recent_count": 60,
    "cache_hit": false
  }
}
```

#### Response Schema (detail=full)

**Full detail response** - Includes time grid and per-quantile paths:

```json
{
  "index": "NIFTY",
  "horizon": 60,
  "timestamp": "1700226896789",
  "forecast": {
    "p10": 180.5,
    "p50": 195.3,
    "p90": 210.8,
    "band_low": 178.2,
    "band_high": 212.5
  },
  "confidence": 0.75,
  "metadata": {
    "latency_ms": 6.8,
    "components_used": ["baseline", "gbrt", "retrieval", "conformal"],
    "weights": {"gbrt": 0.70, "retrieval": 0.30},
    "recent_count": 60,
    "cache_hit": false
  },
  "time_grid": {
    "start": 1700226896789,
    "end": 1700230496789,
    "resolution_ms": 60000,
    "values": [1700226896789, 1700226956789, 1700227016789, ...]
  },
  "quantile_paths": {
    "p10": [180.5, 181.2, 182.0, 182.8, ...],
    "p50": [195.3, 196.1, 196.8, 197.5, ...],
    "p90": [210.8, 211.5, 212.2, 212.9, ...]
  }
}
```

**Fields specific to `detail=full`:**
- `time_grid`: Object containing:
  - `start`: Start timestamp (epoch ms)
  - `end`: End timestamp (epoch ms)
  - `resolution_ms`: Time step resolution (typically 60000 for 1-minute buckets)
  - `values`: Array of timestamps for each forecast point
- `quantile_paths`: Object mapping quantile labels (e.g., "p10", "p50", "p90") to arrays of forecast values
  - Each array has the same length as `time_grid.values`
  - Quantile labels are normalized from float values (0.1 → "p10", 0.5 → "p50", etc.)
  - All requested quantiles are included

**Notes:**
- The snapshot fields (`forecast`, `confidence`, `metadata`) are preserved in full detail mode for backward compatibility
- Empty or zero-length sequences are returned as empty arrays, never null
- Time grid length depends on horizon and resolution (e.g., 60-minute horizon with 1-minute resolution = 61 points including start)

---

### 2. Diagnostics Endpoint

**`GET /api/ml/ensemble/diagnostics`**

Returns health status, component availability, and metrics.

```
curl "http://localhost:9500/api/ml/ensemble/diagnostics?index=NIFTY"
```

---

### 3. Confidence Endpoint

**`GET /api/ml/ensemble/confidence`**

Returns confidence score and contributing factors.

```
curl "http://localhost:9500/api/ml/ensemble/confidence?index=NIFTY"
```

---

### 4. Retrain Endpoint

**`POST /api/ml/ensemble/retrain`**

Schedule a model retraining job.

```
curl -X POST "http://localhost:9500/api/ml/ensemble/retrain" \
  -H "Content-Type: application/json" \
  -d '{"index": "NIFTY", "days": 60, "run_validation": true}'
```

---

### 5. Cache Stats Endpoint

**`GET /api/ml/ensemble/cache/stats`**

Returns forecast cache statistics.

```
curl "http://localhost:9500/api/ml/ensemble/cache/stats"
```

---

### 6. Cache Clear Endpoint

**`POST /api/ml/ensemble/cache/clear`**

Clears the in-memory forecast cache.

```
curl -X POST "http://localhost:9500/api/ml/ensemble/cache/clear"
```

---

## Request Examples

### Snapshot forecast (default)
```bash
curl "http://localhost:9500/api/ml/ensemble/forecast?index=NIFTY&horizon=60"
```

### Full detail forecast with time grid and quantile paths
```bash
curl "http://localhost:9500/api/ml/ensemble/forecast?index=NIFTY&horizon=60&detail=full&quantiles=0.1,0.5,0.9"
```

### Custom quantiles with full detail
```bash
curl "http://localhost:9500/api/ml/ensemble/forecast?index=NIFTY&horizon=120&detail=full&quantiles=0.05,0.25,0.5,0.75,0.95"
```

---

## Quick Start

Run:
```bash
python -m uvicorn src.web.dashboard.app:app --host 0.0.0.0 --port 9500
```

Test:
```bash
python -m pytest -q
```

---

## Environment Variables

### Forecast Cache Configuration

- `G6_FORECAST_CACHE_TTL` (int, default: `30`): Time-to-live in seconds for forecast cache entries.

### Recent Window File Cache Configuration

The recent window file cache reduces disk I/O and CSV parsing overhead when loading recent TP data:

- `G6_RECENT_FILE_CACHE_TTL` (int, default: `60`): Time-to-live in seconds for cached recent window data. Set to `0` to disable caching.
- `G6_RECENT_FILE_CACHE_MAX_SIZE` (int, default: `50`): Maximum number of cache entries. Oldest entries are evicted when limit is reached.

**Cache Key:** `(index, date_str, window_size)`
- Cache automatically invalidates when file mtime changes
- Cache can reuse larger windows for smaller requests (e.g., cached 100 rows can serve request for 60 rows)

**Example:**
```bash
export G6_RECENT_FILE_CACHE_TTL=120
export G6_RECENT_FILE_CACHE_MAX_SIZE=100
```

---

## Cache Statistics

The `/api/ml/ensemble/cache/stats` endpoint returns statistics for both forecast cache and recent file cache:

**Response Structure:**
```json
{
  "forecast_cache": {
    "ttl_sec": 30,
    "size": 5,
    "hits": 120,
    "misses": 25,
    "hit_ratio": 0.8276,
    "oldest_age_sec": 28.5,
    "newest_age_sec": 1.2,
    "entries": [...]
  },
  "recent_file_cache": {
    "ttl_sec": 60,
    "max_size": 50,
    "current_entries": 3,
    "hits": 450,
    "misses": 80,
    "hit_ratio": 0.8491,
    "oldest_age_sec": 55.3,
    "newest_age_sec": 2.1,
    "entries": [
      {
        "key": {
          "index": "NIFTY",
          "date": "2025-11-17",
          "window_size": 60
        },
        "age_sec": 15.2,
        "row_count": 60
      }
    ]
  }
}
```

**Cache Metrics:**
- `recent_file_cache_hits`: Number of times data was served from cache
- `recent_file_cache_misses`: Number of times data was loaded from disk
- `recent_file_cache_current_entries`: Current number of entries in cache

The cache significantly reduces latency when the same recent window is requested multiple times within the TTL period.

---

## Prometheus Metrics

The ensemble API exposes Prometheus metrics when enabled via `ENABLE_PATH_FORECAST_PROM_METRICS=1`.

### Available Metrics

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `g6_forecast_latency_ms` | Histogram | `index`, `horizon` | Distribution of forecast request latency in milliseconds |
| `g6_forecast_cache_hits_total` | Counter | `index` | Total number of forecast cache hits |
| `g6_forecast_cache_misses_total` | Counter | `index` | Total number of forecast cache misses |
| `g6_forecast_cache_size` | Gauge | - | Current number of entries in forecast cache |
| `g6_recent_window_cache_hits_total` | Counter | `index` | Total number of recent window file cache hits |
| `g6_recent_window_cache_misses_total` | Counter | `index` | Total number of recent window file cache misses |
| `g6_recent_window_cache_size` | Gauge | - | Current number of entries in recent window cache |

### Example Queries

**Check forecast latency:**
```bash
curl http://localhost:9500/metrics | grep g6_forecast_latency_ms
```

**Monitor cache hit ratio:**
```bash
curl http://localhost:9500/metrics | grep -E "g6_forecast_cache_(hits|misses)_total"
```

**Check recent window cache performance:**
```bash
curl http://localhost:9500/metrics | grep g6_recent_window_cache
```

For complete Prometheus integration guide, see [`docs/prometheus_metrics_guide.md`](../prometheus_metrics_guide.md).

---

## Common Integration Patterns

### 1. Polling for Updates

Poll the forecast endpoint at regular intervals to track market predictions:

```bash
# Poll every 30 seconds
while true; do
  curl -s "http://localhost:9500/api/ml/ensemble/forecast?index=NIFTY&horizon=60" | jq '.forecast'
  sleep 30
done
```

### 2. Diffing Snapshots

Compare consecutive forecasts to identify significant changes:

```python
import requests
import time
import json

def get_forecast(index="NIFTY", horizon=60):
    url = f"http://localhost:9500/api/ml/ensemble/forecast"
    params = {"index": index, "horizon": horizon}
    return requests.get(url, params=params).json()

def diff_forecasts(old, new):
    """Compare two forecast snapshots."""
    changes = {}
    for key in ['p10', 'p50', 'p90']:
        old_val = old['forecast'].get(key, 0)
        new_val = new['forecast'].get(key, 0)
        change_pct = ((new_val - old_val) / old_val * 100) if old_val != 0 else 0
        changes[key] = {
            'old': old_val,
            'new': new_val,
            'change_pct': round(change_pct, 2)
        }
    return changes

# Example usage
old_forecast = get_forecast()
time.sleep(60)
new_forecast = get_forecast()
print(json.dumps(diff_forecasts(old_forecast, new_forecast), indent=2))
```

### 3. Path Visualization

Use `detail=full` mode to retrieve time series data for visualization:

```python
import requests
import matplotlib.pyplot as plt
from datetime import datetime

def visualize_forecast_paths(index="NIFTY", horizon=120):
    url = "http://localhost:9500/api/ml/ensemble/forecast"
    params = {
        "index": index,
        "horizon": horizon,
        "detail": "full",
        "quantiles": "0.1,0.5,0.9"
    }
    
    response = requests.get(url, params=params).json()
    
    # Extract time grid and paths
    time_values = [datetime.fromtimestamp(t/1000) for t in response['time_grid']['values']]
    
    # Plot quantile paths
    plt.figure(figsize=(12, 6))
    plt.plot(time_values, response['quantile_paths']['p10'], label='P10', linestyle='--')
    plt.plot(time_values, response['quantile_paths']['p50'], label='P50 (Median)', linewidth=2)
    plt.plot(time_values, response['quantile_paths']['p90'], label='P90', linestyle='--')
    plt.fill_between(time_values, 
                     response['quantile_paths']['p10'], 
                     response['quantile_paths']['p90'], 
                     alpha=0.2)
    
    plt.xlabel('Time')
    plt.ylabel('Forecast Value')
    plt.title(f'{index} Ensemble Forecast - {horizon} min horizon')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()

# Example usage
visualize_forecast_paths(index="NIFTY", horizon=120)
```

---

## Versioning & Deprecation Guarantees

**Current Version:** 1.1

### API Stability Commitment

- **Backward Compatibility:** All existing response fields are guaranteed to remain stable across minor version updates (1.x).
- **Additive Changes Only:** New fields may be added without version bump; clients should ignore unknown fields.
- **Deprecation Notice:** Any field deprecation will include:
  - Minimum 2 minor version notice period
  - Warning headers in API responses
  - Migration guide in release notes
- **Breaking Changes:** Major version bump (2.0) required for:
  - Removing or renaming existing fields
  - Changing field types or semantics
  - Modifying default behavior

### Current Guarantees

- **Port 9500** confirmed as stable production port
- **Full detail mode** (`detail=full`) schema locked for Phase 9
- **Cache TTL** environment variables maintain backward compatibility with defaults
- **Metrics endpoint** (`/metrics`) contract stable when `ENABLE_PATH_FORECAST_PROM_METRICS=1`

For detailed deprecation timeline and migration paths, see [`docs/DEPRECATIONS.md`](../DEPRECATIONS.md).

---

## Phase 9 Issue Traceability

This API implementation incorporates features from the following Phase 9 issues:

- **ISSUE_FULL_DETAIL_MODE.md** - Time grid and quantile paths support
- **ISSUE_FORECAST_CACHE_LRU.md** - Forecast cache with TTL configuration
- **ISSUE_RECENT_WINDOW_FILE_CACHE.md** - Recent window file caching optimization
- **ISSUE_PROMETHEUS_METRICS.md** - Prometheus metrics exposure
- **ISSUE_ASYNC_LOAD_TEST_AND_CI.md** - Load testing and CI integration
- **ISSUE_METRICS_VALIDATOR.md** - Metrics validation and integrity
- **ISSUE_DOCS_HARDENING.md** - Documentation consolidation (this document)

See [`docs/ml/issues/`](./issues/) for detailed implementation specifications. 
