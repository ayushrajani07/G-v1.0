# ML Arm Cheatsheet (PowerShell)

Quick commands to operate the ML module. All commands assume the venv is active or use absolute path to the interpreter.

## Env

```powershell
# Activate venv
& C:/Users/Asus/Desktop/g6_reorganized/.venv/Scripts/Activate.ps1
```

## Models and configs

```powershell
# List registered model plugins
C:/Users/Asus/Desktop/g6_reorganized/.venv/Scripts/python.exe scripts/ml/list_models.py
```

## Train / Evaluate (Holdout)

```powershell
# Train any config
C:/Users/Asus/Desktop/g6_reorganized/.venv/Scripts/python.exe scripts/ml/train_model.py --config configs/ml/nifty_tp_forecast_hgb.json --seed 42

# Evaluate (80/20 chrono split)
C:/Users/Asus/Desktop/g6_reorganized/.venv/Scripts/python.exe scripts/ml/evaluate.py --config configs/ml/nifty_tp_forecast_hgb.json --split 0.8 --seed 42

# Save test predictions CSV
C:/Users/Asus/Desktop/g6_reorganized/.venv/Scripts/python.exe scripts/ml/evaluate.py --config configs/ml/nifty_tp_forecast_hgb.json --split 0.8 --save-preds reports/nifty_preds.csv
```

### Train multiple configs (batch)

```powershell
# Train all configs matching pattern then evaluate quick sanity (80/20)
./scripts/ml/train_all.ps1                              # uses *tp_forecast_*.json by default

# Train explicit set
./scripts/ml/train_all.ps1 -Configs "configs/ml/nifty_tp_forecast_hgb.json","configs/ml/banknifty_tp_forecast_hgb.json"

# Use a broader wildcard (includes XGB/MLP/LSTM variants)
./scripts/ml/train_all.ps1 -Pattern "*tp_forecast*.json"

# Skip evaluation, change seed/split
./scripts/ml/train_all.ps1 -NoEval -Seed 123 -Split 0.75
```

Wildcard patterns (what matches what):
- `*tp_forecast_*.json`
	- Meaning: any filename that contains `tp_forecast_` followed by any suffix, ending in `.json`.
	- Matches: `nifty_tp_forecast_hgb.json`, `nifty_tp_forecast_hgb_tuned.json`, `banknifty_tp_forecast_xgb.json`, `sensex_tp_forecast_mlp.json`, `nifty_tp_forecast_lstm.json`.
	- Does NOT match: `tp_forecast_hgb.json` (no prefix before `tp_forecast_`).
- `*tp_forecast*.json`
	- Meaning: any filename that contains `tp_forecast` with or without an underscore suffix, ending in `.json`.
	- Matches: everything above plus `tp_forecast_hgb.json` (no index prefix), and any `...tp_forecast.json` with no model suffix.
	- Good for: training all variants across HGB/XGB/MLP/LSTM in one shot.

Tips:
- Use quotes around patterns on PowerShell to avoid expansion issues.
- You can also pass explicit configs via `-Configs` to be precise and skip wildcarding.

## Walk-forward

```powershell
# Evaluate walk-forward (weekday or chunk fallback)
C:/Users/Asus/Desktop/g6_reorganized/.venv/Scripts/python.exe scripts/ml/evaluate_walkforward.py --config configs/ml/nifty_tp_forecast_hgb.json --train-groups 4 --test-groups 1 --seed 42 --save-csv reports/nifty_wf.csv
```

## Comparisons

```powershell
# Compare multiple configs (plots: overlay, scatter, MSE bar)
C:/Users/Asus/Desktop/g6_reorganized/.venv/Scripts/python.exe scripts/ml/evaluate_and_plot.py --configs configs/ml/nifty_tp_forecast_hgb.json configs/ml/nifty_tp_forecast_hgb_noroll.json --labels HGB_roll HGB_noroll --split 0.8 --outdir reports/plots

# One-click compare all indices (holdout and walk-forward plots)
C:/Users/Asus/Desktop/g6_reorganized/.venv/Scripts/python.exe scripts/ml/compare_all_indices.py --walkforward --train-groups 4 --test-groups 1 --outdir reports/compare_all

# Plot walk-forward CSVs side-by-side
C:/Users/Asus/Desktop/g6_reorganized/.venv/Scripts/python.exe scripts/ml/plot_walkforward.py --csvs reports/compare_all/walkforward/NIFTY_wf.csv reports/compare_all/walkforward/SENSEX_wf.csv reports/compare_all/walkforward/BANKNIFTY_wf.csv --labels NIFTY SENSEX BANKNIFTY --outdir reports/compare_all/walkforward_plots
```

## Live predictions (inference)

```powershell
# One-shot inference using latest CSVs; appends one row to data/ml/live_predictions/<INDEX>.csv
C:/Users/Asus/Desktop/g6_reorganized/.venv/Scripts/python.exe scripts/ml/infer_from_latest_csv.py --config configs/ml/nifty_tp_forecast_hgb.json --artifact models/nifty_tp_forecast_hgb

# Continuous exporter: emits Prometheus metrics on :9208 and appends to CSV every 30s
C:/Users/Asus/Desktop/g6_reorganized/.venv/Scripts/python.exe scripts/ml/live_predict_exporter.py --config configs/ml/nifty_tp_forecast_hgb.json --artifact models/nifty_tp_forecast_hgb --interval 30 --port 9208 --use-custom-registry --reset

# Quick endpoint check (Dashboard API must be running)
# Predictions CSV (Infinity-friendly): http://127.0.0.1:8003/api/ml/predictions?index=NIFTY&horizon=1&tail=600
# Metrics: http://127.0.0.1:9208/metrics

If the exporter exits immediately or you see a message about reusing an existing metrics server, add:
- `--use-custom-registry` to isolate the exporter’s Prometheus registry
- `--reset` to force a fresh registry/server in this process

### Dashboards

	- Variables: index, expiry, offset, horizon
	- Shows Index Price, ATM Premium, one Model Prediction

	- Variables: index (offset fixed to 0)
	- Overlays ALL real-time predictions for the selected index on the same panel, along with Index Price and ATM Premium (offset=0)
	- Data sources:
		- Live: `http://127.0.0.1:8003/api/live_csv?index=${index}&expiry_tag=this_week&offset=0`
		- Predictions: `http://127.0.0.1:8003/api/ml/predictions?index=${index}`

## Auto-load ML dashboards on Grafana startup

- When you start Grafana using `scripts/auto_stack.ps1`, any dashboard JSONs matching `dashboards_modular/ml_*.json` are now staged automatically and provisioned at startup.
- This means the following ML dashboards will auto-appear without manual import:
  - `ml_minimal_predictions.json`
  - `ml_index_overlay_all_models.json`
- If Grafana is already running, restart it via `auto_stack.ps1` (or stop the Windows Grafana service) to pick up the new dashboards. Provisioning is applied at startup.

Troubleshooting:
- If you don’t see the ML dashboards, verify you started Grafana via our script (it sets GF_PATHS_PROVISIONING to the staged folder). You can also search by dashboard title in Grafana’s search bar.
- As a fallback, you can still import the JSONs manually from `dashboards_modular/`.

### Champion selection (automated)

```powershell
# Evaluate all tp_forecast configs, pick best per (index,horizon) by MSE, and write models/champions.json
${env:PYTHON} scripts/ml/select_champions.py --pattern "*tp_forecast*.json" --split 0.8 --metric mse

# Or from VS Code: Run task "ML: Select Champions"

# Launch exporter using the champion for an index (reads models/champions.json)
${env:PYTHON} scripts/ml/launch_exporter_from_champion.py --index NIFTY --horizon 1 --interval 30 --port 9208 --use-custom-registry --reset

# Or from VS Code: Run task "ML: Start Exporter from Champion" (you'll be prompted for index)
```
```

### Autostart options (stack scripts)

```powershell
# Clean observability stack (Web API + Prometheus + Grafana) WITH Live Predictions by default
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\obs_start_clean.ps1

# Override exporter defaults (config/artifact/interval/port) or disable
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\obs_start_clean.ps1 -MLConfig 'configs/ml/nifty_tp_forecast_hgb.json' -MLArtifact 'models/nifty_tp_forecast_hgb' -MLInterval 30 -MLPort 9208
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\obs_start_clean.ps1 -StartMLExporter:$false  # disable exporter

# Full auto stack with exporter (if you use auto_stack.ps1)
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\auto_stack.ps1 -StartPrometheus:$true -StartGrafana:$true -StartWebApi -StartMLExporter -MLConfig 'configs/ml/nifty_tp_forecast_hgb.json' -MLArtifact 'models/nifty_tp_forecast_hgb' -MLInterval 30 -MLPort 9208
```

## Grid search tuning

```powershell
# HGB tuning on a single config; writes CSV and tuned config next to original
C:/Users/Asus/Desktop/g6_reorganized/.venv/Scripts/python.exe scripts/ml/run_grid_search.py --config configs/ml/nifty_tp_forecast_hgb.json --outdir reports --train-frac 0.8
```

## Horizon sweeper (exponential steps)

```powershell
# Evaluate horizons 1,2,4,8 (default base=2, max-h=8)
C:/Users/Asus/Desktop/g6_reorganized/.venv/Scripts/python.exe scripts/ml/evaluate_horizons.py --config configs/ml/nifty_tp_forecast_hgb.json --max-h 8 --base 2 --split 0.8 --outdir reports/horizons

# Custom horizons
C:/Users/Asus/Desktop/g6_reorganized/.venv/Scripts/python.exe scripts/ml/evaluate_horizons.py --config configs/ml/nifty_tp_forecast_hgb.json --horizons 1 3 6 12 --split 0.8 --outdir reports/horizons
```

## Multi-target / experiments

```powershell
# Train the same model for multiple targets (if supported in your setup)
C:/Users/Asus/Desktop/g6_reorganized/.venv/Scripts/python.exe scripts/ml/train_multi.py --config configs/ml/nifty_tp_forecast_hgb.json --targets tp index_price

# Batch run across datasets/configs (holdout)
C:/Users/Asus/Desktop/g6_reorganized/.venv/Scripts/python.exe scripts/ml/run_all_indices.py --configs configs/ml/nifty_tp_forecast_hgb.json configs/ml/sensex_tp_forecast_hgb.json configs/ml/banknifty_tp_forecast_hgb.json --out reports/summary.csv
```

## Notes

- After changing features in a config, retrain before evaluating or plotting.
- Sidecar normalization (`*.fe.json`) is generated by training and used at evaluation time.
- Live predictions use pre-trained artifacts; run training first (scripts/ml/train_model.py or scripts/ml/train_all.ps1) before starting the exporter.
