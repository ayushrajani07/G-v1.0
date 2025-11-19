# G6 ML Arm – Comprehensive Guide (Layman Friendly)

Last updated: 2025-11-08

This guide explains the Machine Learning (ML) part of the G6 project in simple terms first, then dives deep. It covers what the ML system does, how the pieces fit together, how to run common tasks on Windows, and how we monitor and fix problems.

---

## 1) What the ML System Does (Plain English)

- We study how an index (like NIFTY or BANKNIFTY) moved in the past and use similar days to forecast how it might move in the near future. We call this “path forecasting.”
- We train small prediction models (like gradient boosting, XGBoost, LSTM) to forecast target points (TP) over short horizons (e.g., next 1, 30, or 60 minutes).
- We keep our forecasts reliable and lightweight using ANN (Approximate Nearest Neighbors) retrieval to quickly find the most similar days in history.
- We continuously monitor quality: if performance drifts from our baseline (our known-good reference), we raise alerts in Grafana so we can take action.

In short: we forecast, export predictions, visualize them in dashboards, and watch health metrics so we can trust the results.

---

## 2) Key Words You’ll See (Simple Glossary)

- Index: The symbol we’re forecasting, e.g., NIFTY, BANKNIFTY.
- Horizon: How far ahead we forecast (minutes). Example: 60 means “next hour.”
- Window: How much historical data per candidate day we compare (minutes). Example: 60, 120.
- k: How many similar days we consider (e.g., k=10 means use 10 nearest days).
- Mode: Retrieval (nearest neighbors only), Auto (ML model), Hybrid (mix both).
- Tag / Offset: Which expiry set to consider (e.g., this_week, next_week) and offset like +50 to shift the mapping.
- Baseline: Known-good metrics we compare against (our reference). Stored in JSON.
- Speedup: How much faster retrieval is versus a heavier baseline search (higher is better).
- Prune ratio: Portion of candidates dropped (too high can hurt quality and savings).
- MAD (q50_mad): A stability/quality dispersion measure (lower is better).
- Effectiveness: How well retrieval helps the actual task (adjusted version preferred).
- Guard trigger rate: The fraction of times a safeguard kicks in (high can indicate problems).

---

## 3) The Big Picture (Architecture in 1 Minute)

- Data → Path Forecast Harness → Ranking CSVs (which configs worked best) →
- Training & Model Artifacts → Live Prediction Exporters (Prometheus endpoints) →
- Dashboards & Alerts → Continuous Health Checks → Baseline Refresh / Retune / Rollback when needed.

We also run an ANN health exporter in the background that regularly checks performance (speedup, prune ratio, MAD, effectiveness) and raises alerts if it drifts from the baseline.

---

## 4) Where Things Live (Folders & Files)

- scripts/ml/ … core utilities
  - ann_harness_large.py – run ANN-based retrieval evaluations at scale
  - path_forecast_grid_eval.py – generate evaluation runs across grids of settings
  - combine_grid_eval.py – merge results into ranking CSVs
  - ann_health_exporter.py – Prometheus exporter for ANN health
  - ann_daily_health_check.py – one-off health check + optional baseline refresh
  - seed_ann_baseline_from_ranking.py – initialize/refresh ANN baseline from ranking CSV
  - live_predict_exporter.py – serve live ML predictions as metrics
  - calibrate_bands.py / auto_calibrate_daemon.py – calibrate forecast bands, keep them fresh
  - forecast_archiver.py – archive predictions for later analysis
- configs/ml/ … model configs (e.g., nifty_tp_forecast_hgb.json)
- models/ … trained model artifacts
- results/ … run outputs (combined/ann_ranking.csv, logs)
- baselines/ann_daily_baseline.json … ANN baseline (now nested by index)
- ANN_HEALTH_EXPORTER.md … exporter how-to
- ANN_RUNBOOK.md … triage and decision tree

---

## 5) Concepts: Path Forecasting (Deeper Dive)

We compare “today” with many “past” days and pick the most similar ones. We then aggregate their future movement to infer today’s likely path.

- Distance: How we measure similarity (e.g., L2, cosine, or a recency-weighted variant). 
- Windows: We look at a fixed window of minutes to compare shapes (e.g., 60 or 120).
- k-Nearest: We select the top k most similar past days.
- Aggregation: We combine their outcomes (possibly with weights) to form the forecast.

We can run this across a grid of configs to see which settings perform best, generating a ranking CSV.

---

## 6) Concepts: ANN Health & Baselines

Why monitor ANN? ANN makes retrieval fast, but we must ensure quality and stability:
- Speedup should remain good (not collapsing to near-zero).
- Prune ratio shouldn’t be too high (reducing savings or quality).
- MAD shouldn’t spike (quality dispersion).
- Effectiveness should stay in healthy ranges.

We store baseline metrics in baselines/ann_daily_baseline.json:
- Nested format:
  {
    "NIFTY": { "retrieval_60_k10": {...}, "retrieval_120_k10": {...} },
    "BANKNIFTY": { ... }
  }
- Exporter & health check read/write just the relevant index branch.
- We can refresh the baseline (safely) after stable, healthy runs.

Alerts (Grafana) will fire if metrics drift too far from baseline for too long (burn-rate style: fast vs slow).

---

## 7) Common Workflows (Step by Step)

Note: Commands are optional examples for Windows PowerShell. Replace ports/paths as needed.

### 7.1 Grid Evaluation & Ranking
1) Discover and run a grid of path-forecast configurations:
```powershell
# Optional example: generate evaluation runs (adjust indices/horizons/windows/k/modes)
cmd /c "set PYTHONPATH=%CD% & %CD%\.venv\Scripts\python.exe scripts\ml\path_forecast_grid_eval.py --discover --indices NIFTY,BANKNIFTY,SENSEX --horizons 30,60 --windows 60,120 --k 10,15 --modes retrieval,auto,hybrid --bucket-ms 60000 --at end"
```
2) Combine results into a ranking:
```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '%CD%/.venv/Scripts/python.exe' 'scripts/ml/combine_grid_eval.py'"
```
3) Check status:
```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& '%CD%/.venv/Scripts/python.exe' 'scripts/ml/check_grid_status.py'"
```

### 7.2 Train Models & Pick Champions
- Train-all (pattern-based):
```powershell
# Optional example
%CD%\.venv\Scripts\python.exe scripts\ml\train_all.ps1 -Pattern *tp_forecast*.json
```
- Select best champion configs:
```powershell
# Optional example
%CD%\.venv\Scripts\python.exe scripts\ml\select_champions.py --pattern *tp_forecast*.json --split 0.8 --metric mse
```
- Launch exporter from champion:
```powershell
# Optional example
%CD%\.venv\Scripts\python.exe scripts\ml\launch_exporter_from_champion.py --index NIFTY --horizon 1 --interval 30 --port 9208 --use-custom-registry --reset
```

### 7.3 Live Prediction Export (Prometheus)
- Serve predictions as Prometheus metrics:
```powershell
# Optional example
%CD%\.venv\Scripts\python.exe scripts\ml\live_predict_exporter.py --config configs\ml\nifty_tp_forecast_hgb.json --artifact models\nifty_tp_forecast_hgb --interval 30 --port 9208 --use-custom-registry --reset
```
- Mock predictions (off-hours) to test pipelines:
```powershell
# Optional example
%CD%\.venv\Scripts\python.exe scripts\ml\mock_predictions_feeder.py --index NIFTY --horizon 1 --interval 30 --models sk_hgb_regressor,xgb_regressor,torch_lstm_regressor
```
- Archive forecasts for analysis:
```powershell
# Optional example
%CD%\.venv\Scripts\python.exe scripts\ml\forecast_archiver.py --index NIFTY --horizons 30,60 --interval 60 --base-url http://127.0.0.1:9500 --expiry-tag this_week --offset 0 --market-hours-only
```

### 7.4 ANN Health: Exporter & Baseline
- One-shot validation (useful in CI):
```powershell
# Optional example
$env:PYTHONPATH = (Get-Location).Path; %CD%\.venv\Scripts\python.exe scripts\ml\ann_health_exporter.py --index NIFTY --tag this_week --offset 0 --days-back 3 --baseline baselines\ann_daily_baseline.json --port 9308 --interval 300 --min-rows 5 --verbose --once
```
- Continuous exporter (add to Prometheus scrape): see ANN_HEALTH_EXPORTER.md.
- Daily health check + optional baseline refresh (careful!):
```powershell
# Optional example
cmd /c "set PYTHONPATH=%CD% & %CD%\.venv\Scripts\python.exe scripts\ml\ann_daily_health_check.py --index NIFTY --tag this_week --offset 0 --start 2025-11-06 --end 2025-11-08 --baseline baselines\ann_daily_baseline.json --min-rows 5 --history-dir results\ann_daily_check\history --refresh-baseline-if-ok"
```
- Seed/refresh baseline from ranking:
```powershell
# Optional example
cmd /c "set PYTHONPATH=%CD% & %CD%\.venv\Scripts\python.exe scripts\ml\seed_ann_baseline_from_ranking.py --index BANKNIFTY --ranking results\ann_seed_banknifty_sm\combined\ann_ranking.csv --baseline baselines\ann_daily_baseline.json"
```

### 7.5 Calibrate Bands (1-click or daemon)
- Calibrate bands for confidence bands around predictions:
```powershell
# Optional example
%CD%\.venv\Scripts\python.exe scripts\ml\calibrate_bands.py --indices NIFTY --horizons 30,60 --window-minutes 180 --target 0.8 --base-url http://127.0.0.1:9500 --quiet
```
- Keep calibration fresh automatically (daemon):
```powershell
# Optional example
%CD%\.venv\Scripts\python.exe scripts\ml\auto_calibrate_daemon.py --indices NIFTY,BANKNIFTY,SENSEX --horizon 60 --window-minutes 180 --interval 300 --base-url http://127.0.0.1:9500
```

---

## 8) Observability & Alerts (Prometheus + Grafana)

- Exporters expose metrics on local ports (e.g., 9208 for predictions, 9308 for ANN health). Add these to Prometheus scrape config.
- Grafana dashboards visualize key series: speedup, prune ratio, MAD, effectiveness, rows, deltas vs baseline, and regression flags.
- We use recording rules to compute moving averages (5m, 30m, 1h) and p95s (30m, 2h), enabling:
  - Early “fast burn” alerts when things degrade quickly
  - “Slow burn” alerts for long-lived drifts
- Full alert set lives in prometheus_alerts.yml (ann_health.alerts). Quick refs are in GRAFANA_ALERTING_QUICK_REFERENCE.md and GRAFANA_ALERTING_COMPLETE.md.

---

## 9) Running the Dashboard API

- The Dashboard API can be started on an auto-selected or fixed port, and includes endpoints used by calibration/archiver utilities.
- Tasks are available in VS Code (see Run/Task panel) like “Dashboard API: Start (auto-port + reload)” or “Start on 9500 (reload)”.

---

## 10) Safety: Baseline Refresh vs Retune vs Rollback (Simple Rules)

- Collect enough rows first (ann_health_rows ≥ min_rows). If not, wait; don’t change baselines.
- If rapid “fast burn” alerts fire (and quality is collapsing), rollback recent tuning.
- If slow drift persists but quality is OK, consider retuning (candidate caps/prune heuristics) or refreshing the baseline.
- Follow ANN_RUNBOOK.md for the step-by-step decision tree and commands.

---

## 11) Troubleshooting Cheatsheet

- Exporter shows zeros? Likely too few rows or wrong date/tag. Confirm market session and input dates.
- Baseline writes nothing? Ensure you used --refresh-baseline-if-ok and that regressions=0 with row sufficiency.
- BANKNIFTY sparse metrics? Seed baseline from a targeted ranking first, then collect more data.
- Grafana shows no ANN metrics? Verify Prometheus scrape targets include the exporter ports.
- Alerts noisy pre-open? Consider low-row gating and avoiding refresh during the first volatile session hour.

---

## 12) Frequently Asked Questions (FAQ)

Q: Why are there multiple windows (60, 120)?
A: Shorter windows react faster; longer windows smooth noise. We compare both.

Q: What’s “k=10”?
A: We use the top 10 most similar days by distance. k is a standard nearest-neighbors parameter.

Q: Do I need GPUs?
A: No for retrieval/ANN health. Optional for some ML models (LSTM). CPU-only works for the bulk of workflows.

Q: Can I run exporters off-hours?
A: Yes. Use the mock predictions feeder to simulate predictions. ANN exporter can run any time on historical slices.

Q: I see “guard trigger rate” – should it be zero?
A: Not necessarily. It’s a safety valve. Sustained high values suggest retracing tuning or verifying data quality.

---

## 13) Roadmap & What We’re Improving Next

- Composite ANN health score (single stat combining effectiveness, speedup delta, prune p95, and regression flag)
- Automated baseline refresh scheduler (skip first session hour, row gating)
- Dashboard generator integration for ANN panels (no manual seeding)
- Low-row alert suppression for pre-open windows
- BANKNIFTY data enrichment and reseeding for a representative baseline
- Guard heuristic target bands + alerts when outside the desired range

---

## 14) Pointers to More Detail

- ANN Health Exporter: ANN_HEALTH_EXPORTER.md
- ANN Runbook (triage + decisions): ANN_RUNBOOK.md
- Alerting quick reference: GRAFANA_ALERTING_QUICK_REFERENCE.md
- Alerting complete reference: GRAFANA_ALERTING_COMPLETE.md
- Changelog (recent ML & ANN entries): CHANGELOG.md (Unreleased → ANN Retrieval Health Phases & Roadmap)

---

## 15) Minimal Setup (If You’re New)

- Ensure Python virtual environment is activated on Windows:
  .venv\Scripts\Activate.ps1
- Make sure Prometheus & Grafana are installed and the exporter ports are added to Prometheus.
- Try a one-shot ANN exporter run for NIFTY (see examples above). If metrics look healthy and rows are sufficient, proceed to the continuous exporter.
- Open Grafana and browse the ANN health dashboard to see live stats.

If you get stuck, open ANN_RUNBOOK.md and follow the checklists.
