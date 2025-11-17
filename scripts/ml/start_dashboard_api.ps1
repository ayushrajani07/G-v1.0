Param([string]$ApiHost,[int]$Port)

if (-not $ApiHost -or $ApiHost -eq '') { $ApiHost = $Env:DASHBOARD_API_HOST; if (-not $ApiHost) { $ApiHost = '0.0.0.0' } }
if (-not $Port) { if ($Env:DASHBOARD_API_PORT) { $Port = [int]$Env:DASHBOARD_API_PORT } else { $Port = 9500 } }

$scriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path "$scriptDir\..\..").Path
Push-Location $projectRoot
Write-Host ("Starting FastAPI dashboard (uvicorn) on {0}:{1}" -f $ApiHost,$Port) -ForegroundColor Cyan
$env:PYTHONUNBUFFERED = '1'
$logDir = Join-Path $projectRoot 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$pidFile = Join-Path $logDir 'dashboard_api.pid'
if (Test-Path $pidFile) { $existing = Get-Content $pidFile | Select-Object -First 1; if ($existing -and (Get-Process -Id $existing -ErrorAction SilentlyContinue)) { Write-Host "Dashboard already running (PID: $existing)" -ForegroundColor Yellow; Pop-Location; exit 0 } else { Remove-Item $pidFile -Force } }
$outFile = Join-Path $logDir 'dashboard_api.out.log'
$errFile = Join-Path $logDir 'dashboard_api.err.log'
$proc = Start-Process -FilePath python -ArgumentList @('-m','uvicorn','src.web.dashboard.app:app','--host',$ApiHost,'--port',$Port,'--timeout-keep-alive','5','--log-level','info') -RedirectStandardOutput $outFile -RedirectStandardError $errFile -PassThru
$proc.Id | Out-File $pidFile -Encoding ascii
Start-Sleep -Seconds 2
if (-not (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) { Write-Host "Failed to start dashboard API" -ForegroundColor Red; if (Test-Path $pidFile){Remove-Item $pidFile -Force}; Pop-Location; exit 1 }
Write-Host "Dashboard API running (PID: $($proc.Id))" -ForegroundColor Green
$ok = $false; try { $resp = Invoke-WebRequest -Uri "http://localhost:$Port/health" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop; if ($resp.StatusCode -eq 200) { $ok = $true } } catch {}
if ($ok) { Write-Host "Health endpoint responding" -ForegroundColor Green } else { Write-Host "Health endpoint not ready" -ForegroundColor Yellow }
Pop-Location
exit 0