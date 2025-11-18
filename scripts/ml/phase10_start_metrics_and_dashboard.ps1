param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 9500,
    [string]$WindowStyle = "Hidden",
    [string]$Indices = "NIFTY,BANKNIFTY",
    [int]$DriftIntervalSec = 300,
    [int]$EvalStaleSec = 600
)

Write-Host "[Phase10] Enabling rolling metrics + drift evaluator and launching dashboard API" -ForegroundColor Cyan

# Rolling metrics (forecast error/coverage) via path forecast metrics module
$env:ENABLE_PATH_FORECAST_PROM_METRICS = "1"
$env:G6_ROLLING_MAE_ENABLE = "1"

# Drift evaluator
$env:G6_DRIFT_ENABLE = "1"
$env:G6_DRIFT_INDICES = $Indices
$env:G6_DRIFT_EVAL_INTERVAL_SEC = [string]$DriftIntervalSec
$env:G6_DRIFT_EVAL_STALE_SEC = [string]$EvalStaleSec

# Optional: conservative defaults for initial run
if (-not $env:G6_ROLLING_MAE_WINDOW) { $env:G6_ROLLING_MAE_WINDOW = "500" }
if (-not $env:G6_ROLLING_ERROR_BUCKETS) { $env:G6_ROLLING_ERROR_BUCKETS = "0.25,0.5,1,2,5,10,20" }
if (-not $env:G6_ROLLING_NORM_ERROR_BUCKETS) { $env:G6_ROLLING_NORM_ERROR_BUCKETS = "0.005,0.01,0.02,0.05,0.1,0.2,0.5,1" }

# Advisor/Grafana helper
$env:BACKEND_BASE = "http://${BindHost}:${Port}"

# Launch dashboard API (reuses existing script)
$scriptPath = Join-Path $PSScriptRoot "start_dashboard_api.ps1"
if (-not (Test-Path $scriptPath)) {
    # fallback: run uvicorn directly if helper is missing
    Write-Host "start_dashboard_api.ps1 not found; launching uvicorn directly" -ForegroundColor Yellow
    $env:ML_DASHBOARD_HOST = $Host
    $env:ML_DASHBOARD_PORT = [string]$Port
    python -m uvicorn src.web.dashboard.app:app --host $Host --port $Port --reload
    exit $LASTEXITCODE
}

& $scriptPath -Host $BindHost -Port $Port -WindowStyle $WindowStyle
exit $LASTEXITCODE
