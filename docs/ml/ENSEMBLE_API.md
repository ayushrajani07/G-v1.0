# Ensemble API (FastAPI)

This document describes the Ensemble Forecast API exposed by the unified FastAPI dashboard service.

Base URL: `http://localhost:9500`
Router prefix: `/api/ml/ensemble`

## Endpoints

- `GET /forecast`
  - Returns a snapshot forecast for the requested index and horizon.
  - Default response includes p10/p50/p90 and band_low/band_high.
  - Optional `detail=full` returns arrays for the full time grid (see Response: Full Detail).

- `GET /diagnostics`
  - Lightweight component/weights/confidence view for health checks.

- `GET /confidence`
  - Detailed confidence decomposition (implementation-dependent).

- `POST /retrain`
  - Schedule a retraining job. Body: `{ index, days, run_validation }`.

- `GET /cache/stats`
  - Returns forecast cache size, hits, misses, hit ratio, and entry ages.

- `POST /cache/clear`
  - Clears the in-memory forecast cache and resets counters.

## Query Parameters (Forecast)

- `index` (required): e.g., `NIFTY`, `BANKNIFTY`.
- `horizon` (int, default 60): minutes into the future. Range: 1–720.
- `quantiles` (string, default `0.1,0.5,0.9`): comma-separated quantiles.
- `underlying` (float, default 0.0): current underlying level (optional).
- `avg_iv` (float, default 0.2): average implied volatility proxy.
- `minutes_to_expiry` (float, default 375.0): minutes remaining to expiry.
- `recent_window_size` (int, default 60): number of recent TP rows read from today's CSV (0–200).
- `cache_bust` (0|1, default 0): bypasses in-memory forecast cache when set to 1.
- `detail` (string, optional): if `full`, returns full time grid and per-quantile arrays.

## Request Examples

Snapshot forecast:
```
curl "http://localhost:9500/api/ml/ensemble/forecast?index=NIFTY&horizon=60"
```

Full detail forecast:
```
curl "http://localhost:9500/api/ml/ensemble/forecast?index=NIFTY&horizon=60&detail=full&quantiles=0.1,0.5,0.9&recent_window_size=60"
```

Cache stats and clear:
```
curl http://localhost:9500/api/ml/ensemble/cache/stats
curl -X POST http://localhost:9500/api/ml/ensemble/cache/clear
```

## Responses

Snapshot (default):
```
{
  "index": "NIFTY",
  "horizon": 60,
  "timestamp": "<epoch_ms>",
  "forecast": { "p10": 180.5, "p50": 195.3, "p90": 210.8, "band_low": 178.2, "band_high": 212.5 },
  "confidence": 0.75,
  "metadata": {
    "latency_ms": 6.8,
    "components_used": ["baseline","gbrt","retrieval","conformal"],
    "weights": {"gbrt": 0.70, "retrieval": 0.30},
    "recent_count": 60,
    "cache_hit": false
=======
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
    "recent_count": 60,
    "cache_hit": false

## Quick Start

Run:
python -m uvicorn src.web.dashboard.app:app --host 0.0.0.0 --port 9500
```

Test:
```
python -m pytest -q
```
>>>>>>> 
