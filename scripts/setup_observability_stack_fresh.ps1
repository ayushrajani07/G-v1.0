#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Fresh setup of G6 Observability Stack
.DESCRIPTION
    Stops services, configures datasources, provisions dashboards, starts services with IST timezone
#>
param(
    [switch]$CleanGrafanaData,
    [int]$GrafanaPort = 3002,
    [int]$WebApiPort = 9500,
    [int]$PrometheusPort = 9091
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  G6 Observability - Fresh Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ============================================================================
# STEP 1: Stop All Services
# ============================================================================
Write-Host "[1/8] Stopping existing services..." -ForegroundColor Yellow

try {
    $webApiProcs = Get-NetTCPConnection -LocalPort $WebApiPort -State Listen -ErrorAction SilentlyContinue | 
        ForEach-Object { Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue } | 
        Where-Object { $_.ProcessName -eq 'python' } | Select-Object -Unique
    if ($webApiProcs) {
        $webApiProcs | Stop-Process -Force
        Write-Host "  ✓ Stopped Web API" -ForegroundColor Green
        Start-Sleep -Seconds 1
    }
} catch {
    Write-Host "  ! Warning stopping Web API: $_" -ForegroundColor DarkYellow
}

try {
    $grafProcs = Get-Process grafana-server,grafana -ErrorAction SilentlyContinue
    if ($grafProcs) {
        $grafProcs | Stop-Process -Force
        Write-Host "  ✓ Stopped Grafana" -ForegroundColor Green
        Start-Sleep -Seconds 2
    }
} catch {
    Write-Host "  ! Warning stopping Grafana: $_" -ForegroundColor DarkYellow
}

try {
    $promProcs = Get-Process prometheus -ErrorAction SilentlyContinue
    if ($promProcs) {
        $promProcs | Stop-Process -Force
        Write-Host "  ✓ Stopped Prometheus" -ForegroundColor Green
        Start-Sleep -Seconds 1
    }
} catch {
    Write-Host "  ! Warning stopping Prometheus: $_" -ForegroundColor DarkYellow
}

Write-Host "  ✓ Services stopped" -ForegroundColor Green
Write-Host ""

# ============================================================================
# STEP 2: Clean Grafana Data (Optional)
# ============================================================================
if ($CleanGrafanaData) {
    Write-Host "[2/8] Cleaning Grafana data..." -ForegroundColor Yellow
    $grafanaDataRoot = 'C:\GrafanaData'
    if (Test-Path $grafanaDataRoot) {
        Write-Host "  ! WARNING: This will DELETE all Grafana data!" -ForegroundColor Red
        $confirm = Read-Host "  Type 'YES' to confirm deletion"
        if ($confirm -eq 'YES') {
            Remove-Item $grafanaDataRoot -Recurse -Force
            Write-Host "  ✓ Cleaned" -ForegroundColor Green
        } else {
            Write-Host "  × Skipped" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  - No existing data" -ForegroundColor Gray
    }
} else {
    Write-Host "[2/8] Keeping existing data (use -CleanGrafanaData to wipe)" -ForegroundColor Yellow
}
Write-Host ""

# ============================================================================
# STEP 3: Create Directories
# ============================================================================
Write-Host "[3/8] Creating directories..." -ForegroundColor Yellow
$grafanaDataRoot = 'C:\GrafanaData'
$dirs = @(
    "$grafanaDataRoot\data",
    "$grafanaDataRoot\log",
    "$grafanaDataRoot\plugins",
    "$grafanaDataRoot\provisioning\datasources",
    "$grafanaDataRoot\provisioning\dashboards",
    "$grafanaDataRoot\dashboards_live"
)
foreach ($dir in $dirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "  ✓ Created: $dir" -ForegroundColor Green
    }
}
Write-Host ""

# ============================================================================
# STEP 4: Skip Plugin (will auto-install via env var)
# ============================================================================
Write-Host "[4/8] Plugin will auto-install via GF_INSTALL_PLUGINS" -ForegroundColor Yellow
Write-Host ""

# ============================================================================
# STEP 5: Configure Datasources
# ============================================================================
Write-Host "[5/8] Configuring datasources..." -ForegroundColor Yellow

$dsYaml = @"
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    uid: PROM
    url: http://127.0.0.1:$PrometheusPort
    isDefault: true
    jsonData:
      httpMethod: POST
      timeInterval: 5s
    editable: true

  - name: Infinity
    type: yesoreyeram-infinity-datasource
    access: proxy
    uid: INFINITY
    url: http://127.0.0.1:$WebApiPort
    isDefault: false
    jsonData:
      allowedHosts:
        - http://127.0.0.1:$WebApiPort
        - http://localhost:$WebApiPort
        - 127.0.0.1:$WebApiPort
        - localhost:$WebApiPort
    editable: true

  - name: G6 Infinity
    type: yesoreyeram-infinity-datasource
    access: proxy
    uid: G6_INFINITY
    url: http://127.0.0.1:$WebApiPort
    isDefault: false
    jsonData:
      allowedHosts:
        - http://127.0.0.1:$WebApiPort
        - http://localhost:$WebApiPort
        - 127.0.0.1:$WebApiPort
        - localhost:$WebApiPort
    editable: true
"@

$dsPath = "$grafanaDataRoot\provisioning\datasources\datasources.yml"
Set-Content -Path $dsPath -Value $dsYaml -Encoding UTF8
Write-Host "  ✓ Datasources configured" -ForegroundColor Green
Write-Host ""

# ============================================================================
# STEP 6: Configure Dashboards
# ============================================================================
Write-Host "[6/8] Provisioning dashboards..." -ForegroundColor Yellow

$srcDashboards = "$Root\grafana\dashboards\generated"
$dstDashboards = "$grafanaDataRoot\dashboards_live"

if (Test-Path $srcDashboards) {
    $copied = 0
    Get-ChildItem -Path $srcDashboards -Filter *.json -File | Where-Object { $_.Name -ne 'manifest.json' } | ForEach-Object {
        Copy-Item $_.FullName -Destination $dstDashboards -Force
        $copied++
    }
    Write-Host "  ✓ Copied $copied dashboard(s)" -ForegroundColor Green
} else {
    Write-Host "  ! Source dashboards not found" -ForegroundColor Yellow
}

$dbYaml = @"
apiVersion: 1

providers:
  - name: 'G6 Dashboards'
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    allowUiUpdates: true
    options:
      path: $($dstDashboards -replace '\\','/')
      foldersFromFilesStructure: false
"@

$dbPath = "$grafanaDataRoot\provisioning\dashboards\dashboards.yml"
Set-Content -Path $dbPath -Value $dbYaml -Encoding UTF8
Write-Host "  ✓ Dashboard provisioning configured" -ForegroundColor Green
Write-Host ""

# ============================================================================
# STEP 7: Start Services
# ============================================================================
Write-Host "[7/8] Starting services..." -ForegroundColor Yellow
Write-Host ""

# --- Start Web API ---
Write-Host "  [7a] Starting Web API..." -ForegroundColor Cyan
$venvPython = "$Root\.venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $pythonExe = $venvPython
    Write-Host "      Using venv Python" -ForegroundColor Gray
} else {
    $pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $pythonExe) {
        Write-Host "      ✗ Python not found!" -ForegroundColor Red
        exit 1
    }
    Write-Host "      Using system Python" -ForegroundColor Gray
}

$webApiLog = "$grafanaDataRoot\log\webapi.log"
$webApiErrLog = "$grafanaDataRoot\log\webapi_error.log"
Start-Process -FilePath $pythonExe -ArgumentList @(
    '-m', 'uvicorn', 
    'src.web.dashboard.app:app',
    '--host', '127.0.0.1',
    '--port', "$WebApiPort"
) -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput $webApiLog -RedirectStandardError $webApiErrLog

Start-Sleep -Seconds 3

$apiReady = $false
for ($i = 0; $i -lt 10; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$WebApiPort/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            $apiReady = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 1
    }
}

if ($apiReady) {
    Write-Host "      ✓ Web API ready on http://127.0.0.1:$WebApiPort" -ForegroundColor Green
} else {
    Write-Host "      ! Web API may not be ready" -ForegroundColor Yellow
}
Write-Host ""

# --- Start Prometheus ---
Write-Host "  [7b] Starting Prometheus..." -ForegroundColor Cyan

$promExe = $null
$promHome = $null
$promSearchPaths = @('C:\Prometheus', 'C:\Program Files\Prometheus')

foreach ($base in $promSearchPaths) {
    if (-not (Test-Path $base)) {
        continue
    }
    
    # Try direct exe first
    $exePath = Join-Path $base "prometheus.exe"
    if (Test-Path $exePath) {
        $promExe = $exePath
        $promHome = $base
        break
    }
    
    # Try subdirectories
    $subDirs = Get-ChildItem -Path $base -Directory -ErrorAction SilentlyContinue | 
        Where-Object { $_.Name -like 'prometheus*' } | 
        Sort-Object LastWriteTime -Descending
    
    foreach ($subDir in $subDirs) {
        $exePath = Join-Path $subDir.FullName "prometheus.exe"
        if (Test-Path $exePath) {
            $promExe = $exePath
            $promHome = $subDir.FullName
            break
        }
    }
    
    if ($promExe) {
        break
    }
}

if ($promExe) {
    $promConfig = "$Root\prometheus.yml"
    if (Test-Path $promConfig) {
        $promDataDir = "$grafanaDataRoot\data\prometheus"
        if (-not (Test-Path $promDataDir)) {
            New-Item -ItemType Directory -Path $promDataDir -Force | Out-Null
        }
        
        $promLog = "$grafanaDataRoot\log\prometheus.log"
        Start-Process -FilePath $promExe -ArgumentList @(
            "--config.file=`"$promConfig`"",
            "--web.listen-address=127.0.0.1:$PrometheusPort",
            "--storage.tsdb.path=`"$promDataDir`""
        ) -WorkingDirectory $promHome -WindowStyle Hidden -RedirectStandardOutput $promLog
        
        Start-Sleep -Seconds 3
        $promReady = $false
        for ($i = 0; $i -lt 10; $i++) {
            try {
                $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$PrometheusPort/-/ready" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
                if ($resp.StatusCode -eq 200) {
                    $promReady = $true
                    break
                }
            } catch {
                Start-Sleep -Seconds 1
            }
        }
        
        if ($promReady) {
            Write-Host "      ✓ Prometheus ready on http://127.0.0.1:$PrometheusPort" -ForegroundColor Green
        } else {
            Write-Host "      ! Prometheus may not be ready" -ForegroundColor Yellow
        }
    } else {
        Write-Host "      ! prometheus.yml not found" -ForegroundColor Yellow
    }  # End if Test-Path $promConfig
} else {
    Write-Host "      ! Prometheus not found - skipping" -ForegroundColor Yellow
}  # End if $promExe
Write-Host ""

# --- Start Grafana ---
Write-Host "  [7c] Starting Grafana with IST timezone..." -ForegroundColor Cyan

$grafExe = $null
$grafHome = $null
$grafSearchPaths = @('C:\Grafana', 'C:\Program Files\GrafanaLabs\grafana')

foreach ($base in $grafSearchPaths) {
    if (-not (Test-Path $base)) {
        continue
    }
    
    $subDirs = Get-ChildItem -Path $base -Directory -ErrorAction SilentlyContinue | 
        Where-Object { $_.Name -like 'grafana*' } | 
        Sort-Object LastWriteTime -Descending
    
    foreach ($subDir in $subDirs) {
        $exePath = Join-Path $subDir.FullName "bin\grafana-server.exe"
        if (Test-Path $exePath) {
            $grafExe = $exePath
            $grafHome = $subDir.FullName
            break
        }
    }
    
    if ($grafExe) {
        break
    }
}

if (-not $grafExe) {
    Write-Host "      ✗ Grafana not found!" -ForegroundColor Red
    Write-Host "        Install from: https://grafana.com/grafana/download" -ForegroundColor Gray
    exit 2
}

# Set environment variables
$env:GF_SERVER_HTTP_PORT = "$GrafanaPort"
$env:GF_SERVER_HTTP_ADDR = '127.0.0.1'
$env:GF_PATHS_HOME = $grafHome
$env:GF_PATHS_DATA = "$grafanaDataRoot\data"
$env:GF_PATHS_LOGS = "$grafanaDataRoot\log"
$env:GF_PATHS_PLUGINS = "$grafanaDataRoot\plugins"
$env:GF_PATHS_PROVISIONING = "$grafanaDataRoot\provisioning"
$env:GF_DEFAULT_TIMEZONE = 'Asia/Kolkata'
$env:GF_INSTALL_PLUGINS = 'yesoreyeram-infinity-datasource'
$env:GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS = 'yesoreyeram-infinity-datasource'
$env:GF_AUTH_ANONYMOUS_ENABLED = 'true'
$env:GF_AUTH_ANONYMOUS_ORG_ROLE = 'Admin'
$env:GF_AUTH_DISABLE_LOGIN_FORM = 'true'
$env:GF_SECURITY_ALLOW_EMBEDDING = 'true'

$grafLog = "$grafanaDataRoot\log\grafana.log"
Start-Process -FilePath $grafExe -ArgumentList @(
    "--homepath", "`"$grafHome`""
) -WorkingDirectory $grafHome -WindowStyle Hidden -RedirectStandardOutput $grafLog

Start-Sleep -Seconds 5

$grafReady = $false
for ($i = 0; $i -lt 20; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$GrafanaPort/api/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            $grafReady = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 1
    }
}

if ($grafReady) {
    Write-Host "      ✓ Grafana ready on http://127.0.0.1:$GrafanaPort" -ForegroundColor Green
} else {
    Write-Host "      ! Grafana may not be ready" -ForegroundColor Yellow
}
Write-Host ""

# ============================================================================
# STEP 8: Verification
# ============================================================================
Write-Host "[8/8] Verification..." -ForegroundColor Yellow
Write-Host ""

Write-Host "=== Service Status ===" -ForegroundColor Cyan
Write-Host "  Web API:    http://127.0.0.1:$WebApiPort" -ForegroundColor White
Write-Host "              Test: http://127.0.0.1:$WebApiPort/api/live_csv?index=NIFTY&expiry_tag=this_week&offset=0&limit=3" -ForegroundColor Gray
Write-Host ""
Write-Host "  Grafana:    http://127.0.0.1:$GrafanaPort" -ForegroundColor White
Write-Host "              Timezone: Asia/Kolkata (IST)" -ForegroundColor Gray
Write-Host "              Auth: Anonymous Admin" -ForegroundColor Gray
Write-Host ""
if ($promExe) {
    Write-Host "  Prometheus: http://127.0.0.1:$PrometheusPort" -ForegroundColor White
    Write-Host ""
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Setup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$openBrowser = Read-Host "Open Grafana in browser? (Y/n)"
if ($openBrowser -ne 'n' -and $openBrowser -ne 'N') {
    Start-Process "http://127.0.0.1:$GrafanaPort"
}

exit 0
