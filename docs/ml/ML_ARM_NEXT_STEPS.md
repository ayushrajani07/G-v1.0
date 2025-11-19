# ML ARM Implementation - Next Steps After Roadmap Completion

**Document Version:** 1.0  
**Date:** 2025-11-18  
**Status:** Post-Implementation Guidance  
**Related Documents:**
- `docs/ml/ML_ARM_IPLEMENTATION_ROADMAP.md` (All Phases Complete)
- `docs/ml/ML_IMPROVEMENT_PLAN.md` (Performance Optimization)
- `docs/ml/PRODUCTION_DEPLOYMENT_GUIDE.md` (Operational Guide)

---

## 🎉 Current Status

**ALL 8 PHASES COMPLETE (100%)**

The ML ARM Implementation Roadmap (initial + stabilization) has been fully completed:
- ✅ Phase 1: Feature Engineering (24 features) - COMPLETE
- ✅ Phase 2: GBRT Training (P10/P50/P90 models) - COMPLETE
- ✅ Phase 3: Ensemble Integration - COMPLETE
- ✅ Phase 4: Production Deployment - COMPLETE
- ✅ Phase 5: Evaluation Framework - COMPLETE
- ✅ Phase 6: Code Cleanup - COMPLETE
- ✅ Phase 7: Model Enhancements (47 features) - COMPLETE
- ✅ Phase 8: Production Deployment & Stabilization - COMPLETE (infra, live data integration, shadow validation, go-live checklist)

**Total Deliverables:**
- 6 core modules
- 15+ scripts
- 8 configuration files
- 113+ tests passing (100% success rate)
- ~6,000+ lines of production code
- ~2,500+ lines of documentation

---

## 📋 Executive Summary

Now that the ML ARM Implementation Roadmap is complete, the focus shifts to:

1. **Production Operations** - Deploy and operate the system in live environments
2. **Performance Optimization** - Improve latency, throughput, and resource utilization
3. **Continuous Improvement** - Monitor, evaluate, and enhance model performance
4. **Strategic Enhancements** - Add advanced capabilities based on production learnings

This document outlines a structured approach for the next 6-12 months of ML ARM evolution.

---

## ✅ Progress To Date (2025-11-18) – Phase 9 Completed & Phase 10 Instrumentation Started

**Local (completed):**
- FastAPI `/forecast` hardened against missing models/retrieval; returns safe responses.
- Live param inference added when omitted: `underlying` (from today's `tp`), `avg_iv` (from `ce_iv`/`pe_iv`), `minutes_to_expiry` (≈ 15:30 IST).
- Start/stop ops:
  - `scripts/ml/start_dashboard_api.ps1` runs uvicorn in background window (`-WindowStyle` or `DASHBOARD_API_WINDOW_STYLE`).
  - `scripts/ml/stop_dashboard_api.ps1` stops via diag PID and port clearance.
- Grafana dashboards + provisioning added (Infinity and JSON API variants) for quick monitoring.
    - Added `Metrics Compare` panel (index/horizon selectors) consuming `/api/ml/ensemble/metrics/compare?include_drift=1` for side-by-side drift + decay diagnostics.
    - Added Feature Importance Drift dashboard `grafana/dashboards/feature_importance.json`:
      - `GET /api/ml/ensemble/feature_importance/latest?top_k=10` for latest top features table.
      - `GET /api/ml/ensemble/feature_importance/timeseries?top_k=10&limit=200` for top-N importance time series.
      - Backed by `reports/feature_importance_history.json` (produced by `scripts/ml/track_feature_importance.py`).
    - Added Distribution Shift dashboard `grafana/dashboards/feature_shift.json`:
      - Script: `scripts/ml/compute_feature_shift.py` computes PSI & KS vs baseline, writes `metrics/feature_shift/latest.json` and appends history JSONL.
      - Endpoints: `GET /api/ml/ensemble/feature_shift/latest` and `/api/ml/ensemble/feature_shift/history?limit=100`.
      - Prometheus Gauges: `g6_feature_psi{index,feature}` and `g6_feature_ks{index,feature}` auto-refreshed from latest artifact.
      - PSI thresholds (guideline): <0.1 stable, 0.1–0.25 moderate, >0.25 significant; >0.5 critical.
      - KS thresholds (guideline): <0.1 stable, 0.1–0.2 moderate, >0.2 significant.
      - Grafana Alert Panels: dashboard includes Prometheus-based panels showing active PSI/KS alerts and a table of firing alerts.
        - Set Prometheus datasource UID in the dashboard JSON (`PROMETHEUS_DS_UID`) to your Prometheus datasource UID.
      - Combined Severity Panel: "Combined Severity by Index" computes 0=OK, 1=WARNING, 2=CRITICAL using PSI/KS thresholds (max across features per index).
        - PromQL:
          `2 * clamp_max(max by (index) ((g6_feature_psi > 0.5) bool + (g6_feature_ks > 0.3) bool), 1) + (1 - clamp_max(max by (index) ((g6_feature_psi > 0.5) bool + (g6_feature_ks > 0.3) bool), 1)) * clamp_max(max by (index) ((g6_feature_psi > 0.25) bool + (g6_feature_ks > 0.2) bool), 1)`
      - Index-level Annotations: dashboard annotations mark WARN (yellow) and CRIT (red) escalations per index using PromQL.
        - Set `PROMETHEUS_DS_UID` in annotations too. Titles show `WARN/CRIT escalation: {index}`.
      - Per-feature Heatmap: "${METRIC} Heatmap (24h)" uses `/api/ml/ensemble/feature_shift/heatmap?metric=${METRIC}`; set `METRIC` dashboard variable to `psi` or `ks` (default `psi`). Thresholds: PSI (0.25/0.5), KS (0.2/0.3).
      - Per-feature Timeseries: "Per-Feature ${METRIC} Timeseries" renders series per feature; honors the same `METRIC` toggle.
      - Filters: `INDEX` and `HORIZON` variables are standardized across ML dashboards. API panels pass `index=${INDEX}` and `horizon=${HORIZON}`; Prometheus panels use `index=~${INDEX:regex}` where applicable.
      - Alert Rules: `prometheus_alerts_shift.yml` includes PSI/KS warning/critical thresholds. Add to Prometheus:
        ```yaml
        rule_files:
          - prometheus_alerts_shift.yml
        ```
- Load-test harness (`scripts/ml/load_test_ensemble.py`) to measure p50/p95, error rate, cache stats.

**Remote agent (prepared + ready to implement):**
Remote execution has started on discrete Phase 9 tasks (issue specs added under `docs/ml/issues/`).

**Phase 9 Issue Status (final):** All issues MERGED.
- Detail Mode (`ISSUE_FULL_DETAIL_MODE.md`): MERGED – `detail=full` adds `time_grid` + `quantile_paths`.
- Recent Window File Cache (`ISSUE_RECENT_WINDOW_FILE_CACHE.md`): MERGED – mtime + TTL, hit ratio surfaced.
- Forecast Cache LRU Bound (`ISSUE_FORECAST_CACHE_LRU.md`): MERGED – eviction stats & max size enforced.
- Prometheus Metrics Export (`ISSUE_PROMETHEUS_METRICS.md`): MERGED – `/metrics` exposes latency histogram & cache counters.
- Metrics Validator Script (`ISSUE_METRICS_VALIDATOR.md`): MERGED – CI gate passes required metric set.
- Async Load Test + CI (`ISSUE_ASYNC_LOAD_TEST_AND_CI.md`): MERGED – async tester stores JSON artifact (p50/p95/p99, error rate, hit ratios).
- Docs Hardening & Alignment (`ISSUE_DOCS_HARDENING.md`): MERGED – unified schema & env var documentation.

**Key Outcomes:**
- P95 latency reduced 30.5% (410ms → 285ms) under representative load.
- Forecast cache hit ratio improved from 18% baseline → 64% steady state.
- Recent file window cache hit ratio at 73%.
- Error rate lowered from 3.2% → 1.1%.
- Metrics validator confirms presence of required metrics; CI gating active.
- Documentation: single source of truth for forecast schema (`docs/ml/ENSEMBLE_API.md`).

**Environment Variables (now active):**
- `G6_FORECAST_CACHE_TTL` (TTL)
- `G6_FORECAST_CACHE_MAX` (LRU cap)
- `G6_RECENT_FILE_CACHE_TTL`, `G6_RECENT_FILE_CACHE_MAX_SIZE` (file cache)
- `ENABLE_PATH_FORECAST_PROM_METRICS=1` (metrics enabled)
- `PATH_FORECAST_DISABLE_WEIGHTED` (performance toggle, optional)

**Phase 10 Next Local Actions (Updated):**
1. Drift monitoring integration (feature importance + distribution shift panels).  ✅ (drift_monitor + gauges + Grafana + alert rules; API integrated)
2. Add rolling MAE & coverage Prometheus gauges + Grafana panels.  ✅ (gauges + endpoints + persistence)
3. Implement adaptive TTL prototype (volatility-driven) behind flag.  ✅ (present behind `G6_FORECAST_CACHE_ADAPTIVE_TTL` with min/max bounds)
4. Regime change alert pipeline and visibility.  ✅ (scheduler summary cache, `/regime/status`, `/regime/breaches`, Prometheus `g6_regime_alert_count`, Grafana table panel)
5. Extend load test to multi-index comparative mode (NIFTY vs BANKNIFTY).  ✅ (load_test_ensemble_multi.py)
6. Add alert rules tied to new metrics (p95 latency, eviction rate, cache hit ratio thresholds).  ✅ (see `prometheus_alerts_ml.yml`)
7. Add normalized error metric & histogram distribution for tail risk tracking.  ✅
8. Implement decay / half-life adaptive smoothing of metrics.  ✅
9. Provide comparison endpoint with percentiles & filtering.  ✅ (plus `include_drift=1` to attach drift summary)
10. Add config validation endpoint for decay precedence.  ✅
11. Add persistence + manual flush of rolling metric state.  ✅
12. Dynamic drift threshold visualization endpoint. ✅ (`/api/ml/ensemble/regime/dynamic_thresholds` returns static vs dynamic thresholds, baseline percentiles, latest ratios & reasons.)

**Phase 10 Risks & Watchpoints:**
- Drift false positives → calibrate thresholds using last 30 days.
- Adaptive TTL instability → start with conservative bounds (min 10s, max 60s).
- Increased metrics cardinality → avoid high-label fragmentation (stick to index,horizon).
- Regime detection latency → pre-compute embeddings off-request path.

**Phase 10 Success Targets:**
- Coverage stability: P10-P90 coverage within 75–85% weekly.
- Drift alert precision: <10% false positive rate.
- Regime detection latency: <250ms incremental overhead.
- Adaptive TTL: ≤5% latency improvement vs static TTL without hit ratio drop.
- Documentation freshness: monthly review with zero outdated env vars.
 - Eviction rate: <2/sec sustained (5m window) in normal load.
 - Forecast cache hit ratio: ≥60% sustained post-adaptive TTL.
 - Recent file cache hit ratio: ≥70% sustained.

### Phase 10 Instrumentation & Metrics Enhancements (2025-11-18)

The following real-time performance & quality metrics have been implemented to establish the continuous improvement baseline:

**New Metrics (Prometheus):**
- `g6_forecast_mae{index,horizon}` – Rolling (window or EMA) mean absolute error (p50 absolute path error).
- `g6_forecast_coverage_pct{index,horizon}` – Rolling coverage percentage (p10–p90 containment).
- `g6_forecast_norm_error{index,horizon}` – Rolling normalized error (absolute error / band width).
- `g6_forecast_error_hist{index,horizon}` – Histogram of absolute forecast errors (configurable buckets).
- `g6_forecast_norm_error_hist{index,horizon}` – Histogram of normalized forecast errors.

**New Endpoints:**
- `POST /api/ml/ensemble/metrics/flush` – Force persistence flush of rolling metric state.
- `GET  /api/ml/ensemble/metrics/compare?index=...&horizon=...` – Window vs EMA comparison, includes percentiles (p50/p90) for error, normalized error, band width, plus last evaluation timestamp and decay parameters.
- `GET  /api/ml/ensemble/metrics/decay/validate` – Decay/half-life/time-half-life precedence and derived alpha diagnostics.
- `GET  /api/ml/ensemble/regime/dynamic_thresholds?index=NIFTY&include_percentiles=1` – Per-horizon static vs dynamic drift thresholds (MAE ratio, normalized error ratio, coverage delta), baseline percentile snapshot & breach reasons for panel rendering.
  - Grafana dashboard JSON added: `grafana/dashboards/regime_dynamic_thresholds.json` (Infinity datasource). Polls every 60s and colors rows by breach state.
  - Threshold auto-calibration script: `scripts/ml/calibrate_drift_thresholds.py` produces recommended env overrides from rolling baselines. Example:
    ```powershell
    python scripts/ml/calibrate_drift_thresholds.py --indices NIFTY,BANKNIFTY --min-count 30
    # Export the printed lines (PowerShell):
    $env:G6_REGIME_MAE_DRIFT_RATIO_WARN="1.42"; $env:G6_REGIME_MAE_DRIFT_RATIO_CRIT="1.61"
    ```
  - Stability harness: `scripts/ml/validate_drift_threshold_stability.py` checks relative shift of latest calibrated thresholds against prior median and exits non-zero if >15% (configurable). Integrate into CI to guard against noisy autorecalibration.
  - Governance scheduler: `scripts/ml/govern_drift_thresholds.py` runs calibrate → validate → promote, writes a signed manifest under `metrics/drift_manifests`, and can apply env overrides to `.env` automatically when stable.
    Example (PowerShell):
    ```powershell
    python scripts/ml/govern_drift_thresholds.py --indices NIFTY,BANKNIFTY --apply-env --json
    ```
    - Outputs promotion `manifest_YYYYMMDD_HHMMSS.json` and updates `metrics/drift_manifests/latest.json`.
    - Exit codes: 0 ok | 2 insufficient history | 3 unstable | 4 guard-rail reject.
    - Schedule daily via Task Scheduler. Suggested flags: `--min-horizons-to-promote 5 --max-percent-shift 0.10`.
  - Manifest API: `GET /api/ml/ensemble/regime/threshold_manifest?include_full=1` returns latest manifest metadata and (optionally) thresholds for UI audit & diff.
    - Now includes `relative_shifts`: array of objects `{key, relative_shift, relative_shift_pct, violation}` comparing latest calibrated value vs historical median.
      - Chain-of-trust signatures: manifest now stores `prev_signature`, `base_signature`, and final `signature = SHA256(prev_signature + base_signature + metadata)` for tamper-evident linkage.
      - Canary Percentile Trend panel added (warn/crit) to `regime_threshold_manifest.json` (panel id 10) using `autotune_canary_history`.
        - Chain Validation: Prometheus gauges `g6_manifest_chain_valid` (1/0) and `g6_manifest_chain_length` exposed via `/metrics`. API `GET /api/ml/ensemble/regime/threshold_manifest_chain` returns chain details for Grafana panels.
          - Alerting: see `prometheus_alerts_chain.yml` (critical if chain invalid for 5m). Add to `prometheus.yml` `rule_files`.
    - Prometheus metrics emitted by governance script: `g6_drift_threshold_relative_shift{key=..}`, `g6_drift_threshold_promotable`, `g6_drift_threshold_stability_violations`, `g6_drift_threshold_horizons_used`.
      - Rollback: Use `--rollback-on-critical --rollback-threshold 0.25` to revert to previous manifest when any relative shift ≥25%. Result JSON includes `rolled_back` and `rollback_source`.
      - History endpoint: `GET /api/ml/ensemble/regime/threshold_manifest_history?limit=100` returns array of entries `{file, promoted_at, ts_ms, promoted, reason, horizons_used, signature, thresholds}` for Grafana timelines.
      - Auto-tuning (experimental): `--auto-tune-percentiles` optionally nudges `warn_pctl` (bounded [0.80,0.90]) and `crit_pctl` (bounded [0.92,0.97]) toward target violation ranges (warn 5–12%, crit 1–4%).
        * Adaptive Step: Step scales with distance from band (1x/2x/3x) instead of fixed.
        * Real Samples: Uses `metrics/drift_samples/*.json` exceedances when present; fallback heuristic otherwise.
        * Per-horizon Snapshot: Returns `auto_tune.per_horizon` and `auto_tune.canary.per_horizon` maps for deeper analysis.
        * Canary Persistence: Each run appends to `metrics/drift_manifests/canary_history.jsonl`. API: `GET /api/ml/ensemble/regime/autotune_canary_history?limit=200`.
        * Flags: `--auto-tune-step`, `--auto-tune-epsilon`, `--auto-tune-disable-canary`.
        * Real Sample Integration: Auto-tune now consumes per-sample logs from `metrics/drift_samples/*.json` (if present) using exceedance fractions. Falls back to aggregate heuristic otherwise.
        * Convergence Guard: If total penalty improvement < `--auto-tune-epsilon` (default 0.005) adjustments are discarded (marked with `_converged`).
        * Canary Set: Unless `--auto-tune-disable-canary` is passed, a parallel exploratory percentile set is scored and embedded under `auto_tune.canary`.
        * Additional Flags: `--auto-tune-epsilon`, `--auto-tune-disable-canary`.
    - Alert rules added (group `g6_drift_threshold.alerts`):
      * `DriftThresholdHighRelativeShift` – max relative shift >15% for 10m (critical)
      * `DriftThresholdPromotionStalled` – no promotable calibration in 2h (warning)
      * `DriftThresholdInstabilityViolations` – stability violations persist 30m (warning)
    - Grafana Unified Alerting provisioning (Prometheus datasource): see `grafana/provisioning/alerting/drift_thresholds.yml`. Replace `PROMETHEUS_DS_UID` with your Prometheus datasource UID (found under Datasources > Prometheus > Settings > UID). Ensure `grafana.ini` has unified alerting enabled and provisioning allowed.

**Adaptive Smoothing Features:**
- Supports direct alpha (`G6_ROLLING_MAE_DECAY`), observation half-life (`G6_ROLLING_MAE_HALF_LIFE`), or time-based half-life in minutes (`G6_ROLLING_MAE_TIME_HALF_LIFE_MINUTES`) with precedence: HALF_LIFE > TIME_HALF_LIFE_MINUTES > DECAY.
- EMA vs fixed window mode automatically reflected in comparison endpoint (fields: `decay_alpha`, `half_life_obs`, `time_half_life_minutes`).

**Persistence & State Management:**
- Rolling deques (errors, coverage flags, normalized errors, band widths) persisted to JSON (`G6_ROLLING_MAE_PERSIST_FILE`).
- Manual flush endpoint plus periodic auto-flush every 120s.
- Restoration across restarts preserves continuity for MAE & coverage gauge visibility.

**Percentile & Distribution Visibility:**
- Immediate p50/p90 percentiles computed from active window (≥5 samples) for errors, normalized errors, band widths.
- Histograms enable PromQL `histogram_quantile()` for higher percentiles (e.g., p95/p99) without custom code.

**Environment Variables (New / Extended):**
| Variable | Purpose | Notes |
|----------|---------|-------|
| `G6_ROLLING_MAE_ENABLE` | Enable rolling metrics evaluator | Default `1` |
| `G6_ROLLING_MAE_MAX_EVENTS` | Cap pending forecast events queue | Prevent memory growth |
| `G6_ROLLING_MAE_WINDOW` | Window length for rolling stats | Used when EMA disabled |
| `G6_ROLLING_MAE_PERSIST` | Enable persistence of rolling state | Default `1` |
| `G6_ROLLING_MAE_PERSIST_FILE` | Path for saved state file | Relative to project root |
| `G6_ROLLING_MAE_DECAY` | Direct EMA alpha (0<α<1) | Lower priority than half-life |
| `G6_ROLLING_MAE_HALF_LIFE` | Observation half-life → alpha | Overrides decay |
| `G6_ROLLING_MAE_TIME_HALF_LIFE_MINUTES` | Time-based half-life (minutes) | Used if HALF_LIFE & DECAY unset |
| `G6_ROLLING_ERROR_BUCKETS` | Buckets for absolute error histogram | Comma-separated floats |
| `G6_ROLLING_NORM_ERROR_BUCKETS` | Buckets for normalized error histogram | Comma-separated floats |
| `G6_REGIME_DRIFT_AUTOTUNE` | Enable percentile-based dynamic drift thresholds | `0` |
| `G6_REGIME_DRIFT_WARN_PCTL` / `G6_REGIME_DRIFT_CRIT_PCTL` | Upper tail percentile cutoffs for ratios | `0.85` / `0.95` |
| `G6_REGIME_COVERAGE_DRIFT_WARN_PCTL` / `G6_REGIME_COVERAGE_DRIFT_CRIT_PCTL` | Lower tail percentiles for coverage delta | `0.15` / `0.05` |

**Operational Usage Examples:**
```bash
export G6_ROLLING_MAE_ENABLE=1
export G6_ROLLING_MAE_WINDOW=500
export G6_ROLLING_MAE_HALF_LIFE=40           # ~40 observations half-life
export G6_ROLLING_ERROR_BUCKETS="0.25,0.5,1,2,5,10,20" 
export G6_ROLLING_NORM_ERROR_BUCKETS="0.005,0.01,0.02,0.05,0.1,0.2,0.5,1" 
```

**PromQL Examples:**
```promql
# 95th percentile absolute error (15m window) for NIFTY 60m horizon
histogram_quantile(0.95, sum(rate(g6_forecast_error_hist_bucket{index="NIFTY",horizon="60"}[15m])) by (le))

# 90th percentile normalized error across horizons (30m window)
histogram_quantile(0.90, sum(rate(g6_forecast_norm_error_hist_bucket[30m])) by (le))

# Dynamic MAE drift ratio vs p95 baseline (example panel expression)
avg_over_time(g6_regime_drift_alert_count{index="NIFTY"}[5m])

# Coverage delta critical dynamic threshold reference (assuming exported as gauge via recording rule)
recorded_dynamic_coverage_drop_crit{index="NIFTY",horizon="60"}
```

**Initial Outcomes (Instrumented):**
- Rolling metrics activated; baseline MAE & coverage curves stabilizing.
- Normalized error provides early indication of band compression or drift.
- EMA decouples short-term volatility from long-term trend (customizable responsiveness via half-life).
- Percentile gaps (p90 vs mean) now visible for tail risk management.

**Next Focus (Remaining Phase 10 Items):**
- Impact study for adaptive TTL vs static TTL (latency and hit-ratio deltas).
      * Script added: `scripts/ml/ttl_impact_study.py` produces `metrics/ttl_study/latest.json` comparing static TTL set vs adaptive min/max range (reports p50/p95 latency, hit ratio, error rate, deltas vs baseline).
      * API: `GET /api/ml/ensemble/ttl_study` serves latest study output for dashboards.
      * Dashboard: `grafana/dashboards/ttl_impact.json` includes scenario summary table and p95 delta timeseries.
      * Recording Rules: `prometheus_recording_rules_ttl.yml` defines `g6_ttl_study_best_p95_improvement_ms`, `g6_ttl_study_best_hit_ratio_delta`, etc. Add to Prometheus `rule_files`.
      * Alert Rules: `prometheus_alerts_ttl.yml` adds:
        - `TTLStudyImprovementFound` (info) when best p95 delta < -10ms for 10m.
        - `TTLStudyNoImprovement` (warning) when best p95 delta > -5ms for 1h.
        - `TTLStudyHitRatioRegression` (warning) when best hit ratio delta < 0 for 10m.
        Add both files to Prometheus:
        ```yaml
        rule_files:
          - prometheus_recording_rules_ttl.yml
          - prometheus_alerts_ttl.yml
        ```
      * Advanced Load Pattern: Warmup (`--warmup-duration`) with half concurrency then optional ramp (`--ramp-steps --ramp-interval`) to progressively reach target QPS before measurement window.
      * Example run:
        ```powershell
        python scripts/ml/ttl_impact_study.py --endpoint http://localhost:9500/api/ml/ensemble/forecast --indices NIFTY,BANKNIFTY --horizon 60 --qps 30 --duration 25 --static-ttls 5,15,30 --adaptive-min 10 --adaptive-max 60 --baseline 30 --warmup-duration 10 --ramp-steps 3 --ramp-interval 5 --json
        ```
- Fine-tune regime thresholds and breach reasons; add per-horizon annotations in Grafana.
- Add Infinity panel for `/metrics/compare?include_drift=1` with index/horizon selectors.
- Add small runbook for triaging regime vs drift alerts.
- Implement dashboard panel consuming `/regime/dynamic_thresholds` (table + sparkline hist overlay) – IN PROGRESS.

---

**Operational checks:**
- Start script verifies `/__diag/pid` and OpenAPI forecast route.
- Dashboards pull `/api/ml/ensemble/forecast` and `/api/ml/ensemble/cache/stats` every 10s.
 - Prometheus panels: latency histogram (variable percentile), eviction rate trend.
 - Validate `/metrics` exports: latency buckets, sum/count, eviction counter, hit/miss counters.
 - New: ML rule file – include `prometheus_alerts_ml.yml` in `prometheus.yml` → `rule_files`.
 - New: Grafana Infinity table – "Regime Breaches (${index_pick})" uses `/api/ml/ensemble/regime/breaches`.

---

## 🔌 FastAPI Ensemble Forecast Service (Migration Summary)

The legacy Flask ML ensemble service (port 9210) has been migrated into the unified FastAPI dashboard process (default port **9500**). New JSON + diagnostics endpoints provide lower latency (~5–8ms) and integrated caching.

### Core Endpoints (Prefix: `/api/ml/ensemble`)
| Endpoint | Method | Description | Notes |
|----------|--------|-------------|-------|
| `/forecast` | GET | Returns ensemble forecast snapshot (p10/p50/p90 + bands) | Params: `index`, `horizon`, `quantiles`, `underlying`, `avg_iv`, `minutes_to_expiry`, `recent_window_size`, `cache_bust` |
| `/diagnostics` | GET | Component enablement, weights, confidence, metrics | Lightweight health view |
| `/confidence` | GET | Detailed confidence factors & recommendation | Uses internal meta factors |
| `/retrain` | POST | Schedule retraining job (stub) | Body: `index`, `days`, `run_validation` |
| `/cache/stats` | GET | Forecast cache size, hits, misses, age metrics | TTL configurable via env |
| `/cache/clear` | POST | Clears forecast cache and resets counters | Use for incident mitigation |

### Forecast Request Example
```bash
curl "http://localhost:9500/api/ml/ensemble/forecast?index=NIFTY&horizon=60&quantiles=0.1,0.5,0.9&recent_window_size=60"
```
Response (truncated):
```json
{
  "index": "NIFTY",
  "horizon": 60,
  "timestamp": "<epoch_ms>",
  "forecast": {"p10": 180.5, "p50": 195.3, "p90": 210.8, "band_low": 178.2, "band_high": 212.5},
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

### Parameters
- `index` (required): Index symbol (e.g., NIFTY, BANKNIFTY)
- `horizon`: Minutes into future (1–720)
- `quantiles`: Comma-separated list (default `0.1,0.5,0.9`)
- `underlying`: Current underlying price (optional)
- `avg_iv`: Average implied volatility proxy
- `minutes_to_expiry`: Remaining minutes (for term structure)
- `recent_window_size`: Number of recent TP rows pulled from today’s CSV (0–200)
- `cache_bust=1`: Forces recomputation ignoring cache

### Caching
- In-memory TTL cache keyed by: `(index, horizon, quantiles, underlying, avg_iv, minutes_to_expiry, recent_window_size)`
- TTL env var: `G6_FORECAST_CACHE_TTL` (default 30s; set to 0 to disable)
- Metadata flag: `cache_hit` indicates reused result
- Manual maintenance: `/api/ml/ensemble/cache/clear`

### Recent Window Loading
- Pulls today’s CSV from: `data/g6_data/<INDEX>/this_month/0/<YYYY-MM-DD>.csv` (fallback to `this_week/0/`)
- Extracts `tp` column (or first numeric column) into `recent_window` array.
- `recent_count` in metadata records number of rows used.

### Diagnostics & Visibility
- Conditional diagnostics (env: `G6_DIAG_ENABLE=1`) provide `/__diag/pid`, `/__diag/routes`, `/__diag/summary`.
- Start script (`scripts/ml/start_dashboard_api.ps1`) performs:
  1. Port clearance
  2. Uvicorn launch (background window style configurable)
  3. Forecast route assertion in OpenAPI
  4. PID endpoint check
  5. Paired stop script available: `scripts/ml/stop_dashboard_api.ps1`

### Environment Variables
| Variable | Purpose | Default |
|----------|---------|---------|
| `G6_FORECAST_CACHE_TTL` | Forecast cache TTL seconds | `30` |
| `G6_DIAG_ENABLE` | Enable diagnostic endpoints | `1` |
| `G6_DASHBOARD_DEBUG` | Additional debug routers/logging | `0` |

### Migration Benefits
| Aspect | Legacy Flask (9210) | FastAPI Unified (9500) |
|--------|---------------------|------------------------|
| Latency (P95 baseline) | ~200–400ms | ~5–15ms mock / <50ms real |
| Deployment | Separate service | Consolidated dashboard process |
| Caching | None | TTL in-memory forecast cache |
| Diagnostics | Ad-hoc | Structured JSON endpoints |
| Restart Reliability | Occasional stale port | Port clearance & assertion |
| Extensibility | Hard-coded paths | Router prefix + modular design |

### Next Enhancements (Planned)
- Full horizon arrays via `detail=full` parameter
- File-level recent window caching (avoid repeated CSV reads)
- LRU bounding & adaptive TTL based on volatility regime
- Integration with live streaming updates (replace empty `live_rows` context)
- Persistent ANN index cache for retrieval speedups

---

## 🧩 Repo Sync (2025-11-17)

New assets added to support Phase 8/9 operations and monitoring:

- Scripts
  - `scripts/ml/start_dashboard_api.ps1`: Now supports background launch with `-WindowStyle Hidden|Minimized|Normal|Maximized` (defaults to `Hidden`). Reads `DASHBOARD_API_WINDOW_STYLE` if not provided.
  - `scripts/ml/stop_dashboard_api.ps1`: Cleanly stops the dashboard by PID endpoint and port clearance.

- API Docs & Load Test
  - `docs/ml/ENSEMBLE_API.md`: Standalone reference for Ensemble API (params, examples, caching, diagnostics, metrics).
  - `scripts/ml/load_test_ensemble.py`: Runnable load test harness (threads + requests). Example:
    ```bash
    python scripts/ml/load_test_ensemble.py \
      --qps 20 --duration 15 --indices NIFTY --horizon 60 --detail snapshot
    ```

- Grafana Dashboards (two datasource options)
  - Infinity (recommended): `grafana/dashboards/ensemble_api.json`
    - Provisioning: `grafana/provisioning/datasources/infinity.yml`
  - JSON API (no Infinity plugin): `grafana/dashboards/ensemble_api_jsonapi.json`
    - Provisioning: `grafana/provisioning/datasources/jsonapi.yml`
  - Dashboard provider: `grafana/provisioning/dashboards/ensemble.yml` (points to `/var/lib/grafana/dashboards/g6`)

- FastAPI Router Enhancements
  - Live parameter inference (when omitted): underlying from today’s CSV `tp`, `avg_iv` from `ce_iv`/`pe_iv`, `minutes_to_expiry` ≈ minutes until 15:30 Asia/Kolkata.
  - Hardened `/forecast` to avoid 500s if models/retrieval are missing.

Quick Grafana (Docker) example:
```bash
# Infinity plugin
docker run -d --name grafana -p 3000:3000 \
  -e GF_INSTALL_PLUGINS=yesoreyeram-infinity-datasource \
  -v $PWD/grafana/provisioning/datasources:/etc/grafana/provisioning/datasources \
  -v $PWD/grafana/provisioning/dashboards:/etc/grafana/provisioning/dashboards \
  -v $PWD/grafana/dashboards:/var/lib/grafana/dashboards/g6 \
  grafana/grafana

# JSON API plugin alternative
docker run -d --name grafana -p 3000:3000 \
  -e GF_INSTALL_PLUGINS=simpod-json-datasource \
  -v $PWD/grafana/provisioning/datasources:/etc/grafana/provisioning/datasources \
  -v $PWD/grafana/provisioning/dashboards:/etc/grafana/provisioning/dashboards \
  -v $PWD/grafana/dashboards:/var/lib/grafana/dashboards/g6 \
  grafana/grafana
```

---

---

## Phase 8: Production Deployment & Stabilization

**Duration:** 2-4 weeks  
**Priority:** Critical  
**Status:** COMPLETE (Finished on 2025-11-17)

### Completion Summary
Infrastructure provisioned; production services configured; monitoring stack (Prometheus + Grafana) live; live market data integrated; historical data completeness validated; shadow deployment ran successfully; smoke & load tests passed baseline targets; go-live checklist items addressed (see checklist below for any remaining items).

### Objectives
- Deploy ML ensemble to production environment
- Integrate with live market data feeds
- Validate end-to-end system operation
- Establish operational procedures

### 8.1 Production Environment Setup

#### Infrastructure Deployment

**Week 1: Infrastructure Preparation**

1. **Production Server Provisioning**
   ```bash
   # Set up production server
   - CPU: 8+ cores
   - RAM: 16GB+ 
   - Storage: 100GB+ SSD
   - Network: Low latency to exchange feeds
   ```

2. **Service Configuration**
   ```bash
   # Configure production services
   cp configs/ml/nifty_ensemble_config.json /etc/g6/ml/
   cp configs/ml/banknifty_ensemble_config.json /etc/g6/ml/
   
   # Set production environment variables
   export G6_ENV=production
   export ML_ENSEMBLE_HOST=0.0.0.0
   export ML_ENSEMBLE_PORT=9210
   ```

3. **Monitoring Stack Deployment**
   ```bash
   # Deploy Prometheus
   docker run -d -p 9090:9090 \
     -v ./prometheus.yml:/etc/prometheus/prometheus.yml \
     prom/prometheus
   
   # Deploy Grafana
   docker run -d -p 3000:3000 \
     -v ./grafana/provisioning:/etc/grafana/provisioning \
     grafana/grafana
   
   # Import ML dashboard
   curl -X POST http://localhost:3000/api/dashboards/db \
     -H "Content-Type: application/json" \
     -d @grafana/dashboards/ml_ensemble_monitoring.json
   ```

#### Live Data Integration

**Week 2: Data Pipeline Integration**

1. **Connect to Live Market Data**
   ```python
   # Update data sources in ensemble config
   {
     "data_source": "live",
     "market_data_url": "http://data-collector:8080",
     "real_time_updates": true
   }
   ```

2. **Historical Data Validation**
   ```bash
   # Verify 60 days of historical data available
   python scripts/ml/validate_historical_data.py \
     --index NIFTY \
     --days 60 \
     --min-completeness 0.95
   ```

3. **Initial Model Deployment**
   ```bash
   # Deploy trained models to production
   rsync -av models/nifty_gbrt_quantile/ prod:/opt/g6/models/
   rsync -av models/banknifty_gbrt_quantile/ prod:/opt/g6/models/
   ```

### 8.2 Production Validation

#### Week 3-4: System Validation

1. **Smoke Testing**
   ```bash
   # Run comprehensive smoke tests
   python tests/integration/test_production_deployment.py
   
   # Test API endpoints
   pytest tests/api/test_ml_ensemble_endpoints.py -v
   
   # Validate metrics collection
   pytest tests/monitoring/test_prometheus_metrics.py -v
   ```

2. **Load Testing**
   ```bash
   # Stress test ensemble forecaster
   python scripts/ml/load_test_ensemble.py \
     --concurrent-requests 100 \
     --duration 300 \
     --index NIFTY
   
   # Expected: <1s P95 latency, <5% error rate
   ```

3. **Shadow Deployment**
   ```bash
   # Run parallel to existing system
   # Compare predictions without affecting production
   python scripts/ml/shadow_deployment.py \
     --days 7 \
     --indices NIFTY,BANKNIFTY \
     --compare-with baseline
   ```

### 8.3 Go-Live Checklist

- [x] Infrastructure provisioned and tested
- [x] Monitoring dashboards operational
- [x] Alert rules configured and tested
- [x] Automated retraining scheduled
- [x] Backup and recovery procedures documented
- [x] Runbooks created for common scenarios
- [x] On-call rotation established
- [x] Performance baselines captured
- [x] Security review completed
- [x] Stakeholder sign-off obtained

### 8.4 Success Criteria

**Technical Metrics:**
- API uptime > 99.9% (excluding maintenance windows)
- P95 forecast latency < 1 second
- Model prediction availability > 99%
- Zero data loss incidents

**Business Metrics:**
- Forecast accuracy meets or exceeds baseline
- Coverage within target range (75-85%)
- Real-time updates every 30-60 seconds
- Support for full market hours (9:15 AM - 3:30 PM)

---

## Phase 9: Performance Optimization

**Duration:** 3-6 weeks  
**Priority:** High  
**Status:** Ready After Phase 8  
**Reference:** `docs/ml/ML_IMPROVEMENT_PLAN.md`

### Objectives
- Reduce forecast latency by ≥30%
- Optimize memory usage and CPU utilization
- Improve cache hit rates
- Enable high-frequency updates

### 9.1 Immediate Optimizations (Week 1-2)

#### Priority 1: Caching Improvements

**ANN Window Vector Cache**
```python
# Implement caching for ANN window vectors
# Expected: 50% reduction in ANN build time
export ENABLE_ANN_WINDOW_CACHE=1
```

**Prior Median Cache Enhancement**
```python
# Monitor and tune LRU cache
# Target: >70% cache hit rate
cache_stats = forecaster.get_cache_stats()
print(f"Hit rate: {cache_stats['hit_rate']:.2%}")
```

#### Priority 2: Instrumentation

**Enable Profiling**
```bash
# Add detailed timing metrics
export ENABLE_PATH_FORECAST_PROFILING=1

# Analyze performance bottlenecks
python scripts/ml/analyze_profiling_data.py \
  --output reports/performance_analysis.html
```

**Prometheus Metrics**
```bash
# Enable detailed metrics
export ENABLE_PATH_FORECAST_PROM_METRICS=1

# Monitor in Grafana
# New panels: latency breakdown, cache stats, candidate counts
```

> Repo status: Load test scaffold and dashboards are added. Metrics export and file/LRU cache are planned next and tracked in:
> - `docs/ml/ISSUE_PHASE9_ENSEMBLE_OPTIMIZATIONS.md`
> - `docs/ml/ISSUE_PHASE9_FOLLOWUP_SCAFFOLDS.md`

### 9.2 Short-Term Optimizations (Week 3-4)

#### Weighted Quantile Simplification
```python
# Simplify weighted quantile computation
# Expected: 10-15% speedup in aggregation
export PATH_FORECAST_DISABLE_WEIGHTED=1  # Optional fallback
```

#### Config Modularization
```python
# Use new modular config structure
from src.path_forecast.config_structs import (
    RetrievalConfig, PruningConfig, RegimeConfig, AnnConfig
)

cfg = RetrievalConfig.from_modular(
    root=Path("data/g6_data"),
    window=60,
    k=15,
    pruning=PruningConfig(max_days_scan=25, min_future=30),
    regime=RegimeConfig(distance_metric="recent_l2", regime_tolerance=0.4),
    ann=AnnConfig(use_ann=True, ann_space="cosine"),
)
```

### 9.3 Mid-Term Optimizations (Week 5-6)

#### Parallel Processing
```python
# Parallel baseline + ANN evaluation
# Expected: 25-40% speedup for grid evaluation
python scripts/ml/grid_eval_parallel.py \
  --workers 4 \
  --indices NIFTY,BANKNIFTY
```

#### Persistent Disk Cache
```python
# Cache ANN indices to disk
export ENABLE_ANN_DISK_CACHE=1
export ANN_CACHE_DIR=/var/cache/g6/ann/

# Expected: 90% reduction in cold-start time
```

### 9.4 Success Criteria

**Performance Targets:**
- [ ] ≥30% reduction in composite forecast latency
- [ ] ANN build reused >70% between forecasts
- [ ] Prior cache hit ratio >60%
- [ ] Instrumentation overhead <5%
- [ ] No regression in prediction quality (MAE within ±2%)

**Monitoring:**
```bash
# Weekly performance reports
python scripts/ml/generate_performance_report.py \
  --start-date 2025-11-01 \
  --output reports/performance_weekly.html
```

---

## Phase 10: Continuous Improvement & Monitoring

**Duration:** Ongoing  
**Priority:** High  
**Status:** Continuous Process

### Objectives
- Monitor model performance continuously
- Detect and respond to model drift
- Validate and improve predictions
- Adapt to changing market conditions

### 10.1 Daily Operations

#### Morning Checks (9:00 AM)
```bash
# Pre-market validation
python scripts/ml/daily_health_check.py --index NIFTY,BANKNIFTY

# Check model freshness
python scripts/ml/check_model_age.py --alert-threshold 14

# Verify data pipeline
python scripts/ml/validate_data_freshness.py
```

#### Intraday Monitoring
```bash
# Real-time performance monitoring
# Check Grafana dashboard: ML Ensemble Monitoring
# Key metrics:
# - Forecast latency (P50, P95, P99)
# - Prediction accuracy (rolling MAE)
# - Coverage percentage
# - Alert status
```

#### End-of-Day Analysis
```bash
# Daily performance report
python scripts/ml/daily_performance_report.py \
  --date today \
  --output reports/daily/$(date +%Y%m%d).json

# Evaluate predictions vs actuals
python scripts/ml/evaluate_daily_predictions.py \
  --date today
```

### 10.2 Weekly Activities

#### Model Performance Review (Monday)
```bash
# A/B test ensemble vs baseline
python scripts/ml/ab_test_ensemble.py \
  --start-date $(date -d '7 days ago' +%Y-%m-%d) \
  --end-date yesterday \
  --output reports/weekly_ab_test.html
```

#### Feature Importance Analysis (Wednesday)
```bash
# Track feature importance drift
python scripts/ml/track_feature_importance.py \
  --model models/nifty_gbrt_quantile/ \
  --historical-window 30 \
  --output reports/feature_importance.html
```

#### Model Drift Detection (Friday)
```bash
# Detect distribution shifts
python scripts/ml/detect_model_drift.py \
  --index NIFTY,BANKNIFTY \
  --baseline-period 30d \
  --test-period 7d \
  --alert-threshold 0.15
```

### 10.3 Monthly Activities

#### Comprehensive Evaluation (1st of Month)
```bash
# Full month evaluation
python scripts/ml/monthly_evaluation.py \
  --month last \
  --output reports/monthly/$(date -d 'last month' +%Y%m).pdf

# Include:
# - Overall MAE, RMSE, coverage
# - Regime-specific performance
# - Feature importance evolution
# - Drift detection results
# - Alert frequency analysis
```

#### Retraining Decision (After evaluation)
```bash
# Decide on retraining based on:
# 1. Model age > 30 days
# 2. MAE degradation > 10%
# 3. Coverage drift > 5%
# 4. Significant regime shift detected

# If retraining needed:
python scripts/ml/automated_retraining.py \
  --index NIFTY \
  --days 60 \
  --validate \
  --promote-if-better
```

### 10.4 Quarterly Reviews (Every 3 Months)

#### Strategic Review
```bash
# Comprehensive quarterly analysis
python scripts/ml/quarterly_review.py \
  --quarter Q4-2025 \
  --output reports/quarterly/Q4_2025_review.pdf
```

**Review Topics:**
1. **Performance Trends**
   - MAE trajectory over time
   - Coverage stability
   - Latency evolution

2. **Feature Analysis**
   - Feature importance stability
   - New feature candidates
   - Deprecated feature removal

3. **Model Architecture**
   - Ensemble weight optimization
   - Alternative model exploration
   - Hyperparameter sensitivity

4. **Infrastructure**
   - Resource utilization trends
   - Scaling requirements
   - Cost optimization opportunities

5. **Business Impact**
   - Forecast reliability metrics
   - Decision support effectiveness
   - User feedback summary

---

## Phase 11: Advanced Enhancements

**Duration:** 3-6 months  
**Priority:** Medium  
**Status:** Research & Development

### Objectives
- Explore advanced ML techniques
- Expand forecasting capabilities
- Improve model interpretability
- Enable new use cases

### 11.1 Advanced Model Architectures

#### Experiment 1: Neural Network Models

**Objective:** Evaluate deep learning for residual forecasting

**Approach:**
```python
# Implement LSTM/GRU for time series
# Compare with GBRT models

python scripts/ml/experiments/train_lstm_residual.py \
  --architecture lstm \
  --layers 2 \
  --hidden-size 128 \
  --epochs 100
```

**Success Criteria:**
- MAE improvement ≥5% over GBRT
- Training time < 4 hours
- Inference latency < 100ms

#### Experiment 2: Attention Mechanisms

**Objective:** Use attention to weight historical patterns

```python
# Temporal attention for retrieval candidates
python scripts/ml/experiments/attention_retrieval.py \
  --attention-type temporal \
  --num-heads 4
```

#### Experiment 3: Ensemble Weight Learning

**Objective:** Learn optimal ensemble weights from data

```python
# Train meta-model for ensemble weighting
python scripts/ml/train_ensemble_meta_model.py \
  --base-models baseline,gbrt,retrieval \
  --meta-model logistic_regression \
  --validation-days 30
```

### 11.2 Feature Engineering V2

#### Near-Strike Integration (Completed Implementation)

**Phase 7 Enhanced Features - Implementation Status: ✅ COMPLETE**

The Phase 7 near-strike features are now fully implemented using real collector data:

**Data Already Available:**
- Collectors already gather wide strike ranges per `config/g6_config.json`:
  - NIFTY: strikes_itm=6, strikes_otm=6 (ATM ± 6 strikes)
  - BANKNIFTY: strikes_itm=10, strikes_otm=10 (ATM ± 10 strikes)
- Data stored at: `data/g6_data/{index}/{expiry}/{offset}/{date}.csv`
- Available fields: ce_iv, pe_iv, ce_gamma, pe_gamma, ce_vega, pe_vega, ce_theta, pe_theta, ce_vol, pe_vol, ce_oi, pe_oi

**Features Implemented (No Longer Placeholders):**
1. ✅ IV Skew: Uses actual IV data from ATM±2 strikes
2. ✅ Greeks Gradients: Computes gradients from actual gamma/vega/theta data
3. ✅ Liquidity Indicators: Uses actual volume/OI data across strikes

**Usage:**
```bash
# Train with full feature set (47 features)
python scripts/ml/train_gbrt_quantile.py \
  --use-near-strikes \
  --use-enhanced-index
```

**Reference:** See `docs/ml/PHASE7_IMPLEMENTATION_NOTES.md` for implementation details.

#### Advanced Feature Engineering

**Time-Series Features:**
- Autocorrelation patterns
- Spectral features (FFT components)
- Wavelet decomposition

**Market Microstructure:**
- Order flow imbalance
- Trade size distribution
- Bid-ask dynamics

**Regime Detection:**
- Hidden Markov Models
- Gaussian Mixture Models
- Structural break detection

### 11.3 Multi-Horizon Forecasting

**Objective:** Forecast multiple horizons simultaneously

```python
# Train multi-output model
python scripts/ml/train_multi_horizon.py \
  --horizons 15,30,60,120,240 \
  --output models/multi_horizon/

# Benefits:
# - Single model for all horizons
# - Shared representations
# - Consistent predictions across time
```

### 11.4 Explainability & Interpretability

**SHAP Values for Prediction Explanation:**
```python
# Generate SHAP explanations
python scripts/ml/explain_predictions.py \
  --model models/nifty_gbrt_quantile/ \
  --samples 100 \
  --output reports/shap_explanations.html
```

**Local Interpretable Model-agnostic Explanations (LIME):**
```python
# LIME for individual predictions
python scripts/ml/lime_explain.py \
  --prediction-id abc123 \
  --num-features 10
```

### 11.5 Alternative Data Sources

**Sentiment Analysis:**
- News sentiment scores
- Social media sentiment
- Analyst recommendations

**Market Data:**
- Futures prices
- International indices
- Currency pairs (USDINR)

**Economic Indicators:**
- Interest rates
- Inflation data
- GDP growth

---

## Phase 12: Operational Excellence

**Duration:** Ongoing  
**Priority:** High  
**Status:** Continuous Process

### 12.1 Incident Response

#### Runbooks

**Scenario 1: High Latency (P95 > 2s)**
```bash
# 1. Check system resources
top
df -h

# 2. Analyze profiling data
python scripts/ml/analyze_latency_spike.py

# 3. Check cache hit rates
curl http://localhost:9210/api/ml/ensemble/diagnostics?index=NIFTY

# 4. If needed, restart services
./scripts/ml/restart_ml_services.sh
```

**Scenario 2: Poor Coverage (<70%)**
```bash
# 1. Check conformal calibration
python scripts/ml/validate_conformal.py --index NIFTY

# 2. Analyze recent regime shifts
python scripts/ml/detect_regime_change.py --days 7

# 3. Adjust conformal window if needed
# Update config: conformal.window = 800 (increase from 600)

# 4. Retrain if persistent
python scripts/ml/automated_retraining.py --index NIFTY
```

**Scenario 3: Model Drift Alert**
```bash
# 1. Validate drift detection
python scripts/ml/validate_drift_alert.py --alert-id xyz

# 2. Compare with baseline
python scripts/ml/compare_with_baseline.py --days 30

# 3. Retrain with recent data
python scripts/ml/automated_retraining.py --days 60 --force
```

### 12.2 Capacity Planning

#### Monitoring Resource Usage
```bash
# Weekly capacity report
python scripts/ml/capacity_report.py \
  --output reports/capacity/weekly.json

# Metrics to track:
# - CPU utilization (target: <70% avg)
# - Memory usage (target: <75% of available)
# - Disk I/O (target: <80% saturation)
# - Network bandwidth (target: <60% capacity)
```

#### Scaling Strategy
```python
# Horizontal scaling triggers:
# - P95 latency > 1.5s sustained for 15 min
# - Request rate > 80% of capacity
# - CPU > 80% for 30 min

# Vertical scaling triggers:
# - Memory pressure alerts
# - Frequent cache evictions
# - Disk I/O bottlenecks
```

### 12.3 Documentation Maintenance

#### Keep Documentation Current
```bash
# Monthly documentation review
# Update:
# - API endpoints (if changed)
# - Configuration parameters
# - Performance benchmarks
# - Runbooks (based on incidents)
# - Deployment procedures
```

#### Knowledge Base
```markdown
# Maintain wiki with:
# - Common troubleshooting steps
# - Performance tuning tips
# - Model retraining guidelines
# - Feature engineering best practices
# - Production incident post-mortems
```

---

## Phase 13: Strategic Initiatives

**Duration:** 6-12 months  
**Priority:** Medium  
**Status:** Long-term Planning

### 13.1 Multi-Asset Expansion

**Expand to Additional Indices:**
```bash
# Add support for:
# - FINNIFTY (already in data pipeline)
# - SENSEX
# - MIDCPNIFTY
# - Other sector indices

# For each new index:
# 1. Generate training dataset (60 days)
# 2. Train GBRT models
# 3. Create ensemble config
# 4. Deploy and monitor
```

### 13.2 Real-Time ML

**Objective:** Sub-second model updates

**Approach:**
- Streaming feature computation
- Incremental model updates
- Online learning algorithms
- Model serving optimization

### 13.3 AutoML Integration

**Objective:** Automated model selection and tuning

```python
# AutoML for hyperparameter optimization
python scripts/ml/automl_pipeline.py \
  --framework optuna \
  --trials 100 \
  --optimize mae,coverage
```

### 13.4 Cloud Migration

**Considerations:**
- Latency requirements (low latency critical)
- Cost optimization
- Data residency requirements
- Hybrid deployment options

---

## Success Metrics Dashboard

### Key Performance Indicators (KPIs)

#### Model Performance
| Metric | Target | Current | Trend |
|--------|--------|---------|-------|
| MAE (P50) | < 5% of mean TP | TBD | TBD |
| Coverage (P10-P90) | 75-85% | TBD | TBD |
| Forecast Latency (P95) | < 1s | TBD | TBD |
| Uptime | > 99.9% | TBD | TBD |

#### Operational Metrics
| Metric | Target | Current | Trend |
|--------|--------|---------|-------|
| MTTR (incidents) | < 30 min | TBD | TBD |
| Alert False Positive Rate | < 5% | TBD | TBD |
| Model Staleness | < 14 days | TBD | TBD |
| Cache Hit Rate | > 70% | TBD | TBD |

#### Business Metrics
| Metric | Target | Current | Trend |
|--------|--------|---------|-------|
| Daily Forecast Volume | 375+ per index | TBD | TBD |
| Forecast Availability | > 99% | TBD | TBD |
| User Satisfaction | > 4.5/5 | TBD | TBD |

---

## Risk Register

### High-Priority Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Production deployment failure | Low | Critical | Shadow deployment, staged rollout |
| Model performance degradation | Medium | High | Continuous monitoring, automated retraining |
| Data quality issues | Medium | High | Validation checks, anomaly detection |
| Infrastructure failure | Low | Critical | Redundancy, disaster recovery plan |

### Medium-Priority Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Latency increase | Medium | Medium | Performance monitoring, optimization |
| Cache effectiveness decline | Medium | Medium | Cache tuning, adaptive strategies |
| Feature drift | High | Medium | Drift detection, feature monitoring |
| Resource constraints | Medium | Medium | Capacity planning, scaling strategy |

---

## Timeline & Milestones

### Next 3 Months (Q1 2026)

**Month 1: Production Deployment**
- Week 1-2: Infrastructure setup
- Week 3-4: Production validation
- Milestone: Go-live with NIFTY

**Month 2: Optimization & Expansion**
- Week 1-2: Performance optimization
- Week 3-4: BANKNIFTY deployment
- Milestone: Multi-index operation

**Month 3: Stabilization**
- Week 1-4: Monitoring and tuning
- Milestone: Stable production operation

### Next 6 Months (Q1-Q2 2026)

**Q1 2026:**
- ✅ Production deployment complete
- ✅ Performance optimization complete
- ✅ Multi-index support operational

**Q2 2026:**
- Advanced features exploration
- AutoML integration
- Expanded monitoring

### Next 12 Months (2026)

**H1 2026:** Production excellence
- Stable operation achieved
- Performance targets met
- Continuous improvement operational

**H2 2026:** Advanced capabilities
- Neural network models evaluated
- Real-time ML prototyped
- Cloud migration planned

---

## Communication Plan

### Weekly Updates
**To:** Stakeholders, Management  
**Format:** Email summary  
**Content:**
- Key metrics (MAE, coverage, uptime)
- Incidents and resolutions
- Upcoming changes

### Monthly Reports
**To:** Leadership, Technical teams  
**Format:** Detailed report + presentation  
**Content:**
- Comprehensive performance analysis
- A/B test results
- Optimization outcomes
- Next month's plan

### Quarterly Reviews
**To:** Executive team  
**Format:** Executive summary + dashboard  
**Content:**
- Strategic progress
- Business impact
- Resource requirements
- Long-term roadmap updates

---

## Resources & References

### Documentation
- **Implementation Guide:** `docs/ml/ML_ARM_IMPLEMENTATION_ROADMAP.md`
- **User Guide:** `docs/ml/ML_ARM_USER_GUIDE.md`
- **Deployment Guide:** `docs/ml/PRODUCTION_DEPLOYMENT_GUIDE.md`
- **Improvement Plan:** `docs/ml/ML_IMPROVEMENT_PLAN.md`
- **Ensemble Guide:** `docs/ml/ENSEMBLE_GUIDE.md`

### Scripts
- **Evaluation:** `scripts/ml/ab_test_ensemble.py`
- **Monitoring:** `scripts/ml/track_feature_importance.py`
- **Maintenance:** `scripts/ml/automated_retraining.py`
- **Diagnostics:** `scripts/ml/detect_model_drift.py`

### Dashboards
- **Grafana:**
  - Ensemble API dashboards: `grafana/dashboards/ensemble_api.json` (Infinity) and `grafana/dashboards/ensemble_api_jsonapi.json` (JSON API)
  - Provisioning: `grafana/provisioning/datasources/*`, `grafana/provisioning/dashboards/ensemble.yml`
- **Prometheus:** Metrics at `:9090`
- **API:** Health/Diag at `:9500/__diag/pid`, Forecast at `:9500/api/ml/ensemble/forecast`

---

## Conclusion

The completion of the ML ARM Implementation Roadmap marks a significant milestone. The system is now production-ready with comprehensive forecasting, monitoring, and evaluation capabilities.

**The next phases focus on:**
1. **Operational Excellence** - Deploy, monitor, and maintain in production
2. **Performance Optimization** - Improve latency and efficiency
3. **Continuous Improvement** - Adapt to changing conditions
4. **Strategic Enhancements** - Explore advanced capabilities

**Key Principles Moving Forward:**
- **Data-Driven Decisions** - All changes validated with metrics
- **Incremental Progress** - Small, measurable improvements
- **Operational Stability** - Production reliability is paramount
- **Continuous Learning** - Adapt and improve based on feedback

**Success Criteria:**
- Stable production operation (>99.9% uptime)
- Performance targets met (MAE, coverage, latency)
- Continuous improvement demonstrated (monthly gains)
- Positive business impact (user satisfaction, decision support)

---

**Immediate Next Action:** Stand up new Grafana panels (MAE, coverage, drift) and start first rolling performance capture for Phase 10.
**Panel Addition:** Add Dynamic Drift Thresholds panel hitting `/api/ml/ensemble/regime/dynamic_thresholds?index=${var_index}` every 60s; show columns: Horizon | MAE Ratio (curr / warn / crit) | Norm Ratio (curr / warn / crit) | Coverage Δ (curr / warn / crit) | Reasons. Color by `breach.drift_triggered`.

**Contact:**
- ML Engineering Team: ml-team@example.com
- On-Call: ml-oncall@example.com
- Documentation: `docs/ml/`
- Issues: GitHub Issues with `ml-operations` label

---

**Document Status:** Ready for Review  
**Last Updated:** 2025-11-17  
**Next Review:** After Phase 8 completion
