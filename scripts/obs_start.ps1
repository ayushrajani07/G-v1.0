# Observability Stack Startup Script
# Starts Prometheus, Grafana (with auth), and optionally InfluxDB

param(
    [switch]$SkipPrometheus,
    [switch]$SkipGrafana,
    [switch]$StartInflux,
    [switch]$OpenBrowser,
    [string]$GrafanaPassword = "admin123"
)

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  G6 Observability Stack Startup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$repoRoot = Split-Path $PSScriptRoot -Parent

# Step 1: Stop existing processes
Write-Host "[1/3] Stopping existing observability processes..." -ForegroundColor Yellow
Get-Process | Where-Object {
    $_.ProcessName -like "*grafana*" -or 
    $_.ProcessName -like "*prometheus*" -or 
    $_.ProcessName -like "*influxd*"
} | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Write-Host "  Done" -ForegroundColor Green

# Step 2: Start Prometheus (if not skipped)
if (-not $SkipPrometheus) {
    Write-Host ""
    Write-Host "[2/3] Starting Prometheus..." -ForegroundColor Yellow
    
    # Call auto_stack to start only Prometheus
    & "$PSScriptRoot\auto_stack.ps1" -StartPrometheus $true -StartGrafana $false -StartInflux $false
    
    Start-Sleep -Seconds 3
    
    # Check if Prometheus started
    $promPort = $null
    foreach ($port in 9090..9100) {
        try {
            $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
            if ($conn) {
                $promPort = $port
                break
            }
        } catch {}
    }
    
    if ($promPort) {
        Write-Host "  Prometheus started on port: $promPort" -ForegroundColor Green
        Write-Host "  URL: http://localhost:$promPort" -ForegroundColor Cyan
    } else {
        Write-Host "  WARNING: Prometheus may not have started" -ForegroundColor Yellow
    }
} else {
    Write-Host ""
    Write-Host "[2/3] Skipping Prometheus (--SkipPrometheus)" -ForegroundColor DarkGray
}

# Step 3: Start Grafana with Auth (if not skipped)
if (-not $SkipGrafana) {
    Write-Host ""
    Write-Host "[3/3] Starting Grafana with Authentication..." -ForegroundColor Yellow
    
    # Use auto_stack to start Grafana (simpler and faster)
    & "$PSScriptRoot\auto_stack.ps1" -StartPrometheus $false -StartGrafana $true -StartInflux $false -GrafanaAdminPassword $GrafanaPassword
    
    Start-Sleep -Seconds 3
    
    # Check if Grafana started
    $grafanaPort = $null
    $grafanaReady = $false
    
    foreach ($port in 3000..3010) {
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:$port/api/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) {
                $grafanaReady = $true
                $grafanaPort = $port
                break
            }
        } catch {}
    }
    
    if ($grafanaReady) {
        Write-Host "  Grafana started on port: $grafanaPort" -ForegroundColor Green
        Write-Host "  URL: http://localhost:$grafanaPort" -ForegroundColor Cyan
        Write-Host "  Username: admin" -ForegroundColor White
        Write-Host "  Password: admin (default)" -ForegroundColor White
        
        if ($OpenBrowser) {
            Write-Host ""
            Write-Host "  Opening browser..." -ForegroundColor Yellow
            Start-Process "http://localhost:$grafanaPort"
        }
    } else {
        Write-Host "  WARNING: Grafana may still be starting..." -ForegroundColor Yellow
        Write-Host "  Try accessing: http://localhost:3002 or http://localhost:3000" -ForegroundColor Cyan
    }
    
} else {
    Write-Host ""
    Write-Host "[3/3] Skipping Grafana (--SkipGrafana)" -ForegroundColor DarkGray
}

# Step 4: Start InfluxDB (if requested)
if ($StartInflux) {
    Write-Host ""
    Write-Host "[Optional] Starting InfluxDB..." -ForegroundColor Yellow
    
    & "$PSScriptRoot\auto_stack.ps1" -StartPrometheus $false -StartGrafana $false -StartInflux $true
    
    Start-Sleep -Seconds 2
    
    # Check if InfluxDB started
    $influxPort = $null
    foreach ($port in 8086..8096) {
        try {
            $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
            if ($conn) {
                $influxPort = $port
                break
            }
        } catch {}
    }
    
    if ($influxPort) {
        Write-Host "  InfluxDB started on port: $influxPort" -ForegroundColor Green
        Write-Host "  URL: http://localhost:$influxPort" -ForegroundColor Cyan
    } else {
        Write-Host "  InfluxDB not started (optional)" -ForegroundColor DarkGray
    }
}

# Summary
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Observability Stack Status" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

# Check all services
$services = @()

# Prometheus
foreach ($port in 9090..9100) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:$port/api/v1/status/runtimeinfo" -UseBasicParsing -TimeoutSec 1 -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) {
            $services += [PSCustomObject]@{
                Service = "Prometheus"
                Port = $port
                Status = "Running"
                URL = "http://localhost:$port"
            }
            break
        }
    } catch {}
}

# Grafana
foreach ($port in 3000..3010) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:$port/api/health" -UseBasicParsing -TimeoutSec 1 -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) {
            $services += [PSCustomObject]@{
                Service = "Grafana"
                Port = $port
                Status = "Running"
                URL = "http://localhost:$port"
            }
            break
        }
    } catch {}
}

# InfluxDB
foreach ($port in 8086..8096) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:$port/health" -UseBasicParsing -TimeoutSec 1 -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) {
            $services += [PSCustomObject]@{
                Service = "InfluxDB"
                Port = $port
                Status = "Running"
                URL = "http://localhost:$port"
            }
            break
        }
    } catch {}
}

if ($services.Count -gt 0) {
    $services | Format-Table -AutoSize
} else {
    Write-Host "  No services detected as running" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Dashboard Import:" -ForegroundColor Yellow
Write-Host "  File: $repoRoot\grafana\dashboards\generated\analytics_infinity_v3.json" -ForegroundColor White
Write-Host "  Time Range: Last 12 hours" -ForegroundColor White
Write-Host ""

Write-Host "Observability stack startup complete!" -ForegroundColor Green
Write-Host ""
