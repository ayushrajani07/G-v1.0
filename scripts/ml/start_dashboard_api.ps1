Param(
	[string]$ApiHost,
	[int]$Port,
	[ValidateSet('Hidden','Minimized','Normal','Maximized')]
	[string]$WindowStyle
)

if (-not $ApiHost -or $ApiHost -eq '') { $ApiHost = $Env:DASHBOARD_API_HOST; if (-not $ApiHost) { $ApiHost = '0.0.0.0' } }
if (-not $Port) { if ($Env:DASHBOARD_API_PORT) { $Port = [int]$Env:DASHBOARD_API_PORT } else { $Port = 9500 } }
$styleEnv = $Env:DASHBOARD_API_WINDOW_STYLE
if (-not $WindowStyle -or $WindowStyle -eq '') {
	if ($styleEnv -and $styleEnv -ne '') { $WindowStyle = $styleEnv } else { $WindowStyle = 'Hidden' }
}

$scriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path "$scriptDir\..\..").Path
Push-Location $projectRoot
Write-Host ("Starting FastAPI dashboard (uvicorn) on {0}:{1}" -f $ApiHost,$Port) -ForegroundColor Cyan
$env:PYTHONUNBUFFERED = '1'
$env:G6_DIAG_ENABLE = '1'
$logDir = Join-Path $projectRoot 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$pidFile = Join-Path $logDir 'dashboard_api.pid'

# --------------------------- Port Clearance ---------------------------
Write-Host "Clearing existing processes bound to port $Port" -ForegroundColor Cyan
$owners = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
foreach($op in $owners){ if($op -and $op -gt 0){ Write-Host "Stopping PID $op (port $Port)" -ForegroundColor Yellow; Stop-Process -Id $op -Force -ErrorAction SilentlyContinue } }
Start-Sleep -Seconds 2
$still = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
if($still){ Write-Host "Warning: port $Port still shows occupant PID $($still.OwningProcess)" -ForegroundColor Red }

# Remove stale pid file if process not alive
if (Test-Path $pidFile) {
	$existing = Get-Content $pidFile | Select-Object -First 1
	if ($existing -and (Get-Process -Id $existing -ErrorAction SilentlyContinue)) {
		Write-Host "Stale running process found for pid file (PID $existing); terminating" -ForegroundColor Yellow
		Stop-Process -Id $existing -Force -ErrorAction SilentlyContinue
		Start-Sleep -Seconds 1
	}
	Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

$outFile = Join-Path $logDir 'dashboard_api.out.log'
$errFile = Join-Path $logDir 'dashboard_api.err.log'
$args = @('-m','uvicorn','src.web.dashboard.app:app','--host',$ApiHost,'--port',$Port,'--timeout-keep-alive','5','--log-level','info')
Write-Host "Launching uvicorn: python $($args -join ' ') (WindowStyle=$WindowStyle)" -ForegroundColor Cyan
$proc = Start-Process -FilePath python -ArgumentList $args -RedirectStandardOutput $outFile -RedirectStandardError $errFile -WindowStyle $WindowStyle -PassThru -WorkingDirectory $projectRoot
$proc.Id | Out-File $pidFile -Encoding ascii
Start-Sleep -Seconds 3
if (-not (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) { Write-Host "Failed to start dashboard API" -ForegroundColor Red; if (Test-Path $pidFile){Remove-Item $pidFile -Force}; Pop-Location; exit 1 }
Write-Host "Dashboard API launcher PID: $($proc.Id)" -ForegroundColor Green

# --------------------------- Health & Route Assertions ---------------------------
$healthOk = $false
try { $resp = Invoke-WebRequest -Uri "http://localhost:$Port/__diag/pid" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop; if ($resp.StatusCode -eq 200) { $healthOk = $true; Write-Host "PID endpoint OK: $($resp.Content)" -ForegroundColor Green } } catch { Write-Host "PID endpoint not ready" -ForegroundColor Yellow }
if (-not $healthOk) {
	Write-Host "Retrying health endpoint..." -ForegroundColor Yellow
	Start-Sleep -Seconds 2
	try { $resp = Invoke-WebRequest -Uri "http://localhost:$Port/__diag/pid" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop; if ($resp.StatusCode -eq 200) { $healthOk = $true; Write-Host "PID endpoint OK (retry): $($resp.Content)" -ForegroundColor Green } } catch {}
}

$openapiOk = $false
if ($healthOk) {
	foreach($i in 1..5){
		try {
			$spec = Invoke-WebRequest -Uri "http://localhost:$Port/openapi.json" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
			if ($spec.StatusCode -eq 200 -and ($spec.Content -like '*"/api/ml/ensemble/forecast"*')) { $openapiOk = $true; break }
		} catch {}
		Start-Sleep -Milliseconds 600
	}
}
if ($openapiOk) { Write-Host "Forecast route present in OpenAPI" -ForegroundColor Green } else { Write-Host "Forecast route NOT detected in OpenAPI" -ForegroundColor Red }

if (-not $openapiOk) {
	Write-Host "Startup failed route assertion; check logs: $errFile" -ForegroundColor Red
}

Pop-Location
exit 0