# TP Forecasting ML Roadmap (Quantiles, Conformal, Hybrid, Ensemble)

_Last updated: 2025-11-11 (Phase 9 applied_k operationalization complete; Phase 10 adaptive planning + disagreement forecast stub added)_

This document outlines the prioritized evolution path for improving live ATM Total Premium (TP) forecasting beyond the current ANN / HGB baselines.

---
## Problem Context

Intraday TP forecasting requires:
- Low-latency, robust point predictions across short horizons (1–8 bars / minutes buckets)
- Reliable uncertainty bands (operational decisions, risk gating, band alerts)
- Stability over regime shifts (volatility spikes, expiry rolls, gap opens)
- Simple operational footprint (Prometheus + Grafana already integrated)

Current stack highlights:
- Models: `sk_hgb_regressor`, `xgb_regressor`, `torch_lstm_regressor`, `baseline_linear`
- Live exporter writes CSV: `data/ml/live_predictions/<INDEX>.csv`
- API endpoints: `/api/ml/predictions`, `/api/ml/diagnostics`, `/api/ml/delta`, `/api/ml/model_matrix`
- Dashboards consume CSV via Grafana Infinity
- Band calibration script exists (static/empirical)

---
## Phase Overview

| Phase | Goal | Key Deliverable | Risk | Effort |
|-------|------|-----------------|------|--------|
| 1 | Native probabilistic outputs | Quantile regression trees (LightGBM or CatBoost) + p10/p50/p90 + Prom metrics | Low | Medium |
| 2 | Adaptive, distribution-free coverage | Conformal bands wrapper around existing point models | Low | Low |
| 3 | Structural + data-driven blend | Hybrid option-pricing baseline + residual ML | Low/Med | Medium |
| 4 (opt) | Noise reduction, regime signal | Kalman smoother + shock detection | Medium | Medium |
| 5 (opt) | Actionable signal focus | Two-stage move classifier + conditional regression | Medium | Medium |
| 6 (opt) | Stability via consensus + drift sensing | Ensemble consensus exporter + disagreement metrics/alerts | Medium | Low |

---
## Phase 1: Quantile Regression (Priority)

Add a model plugin producing predictive quantiles for TP.

Approach:
1. Train three LightGBM (or CatBoost) models independently for q=0.1,0.5,0.9 using pinball (quantile) loss.
2. Artifacts: `*_q10.joblib`, `*_q50.joblib`, `*_q90.joblib` (plus `.fe.json` sidecars).
3. Exporter enhancement: each prediction row emits columns: `timestamp,prediction,p10,p50,p90,model,index,horizon` where `prediction == p50`.
4. Prometheus metrics: gauges `g6_ml_prediction_p10`, `g6_ml_prediction_p50`, `g6_ml_prediction_p90` (implemented in exporter with `--port`).
5. Dashboards: fill band between p10 and p90; keep existing HGB baseline for comparison.
6. Champion selection: extend script to compute _average pinball loss_ (q10 + q50 + q90)/3.

Benefits:
- Direct, model-based uncertainty (no post-hoc heuristics).
- Lower complexity vs deep ANN; strong tabular performance.

---
## Phase 2: Conformal Prediction Bands

Goal: Provide statistically valid coverage even under distribution drift.

Mechanics:
- Maintain rolling residuals (|prediction - actual|) over last N buckets (e.g., N=600) per (index,horizon,model).
- Desired coverage c (e.g. 0.8) → radius = empirical quantile at c.
- Bands: `[pred - radius, pred + radius]` (independent of parametric assumptions).
- If quantile models exist, conformal becomes (a) fallback, (b) coverage guard, or (c) ensemble (choose max of model band and conformal radius to avoid under-coverage).

Extensions:
- Track realized coverage over trailing window; auto-adjust target quantile upward if coverage < c for M successive windows.
- Emit `band_low`, `band_high`, `conformal_radius`, `coverage_estimate` via diagnostics endpoint. Export rolling `g6_ml_conformal_radius` (implemented) and `g6_ml_conformal_coverage_estimate` (implemented) in exporter with CLI controls `--coverage`, `--band-window`.

---
## Phase 3: Hybrid Option-Pricing Residual Model

Motivation: TP exhibits deterministic decay (theta) + volatility-driven excursions.

Steps:
1. Compute fast baseline TP: simplified ATM Bachelier (or Black approximation) using underlying price, time-to-expiry, IV proxy.
2. Residual target = `tp_actual - baseline_tp`.
3. Train a tree model to predict residual; final prediction = baseline + residual_pred.
4. Features: underlying price, minutes to expiry, intra-session progress %, recent TP lags, IV proxy, directional microstructure signals.
5. Diagnostics: compare RMSE of baseline vs hybrid; log improvement ratio.

Benefits:
- Better extrapolation across expiries & volatility regimes.
- Interpretability (decompose into structural + learned residual).

Artifacts (added):
- `src/analytics/ml/baseline.py` — baseline_tp implementation with safeguards.
- `configs/ml/nifty_tp_forecast_hybrid_residual.json` — config for residual model training.
- `scripts/ml/train_tp_hybrid_residual.py` — trainer that fits residuals with HGB/GBR and saves artifact.
- VS Code task: "ML: Train Hybrid Residual TP Model (NIFTY)" (prompts for training CSV).

---
## Phase 4 (Optional): Kalman Smoother & Shock Detection

- Implemented: 1D Kalman smoother for TP with exporter writing to `data/ml/live_predictions/<INDEX>_smooth.csv` using schema `timestamp,prediction,raw_tp,shock_score,model,index,horizon` where `model=kalman_smooth`.
- Prometheus (optional): `g6_ml_smoothed_tp`, `g6_ml_raw_tp` via `--port`.
- Shock score added: `g6_ml_tp_shock_score` (|raw - smooth| / rolling_std) with recording rules `ml:tp:shock_p95_15m`, `ml:tp:shock_avg_5m` and alerts `MLTPShockElevated`, `MLTPShockSevere`.
- Suggested: Add dashboard overlay of raw vs smoothed TP.
- Future (optional): shock score = |raw - smooth| / sigma to adapt bands.

---
## Phase 5 (Optional): Two-Stage Event/Magnitude Modeling

- Implemented scaffolding: volatility-adjusted threshold labeling using rolling std of |ΔTP| (window=60) * factor (1.25).
- Classifier artifact (`nifty_tp_move_classifier.joblib`) trained via `scripts/ml/train_tp_move_classifier.py` with AUC metric.
- Conditional regressor artifact (`nifty_tp_move_conditional.joblib`) trained only on move events; falls back to mean magnitude if sparse.
- Exporter (`scripts/ml/move_predict_exporter.py`) emits CSV: `timestamp,move_prob,move_label_pred,conditional_magnitude,model,index,horizon` and gauges: `g6_ml_move_probability`, `g6_ml_move_conditional_magnitude`.
- VS Code tasks added for training and continuous exporter run.
- Next: Grafana panels (probability timeseries + magnitude distribution) and optional Prometheus alert on sustained high move probability.

---
## Phase 6 (Optional): Ensemble Consensus & Disagreement Layer

Purpose: Reduce sensitivity to single-model drift and surface regime shifts through cross-model disagreement.

Components:
1. Continuous exporter aggregating latest per-bucket predictions across configured models (default: `sk_hgb_regressor,xgb_regressor,torch_lstm_regressor,sk_hgb_residual`).
2. Output CSV (`<INDEX>_ensemble.csv`) columns: `timestamp,consensus,disagreement,models_count,models,index,horizon` where:
    - `consensus` = mean of member predictions (optionally extend to median/weighted in future).
    - `disagreement` = std dev of member predictions (future: add max spread, MAD).
3. Prometheus gauges: `g6_ml_ensemble_consensus`, `g6_ml_ensemble_disagreement`, `g6_ml_ensemble_models_count` with recording rules:
    - `ml:ensemble:disagreement_avg_15m` (average disagreement window)
    - `ml:ensemble:disagreement_p95_15m` (tail risk of divergence)
    - `ml:ensemble:models_count_min_15m` (availability health of ensemble members)
4. Alerts:
    - `MLEnsembleDisagreementHigh` (warning sustained elevated std)
    - `MLEnsembleDisagreementSurge` (critical tail divergence)
    - `MLEnsembleTooFewModels` (info; exporter/member outage detection)
5. Grafana panels: consensus line vs champion prediction; area plot of disagreement; single-stat of contributing models; heatmap (optional) of disagreement over session timeline.
6. Diagnostics roadmap: add consensus vs champion delta metrics and improvement ratio (future extension) to `/api/ml/diagnostics`.

Edge Cases:
| Scenario | Risk | Mitigation |
|----------|------|-----------|
| Missing member CSV rows | Bias consensus | Drop bucket if <2 members; alert on low models_count |
| One model outlier due to feature glitch | Inflated disagreement | Add per-model z-score flag; optional robust aggregator (median) |
| Members with different latency | Stale vs fresh mixing | Use bucketed timestamp rounding (already implemented) |

Success Targets:
- Ensemble disagreement p95 stable within historical band except during genuine volatility spikes (validated against shock score).
- Consensus RMSE improvement ≥5% vs single champion over rolling week.
- Alert false positive rate for disagreement < 1 per day during normal regimes.

Future Extensions:
- Weighted consensus (weights from validation inverse RMSE).
- Drift detector: rising disagreement + falling hybrid improvement ratio.
- Automatic member quarantine when its z-score > threshold for M buckets.

---
## Phase 7 (Optional): Advanced Ensemble Management (Weighted + Quarantine + Drift + Adaptive Bands)

Status: Implemented in code, shipped as endpoints, gauges, and dashboard panels.

Motivation: Improve resilience to single-model drift and uncertainty under regime shifts by adapting aggregation, gating untrustworthy members, and inflating uncertainty when models diverge.

Deliverables:
- Weighted consensus: inverse-RMSE weighting over a rolling window (configurable `--weights-window-minutes`), emitted as `weighted_consensus` in `<INDEX>_ensemble.csv` and Prometheus gauge `g6_ml_ensemble_weighted_consensus`.
- Weights sidecar: `<INDEX>_ensemble_weights.json` with `{timestamp, weights, rmse}`; exposed at `/api/ml/ensemble/weights`.
- Model quarantine: z-score breach detection (`--z-threshold`, `--z-consecutive`) with timed quarantine (`--quarantine-minutes`). Current quarantined members per bucket exported in CSV column `quarantined_models` and gauge `g6_ml_ensemble_models_quarantined`; detailed log `<INDEX>_ensemble_quarantine.log` exposed at `/api/ml/ensemble/quarantine_log`.
- Drift monitors: per-model residual mean/std/KS over rolling window published as `g6_ml_ensemble_model_residual_{mean,std,ks}` with recording rules and alerts (bias shift, variance rise, KS surge).
- Adaptive bands: effective band radius per bucket `radius_eff = max(conformal_radius, k * disagreement)` integrated into `/api/ml/diagnostics` via `include_effective_bands=1&disagreement_k=k`, returning `effective_cov_estimate,effective_radius_avg,effective_radius_last`.

Grafana Dashboard Extensions (added):
- Per-horizon disagreement timeline panel (status/heatmap-style) to spot divergence across 1/30/60-min horizons.
- Model Weights table fed by `/api/ml/ensemble/weights`.
- Quarantine Events table fed by `/api/ml/ensemble/quarantine_log`.

Success Criteria:
- Effective coverage within ±2% of target over rolling 3-hour windows when `k` tuned via calibration task; no persistent under-coverage during volatility spikes.
- Weighted consensus RMSE ≤ unweighted consensus RMSE on 4/5 most recent sessions (rolling eval); quarantine reduces large-error tail (>p95) contribution by ≥30% when triggered.
- Drift alerts (bias/variance/KS) have < 1/day false positives in normal regimes and trigger within 10 minutes during genuine shifts.

Risks & Mitigations:
- Over-quarantine in choppy markets: use consecutive-breach gate (`--z-consecutive`) and auto-unquarantine; visualize events to tune.
- Sidecar/CSV skew: weights are single-horizon; ensure one exporter instance per horizon; panel filters by horizon variable for clarity.
- Heatmap fidelity: Grafana state-timeline approximates a heatmap; upgrade to histogram heatmap if recording histogram buckets in Prometheus later.

Operations Notes:
- Files: `data/ml/live_predictions/<INDEX>_ensemble.csv`, `<INDEX>_ensemble_weights.json`, `<INDEX>_ensemble_quarantine.log`.
- Endpoints: `/api/ml/ensemble`, `/api/ml/ensemble/weights`, `/api/ml/ensemble/quarantine_log`, diagnostics `include_effective_bands=1`.
- Tasks: ensure ensemble exporter started with appropriate flags (`--weighted`, quarantine params) and Prometheus port for gauges.

---
## Phase 8 (Optional): Auto-Calibrate Effective Bands (Recommend k)

Goal: Automatically recommend a disagreement scaling factor k for effective bands such that realized coverage matches a target (e.g., 0.8) over a trailing window.

Definition: Effective radius per bucket b is

    radius_eff(b) = max(conformal_radius, k · disagreement(b))

Where conformal_radius is the empirical quantile (target) of |prediction − tp| over the window and disagreement(b) is the ensemble std at bucket b.

Deliverables:
- New utility `scripts/ml/auto_calibrate_ensemble.py`:
    - Inputs: index, horizon, window_minutes, target (coverage), bucket_ms, use-weighted flag.
    - Reads `<INDEX>_ensemble.csv` (uses `weighted_consensus` if available; falls back to `consensus`) and live tp via `find_live_csv`.
    - Computes conformal_radius from |pred − tp| and scans k over a grid to minimize |effective_coverage − target|.
    - Outputs recommended k, summary stats (n, band_radius, eff_cov), and writes optional sidecar `data/ml/live_predictions/<INDEX>_ensemble_k_calibration.json`.
    - Daemon mode (interval loop) with Prometheus gauge `g6_ml_ensemble_k_recommended{index,horizon}` when `--port` provided.

Success Criteria:
- Recommended k stabilizes within ±0.2 during quiet regimes, adapts up during high disagreement spikes, and maintains realized coverage within ±2% of target over 3-hour windows.

Risks & Mitigations:
- Overfitting to short windows → allow min window (e.g., ≥120 min) and smoothing (EMA) on k in daemon mode.
- Double-inflation if conformal_radius already elevated → max() form ensures no shrink; monitoring `effective_cov_estimate` guards outcomes.

Operational Notes:
- Prefer one exporter per horizon to keep weights/quarantine/ensembles horizon-specific.
- If live tp is sparse early session, fallback to previous day’s tail may be added later (v2).

Next Extensions:
- Persist and serve recommended k via a lightweight endpoint for dashboards and exporters.
- Auto-tune RMSE weights window length using drift signals (std/KS) to maintain stability without lag.

---
## Phase 9 (Optional): Operationalize Calibrated k (applied_k + Observability)

Goal: Transition from raw recommended_k to a production-safe applied_k that is stable, observable, overrideable, and coverage-audited.

Core Concepts:
- recommended_k: Point estimate from calibration grid minimizing coverage error.
- k_smooth: EMA-smoothed recommended_k to reduce jumpiness between successive calibrations.
- applied_k: Final value used for band scaling with precedence: override > k_smooth > recommended_k.
- scaled_radius: applied_k * disagreement (combined with conformal via max()).
- effective_hit: Binary indicator (1/0) whether consensus lies within effective band.

Deliverables (Implemented):
- Exporter columns: `applied_k,applied_k_source,scaled_radius` appended to ensemble CSV.
- Prometheus gauges: `g6_ml_ensemble_applied_k`, `g6_ml_ensemble_scaled_radius`, `g6_ml_ensemble_effective_hit`.
- Recording rules: Effective coverage windows (15m/60m) and latest applied_k & scaled_radius.
- Alerts: Fast/slow coverage drift + long-lived override duration.
- API: `/api/ml/ensemble/k_applied`, `/api/ml/ensemble/k_override` (POST with audit), `/api/ml/ensemble/k_overrides` (listing).
- Audit Log: Per override append entries capturing timestamp + k + horizon + optional expiry.
- Grafana Panels: Applied k timeline vs smooth/raw; scaled radius trend; effective coverage stats; active overrides table.
- Tests: Smooth preference, override precedence, scaled radius consistency, endpoint schema checks.

Success Criteria (Achieved):
- Coverage maintained within selected alert bands absent volatility shocks.
- Operators can safely apply temporary overrides with visibility & expiry.
- Scaled radius reacts proportionally to disagreement without destabilizing coverage.

Risks & Mitigations:
- Override misuse → alert on duration; audit trail; planned metadata enrichment.
- Over-smoothing → retain fallback to raw recommended_k when EMA unavailable or window too short.
- Under-coverage during disagreement spike → scaled_radius inflation via applied_k selection ensures rapid widening.

Follow-up Enhancements (Phase 10 feed-ins):
- Adaptive coverage target adjustments based on effective coverage drift.
- Predictive disagreement to pre-emptively scale bands.
- Rich audit metadata (actor, reason, source IP/hash) & override safety auto-revert.

---
## Phase 10 (Adaptive): Dynamic Coverage Target & Predictive Disagreement (In Progress)

Goal: Reduce manual overrides and shorten recovery time after volatility/regime shifts by (a) adaptively steering the coverage target, and (b) pre‑widening uncertainty bands using a disagreement forecast.

### 10.1 Design Rationale
- Manual overrides are reactive and can linger (risk of over‑widened bands). Adaptive target adjusts proactively within bounded guardrails.
- Disagreement tends to surge before sustained under‑coverage; forecasting (even a simple EMA) allows anticipatory widening instead of after‑the‑fact overrides.
- Combining conformal bands (distribution‑free) with a calibrated k and a predictive floor retains statistical validity while improving responsiveness.

### 10.2 Adaptive Coverage Target Mechanics
Inputs: effective coverage estimates from short (15m) and long (60m) windows; baseline target T_base (e.g. 0.80).
Parameters:
- step: target increment/decrement (e.g. 0.01)
- delta_low / delta_high: hysteresis margins (e.g. 0.02 below, 0.015 above)
- W_low / W_high: sustained window breach counts before adjusting (e.g. 3, 4 cycles)
- target_min / target_max bounds (e.g. 0.76, 0.84)
- dwell_cycles: minimum cycles between successive adjustments (e.g. 6) to damp oscillation
- grace_open_cycles: ignore adjustments in first N cycles of session (e.g. 10)

Logic (pseudo):
1. Collect cov_fast, cov_slow.
2. If both < T_current - delta_low for W_low cycles and dwell satisfied → raise target min(T_current + step, target_max).
3. Else if both > T_current + delta_high for W_high cycles and dwell satisfied → lower target max(T_current - step, target_min).
4. Else maintain target and reset/age counters.
5. Adaptive state = raising | lowering | stable.

Output persisted in sidecar: `dynamic_target_coverage`, `adaptive_state`, plus `target` (static baseline) for comparison.

Metrics & Alerts:
- Gauge: `g6_ml_ensemble_target_coverage_dynamic`.
- Recording rule: latest dynamic vs static ratio; alert if oscillations > threshold (e.g. >4 changes/hour) or drift outside bounds.

### 10.3 Disagreement Forecasting Enhancements
Current Implementation: EMA(α) one‑step forecast (`predicted_disagreement`), projected radius = `max(band_radius, applied_k * predicted_disagreement)`.
Planned Upgrades:
- AR(1) residual layer: fit `dis_t = c + φ * dis_{t-1} + ε_t` on rolling window; blend with EMA: `forecast = w * ema + (1-w) * ar1` (w adaptive by error ranking).
- Optional exogenous features: shock_score, realized volatility proxy, model residual KS statistics.
- Spike anticipation: define `spike_pred = forecast / current_disagreement`; if > (1 + spike_threshold) widen floor.

Exporter Integration Flags (added):
- `--use-forecast-floor`: effective band hit metric uses max(conformal_radius, scaled_radius, applied_k * predicted_disagreement).
- `--inflate-k-from-forecast`: if no override, inflate applied_k so scaled_radius anticipates forecast AND respects conformal radius (applied_k_source suffixed with `+forecast`).
Safety: Both off by default; only widen (never shrink) to avoid accidental under‑coverage.

Future Flag (planned): `--forecast-mode=ema|ar1|blend` to select forecasting strategy.

### 10.4 Success Criteria
- Adaptive target changes ≤3 times on normal (non‑volatile) session; ≥30% reduction in time spent under target vs static approach during induced low‑coverage simulation.
- Forecast pre‑widen reduces under‑coverage hit misses (effective_hit=0 while conformal within band) during top 5 spikes by ≥25%.
- Coverage deviation |effective_cov - dynamic_target_coverage| median < 0.015 over rolling 3‑hour window.
- No override persists > configured TTL without auto‑revert when stability returns.

### 10.5 Risks & Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| Target oscillation | Jittery bands, operator confusion | Hysteresis (delta_low/high), dwell_cycles, change rate alert |
| Forecast overshoot | Unnecessarily wide bands (opportunity cost) | Only widen; cap inflation factor; monitor MAPE & ratio applied_vs_projected_radius |
| Forecast lag / misses | Under‑coverage still occurs | Blend EMA+AR(1); spike_threshold failsafe; alert on high MAPE window |
| Override conflict | Adaptive logic masked by manual k | Log applied_k_source; skip inflation when override active; auto-revert on stability |
| Data sparsity early session | Spurious target adjustments | grace_open_cycles gate |
| Privacy in audit (actor) | Sensitive metadata exposure | Hash actor option + retention policy |

### 10.6 Configuration Reference (tentative defaults)
```text
adaptive:
    step: 0.01
    delta_low: 0.02
    delta_high: 0.015
    W_low: 3
    W_high: 4
    dwell_cycles: 6
    target_min: 0.76
    target_max: 0.84
    grace_open_cycles: 10
forecast:
    ema_alpha: 0.6
    mode: ema   # future: ar1|blend
    spike_threshold: 0.25   # 25% predicted surge vs current disagreement
    max_inflation_factor: 1.15   # cap applied_k inflation
```

### 10.7 Testing Plan
Unit:
- Adaptive raise/lower transitions with synthetic coverage sequences.
- Hysteresis: ensure no oscillation under alternating minor deviations.
- Forecast inflation: confirm applied_k_source suffix and cap adherence.
Property-Based:
- Random coverage series ensuring target remains within bounds and change rate limit.
Integration:
- Replay historical high-volatility day; measure under‑coverage reduction.
Regression:
- Backwards compatibility: exporter without new flags still passes existing tests.

### 10.8 Rollout Phases
1. Dark launch: compute dynamic_target_coverage & predicted_disagreement; do not influence applied_k.
2. Enable `--use-forecast-floor` on one index (e.g. NIFTY) for observation.
3. Enable adaptive target influence in effective_hit computations, still passive for k selection.
4. A/B test `--inflate-k-from-forecast` vs control horizon; compare under‑coverage metrics.
5. Evaluate AR(1) blended forecast; adopt if MAPE improves ≥10%.
6. Finalize alerts & dashboards; update runbook; retire manual overrides for routine band widening.

### 10.9 Observability Additions
- Recording rules: dynamic target latest, change count per hour, forecast surge ratio, applied_vs_projected_radius_ratio (already stubbed), forecast_mape_30m/180m.
- Alerts:
    - MLAdaptiveTargetOscillationHigh
    - MLDisagreementForecastMAPEHigh (implemented)
    - MLProjectedRadiusLagging (implemented)
    - MLAdaptiveUnderCoveragePersistent (dynamic target failing to recover)

### 10.10 Data Retention & Audit
- Sidecar version tag for schema evolution (`version": "1.0-adaptive"`).
- Override log rotation daily; optional compression after 7 days.
- Privacy: optional hashing of actor field if `G6_HASH_OVERRIDE_ACTOR=1`.

### 10.11 Open Questions
- Should dynamic target ever decrease below baseline during sustained over‑coverage, or simply rely on k_smooth decay? (Current plan: allow downward adjustments within bounds.)
- Is a multi-horizon joint adaptive target preferable (shared volatility context) vs per-horizon independent? (Deferred; initial release per-horizon.)
- Should forecast incorporate quarantined model count or residual KS metrics? (Under evaluation; early correlation analysis pending.)

### 10.12 Deferred Items
- Regime classifier (volatility regime tag) for conditional adaptive parameters.
- Bayesian updating of k recommendation incorporating prior session distribution.
- Quantile regression integration into dynamic target (target adaptation by asymmetric tail hits).

Status: EMA forecast + projected_radius + override auto‑revert delivered; exporter adaptive flags shipped (off by default). Remaining: dynamic target computation, blended forecast, alerts, expanded tests.

---

---
## API & Dashboard Integration Plan

Current endpoint `/api/ml/predictions` is CSV passthrough; remain backward compatible by:
- Adding optional columns (p10,p90,band_low,band_high,baseline_tp) without breaking existing panels.
- Updating dashboards to detect presence of bands → render filled area automatically.
- Adding a `model_matrix` enhancement: coverage metrics & band width.

Diagnostics Enhancements:
- Implemented: `coverage_estimate` (via conformal), and Hybrid diagnostics: `baseline_rmse`, `hybrid_rmse`, `improvement_ratio` (only when Hybrid model data is present). The improvement ratio is defined as `baseline_rmse / hybrid_rmse` (>1 indicates Hybrid improves over baseline). Columns `last_baseline` and `last_residual` are also surfaced for quick sanity checks.

---
## Data & Evaluation Metrics

Point Metrics:
- MAE, RMSE, Bias Mean/Median, Correlation, Trend slopes.

Probabilistic Metrics:
- Pinball loss per quantile.
- Coverage (empirical) vs target.
- Average Band Width (narrow + correct coverage preferred).

Structural Metrics (Hybrid):
- Baseline RMSE vs Hybrid RMSE.
- Residual stationarity check (Augmented Dickey-Fuller optional offline).

---
## Edge Cases & Mitigations

| Scenario | Issue | Mitigation |
|----------|-------|------------|
| Expiry roll | Feature discontinuity | Separate residual history per expiry_tag; warm start baseline. |
| Vol spike | Underestimation of band | Conformal radius inflates rapidly; shock score widens fallback. |
| Sparse early session | Unstable quantiles | Minimum radius floor from historical median residual. |
| Data lag / missing rows | False narrow bands | Skip residual updates when time gap > 2× cadence. |
| Drift in IV proxy | Hybrid baseline bias | Monitor residual bias; retrain or re-scale baseline coefficient. |

---
## Implementation Artifacts to Add

1. `configs/ml/nifty_tp_forecast_lgbm_quantile.json`
2. `configs/ml/nifty_tp_forecast_hybrid_residual.json`
3. `src/ml_arm/plugins/lightgbm_quantile.py` (or `catboost_quantile.py` alternative)
4. `src/ml_arm/conformal.py` (rolling residual store)
5. Exporter modifications (quantile & conformal support); Hybrid exporter added with baseline/residual metrics
6. Dashboards: optional panel variant with bands fill
7. Tests: `tests/ml/test_conformal_basic.py`, `tests/ml/test_quantile_integration.py`

---
## Minimal Interfaces

Quantile Plugin:
```python
class QuantileRegressorPlugin(ModelPlugin):
    def __init__(self, quantiles=(0.1,0.5,0.9), **params): ...
    def fit(self, X, y): ...  # trains one model per quantile or multi-objective
    def predict(self, X): -> dict[str, np.ndarray]  # {'q10': ..., 'q50': ..., 'q90': ...}
    def save(self, path): ...
    def load(self, path): ...
```

Conformal Engine:
```python
class ConformalBand:
    def __init__(self, target_coverage=0.8, window=600): ...
    def update(self, pred: float, actual: float): ...
    def radius(self) -> float: ...  # exporter publishes as g6_ml_conformal_radius
    def band(self, pred: float) -> tuple[float,float]: ...
```

Hybrid Baseline (simplified ATM Bachelier proxy):
```python
def baseline_tp(underlying: float, iv: float, minutes_to_expiry: float) -> float:
    # scaled linear form: underlying * iv * sqrt(T) * k
```

---
## Prioritized Next Steps (Actionable)

1. Scaffold quantile LightGBM plugin + config and integrate into exporter.
2. Implement conformal residual module and append band columns.
3. Add hybrid residual config with baseline function stub (offline validation first).
4. Enhance diagnostics endpoint to surface coverage & band widths.
5. Update dashboards for (p10,p90) fill and band overlay toggle.

---
## How to run (quickstart)

- Train model (example): see `README_QUANTILE_EXPORTER.md` for end-to-end commands.
- Start exporter: use the VS Code task "ML: Start Quantile Prediction Exporter (continuous)" to write p10/p50/p90 into `data/ml/live_predictions/<INDEX>.csv`. Add `--port 9208` to enable Prometheus metrics, and optionally `--coverage 0.8 --band-window 600` to control conformal radius.
- Visualize: add bands in Grafana by plotting `p10` and `p90` as lower/upper area.

---
## Success Criteria

- Coverage of 80% target bands within ±3% absolute error of target over rolling 2-hour windows.
- Hybrid model improves RMSE vs baseline pricing by ≥10% on validation weeks.
- Band width reduction ≥15% vs legacy static calibration at equal (or better) coverage.
- No >50ms added latency per prediction cycle.

---
## Instrumentation Status (current)

- Exporter metrics: `g6_ml_prediction_p10/p50/p90`, `g6_ml_conformal_radius`, `g6_ml_conformal_coverage_estimate` — available when `--port` provided.
- CLI flags: `--coverage`, `--band-window`, `--residual-store` control conformal behavior and persistence.
- Grafana: dashboards `grafana/dashboards/ml_prediction_bands.json` (bands) and `grafana/dashboards/ml_conformal_metrics.json` (radius, coverage). Alert overview added: `grafana/dashboards/ml_conformal_alert_overview.json`.
- Prometheus: recording rules in `prometheus_rules_ml.yml` and alerts `MLConformalUnderCoverage15m` (warning) and `MLConformalPersistentUnderCoverage` (critical) wired via `prometheus.yml`.
 - Hybrid dashboards: `grafana/dashboards/ml_hybrid_vs_quantile.json` overlays Hybrid vs p50 and Baseline. Recording rule `ml:hybrid:residual_avg_15m` and alert `MLHybridResidualSpike` added.
 - Ensemble: gauges (`g6_ml_ensemble_consensus`, `g6_ml_ensemble_disagreement`, `g6_ml_ensemble_models_count`), recording (`ml:ensemble:disagreement_avg_15m`, `ml:ensemble:disagreement_p95_15m`, `ml:ensemble:models_count_min_15m`) and alerts (`MLEnsembleDisagreementHigh`, `MLEnsembleDisagreementSurge`, `MLEnsembleTooFewModels`). CSV served via `/api/ml/ensemble` endpoint.

---
## Notes

This roadmap is designed to be incremental: each phase is independently deployable and offers measurable value. Conformal layers and quantile regressors can coexist, allowing continuous coverage monitoring and fallback resilience.

---

_End of document._
