# G6 Stack Launcher
# Stops existing services, launches all services, waits for health checks, displays status

param(
    [switch]$SkipPrometheus,
    [switch]$SkipGrafana,
    [switch]$SkipWebApi,
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  G6 Stack Launcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$repoRoot = Split-Path $PSScriptRoot -Parent

# ============================================
# STEP 1: STOP ALL EXISTING SERVICES (if requested)
# ============================================
Write-Host "[1/3] Stopping existing services..." -ForegroundColor Yellow

# Stop Grafana (both grafana and grafana-server processes)
Get-Process | Where-Object {$_.ProcessName -like "*grafana*" -or $_.ProcessName -eq "grafana-server"} | Stop-Process -Force -ErrorAction SilentlyContinue

# Stop Prometheus
Get-Process | Where-Object {$_.ProcessName -like "*prometheus*"} | Stop-Process -Force -ErrorAction SilentlyContinue

# Stop Web API (Python/Uvicorn)
Get-Process | Where-Object {$_.Name -eq "python" -or $_.Name -eq "pythonw"} | ForEach-Object {
    try {
        $cmd = (Get-WmiObject Win32_Process -Filter "ProcessId=$($_.Id)" -ErrorAction SilentlyContinue).CommandLine
        if ($cmd -like "*uvicorn*" -or $cmd -like "*dashboard*" -or $cmd -like "*start_dashboard_api*") {
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        }
    } catch {}
}

# Wait for processes to fully terminate
Start-Sleep -Seconds 3

# Verify all processes are stopped
$remainingGrafana = Get-Process | Where-Object {$_.ProcessName -like "*grafana*"} -ErrorAction SilentlyContinue
if ($remainingGrafana) {
    Write-Host "  Warning: Some Grafana processes still running, waiting..." -ForegroundColor Yellow
    Start-Sleep -Seconds 3
}

Write-Host "  All existing services stopped" -ForegroundColor Green

# ============================================
# STEP 2: START ALL SERVICES
# ============================================
Write-Host ""
Write-Host "[2/3] Starting services..." -ForegroundColor Yellow

$services = @{
    Prometheus = @{
        Enabled = -not $SkipPrometheus
        Port = $null
        Url = $null
        Status = "Not Started"
    }
    Grafana = @{
        Enabled = -not $SkipGrafana
        Port = $null
        Url = $null
        Status = "Not Started"
    }
    WebAPI = @{
        Enabled = -not $SkipWebApi
        Port = $null
        Url = $null
        Status = "Not Started"
    }
}

# Start Prometheus
if ($services.Prometheus.Enabled) {
    Write-Host "  Starting Prometheus..." -ForegroundColor Cyan
    $prometheusExe = "C:\Program Files\Prometheus\prometheus.exe"
    if (Test-Path $prometheusExe) {
        $prometheusDir = "C:\Program Files\Prometheus"
        $prometheusConfig = Join-Path $repoRoot "prometheus.yml"
        $prometheusData = Join-Path $repoRoot "data\prometheus"
        
        # Create data directory if it doesn't exist
        if (-not (Test-Path $prometheusData)) {
            New-Item -ItemType Directory -Path $prometheusData -Force | Out-Null
        }
        
        Start-Process $prometheusExe -ArgumentList "--config.file=$prometheusConfig", "--storage.tsdb.path=$prometheusData" -WindowStyle Hidden -WorkingDirectory $prometheusDir
        $services.Prometheus.Status = "Starting"
    } else {
        Write-Host "    WARNING: Prometheus not found at $prometheusExe" -ForegroundColor Yellow
        $services.Prometheus.Enabled = $false
    }
}

# Start Grafana
if ($services.Grafana.Enabled) {
    Write-Host "  Starting Grafana..." -ForegroundColor Cyan
    $grafanaExe = "C:\Grafana\grafana-v11.2.0\bin\grafana-server.exe"
    $grafanaHome = "C:\Grafana\grafana-v11.2.0"
    $grafanaConfig = "C:\Grafana\grafana-v11.2.0\conf\custom.ini"
    
    if (Test-Path $grafanaExe) {
        Start-Process $grafanaExe -ArgumentList "--homepath", $grafanaHome, "--config", $grafanaConfig -WindowStyle Hidden -WorkingDirectory $grafanaHome
        $services.Grafana.Status = "Starting"
    } else {
        Write-Host "    WARNING: Grafana not found at $grafanaExe" -ForegroundColor Yellow
        $services.Grafana.Enabled = $false
    }
}

# Start Web API
if ($services.WebAPI.Enabled) {
    Write-Host "  Starting Web API..." -ForegroundColor Cyan
    
    # Find Python
    $pythonExe = $null
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $pythonExe = $venvPython
    } else {
        try {
            $pythonCmd = Get-Command python -ErrorAction Stop
            if ($pythonCmd) { $pythonExe = $pythonCmd.Source }
        } catch {}
    }
    
    if ($pythonExe) {
        $webApiScript = Join-Path $repoRoot "scripts\start_dashboard_api.py"
        Start-Process $pythonExe -ArgumentList $webApiScript -WindowStyle Hidden -WorkingDirectory $repoRoot
        $services.WebAPI.Status = "Starting"
    } else {
        Write-Host "    WARNING: Python not found, skipping Web API" -ForegroundColor Yellow
        $services.WebAPI.Enabled = $false
    }
}

# Give services initial startup time before health checks
# Grafana typically takes 15-20 seconds to fully start
Write-Host "  Waiting for services to initialize..." -ForegroundColor Cyan
Start-Sleep -Seconds 15

# ============================================
# STEP 3: HEALTH CHECK LOOP
# ============================================
Write-Host ""
Write-Host "[3/3] Waiting for services to be ready..." -ForegroundColor Yellow
Write-Host ""

$maxWaitSeconds = 120
$checkInterval = 10
$elapsed = 0
$allReady = $false

while ($elapsed -lt $maxWaitSeconds -and -not $allReady) {
    $allReady = $true
    $statusLines = @()
    
    # Check Prometheus
    if ($services.Prometheus.Enabled) {
        $ready = $false
        foreach ($port in 9090..9100) {
            try {
                $response = Invoke-WebRequest -Uri "http://localhost:$port/api/v1/status/runtimeinfo" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
                if ($response.StatusCode -eq 200) {
                    $services.Prometheus.Port = $port
                    $services.Prometheus.Url = "http://127.0.0.1:$port"
                    $services.Prometheus.Status = "Running"
                    $ready = $true
                    break
                }
            } catch {}
        }
        
        if (-not $ready) {
            $services.Prometheus.Status = "Starting"
            $allReady = $false
        }
        
        $status = if ($services.Prometheus.Status -eq "Running") { "[OK]" } else { "..." }
        $statusLines += "  Prometheus: $status $($services.Prometheus.Status)"
    }
    
    # Check Grafana
    if ($services.Grafana.Enabled) {
        $ready = $false
        foreach ($port in 3000..3010) {
            try {
                $response = Invoke-WebRequest -Uri "http://localhost:$port/api/health" -UseBasicParsing -TimeoutSec 5 -ErrorAction SilentlyContinue
                if ($response.StatusCode -eq 200) {
                    $services.Grafana.Port = $port
                    $services.Grafana.Url = "http://127.0.0.1:$port"
                    $services.Grafana.Status = "Running"
                    $ready = $true
                    break
                }
            } catch {}
        }
        
        if (-not $ready) {
            $services.Grafana.Status = "Starting"
            $allReady = $false
        }
        
        $status = if ($services.Grafana.Status -eq "Running") { "[OK]" } else { "..." }
        $statusLines += "  Grafana:    $status $($services.Grafana.Status)"
    }
    
    # Check Web API
    if ($services.WebAPI.Enabled) {
        $ready = $false
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:9500/health" -UseBasicParsing -TimeoutSec 5 -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) {
                $services.WebAPI.Port = 9500
                $services.WebAPI.Url = "http://127.0.0.1:9500"
                $services.WebAPI.Status = "Running"
                $ready = $true
            }
        } catch {}
        
        if (-not $ready) {
            $services.WebAPI.Status = "Starting"
            $allReady = $false
        }
        
        $status = if ($services.WebAPI.Status -eq "Running") { "[OK]" } else { "..." }
        $statusLines += "  Web API:    $status $($services.WebAPI.Status)"
    }
    
    # Print status
    Write-Host "`r$(' ' * 80)`r" -NoNewline
    foreach ($line in $statusLines) {
        Write-Host "`r$line" -NoNewline
        if ($statusLines.IndexOf($line) -lt ($statusLines.Count - 1)) {
            Write-Host ""
        }
    }
    
    if (-not $allReady) {
        Start-Sleep -Seconds $checkInterval
        $elapsed += $checkInterval
        Write-Host ""
        Write-Host ""
    }
}

Write-Host ""
Write-Host ""

# ============================================
# STEP 4: FINAL STATUS REPORT
# ============================================

if ($allReady) {
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Stack Ready" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
} else {
    Write-Host "========================================" -ForegroundColor Yellow
    Write-Host "  Stack Partially Ready" -ForegroundColor Yellow
    Write-Host "========================================" -ForegroundColor Yellow
}

Write-Host ""

# Print Grafana
if ($services.Grafana.Enabled) {
    if ($services.Grafana.Status -eq "Running") {
        Write-Host "Grafana:    $($services.Grafana.Url) (login: admin/admin)" -ForegroundColor Cyan
    } else {
        Write-Host "Grafana:    Not ready (try: http://127.0.0.1:3002)" -ForegroundColor Yellow
    }
}

# Print Prometheus
if ($services.Prometheus.Enabled) {
    if ($services.Prometheus.Status -eq "Running") {
        Write-Host "Prometheus: $($services.Prometheus.Url)" -ForegroundColor Cyan
    } else {
        Write-Host "Prometheus: Not ready (try: http://127.0.0.1:9090)" -ForegroundColor Yellow
    }
}

# Print Web API
if ($services.WebAPI.Enabled) {
    if ($services.WebAPI.Status -eq "Running") {
        Write-Host "Web API:    $($services.WebAPI.Url)" -ForegroundColor Cyan
        Write-Host "  - Live data:    /api/live_csv" -ForegroundColor DarkGray
        Write-Host "  - Overlay data: /api/overlay" -ForegroundColor DarkGray
        Write-Host "  - Health check: /health" -ForegroundColor DarkGray
    } else {
        Write-Host "Web API:    Not ready (try: http://127.0.0.1:9500/health)" -ForegroundColor Yellow
    }
}

Write-Host ""

# Dashboard info
if ($services.Grafana.Status -eq "Running") {
    Write-Host "Dashboard:  Import via Grafana UI" -ForegroundColor White
    Write-Host "  File: $repoRoot\grafana\dashboards\generated\analytics_infinity_v3.json" -ForegroundColor DarkGray
    Write-Host "  Time Range: Last 12 hours" -ForegroundColor DarkGray
    Write-Host ""
}

# Open browser
if ($OpenBrowser -and $services.Grafana.Status -eq "Running") {
    Write-Host "Opening browser..." -ForegroundColor Yellow
    Start-Process $services.Grafana.Url
    Write-Host ""
}

# Summary
$runningCount = ($services.Values | Where-Object { $_.Enabled -and $_.Status -eq "Running" }).Count
$totalCount = ($services.Values | Where-Object { $_.Enabled }).Count

if ($runningCount -eq $totalCount) {
    Write-Host "All $totalCount services are running!" -ForegroundColor Green
} else {
    Write-Host "$runningCount of $totalCount services are running" -ForegroundColor Yellow
}

Write-Host ""
