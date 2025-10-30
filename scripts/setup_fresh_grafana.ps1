# Fresh Grafana Setup with Authentication
# This script sets up a clean Grafana instance with proper authentication

param(
    [string]$GrafanaVersion = "11.2.0",
    [string]$DataDir = "C:\GrafanaData_Fresh",
    [int]$Port = 3005,
    [string]$AdminUser = "admin",
    [string]$AdminPassword = "admin123",
    [switch]$SkipDownload
)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Fresh Grafana Setup with Auth" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Stop any existing Grafana processes
Write-Host "[1/7] Stopping existing Grafana processes..." -ForegroundColor Yellow
Get-Process | Where-Object {$_.ProcessName -like "*grafana*"} | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Write-Host "  Done" -ForegroundColor Green

# Step 2: Clean up old data directory
Write-Host "[2/7] Setting up fresh data directory..." -ForegroundColor Yellow
if (Test-Path $DataDir) {
    Write-Host "  Removing old data directory: $DataDir" -ForegroundColor DarkYellow
    Remove-Item -Path $DataDir -Recurse -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
Write-Host "  Created: $DataDir" -ForegroundColor Green

# Step 3: Create directory structure
Write-Host "[3/7] Creating directory structure..." -ForegroundColor Yellow
$dirs = @(
    "$DataDir\data",
    "$DataDir\logs",
    "$DataDir\plugins",
    "$DataDir\provisioning\datasources",
    "$DataDir\provisioning\dashboards",
    "$DataDir\dashboards_live"
)
foreach ($dir in $dirs) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    Write-Host "  Created: $dir" -ForegroundColor Green
}

# Step 4: Download Grafana if needed
$grafanaExe = "C:\Program Files\GrafanaLabs\grafana\bin\grafana-server.exe"
if (-not (Test-Path $grafanaExe) -and -not $SkipDownload) {
    Write-Host "[4/7] Grafana not found. Please install Grafana from:" -ForegroundColor Yellow
    Write-Host "  https://grafana.com/grafana/download?platform=windows" -ForegroundColor Cyan
    Write-Host "  Or run: choco install grafana" -ForegroundColor Cyan
    exit 1
} elseif ($SkipDownload) {
    Write-Host "[4/7] Skipping Grafana installation check" -ForegroundColor Yellow
} else {
    Write-Host "[4/7] Found Grafana at: $grafanaExe" -ForegroundColor Green
}

# Step 5: Create datasource provisioning
Write-Host "[5/7] Creating datasource provisioning..." -ForegroundColor Yellow
$datasourceYaml = @"
apiVersion: 1

datasources:
  - name: Infinity
    type: yesoreyeram-infinity-datasource
    access: proxy
    uid: INFINITY
    url: http://127.0.0.1:9500
    isDefault: true
    jsonData:
      tlsSkipVerify: true
    editable: true
    version: 1

  - name: Prometheus
    type: prometheus
    access: proxy
    uid: PROM
    url: http://127.0.0.1:9090
    isDefault: false
    editable: true
    version: 1
"@
$datasourceYaml | Out-File -FilePath "$DataDir\provisioning\datasources\datasources.yml" -Encoding UTF8 -Force
Write-Host "  Created datasource provisioning" -ForegroundColor Green

# Step 6: Create Grafana configuration
Write-Host "[6/7] Creating Grafana configuration..." -ForegroundColor Yellow
$grafanaIni = @"
[paths]
data = $DataDir\data
logs = $DataDir\logs
plugins = $DataDir\plugins
provisioning = $DataDir\provisioning

[server]
protocol = http
http_addr = 127.0.0.1
http_port = $Port
domain = localhost
root_url = http://localhost:$Port/

[database]
type = sqlite3
path = grafana.db

[security]
admin_user = $AdminUser
admin_password = $AdminPassword
disable_initial_admin_creation = false
allow_embedding = true
cookie_secure = false

[auth]
disable_login_form = false
disable_signout_menu = false

[auth.anonymous]
enabled = false

[users]
allow_sign_up = false
allow_org_create = false
auto_assign_org = true
auto_assign_org_role = Viewer

[session]
provider = memory

[analytics]
reporting_enabled = false
check_for_updates = false

[log]
mode = console file
level = info

[log.console]
level = info
format = console

[log.file]
level = info
log_rotate = true
max_lines = 1000000
max_size_shift = 28
daily_rotate = true
max_days = 7

[alerting]
enabled = false

[unified_alerting]
enabled = false

[explore]
enabled = true

[plugins]
enable_alpha = false
allow_loading_unsigned_plugins = yesoreyeram-infinity-datasource

[plugin.yesoreyeram-infinity-datasource]
allow_unsafe_query = true
"@
$grafanaIni | Out-File -FilePath "$DataDir\grafana.ini" -Encoding UTF8 -Force
Write-Host "  Created Grafana configuration" -ForegroundColor Green

# Step 7: Start Grafana
Write-Host "[7/7] Starting Grafana on port $Port..." -ForegroundColor Yellow
$env:GF_PATHS_CONFIG = "$DataDir\grafana.ini"
$env:GF_PATHS_DATA = "$DataDir\data"
$env:GF_PATHS_LOGS = "$DataDir\logs"
$env:GF_PATHS_PLUGINS = "$DataDir\plugins"
$env:GF_PATHS_PROVISIONING = "$DataDir\provisioning"
$env:GF_SERVER_HTTP_PORT = $Port
$env:GF_SECURITY_ADMIN_USER = $AdminUser
$env:GF_SECURITY_ADMIN_PASSWORD = $AdminPassword

$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = $grafanaExe
$startInfo.Arguments = "--config `"$DataDir\grafana.ini`" --homepath `"C:\Program Files\GrafanaLabs\grafana`""
$startInfo.UseShellExecute = $false
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true
$startInfo.CreateNoWindow = $false
$startInfo.WorkingDirectory = "C:\Program Files\GrafanaLabs\grafana"

try {
    $process = [System.Diagnostics.Process]::Start($startInfo)
    Write-Host "  Grafana starting... (PID: $($process.Id))" -ForegroundColor Green
    
    # Wait for Grafana to start
    Write-Host "  Waiting for Grafana to become ready..." -ForegroundColor Yellow
    $maxWait = 30
    $waited = 0
    $ready = $false
    while ($waited -lt $maxWait) {
        Start-Sleep -Seconds 1
        $waited++
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:$Port/api/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {}
        Write-Host "." -NoNewline -ForegroundColor DarkGray
    }
    Write-Host ""
    
    if ($ready) {
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Green
        Write-Host "  Grafana is ready!" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Green
        Write-Host ""
        Write-Host "  URL:      http://localhost:$Port" -ForegroundColor Cyan
        Write-Host "  Username: $AdminUser" -ForegroundColor Cyan
        Write-Host "  Password: $AdminPassword" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  Data Dir: $DataDir" -ForegroundColor DarkGray
        Write-Host "  PID:      $($process.Id)" -ForegroundColor DarkGray
        Write-Host ""
        Write-Host "Next steps:" -ForegroundColor Yellow
        Write-Host "  1. Open http://localhost:$Port in your browser" -ForegroundColor White
        Write-Host "  2. Login with username '$AdminUser' and password '$AdminPassword'" -ForegroundColor White
        Write-Host "  3. Install Infinity datasource plugin (if not already installed)" -ForegroundColor White
        Write-Host "  4. Import your dashboard JSON via Dashboards > Import" -ForegroundColor White
        Write-Host ""
        
        # Open browser
        Start-Process "http://localhost:$Port"
        
    } else {
        Write-Host ""
        Write-Host "WARNING: Grafana started but health check failed after ${maxWait}s" -ForegroundColor Yellow
        Write-Host "  Check logs at: $DataDir\logs\" -ForegroundColor Yellow
        Write-Host "  Try accessing: http://localhost:$Port" -ForegroundColor Yellow
    }
    
} catch {
    Write-Host ""
    Write-Host "ERROR: Failed to start Grafana" -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
