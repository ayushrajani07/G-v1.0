Param([string]$ApiHost, [int]$Port)

if (-not $ApiHost -or $ApiHost -eq '') { $ApiHost = $Env:ML_API_HOST; if (-not $ApiHost) { $ApiHost = '0.0.0.0' } }
if (-not $Port) { if ($Env:ML_API_PORT) { $Port = [int]$Env:ML_API_PORT } else { $Port = 9210 } }

$scriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path "$scriptDir\..\..").Path
$logDir      = Join-Path $projectRoot 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$pidFile = Join-Path $logDir 'ml_api.pid'
$logFile = Join-Path $logDir 'ml_api.log'

if (Test-Path $pidFile) {
  $existingPid = Get-Content $pidFile | Select-Object -First 1
  if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
    Write-Host "ML API already running (PID: $existingPid)" -ForegroundColor Yellow
    exit 0
  } else { Remove-Item $pidFile -Force }
}

Write-Host "Starting ML Ensemble API server..." -ForegroundColor Cyan
Write-Host "  Host: $ApiHost"
Write-Host "  Port: $Port"
Write-Host "  Log:  $logFile"

Push-Location $projectRoot
$stdoutFile = Join-Path $logDir 'ml_api.out.log'
$stderrFile = Join-Path $logDir 'ml_api.err.log'
$process = Start-Process -FilePath python -ArgumentList @('-m','src.web.api.ml_ensemble','--host',$ApiHost,'--port',$Port) -RedirectStandardOutput $stdoutFile -RedirectStandardError $stderrFile -PassThru
$process.Id | Out-File $pidFile -Encoding ascii
Start-Sleep -Seconds 2
if (-not (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)) {
  Write-Host "Failed to start ML API" -ForegroundColor Red
  if (Test-Path $pidFile) { Remove-Item $pidFile -Force }
  Pop-Location; exit 1
}
if ($process -and $process.Id) {
  Write-Host "Started ML API (PID: $($process.Id))" -ForegroundColor Green
} else {
  Write-Host "API process handle missing" -ForegroundColor Red
  Pop-Location; exit 1
}
Start-Sleep -Seconds 1
$healthOk = $false
try { $resp = Invoke-WebRequest -Uri "http://localhost:$Port/health" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop; if ($resp.StatusCode -eq 200) { $healthOk = $true } } catch {}
if ($healthOk) { Write-Host "Health check passed" -ForegroundColor Green } else { Write-Host "Health check failed (non-200 or unreachable)" -ForegroundColor Yellow }
Pop-Location
exit 0