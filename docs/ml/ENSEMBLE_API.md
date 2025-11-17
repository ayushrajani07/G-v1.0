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

Run the server:
```bash
python -m uvicorn src.web.dashboard.app:app --host 0.0.0.0 --port 9500
```

Test the API:
```bash
python -m pytest tests/test_ensemble_api*.py -v
```

---

## Version History

- **v1.1** (2025-11-17): Added `detail=full` mode with time grid and quantile paths
- **v1.0** (2025-11-17): Initial production release with Phase 9 optimizations 
