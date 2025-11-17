Param([int]$NiftyPort,[int]$BankNiftyPort,[int]$Interval)

if (-not $NiftyPort)    { if ($Env:ML_METRICS_NIFTY_PORT)     { $NiftyPort    = [int]$Env:ML_METRICS_NIFTY_PORT }     else { $NiftyPort    = 9325 } }
if (-not $BankNiftyPort){ if ($Env:ML_METRICS_BANKNIFTY_PORT) { $BankNiftyPort= [int]$Env:ML_METRICS_BANKNIFTY_PORT } else { $BankNiftyPort= 9326 } }
if (-not $Interval)     { if ($Env:ML_METRICS_INTERVAL)       { $Interval     = [int]$Env:ML_METRICS_INTERVAL }       else { $Interval     = 60 } }

$scriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path "$scriptDir\..\..").Path
$logDir      = Join-Path $projectRoot 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

function StartIndexExporter($Index,$Port) {
  $config = Join-Path $projectRoot ("configs/ml/{0}_ensemble_config.json" -f $Index.ToLower())
  if (-not (Test-Path $config)) { Write-Host "Config not found for ${Index}: $config" -ForegroundColor Yellow; return }
  $pidFile = Join-Path $logDir ("ml_metrics_{0}.pid" -f $Index.ToLower())
  if (Test-Path $pidFile) {
    $existingPid = Get-Content $pidFile | Select-Object -First 1
    if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) { Write-Host "$Index exporter already running (PID: $existingPid)" -ForegroundColor Yellow; return } else { Remove-Item $pidFile -Force }
  }
  $outFile = Join-Path $logDir ("ml_metrics_{0}.out.log" -f $Index.ToLower())
  $errFile = Join-Path $logDir ("ml_metrics_{0}.err.log" -f $Index.ToLower())
  Write-Host "Starting $Index metrics exporter on port $Port (interval $Interval s)" -ForegroundColor Cyan
  Push-Location $projectRoot
  $proc = Start-Process -FilePath python -ArgumentList @('scripts/ml/ml_ensemble_metrics_exporter.py','--index',$Index,'--config',$config,'--port',$Port,'--interval',$Interval) -RedirectStandardOutput $outFile -RedirectStandardError $errFile -PassThru
  Pop-Location
  $proc.Id | Out-File $pidFile -Encoding ascii
  Start-Sleep -Seconds 2
  if (-not (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) { Write-Host "Failed to start $Index exporter" -ForegroundColor Red; if (Test-Path $pidFile){Remove-Item $pidFile -Force}; return }
  Write-Host "$Index exporter running (PID: $($proc.Id))" -ForegroundColor Green
  Start-Sleep -Seconds 1
  $ok=$false; try { $resp = Invoke-WebRequest -Uri "http://localhost:$Port/metrics" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop; if ($resp.StatusCode -eq 200){$ok=$true} } catch {}
  if ($ok){ Write-Host "$Index metrics endpoint responding" -ForegroundColor Green } else { Write-Host "$Index metrics endpoint not ready" -ForegroundColor Yellow }
}

Write-Host "Starting ML Ensemble Metrics Exporters..." -ForegroundColor Cyan
StartIndexExporter 'NIFTY' $NiftyPort
StartIndexExporter 'BANKNIFTY' $BankNiftyPort
Write-Host "Exporter start attempts complete" -ForegroundColor Green
exit 0