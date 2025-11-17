<#
 Stop ML Ensemble Services (Windows PowerShell)
 Mirrors logic of stop_ml_services.sh
#>

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path "$scriptDir\..\.." | ForEach-Object { $_.Path }
$logDir = Join-Path $projectRoot 'logs'

function Stop-ServiceByPidFile {
    param([string]$Name)
    $pidFile = Join-Path $logDir ("{0}.pid" -f $Name)
    if (-not (Test-Path $pidFile)) {
        Write-Host ("PID file not found for {0}" -f $Name) -ForegroundColor Yellow
        return
    }
    $existingPid = Get-Content $pidFile | Select-Object -First 1
    if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
        Write-Host ("Stopping {0} (PID: {1})" -f $Name,$existingPid) -ForegroundColor Cyan
        try { Stop-Process -Id $existingPid -ErrorAction Stop } catch { Write-Host ("Error stopping {0}: {1}" -f $Name, $_.Exception.Message) -ForegroundColor Red }
        Start-Sleep -Seconds 2
        if (Get-Process -Id $existingPid -ErrorAction SilentlyContinue) {
            Write-Host ("Force stopping {0}" -f $Name) -ForegroundColor Yellow
            try { Stop-Process -Id $existingPid -Force -ErrorAction Stop } catch {}
        }
        Remove-Item $pidFile -Force
        Write-Host ("Stopped {0}" -f $Name) -ForegroundColor Green
    } else {
        Write-Host ("{0} not running (stale PID file)" -f $Name) -ForegroundColor Yellow
        Remove-Item $pidFile -Force
    }
}

Write-Host "Stopping ML Ensemble Services..." -ForegroundColor Cyan
Stop-ServiceByPidFile -Name 'ml_api'
Stop-ServiceByPidFile -Name 'ml_metrics_nifty'
Stop-ServiceByPidFile -Name 'ml_metrics_banknifty'
Write-Host "All ML services stop attempts done" -ForegroundColor Green
exit 0