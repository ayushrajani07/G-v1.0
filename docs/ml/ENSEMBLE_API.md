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
  }
}
```

Full detail (when `detail=full`):
```
{
  "index": "NIFTY",
  "horizon": 60,
  "timestamp": "<epoch_ms>",
  "time_grid": [ <ms_0>, <ms_1>, ... ],
  "quantiles": {
    "0.1": [ v0, v1, ... ],
    "0.5": [ v0, v1, ... ],
    "0.9": [ v0, v1, ... ]
  },
  "metadata": { ... }
}
```

## Recent Window Loading

- CSV locations checked in order:
  - `data/g6_data/<INDEX>/this_month/0/<YYYY-MM-DD>.csv`
  - `data/g6_data/<INDEX>/this_week/0/<YYYY-MM-DD>.csv`
- Extracts `tp` column (or first numeric column if `tp` not found).
- `recent_count` records how many rows were used.

## Caching

- Forecast result cache: in-memory TTL cache keyed by `(index, horizon, quantiles, underlying, avg_iv, minutes_to_expiry, recent_window_size)`.
  - Env: `G6_FORECAST_CACHE_TTL` (seconds, default `30`), `G6_FORECAST_CACHE_MAX` (max entries, default `500`).
  - Endpoints: `/cache/stats`, `/cache/clear`.
- File-level cache for recent window (planned):
  - Env: `G6_RECENT_FILE_CACHE_TTL` (seconds, default `60`).
  - Mtime-aware invalidation.

## Diagnostics

- Enabled when `G6_DIAG_ENABLE=1`.
- `/__diag/pid`, `/__diag/routes`, `/__diag/summary`.

## Metrics (Prometheus)

Planned/expected metric families (names subject to final implementation):
- `g6_forecast_latency_ms` (histogram) — labels: `index`, `horizon`.
- `g6_forecast_cache_hits_total`, `g6_forecast_cache_misses_total` — labels: `index`, `horizon`.
- `g6_recent_file_cache_hits_total`, `g6_recent_file_cache_misses_total` — labels as appropriate.

## Versioning & Compatibility

- Snapshot response is the default and stable.
- `detail=full` is additive; no breaking changes to default response.
- Any schema changes will be guarded by tests and documented here.

## Quick Start

Run:
```
python -m uvicorn src.web.dashboard.app:app --host 0.0.0.0 --port 9500
```

Test:
```
python -m pytest -q
```
