# Progress Summary — 2025-11-06

This document captures what we delivered for the intraday path-forecasting service, how it was validated, open items, and how to resume later.

## Delivered in this iteration

- FastAPI backend: endpoints and contracts
  - Ribbons: `/api/ml/path_forecast_json` (JSON) and CSV counterpart
  - Meta: `/api/ml/path_forecast_meta` (mode, retrieval details, gen timestamps, calibration snapshot, source day/status)
  - Diagnostics/Stats: endpoints for quick checks and windows (unchanged contracts)
  - Advisor (+flags): thresholds, saturation, and flags; panel-friendly outputs
  - Calibration: compute-only GET and persist POST
    - GET: `/api/ml/path_calibrate_now` (requires `confirm=true` guard for safety)
    - POST: `/api/ml/path_calibrate` (persists snapshot and appends history)
  - Coverage history: `/api/ml/path_coverage_history` (JSON) and `_csv`
  - Correlations: `/api/ml/correlations` now uses `set_name` (with alias `set` preserved)
- Core behaviors and infra
  - "Auto" expiry normalization (NIFTY/SENSEX → `this_week`; BANKNIFTY/FINNIFTY → `this_month`)
  - Live CSV resolver + nearest-neighbor alignment (±bucket_ms/2)
  - In-process TTL caching for forecasts
  - Archival writers: q50 primary plus bands companion files
  - Calibration persistence:
    - Snapshot JSON per index under `data/ml/path_forecasts/_calibration/INDEX.json`
    - History CSV under `data/ml/path_forecasts/_calibration_history/INDEX.csv`
    - Fields: `band_scale, prev, target, actual, samples, ts_iso/ts_ms`
- Grafana & operations
  - Panels switched to backend parsing to enable alerting
  - Alert rules added and dashboards hardened (quick links, debug/backfill indicators)
- Code hygiene and fixes
  - `src/web/dashboard/routes/path_forecast.py` cleaned up (removed duplicate/interleaved blocks; fixed dangling try/indent)
  - Calibration helpers restored: `_calibration_dirs`, `_load_calibration`, `_save_calibration`, `_apply_band_scale`
  - Implemented calibration endpoints above and type-safe archival casts
  - `src/web/dashboard/routes/ml.py` correlations: parameter rename to `set_name` (alias `set`), and fixed key-union logic to avoid shadowing `set()`

## Verification and runs

- API start and health
  - Task: "Dashboard API: Start on 9500 (reload)" → OK
  - Health check task → OK
- Endpoint smoke tests
  - `GET /api/ml/path_forecast_json?index=BANKNIFTY&horizon_minutes=60&date_str=2025-11-04` returned ~60 ribbon rows `{time,q10,q50,q90}`
  - `GET /api/ml/path_forecast_meta?index=NIFTY&horizon_minutes=60` returned meta with retrieval details, calibration snapshot, and `source_status: ok`
- Calibration batch (one-shot for 2025-11-04)
  - Command: `scripts/ml/calibrate_bands.py --indices NIFTY,BANKNIFTY --horizons 60 --window-minutes 180 --target 0.8 --base-url http://127.0.0.1:9500 --date-str 2025-11-04`
  - Results:
    - NIFTY → 200 OK; `band_scale=5.0`, `prev=5.0`, `target=0.8`, `actual=0.0`, `samples=240`
    - BANKNIFTY → 200 with `error="no comparable points"` (expected if archives/realized overlap is sparse for that day/window)
  - Persistence verified:
    - `data/ml/path_forecasts/_calibration/NIFTY.json` → current snapshot
    - `data/ml/path_forecasts/_calibration_history/NIFTY.csv` → appended row
- Grafana
  - Reload + open task is generally fine; in one run it returned exit code 1, likely transient; dashboard data paths/alerts remain valid.

## Quality gates (current)

- Build/Service: PASS (API runs; core endpoints return expected structures)
- Python typecheck: PASS for changed files (`path_forecast.py`, `ml.py`)
- PowerShell lint/compile: MIXED (non-blocking for API)
  - `scripts/kill_dashboard_ports.ps1`: `$pid` naming and `${}` interpolation issues
  - `scripts/force_rebind_9500.ps1`: `$pid/$args` naming, unapproved verb warning
  - `scripts/obs_start_clean.ps1`: `$args` naming, unapproved verb warning
- Tests: Not added in this iteration (see next steps)

## Known issues / notes

- BANKNIFTY calibration for 2025-11-04 reported `no comparable points`; try running for today (no `date_str`) or expand window to build overlap.
- Some ops scripts have PowerShell style violations; safe to fix in-place without affecting runtime behavior.

## How to resume quickly

1) Start the API on 9500
   - VS Code task: "Dashboard API: Start on 9500 (reload)"
2) Verify endpoints (optional)
   - `scripts/verify_ml_endpoints.py --base-url http://127.0.0.1:9500 --index NIFTY --horizon 1 --model sk_hgb_regressor --window-minutes 60 --tail 5`
3) Seed calibration
   - `scripts/ml/calibrate_bands.py --indices NIFTY,BANKNIFTY --horizons 30,60 --window-minutes 180 --target 0.8 --base-url http://127.0.0.1:9500`
4) Reload Grafana panels (optional)
   - VS Code task: "Grafana: Reload + Open"

## Next steps (when we return)

- Calibration/data
  - Run a broader calibration sweep for today (indices: NIFTY, BANKNIFTY, FINNIFTY; horizons: 30,60; window: 180–240) to populate history
  - Add unit tests for calibration math (happy path + no-samples) and JSON ribbon building
- Dashboard polish
  - Migrate any lingering panels to the `set_name` parameter (alias `set` already supported)
  - Add a small calibration health panel (target vs. actual, samples, last updated)
- Ops hardening
  - Fix PowerShell script issues: rename `$pid/$args`, use `${}` in interpolated strings, replace unapproved verbs
  - Add CI tasks for quick API smoke test and endpoint schema check
- Enhancements
  - Expand advisor alerts and thresholds
  - Optional: backfill historical calibration over recent days to stabilize early sessions

---
Last updated: 2025-11-06

## Appendix: Orchestrator quick fix (2025-11-06)

Observed issues when running `scripts/run_orchestrator_loop.py`:
- Missing packages resulted in provider facade and token manager failures (e.g., `Unknown token provider 'kite'`, `No module named 'tenacity'`), plus optional warnings (`psutil not installed`, `tzdata not found`).

What we installed into the workspace venv:
- `kiteconnect`, `flask`, `tenacity`, `psutil`, `tzdata`, `python-dotenv`

How to proceed:
1) Ensure `.env` contains valid credentials (no quotes, no inline comments):
  - `KITE_API_KEY=...`
  - `KITE_API_SECRET=...`
2) Start the orchestrator (token manager will handle login if needed):
  - `python scripts/run_orchestrator_loop.py --cycles 1 --interval 5`
3) If you prefer explicit token flow first:
  - `python -m src.tools.token_manager` (guides browser login and persists `KITE_ACCESS_TOKEN`)

Notes:
- We observed an invalid env value: `G6_CYCLE_SLA_FRACTION` containing an inline comment. Keep env values clean (e.g., `G6_CYCLE_SLA_FRACTION=0.85`).
- After login, the orchestrator refreshed provider credentials and proceeded with a cycle; metrics and storage initialized successfully.
