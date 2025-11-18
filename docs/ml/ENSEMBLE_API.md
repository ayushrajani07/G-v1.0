# Ensemble API Reference

**Version:** 1.3  
**Last Updated:** 2025-11-18  
**Status:** Production (Phase 10 kickoff)

## Overview

The ML Ensemble Forecasting API provides real-time price path predictions combining multiple forecasting models (GBRT, retrieval-based, conformal prediction) with Phase 9 performance optimizations and new Phase 10 observability extensions (latency percentile selector, eviction rate trend).

**Base URL:** `http://localhost:9500/api/ml/ensemble`

**Key Features:**
- Real-time ensemble forecasting with quantile predictions
- Full detail mode with time grid and quantile paths (`detail=full`)
- Caching layer (TTL + LRU bound) with eviction statistics
- Recent window file cache (TTL + size bound, reuse larger window subsets)
- Prometheus metrics export (latency histogram buckets, eviction counter, hit/miss counters)
- Component diagnostics and health checks
- Grafana dashboards (Infinity + JSON API variants) with latency percentile selector
- Backward-compatible API design
 - Regime and drift visibility endpoints and Grafana table panel

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

### 6. Rolling Metrics Comparison (+ Drift)

**`GET /api/ml/ensemble/metrics/compare`**

Compare window vs EMA metrics, with optional drift summary.

Query params:
- `index` (optional)
- `horizon` (optional)
- `include_drift` (0|1, default 0): when 1 and `index` is provided, attaches `drift_summary`:

```json
{
  "...": {},
  "drift_summary": { "index": "NIFTY", "ts_ms": 1700312345678, "alert_count": 2, "feature_count": 25 }
}
```

---

### 7. Regime Status

**`GET /api/ml/ensemble/regime/status`**

Returns last computed regime evaluation summary.

- With `?index=NIFTY`: a single object; 404 if unavailable.
- Without `index`: map of `{ index -> summary }`.

Shape (example):
```json
{
  "index": "NIFTY",
  "ts_ms": 1700312345678,
  "alerts": 1,
  "total_horizons": 6,
  "coverage_min": 0.72,
  "norm_error_p90_max": 0.31,
  "breaches": [
    {"horizon": 60, "coverage_window_pct": 72.5, "norm_error_p90": 0.31, "triggered": true, "reasons": ["coverage<75","norm_p90>0.3"]}
  ]
}
```

---

### 8. Regime Breaches (flat for Grafana)

**`GET /api/ml/ensemble/regime/breaches?index=NIFTY`**

Returns only the `breaches` array for easy table rendering:

```json
[
  {"horizon": 60, "coverage_window_pct": 72.5, "norm_error_p90": 0.31, "triggered": true, "reasons": ["coverage<75","norm_p90>0.3"]}
]
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

### Core

- `ENABLE_PATH_FORECAST_PROM_METRICS` (int, default: `1`): Enables Prometheus metrics export (`/metrics`). Set to `0` to disable.
- `G6_DIAG_ENABLE` (int, default: `1`): Enables diagnostic endpoints.
- `PATH_FORECAST_DISABLE_WEIGHTED` (int, default: `0`): Disable weighted quantile computation (performance fallback).

### Forecast Cache Configuration

- `G6_FORECAST_CACHE_TTL` (int, default: `30`): Time-to-live in seconds for forecast cache entries.
- `G6_FORECAST_CACHE_MAX` (int, default: `500`): Maximum number of forecast cache entries (LRU eviction enforced when exceeded).

### Recent Window File Cache Configuration

Reduces disk I/O and CSV parsing overhead when loading recent TP data.

- `G6_RECENT_FILE_CACHE_TTL` (int, default: `60`): TTL for cached recent window data (set `0` to disable).
- `G6_RECENT_FILE_CACHE_MAX_SIZE` (int, default: `50`): Maximum number of cached recent file windows.

**Recent File Cache Key:** `(index, date_str, window_size)`
- Invalidates automatically on file mtime change.
- Larger cached window can serve smaller requested window sizes.

**Example:**
```bash
export G6_FORECAST_CACHE_TTL=30
export G6_FORECAST_CACHE_MAX=500
export G6_RECENT_FILE_CACHE_TTL=120
export G6_RECENT_FILE_CACHE_MAX_SIZE=100
export ENABLE_PATH_FORECAST_PROM_METRICS=1
export G6_ROLLING_MAE_ENABLE=1
export G6_DRIFT_ENABLE=1
export G6_REGIME_ALERT_ENABLE=1
```

---

## Cache & Metrics Statistics

The `/api/ml/ensemble/cache/stats` endpoint returns statistics for both forecast cache and recent file cache (subset of fields shown). Additional metrics are exposed via Prometheus when `ENABLE_PATH_FORECAST_PROM_METRICS=1`.

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

### Cache Metrics (Prometheus Counters/Gauges)
- `g6_forecast_cache_hits_total`: Total forecast cache hits
- `g6_forecast_cache_misses_total`: Total forecast cache misses
- `g6_forecast_cache_evictions_total`: Total forecast cache evictions (LRU)
- `g6_forecast_cache_size`: Current number of forecast cache entries
- `g6_recent_file_cache_hits_total`: Recent file cache hits
- `g6_recent_file_cache_misses_total`: Recent file cache misses
- `g6_recent_file_cache_entries`: Current recent file cache entry count

### Latency Histogram Metrics
Histogram: `g6_forecast_latency_ms_bucket`, with companion `g6_forecast_latency_ms_sum`, `g6_forecast_latency_ms_count`.

Quantiles (Grafana):
```promql
histogram_quantile(${lat_q}, sum by (le) (rate(g6_forecast_latency_ms_bucket[5m])))
```

Mean latency:
```promql
rate(g6_forecast_latency_ms_sum[5m]) / rate(g6_forecast_latency_ms_count[5m])
```

Eviction rate (LRU pressure):
```promql
rate(g6_forecast_cache_evictions_total[5m])
```

### Dashboard Variables
- `index` (e.g., NIFTY, BANKNIFTY)
- `horizon` (15,30,60,120,240)
- `lat_q` (0.90,0.95,0.99) – used in latency histogram quantile selection

### Operational Notes
- High eviction rate with stable size indicates LRU pressure: consider increasing `G6_FORECAST_CACHE_MAX` or optimizing key cardinality.
- Low hit ratio with frequent evictions may indicate overly aggressive horizon diversity; review typical query distribution.
- Recent file cache hit ratio <50%: consider raising TTL or window reuse strategy.

### Alerting Suggestions
- Latency p95 > 500ms for 5m → Performance degradation alert.
- Eviction rate spikes > 2/sec sustained 5m → Investigate cache size; possible thrashing.
- Cache hit ratio <40% over 15m → Inspect request diversity & TTL.
- Recent file cache hit ratio <50% over 30m → Validate data freshness vs TTL.

The cache layers significantly reduce latency when identical or similar requests recur within TTL windows; latency histogram plus eviction trend aid adaptive tuning in Phase 10.

---

## Prometheus Alert Rules (ML)

Add the ML alerts file to your Prometheus config and reload:

`prometheus.yml` snippet:
```yaml
rule_files:
  - prometheus_alerts.yml
  - prometheus_alerts_ml.yml
```

Example alert ideas covered:
- Regime change detected (`g6_regime_alert_count > 0` for 10m)
- Drift alerts present (`g6_drift_alert_count > 0` for 10m)
- Forecast latency p95 high (from `g6_forecast_latency_ms_bucket`)
- Coverage low (`g6_forecast_coverage_pct < 70` for 15m)
- Normalized error high (`g6_forecast_norm_error > 0.25` for 15m)

---

## Grafana: Regime Breaches Table (Infinity)

Use the Infinity datasource pointing to:
```
http://127.0.0.1:9500/api/ml/ensemble/regime/breaches?index=${index_pick}
```

Panel: Table → Data source: `INFINITY` → Type: JSON → Source: URL.

Recommended panel setup:
- Variable `index_pick` from Prometheus label values (`index` label)
- Columns: `horizon`, `coverage_window_pct` (rename to `coverage%`), `norm_error_p90` (rename to `norm_p90`), `triggered`, `reasons`

---

## Adaptive TTL Prototype (Optional)

When enabled, per-key cache TTL adapts based on IV and recent window volatility.

Env:
```bash
export G6_FORECAST_CACHE_ADAPTIVE_TTL=1
export G6_FORECAST_CACHE_TTL_MIN=10
export G6_FORECAST_CACHE_TTL_MAX=60
export G6_ADAPTIVE_TTL_IV_REF=0.35
export G6_ADAPTIVE_TTL_W_IV=0.7
export G6_ADAPTIVE_TTL_W_WIN=0.3
```

Check current behavior at `/api/ml/ensemble/cache/stats` → `forecast_cache.adaptive=true` and per-entry `ttl_sec`.
