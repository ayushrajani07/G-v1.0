# Quickstart

## Setup

```powershell
python -m venv .venv
./.venv/Scripts/Activate.ps1
pip install -r requirements.txt
```

## Run (mock mode)

```powershell
$env:G6_USE_MOCK_PROVIDER='1'
python scripts/run_orchestrator_loop.py --config config/g6_config.json --interval 30 --cycles 2
```

## Launch summary UI

```powershell
python -m scripts.summary.app --refresh 1
```

## Simulator demo

```powershell
python scripts/status_simulator.py --status-file data/runtime_status_demo.json --indices NIFTY,BANKNIFTY,FINNIFTY,SENSEX --interval 60 --refresh 0.1 --open-market --with-analytics --cycles 1
python -m scripts.summary.app --refresh 0.5 --status-file data/runtime_status_demo.json
```

## Tests (two-phase)

```powershell
pytest -q
pytest -q -m serial -n 0
```
