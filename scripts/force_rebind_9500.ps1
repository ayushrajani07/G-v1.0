param(
    [switch]$Reload,
    [int]$PollSeconds = 25
)

$ErrorActionPreference = 'SilentlyContinue'

function Stop-Listeners([int[]]$Ports) {
    foreach ($port in $Ports) {
        try {
            $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
            if ($conns) {
                $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
                foreach ($procId in $pids) {
                    try {
                        Write-Host "Stopping PID $procId on port $port" -ForegroundColor Yellow
                        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                    } catch {}
                }
                Start-Sleep -Milliseconds 300
            }
        } catch {}
    }
}

function Get-PythonPath() {
    try {
        if ($env:VIRTUAL_ENV) {
            $p = Join-Path $env:VIRTUAL_ENV 'Scripts/python.exe'
            if (Test-Path $p) { return $p }
        }
    } catch {}
    try {
        $p = Join-Path (Join-Path (Get-Location) '.venv') 'Scripts/python.exe'
        if (Test-Path $p) { return $p }
    } catch {}
    return 'py'
}

function Start-Server([string]$PythonPath, [switch]$Reload) {
    $pyArgs = @('scripts/start_dashboard_api.py','--ports','9500')
    if ($Reload) { $pyArgs = @('scripts/start_dashboard_api.py','--reload','--ports','9500') }
    Write-Host "Launching server on 9500..." -ForegroundColor Cyan
    Start-Process -FilePath $PythonPath -ArgumentList $pyArgs -WindowStyle Minimized | Out-Null
}

function Wait-Healthy([int]$TimeoutSec) {
    $u = 'http://127.0.0.1:9500/api/ml/path_forecast_json?index=NIFTY&horizon_minutes=60&no_cache=true&calibrate=false'
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 4
            if ($r.StatusCode -eq 200) {
                $ver = $r.Headers['X-Route-Version']
                if ($ver -and ($ver -eq 'json-v2' -or $ver -eq 'json-v3')) {
                    Write-Host "Healthcheck PASS (X-Route-Version=$ver)" -ForegroundColor Green
                    return $true
                } else {
                    Write-Host "Healthcheck: waiting for json-v2/v3 (got '$ver')" -ForegroundColor DarkYellow
                }
            }
        } catch {}
        Start-Sleep -Seconds 1
    }
    Write-Host "Healthcheck FAIL: JSON route version not detected" -ForegroundColor Red
    return $false
}

# 1) Stop old listeners on 9500 and 8003
Stop-Listeners -Ports @(9500,8003)

# 2) Start the server on 9500 from this workspace
$py = Get-PythonPath
Start-Server -PythonPath $py -Reload:$Reload

# 3) Wait for the server to serve updated JSON route
$ok = Wait-Healthy -TimeoutSec $PollSeconds
if (-not $ok) { exit 1 } else { exit 0 }
