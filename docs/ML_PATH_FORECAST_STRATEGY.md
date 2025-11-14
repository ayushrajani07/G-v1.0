# Dynamic intraday path forecasting for tp

This document reframes the problem, compares model families for intraday multi-horizon path forecasting, and proposes a pragmatic architecture and rollout plan.

Status: Phase 0 retrieval baseline is live with tunables and diagnostics. Phase 1 hybridization (historical-median prior + retrieval blending) is implemented behind the same API. Multi-quantile bands are archived in a companion file for coverage diagnostics.

## Problem statement (refined)

- Goal: At market open, emit a full-day minute-level forecast path of tp (ATM premium) up to market close. As live data arrives each minute, update the remaining future path by conditioning on the latest observed sequence and current market context.
- Inputs (streaming): Per-minute features from live_csv — {tp, index_price, OI/IV, Greeks, PCR, volumes, expiry metadata, time-of-day, days-to-expiry}, optional regime flags.
- Output: Future path Y_{t+1:t+H} of tp where H ≈ minutes until market close (e.g., up to 390 at open; shrinks over day). Provide point forecasts and ideally prediction intervals (P10/P50/P90).
- Update cadence: Δt = 1 minute; update should recompute the remaining path within latency L ≤ 1s on CPU (target) per index.
- Failure modes: Missing features; gaps; warm-up at open; concept shift across expiries; restarts mid-day; bounded memory.

Contract (per tick t):
- Input: recent window W of features (e.g., last 64 minutes) + static/context features (index, DTE, weekday, session time)
- Output: vector f̂ ∈ R^{H_t}, optional intervals q̂_low, q̂_med, q̂_high of length H_t
- SLA: end-to-end latency ≤ 1s; memory ≤ 500MB per running forecaster; resilient to missing rows (≤ 3 consecutive minutes)

Success criteria:
- Short-horizon accuracy: MAE/RMSE over next 30–60m better than baseline (dte×tod) by ≥ 15%
- Stability: No persistent bias over rolling 2–3 hours; corr(pred,tp) ≥ 0.5 on most sessions
- UX: Smooth path updates (no large jitter unless regime truly shifts)

## Model families — functionality, pros/cons
  - Functionality: Learns temporal dependencies; can emit multi-horizon via encoder–decoder or direct multi-head outputs.
  - Pros: Mature; robust on small/medium data; easy to deploy; good with modest horizons.
  - Cons: Limited long-range memory; slower training; less parallelism; harder to produce sharp multi-horizon distributions.

- GRU
  - Functionality: Like LSTM with fewer gates; encoder–decoder or direct multi-horizon.
  - Pros: Fewer parameters; faster to train; similar accuracy to LSTM for many tasks.
  - Cons: Same long-range limits; may underfit complex intraday regimes.

- TCN (Temporal Convolutional Networks)
  - Functionality: 1D dilated causal convolutions; large receptive fields with depth.
  - Pros: Parallelizable; stable gradients; efficient inference; good for long contexts.
  - Cons: Multi-horizon decoding needs careful head design; less flexible with highly irregular contexts.

- Transformers (TFT, PatchTST, Informer/FEDformer/TimesNet)
  - Functionality: Attention over long histories; multi-horizon forecasting; handle known/observed/static covariates.
  - Functionality: Backcasting/forecasting blocks (univariate or small multivariate) for shape-based forecasts.
  - Pros: Strong on seasonal/level/trend decomposition; fast; interpretable components.
  - Cons: Less suited to many exogenous features without extensions; combining with rich covariates is non-trivial.

- State-space (S4/SSM, Mamba)
  - Functionality: Efficient long-sequence modeling via implicit state updates.
  - Pros: Scales to very long L; strong on long context; efficient inference.
  - Cons: Less battle-tested in typical production stacks; higher integration cost.

- Retrieval/nearest-neighbors (kNN/DTW/embedding search)
  - Functionality: Find historical windows most similar to current context; average or align their future segments to form a path; optionally learn a residual.

- Classical baselines (ARIMA/ETS/Kalman)
  - Pros: Fast, explainable; good sanity baseline; incremental updates are trivial.
  - Cons: Weak with nonlinearity and many covariates; path-level multi-horizon less expressive.

## Recommendation (hybrid, pragmatic)

- Use a two-stage hybrid forecaster:
  1) Day-open full-path prior: Transformer-based multi-horizon model (PatchTST/TFT) trained to output the whole remaining session path given recent window + known future inputs (time bins, DTE schedule). Train with quantile loss to get P10/P50/P90.
  2) Minute-by-minute updates: Retrieval-augmented refinement. Encode the last W minutes with a light encoder (GRU/TCN/Transformer encoder) → embedding. Retrieve K nearest historical windows (per index, matched on weekday/DTE bucket/regime flags). Aggregate their future segments (weighted) as a correction to the prior. Optionally, a small GRU refiner learns residuals between prior and retrieved ensemble.

  - Keeps inference light (encoder+ANN+small head), enabling sub-second updates on CPU.

## Data and features

- Base live features: tp, index_price, ce_oi, pe_oi, ce_iv, pe_iv, PCR, Greeks, volumes
- Context: day_of_week, is_expiry_day, days_to_expiry, time_of_day_min, tod_bin, early_drop_flag, oi_bias_flag, rally_past_open_flag
  - For tp, work in deviation from dte×time-of-day baseline (as in FE v2), not pure z-score

## Inference interface (proposed)

- New API: `/api/ml/path_forecast`
  - Query: index=NIFTY&horizon_minutes=390&quantiles=0.1,0.5,0.9
  - Response CSV (wide): `time, q10, q50, q90`
  - Response CSV (long): `time, quantile, value`
- Exporter: extend to write `data/ml/path_forecasts/<INDEX>.csv` with rolling path updates (first row is current time; future rows are predictions)

## Rollout plan

- Phase 0: Baselines
  - Implement retrieval-only path forecast: encode last W via simple feature vector (handcrafted stats + FE v2); kNN over historical windows; output mean future path; smooth with exponential weights.
  - Add `/api/ml/path_forecast` endpoint + Grafana panel (bands P10/P50/P90 from percentiles over neighbors).

### Diagnostics and tunables (Phase 0)

Lightweight improvements have been added to aid validation and iteration:

- Retrieval tunables via query params on `/api/ml/path_forecast`:
  - `expiry_tag` (default: `this_week`)
  - `offset` (default: `0`)
  - `window` (default: `60`, minutes used for similarity)
  - `k` (default: `15`, neighbors aggregated)

- Diagnostic headers (non-breaking for CSV consumers):
  - `X-PathForecast-Mode`: `retrieval` or `fallback`
  - `X-Retrieval-Candidates`: number of eligible historical candidates found
  - `X-Retrieval-KUsed`: number of neighbors actually aggregated
  - `X-Retrieval-Window`: window length used for similarity

- Meta endpoint for JSON diagnostics: `/api/ml/path_forecast_meta`
  - Returns `{ mode, index, expiry_tag, offset, window, k, horizon_minutes, retrieval: { candidates_total, k_used, window_used, threshold_needed, ... } }`
  - If retrieval cannot run (insufficient history etc.), `mode` is `fallback` and `retrieval.error` contains the reason.

OpenAPI/Swagger notes:
- The `/api/ml/path_forecast` OpenAPI now includes the `mode` query parameter with allowed values `auto|hybrid|retrieval|stub`.
- For quick runtime verification, the endpoint also echoes the requested mode via the header `X-PathForecast-RequestedMode`.

Notes:
- “Enough history” for retrieval is currently defined as at least `max(1, min(min_days, k//2))` candidate days. With defaults (`min_days=8`, `k=15`) this equals `7` days.
- When insufficient candidates exist, the endpoint falls back to a flat-band stub so dashboards stay live.

### Modes (runtime)

- New query param `mode=auto|hybrid|retrieval|stub` (default `auto`).
  - `auto`: attempt hybrid (prior+retrieval), fallback to retrieval, then stub.
  - `hybrid`: force prior+retrieval blending.
  - `retrieval`: retrieval-only.
  - `stub`: flat-band fallback.

Additional headers when `hybrid` is used:
- `X-PathForecast-Alpha`: blending weight on retrieval median
- `X-Prior-Days`: number of historical days contributing to the prior
- `X-Retrieval-KUsed` and `X-Retrieval-Window` are also populated in hybrid mode for consistency.

Examples:
- `.../api/ml/path_forecast?index=NIFTY&horizon_minutes=30&quantiles=0.1,0.5,0.9&format=wide&window=60&k=10&expiry_tag=this_week&offset=0&mode=hybrid`
- `.../api/ml/path_forecast?index=NIFTY&mode=retrieval`

### Archival and live evaluation

- The forecast endpoint appends a compact snapshot per call (q50 path only) to `data/ml/path_forecasts/<INDEX>/<YYYY-MM-DD>.csv`.
  - Columns: `gen_time_iso,gen_ms,index,mode,alpha,prior_days,k_used,window_used,target_time_iso,target_ms,horizon_min,q50`
  - This enables lightweight, rolling live evaluation of the last N minutes.
  - Additionally, a companion multi-quantile archive is written to `data/ml/path_forecasts/<INDEX>/<YYYY-MM-DD>_bands.csv` with columns:
    - `gen_time_iso,gen_ms,index,target_time_iso,target_ms,horizon_min,q10,q50,q90` (quantile columns present depend on request; header is preserved on first write).
- New diagnostics endpoint: `/api/ml/path_diagnostics`
  - Params: `index`, `window_minutes` (default 120), `horizons` (e.g., `30,60`), optional `date_str` for off-hours testing.
  - Returns JSON with counts and metrics:
    - `count_by_horizon.{H}`: number of comparable points
    - `mae_by_horizon.{H}`: MAE for horizon H
    - `bias_by_horizon.{H}`: mean(pred - tp) for horizon H
    - `jitter_mean_abs`: average absolute change between successive q50 forecasts for the same target times
    - If the bands archive is available, additional metrics are included:
      - `coverage_p10_p90_by_horizon.{H}`: share of realized values falling inside [q10, q90] (target ≈ 0.8 when using 10–90 bands)
      - `band_width_mean_by_horizon.{H}`: average (q90 - q10), a measure of forecasted uncertainty
  - Realized tp is read from the same-day `live_csv`; only targets <= now are evaluated.

- Phase 1: Hybridization (prior + retrieval)
  - Compute a historical-median prior path per horizon step from past days aligned to the current time index.
  - Blend the retrieval median and the prior median using a simple gate α based on candidate availability.
  - Center retrieval quantile bands around the blended median (shifted q10/q90), preserving shape while anchoring to prior when retrieval is weak.
  - Next: swap median prior with a learned encoder+residual (GRU) once training harness is wired.

- Phase 2: Transformer prior
  - Train PatchTST/TFT to output full-day path at open and rolling horizons intra-day.
  - Fuse with retrieval correction using a gate α(t) that increases weight on retrieval when regime flags fire.

- Phase 3: Uncertainty and calibration
  - Quantile loss; conformal calibration to tighten P-bands; bias control with live diagnostics loop.

### JSON ribbon + calibration + caching (Phase 1.5)

New lightweight enhancements for Grafana and operational stability:

- JSON ribbon endpoint for Grafana Infinity
  - GET `/api/ml/path_forecast_json`
  - Query: `index`, `horizon_minutes`, `expiry_tag`, `offset`, `window`, `k`, `mode`, `bucket_ms`, `date_str`, `calibrate`, `no_cache`
  - Response: array of objects with `{ time, q10, q50, q90 }`
  - Headers echo diagnostics: `X-PathForecast-Mode`, and retrieval meta; hybrid also echoes `X-PathForecast-Alpha`, `X-Prior-Days`.
  - Side effects: archives q50 snapshot and multi-quantile bands (same as CSV route) so diagnostics and calibration remain up-to-date.

- Band calibration loop (coverage targeting)
  - POST `/api/ml/path_calibrate`
  - Inputs: `index`, `expiry_tag`, `offset`, `window_minutes` (lookback), `horizon`, `target` (desired coverage, default 0.8), optional `date_str`.
  - Reads realized tp from same-day live_csv and bands archive to compute coverage of [q10, q90] at the selected horizon over the window; proposes a smoothed `band_scale` update.
  - Persists calibration to `data/ml/path_forecasts/_calibration/<INDEX>.json` with fields: `{ band_scale, target, actual, samples, updated_at }`.
  - When `calibrate=true` on CSV/JSON forecast routes, `q10/q90` are scaled around `q50` using the persisted `band_scale`.

- In-process memoization cache with TTL and controls
  - Forecast responses are memoized per key: `(route | index | expiry_tag | offset | window | k | horizon | bucket_ms | mode | quantiles | bucket_key)`.
  - TTL: 90 seconds. Entries older than TTL are ignored.
  - Headers: CSV route sets `X-Cache: HIT` on cache hits.
  - Admin/debug endpoints:
    - GET `/api/ml/_debug/cache_stats` (optional `prefix=csv|json`, `detail=true` for sample)
    - POST `/api/ml/_admin/cache_clear` (optional `prefix`)

Grafana Infinity example (JSON):
- URL: `http://127.0.0.1:9500/api/ml/path_forecast_json?index=NIFTY&horizon_minutes=390&mode=auto&calibrate=true`
- Format: JSON -> Fields
  - Root selector: leave default (array)
  - Columns: time (as Time), q10, q50, q90 (as Numbers)
  - Visualization: Time series with 3 lines; optionally fill between q10–q90 for a band.

### Interpreting the ribbon (q10/q50/q90) and using time override

- q50 (middle line)
  - The median forecast from the generation time (effective "now"). It’s the model’s best single guess for each future minute.

- q10 and q90 (outer lines)
  - Lower/upper quantiles at each future minute; the shaded area is the uncertainty band.
  - With calibration enabled (`calibrate=true`), we target ≈80% coverage: P(q10 ≤ realized ≤ q90) ≈ 0.8. Band width reflects uncertainty.

- Practical reading
  - Narrow band + trending q50 → confident directional view.
  - Flat q50 + widening band → uncertainty rising without a strong directional edge.
  - Longer horizons typically widen as uncertainty compounds.
  - Toggle Calibrate to compare raw vs calibrated dispersion; calibration widens/tightens bands to track the target coverage using recent history.

#### now_override_ms (epoch ms) and date_str

- Purpose
  - Forces the effective generation time used to produce the path. The server finds the last row at or before this timestamp and forecasts forward from there.

- Inputs and behavior
  - Query params: `now_override_ms` (epoch ms) and optional `date_str` (YYYY-MM-DD).
  - Empty or missing `now_override_ms` → latest available row is used.
  - The server clamps the override to the file’s timestamp range to avoid errors.
  - Headers from the JSON route echo what was used:
    - `X-Gen-Iso`/`X-Gen-Ms`: effective generation time.
    - `X-Query-Now-Keys`: which param name was picked up (`now_override_ms`, `nowMs`, `now_ms`, or `now`).

- When to use
  - Intraday replay/backfill: “What would the model have forecast at 15:45?”
  - Off-hours inspection: Set `date_str` to the session date and `now_override_ms` to an in-session time; widen the Grafana time range accordingly.
  - Reproducibility & debugging: Lock the same generation time while toggling `calibrate`/parameters.

- Caching note
  - Responses are memoized per-minute bucket. Changing `now_override_ms` across minute boundaries forces a fresh compute (or use `no_cache=true`).

Common dashboard gotchas:
- If the panel shows “No data,” the graph’s time window likely doesn’t intersect the returned timestamps; widen the time picker or set `date_str`/`now_override_ms` to aim at a visible window.
- Infinity queries must use `GET` (set in dashboard json `url_options.method=GET`). An empty `now_override_ms` is tolerated by the API (no 422).

### At-a-glance calibration diagnostics in Grafana

The JSON dashboard includes small Stat panels driven by `/api/ml/path_diagnostics`:

- Coverage p10–p90 @30m and @60m: share of realized points inside the ribbon for the last `window_minutes` (defaults to 180).
- Avg band width @60m: mean(q90 - q10) across comparable samples; wider implies higher forecasted uncertainty.

Notes:
- These stats populate only after the bands archive begins to fill for the day; early sessions may show blanks.
- You can change the time window or horizons by editing the panel URLs or wiring variables similarly to the ribbon panel.

Tip: The JSON dashboard includes a variable `diag_window` (default 180) that feeds the Stat panels via `window_minutes=${diag_window}`. Adjust it to tighten/loosen the lookback without editing the JSON.

#### New: Calibrated vs Raw coverage panels (side-by-side)

- Two Stat panels powered by `/api/ml/path_stats` compare calibrated vs raw coverage at the selected horizon:
  - Calibrated coverage: `.../api/ml/path_stats?variant=calibrated&index=${index}&horizon=${horizon}&window_minutes=${diag_window}&date_str=${date_str}`
  - Raw coverage: `.../api/ml/path_stats?variant=raw&index=${index}&horizon=${horizon}&window_minutes=${diag_window}&date_str=${date_str}`
- Both display `coverage_p10_p90` as a percentage with thresholds:
  - Red < 0.65, Orange ≥ 0.65, Green ≥ 0.75
- A third Stat panel shows `band_width_mean` for the same horizon and window.
- Notes:
  - Early-day or when no bands archive exists for the date, these stats may show blank (null) until samples accumulate.
  - `date_str` and `now_override_ms` from the top-level variables keep Meta, Ribbon, and Stats in sync for backtesting or off-hours inspection.

## Metrics and diagnostics (live)

- Report: MAE@30m/60m, RMSE@60m, bias_mean, corr, slope_pred/TP over window; path jitter metric (ΔL2 between successive path forecasts).
- Per-regime breakouts: early_drop_flag, oi_bias_flag, expiry day.
- Compare to FE v2 daily baseline.

## Risks and mitigations

- Data gaps / misalignment → bucket by minute; robust timestamp parsing; carry-forward imputation ≤ 2–3 min.
- Regime shifts → retrieval dominates; freshness weighting; blacklist outlier neighbors.
- Heavy inference → use efficient ANN (FAISS) and CPU-friendly encoders; cap W and K.
- Drift across expiries → normalize with (weekday, expiry_date); include DTE in encoder.

## Minimal resource targets

- CPU-only OK for live loop; optional GPU for training.
- Update latency: < 1s per index; memory: < 500MB; storage: historical window index per index ≤ few GB.

---
Generated 2025-11-05.
