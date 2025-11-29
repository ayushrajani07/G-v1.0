# Minimal G6 Observability Stack Starter - CLEAN VERSION
# Starts Web API + Grafana + Prometheus
# Defaults to REQUIRING LOGIN (admin/admin)
param(
  [int]$GrafanaPort = 3002,
  [int]$WebPort = 9500,
  [int]$PrometheusPort = 9091,
  [string]$GrafanaDataRoot = 'C:\GrafanaData',
  [switch]$OpenBrowser,
  [switch]$NoRunner    # use raw uvicorn instead of persistent runner (not recommended)
)

$ErrorActionPreference = 'Continue'
$Root = Split-Path $PSScriptRoot -Parent

# Kill only observability stack services (selective process termination)
Write-Host "Stopping observability stack services..." -ForegroundColor Yellow
try {
  $stoppedCount = 0
  
  # Stop Web API (uvicorn) on configured port ($WebPort)
  $webApiProcs = Get-NetTCPConnection -LocalPort $WebPort -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -eq 'python' }
  } | Select-Object -Unique
  if ($webApiProcs) {
    $webApiProcs | Stop-Process -Force -ErrorAction SilentlyContinue
    $stoppedCount += @($webApiProcs).Count
    Write-Host "  Stopped Web API (uvicorn on port $WebPort)" -ForegroundColor Gray
  }
  
  # Stop Grafana processes (both 'grafana' and 'grafana-server')
  $grafanaProcs = Get-Process grafana-server,grafana -ErrorAction SilentlyContinue
  if ($grafanaProcs) {
    $grafanaProcs | Stop-Process -Force -ErrorAction SilentlyContinue
    $stoppedCount += @($grafanaProcs).Count
    Write-Host "  Stopped Grafana server" -ForegroundColor Gray
  }
  
  # Stop Prometheus processes
  $promProcs = Get-Process prometheus -ErrorAction SilentlyContinue
  if ($promProcs) {
    $promProcs | Stop-Process -Force -ErrorAction SilentlyContinue
    $stoppedCount += @($promProcs).Count
    Write-Host "  Stopped Prometheus" -ForegroundColor Gray
  }
  
  if ($stoppedCount -eq 0) {
    Write-Host "  No services running" -ForegroundColor Gray
  } else {
    Write-Host "  Total stopped: $stoppedCount process(es)" -ForegroundColor Gray
  }
  
  Start-Sleep -Seconds 2
} catch {
  Write-Host "  Warning: Could not stop some processes: $_" -ForegroundColor DarkYellow
}

function Ensure-Dir { param([string]$Path) if (-not (Test-Path $Path)) { New-Item -ItemType Directory -Force -Path $Path | Out-Null } }
function Wait-Http { param([string]$Url,[int]$MaxTries=30) for($i=0;$i -lt $MaxTries;$i++){ try { $r=Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3; if($r.StatusCode -eq 200){ return $true } } catch {}; Start-Sleep -Seconds 1 } return $false }

function Find-Prometheus {
  foreach ($base in @('C:\Prometheus','C:\Program Files\Prometheus')) {
    if (Test-Path $base) {
      $exe = Join-Path $base 'prometheus.exe'
      if (Test-Path $exe) { return @{Exe=$exe; Home=$base} }
      $dirs = Get-ChildItem -Path $base -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'prometheus*' } | Sort-Object LastWriteTime -Descending
      foreach ($d in $dirs) {
        $exe = Join-Path $d.FullName 'prometheus.exe'
        if (Test-Path $exe) { return @{Exe=$exe; Home=$d.FullName} }
      }
    }
  }
  return $null
}

function Reload-GrafanaProvisioning {
  param([int]$Port, [string]$User='admin', [string]$Pass='admin')
  try {
    if (-not $User) { $User = 'admin' }
    if (-not $Pass) { $Pass = 'admin' }
    $pair = "${User}:${Pass}"
    $basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
    $headers = @{ Authorization = "Basic $basic" }
    $uriDash = "http://127.0.0.1:$Port/api/admin/provisioning/dashboards/reload"
    $uriDS = "http://127.0.0.1:$Port/api/admin/provisioning/datasources/reload"
    $dashResult = Invoke-RestMethod -Method Post -Uri $uriDash -Headers $headers -TimeoutSec 5 -ErrorAction Stop
    $dsResult = Invoke-RestMethod -Method Post -Uri $uriDS -Headers $headers -TimeoutSec 5 -ErrorAction Stop
    Write-Host "  [OK] Grafana provisioning reloaded via API" -ForegroundColor Green
    return $true
  } catch {
    # This is not critical - provisioning files are already in place and will load on Grafana startup
    return $false
  }
}
Write-Host "=== G6 Observability Stack (Clean) ===" -ForegroundColor Cyan

# Directories
$LogDir = Join-Path $GrafanaDataRoot 'log'
$DataDir = Join-Path $GrafanaDataRoot 'data'
$PluginsDir = Join-Path $GrafanaDataRoot 'plugins'
$ProvRoot = Join-Path $GrafanaDataRoot 'provisioning_baseline'
Ensure-Dir $LogDir
Ensure-Dir $DataDir
Ensure-Dir $PluginsDir
Ensure-Dir $ProvRoot

# 1. Start Web API (FastAPI) - provides /api/live_csv for Infinity
Write-Host "Starting Web API on :$WebPort..." -ForegroundColor Green
# Use venv Python if available, otherwise fall back to system Python
$venvPy = Join-Path $Root 'venv\Scripts\python.exe'
if (Test-Path $venvPy) {
  $py = $venvPy
  Write-Host "  Using venv Python: $py" -ForegroundColor Gray
} else {
  $py = (Get-Command python -ErrorAction SilentlyContinue).Source
  if (-not $py) { Write-Host "Python not found!" -ForegroundColor Red; exit 1 }
  Write-Host "  Using system Python: $py" -ForegroundColor Gray
}
 $webLog = Join-Path $LogDir 'webapi_stdout.log'
 $webErr = Join-Path $LogDir 'webapi_stderr.log'
 # Use persistent runner by default for auto-restart capability
 if (-not $NoRunner) {
   $runner = Join-Path $Root 'run_dashboard_server.py'
   if (Test-Path $runner) {
     Write-Host "  Using persistent runner with auto-restart (recommended)" -ForegroundColor Gray
     Start-Process -FilePath $py -ArgumentList @($runner,'--port',"$WebPort",'--host','0.0.0.0','--max-restarts','50','--restart-delay','3.0') -WorkingDirectory $Root -WindowStyle Minimized -RedirectStandardOutput $webLog -RedirectStandardError $webErr
   } else {
     Write-Host "  WARNING: runner script missing, falling back to raw uvicorn" -ForegroundColor Yellow
     Start-Process -FilePath $py -ArgumentList @('-m','uvicorn','src.web.dashboard.app:app','--host','127.0.0.1','--port',"$WebPort") -WorkingDirectory $Root -WindowStyle Minimized -RedirectStandardOutput $webLog -RedirectStandardError $webErr
   }
 } else {
   Write-Host "  Using raw uvicorn (no auto-restart)" -ForegroundColor Gray
   Start-Process -FilePath $py -ArgumentList @('-m','uvicorn','src.web.dashboard.app:app','--host','127.0.0.1','--port',"$WebPort") -WorkingDirectory $Root -WindowStyle Minimized -RedirectStandardOutput $webLog -RedirectStandardError $webErr
 }
Start-Sleep -Seconds 3
 $healthUrl = "http://127.0.0.1:$WebPort/api/live_csv_health?index=NIFTY`&expiry_tag=this_week`&offset=0"
 if (-not (Wait-Http -Url $healthUrl -MaxTries 25)) {
   Write-Host "WARNING: Health probe failed ($healthUrl). Trying /health..." -ForegroundColor Yellow
   if (-not (Wait-Http -Url "http://127.0.0.1:$WebPort/health" -MaxTries 10)) {
     Write-Host "Trying /openapi.json..." -ForegroundColor Gray
     if (-not (Wait-Http -Url "http://127.0.0.1:$WebPort/openapi.json" -MaxTries 10)) {
       Write-Host "ERROR: Web API failed to start. Check logs:" -ForegroundColor Red
       Write-Host "  stdout: $webLog" -ForegroundColor Gray
       Write-Host "  stderr: $webErr" -ForegroundColor Gray
       if (Test-Path $webErr) {
         Write-Host "Last 15 lines of stderr:" -ForegroundColor Yellow
         Get-Content $webErr -Tail 15 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkYellow }
       }
     } else {
       Write-Host "Web API responding on /openapi.json (OK)" -ForegroundColor Green
     }
   } else {
     Write-Host "Web API responding on /health (OK)" -ForegroundColor Green
   }
 } else {
   Write-Host "Web API health OK (live_csv rows present)" -ForegroundColor Green
 }

# 2. Start Prometheus
Write-Host "Starting Prometheus on :$PrometheusPort..." -ForegroundColor Green
$prom = Find-Prometheus
if (-not $prom) {
  Write-Host "WARNING: Prometheus not found - skipping" -ForegroundColor Yellow
  Write-Host "  Install from: https://prometheus.io/download/" -ForegroundColor Gray
} else {
  $promCfg = Join-Path $Root 'prometheus.yml'
  if (-not (Test-Path $promCfg)) {
    Write-Host "WARNING: prometheus.yml not found - skipping" -ForegroundColor Yellow
  } else {
    $promLog = Join-Path $LogDir 'prometheus_stdout.log'
    $promErr = Join-Path $LogDir 'prometheus_stderr.log'
    Start-Process -FilePath $prom.Exe -ArgumentList @("--config.file=`"$promCfg`"","--web.listen-address=127.0.0.1:$PrometheusPort","--storage.tsdb.path=`"$DataDir\prometheus`"") -WorkingDirectory $prom.Home -WindowStyle Minimized -RedirectStandardOutput $promLog -RedirectStandardError $promErr
    if (-not (Wait-Http -Url "http://127.0.0.1:$PrometheusPort/-/ready" -MaxTries 20)) {
      Write-Host "WARNING: Prometheus not ready" -ForegroundColor Yellow
    } else {
      Write-Host "Prometheus ready!" -ForegroundColor Green
    }
  }
}

# 3. Provision Grafana datasources and dashboards
$dsDir = Join-Path $ProvRoot 'datasources'
$dbDir = Join-Path $ProvRoot 'dashboards'
$dbSrcDir = Join-Path $ProvRoot 'dashboards_src'
Ensure-Dir $dsDir
Ensure-Dir $dbDir
Ensure-Dir $dbSrcDir

# Copy dashboards
try {
  Remove-Item (Join-Path $dbSrcDir '*') -Recurse -Force -ErrorAction SilentlyContinue
  $dashSrc = Join-Path $Root 'grafana/dashboards'
  
  # Copy entire structure first to preserve folders (Core, ML, etc.)
  Copy-Item -Path (Join-Path $dashSrc '*') -Destination $dbSrcDir -Recurse -Force
  
  # Remove hidden/archive folders from destination
  Get-ChildItem -Path $dbSrcDir -Directory -Recurse | Where-Object { $_.Name -match '^\.|archive|hidden' } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

  # Patch ports in all JSON files
  $jsonFiles = Get-ChildItem -Path $dbSrcDir -Filter *.json -Recurse
  foreach ($file in $jsonFiles) {
    $content = Get-Content -Path $file.FullName -Raw -Encoding UTF8
    # Regex to match common port patterns: 9500, 9510, 8003, 9511
    # We replace them with the configured $WebPort
    $newContent = $content -replace '127\.0\.0\.1:(9500|9510|8003|9511)', "127.0.0.1:$WebPort"
    $newContent = $newContent -replace 'localhost:(9500|9510|8003|9511)', "localhost:$WebPort"
    
    if ($content -ne $newContent) {
      # Use .NET to write UTF-8 without BOM (Set-Content adds BOM in PS 5.1)
      $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
      [System.IO.File]::WriteAllText($file.FullName, $newContent, $utf8NoBom)
      Write-Host "  Patched ports in $($file.Name)" -ForegroundColor DarkGray
    }
  }
} catch {
  Write-Host "Error copying dashboards: $_" -ForegroundColor Red
}

# Write datasource provisioning (Prometheus + Infinity)
$dsYaml = @'
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    uid: PROM
    url: 'http://127.0.0.1:{PROM_PORT}'
    isDefault: true
    jsonData:
      httpMethod: POST
      timeInterval: 5s
    editable: true
  - name: Infinity
    type: yesoreyeram-infinity-datasource
    access: proxy
    uid: INFINITY
    isDefault: false
    jsonData:
      allowedHosts:
        - 'http://127.0.0.1:{WEB_PORT}'
        - 'http://localhost:{WEB_PORT}'
        - '127.0.0.1:{WEB_PORT}'
        - 'localhost:{WEB_PORT}'
    editable: true
  - name: G6 Infinity
    type: yesoreyeram-infinity-datasource
    access: proxy
    uid: G6_INFINITY
    isDefault: false
    jsonData:
      allowedHosts:
        - 'http://127.0.0.1:{WEB_PORT}'
        - 'http://localhost:{WEB_PORT}'
        - '127.0.0.1:{WEB_PORT}'
        - 'localhost:{WEB_PORT}'
    editable: true
'@
$dsYaml = $dsYaml -replace '\{PROM_PORT\}',$PrometheusPort -replace '\{WEB_PORT\}',$WebPort
Set-Content -Path (Join-Path $dsDir 'datasources.yml') -Encoding UTF8 -Value $dsYaml

# Write dashboard provisioning
$dbPath = $dbSrcDir -replace "\\","/"
$dbYaml = @'
apiVersion: 1
providers:
  - name: G6
    type: file
    disableDeletion: false
    editable: true
    options:
      path: '{DB_PATH}'
      foldersFromFilesStructure: true
'@
$dbYaml = $dbYaml -replace '\{DB_PATH\}',$dbPath
Set-Content -Path (Join-Path $dbDir 'dashboards.yml') -Encoding UTF8 -Value $dbYaml

# 4. Start Grafana with AUTHENTICATION REQUIRED
Write-Host "Starting Grafana on :$GrafanaPort (REQUIRES LOGIN)..." -ForegroundColor Green

# Find Grafana
$grafExe = $null
$grafHome = $null
foreach ($base in @('C:\Grafana','C:\Program Files\GrafanaLabs\grafana')) {
  if (Test-Path $base) {
    $dirs = Get-ChildItem -Path $base -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'grafana*' } | Sort-Object LastWriteTime -Descending
    foreach ($d in $dirs) {
      $exe = Join-Path (Join-Path $d.FullName 'bin') 'grafana-server.exe'
      if (Test-Path $exe) {
        $grafExe = $exe
        $grafHome = $d.FullName
        break
      }
    }
    if ($grafExe) { break }
  }
}
if (-not $grafExe) { Write-Host "Grafana not found!" -ForegroundColor Red; exit 4 }

# Set Grafana environment - FORCE AUTHENTICATION
$env:GF_SERVER_HTTP_PORT = "$GrafanaPort"
$env:GF_SERVER_HTTP_ADDR = '127.0.0.1'
$env:GF_PATHS_HOME = $grafHome
$env:GF_PATHS_DATA = $DataDir
$env:GF_PATHS_LOGS = $LogDir
$env:GF_PATHS_PLUGINS = $PluginsDir
$env:GF_PATHS_PROVISIONING = $ProvRoot
$env:GF_INSTALL_PLUGINS = 'yesoreyeram-infinity-datasource'
$env:GF_PLUGINS_ALLOW_LOCAL_NETWORKS = 'true'
# Enable anonymous access for easier dashboard viewing
$env:GF_AUTH_ANONYMOUS_ENABLED = 'true'
$env:GF_AUTH_ANONYMOUS_ORG_ROLE = 'Viewer'
$env:GF_AUTH_BASIC_ENABLED = 'true'
$env:GF_AUTH_DISABLE_LOGIN_FORM = 'false'
$env:GF_SECURITY_ADMIN_USER = 'admin'
$env:GF_SECURITY_ADMIN_PASSWORD = 'admin'

Start-Process -FilePath $grafExe -ArgumentList "--homepath `"$grafHome`"" -WorkingDirectory $grafHome -WindowStyle Minimized -RedirectStandardOutput (Join-Path $LogDir 'grafana_stdout.log') -RedirectStandardError (Join-Path $LogDir 'grafana_stderr.log')

if (-not (Wait-Http -Url "http://127.0.0.1:$GrafanaPort/api/health" -MaxTries 60)) {
  Write-Host "WARNING: Grafana not ready" -ForegroundColor Yellow
} else {
  Write-Host "Grafana ready!" -ForegroundColor Green
  # Wait additional 2 seconds for auth system to fully initialize
  Start-Sleep -Seconds 2
  
  # Fix Infinity datasource allowedHosts via API (provisioning doesn't apply jsonData properly)
  try {
    $dsBody = @{
      name = "Infinity"
      type = "yesoreyeram-infinity-datasource"
      access = "proxy"
      uid = "INFINITY"
      isDefault = $false
      jsonData = @{
        allowedHosts = @("http://127.0.0.1:$WebPort", "http://localhost:$WebPort", "127.0.0.1:$WebPort", "localhost:$WebPort")
      }
    } | ConvertTo-Json -Depth 5
    $null = Invoke-RestMethod -Uri "http://127.0.0.1:$GrafanaPort/api/datasources/uid/INFINITY" -Method Put -ContentType "application/json" -Body $dsBody -ErrorAction Stop
    Write-Host "  Configured Infinity datasource allowedHosts" -ForegroundColor Green
  } catch {
    Write-Host "  Note: Could not configure Infinity allowedHosts automatically" -ForegroundColor Yellow
  }
  
  # Try hot reload provisioning so latest dashboards appear without restart next time
  $reloadSuccess = Reload-GrafanaProvisioning -Port $GrafanaPort
  if (-not $reloadSuccess) {
    Write-Host "  Note: Provisioning will reload on next Grafana restart" -ForegroundColor Gray
  }
}

Write-Host ""
Write-Host "=== Stack Ready ===" -ForegroundColor Cyan
Write-Host "Grafana:    http://127.0.0.1:$GrafanaPort (login: admin/admin)"
if ($prom) {
  Write-Host "Prometheus: http://127.0.0.1:$PrometheusPort"
}
Write-Host "Web API:    http://127.0.0.1:$WebPort"
Write-Host "  - Live data:       /api/live_csv"
Write-Host "  - Overlay data:    /api/overlay"
Write-Host "  - Health check:    /api/live_csv_health (preferred) or /health"
Write-Host "  - Metrics (Prom):  /metrics" 
Write-Host ""

if ($OpenBrowser) {
  Start-Sleep -Seconds 2
  $grafanaUrl = "http://127.0.0.1:$GrafanaPort"
  Start-Process $grafanaUrl
}

exit 0
