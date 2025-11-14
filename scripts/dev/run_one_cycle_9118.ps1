param(
  [int]$LingerSeconds = 15,
  [int]$PollSeconds = 12
)
$ErrorActionPreference = 'Continue'
Push-Location (Split-Path $MyInvocation.MyCommand.Path -Parent | Split-Path -Parent)
try {
  $py = (Get-Command python -ErrorAction Stop).Source
} catch {
  Write-Host "Python not found on PATH." -ForegroundColor Red
  Pop-Location; exit 1
}
$env:G6_FORCE_NEW_REGISTRY = '1'
$env:G6_ALLOW_PROVIDERLESS_CYCLES = '1'
$env:G6_DISABLE_AUTH_PREFLIGHT = '1'
$env:G6_METRICS_PORT = '9118'
$env:G6_METRICS_HOST = '127.0.0.1'
Write-Host ("Starting orchestrator one-shot on 9118 (linger={0}s)..." -f $LingerSeconds) -ForegroundColor Cyan
$p = Start-Process -FilePath $py -ArgumentList @(
  'scripts/run_orchestrator_loop.py',
  '--config','config/g6_config.json',
  '--cycles','1',
  '--allow-offhours',
  '--linger-seconds',"$LingerSeconds",
  '--metrics-port','9118',
  '--metrics-host','127.0.0.1'
) -WorkingDirectory (Get-Location) -PassThru

# Poll for metrics readiness
$ok=$false
for ($i=0; $i -lt $PollSeconds; $i++) {
  try {
    $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 http://127.0.0.1:9118/metrics
    if ($r.StatusCode -eq 200) { $ok=$true; $body=$r.Content; break }
  } catch {}
  Start-Sleep -Seconds 1
}
if (-not $ok) {
  Write-Host "Metrics endpoint not reachable on 9118." -ForegroundColor Yellow
} else {
  Write-Host "`n--- Metrics snapshot (filtered) ---" -ForegroundColor Green
  $patterns = @(
    '^g6_collection_cycle_time_seconds',
    '^g6_cycles_per_hour',
    '^g6_options_processed_per_minute',
    '^g6_collection_success_rate_percent',
    '^g6_cycle_process_time_seconds_count',
    '^g6_cycle_process_time_seconds_sum'
  )
  $body -split "`n" | Select-String -Pattern ($patterns -join '|') | ForEach-Object { $_.ToString() }
}
# Allow linger window to elapse further, then cleanup
Start-Sleep -Seconds ([Math]::Max(3, [int]([double]$LingerSeconds/2)))
try { if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } } catch {}
Pop-Location
