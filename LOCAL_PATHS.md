# Local Installation Paths Reference

This document contains the canonical paths for all external dependencies installed on the development machine.

## Core Services

### Prometheus
- **Installation Directory**: `C:\Program Files\Prometheus\`
- **Executable**: `C:\Program Files\Prometheus\prometheus.exe`
- **Tool**: `C:\Program Files\Prometheus\promtool.exe`
- **Config File** (G6): `C:\Users\Asus\Desktop\g6_reorganized\prometheus.yml`
- **Data Directory** (G6): `C:\Users\Asus\Desktop\g6_reorganized\data\prometheus\`
- **Default Port**: 9090 (auto-discovery: 9090-9100)
- **Note**: Must use `--storage.tsdb.path` pointing to writable directory (not `C:\Program Files`)

### Grafana
- **Installation Directory**: `C:\Grafana\grafana-v11.2.0\`
- **Server Executable**: `C:\Grafana\grafana-v11.2.0\bin\grafana-server.exe`
- **CLI Tool**: `C:\Grafana\grafana-v11.2.0\bin\grafana-cli.exe`
- **Custom Config**: `C:\Grafana\grafana-v11.2.0\conf\custom.ini`
- **Data Directory**: `C:\GrafanaData\`
- **Logs Directory**: `C:\GrafanaData\log\`
- **Plugins Directory**: `C:\GrafanaData\plugins\`
- **Provisioning Directory**: `C:\GrafanaData\provisioning_baseline\`
- **Fresh Data Directory**: `C:\GrafanaData_Fresh\` (for clean setups)
- **Default Port**: 3002 (auto-discovery: 3000-3010)
- **Version**: 11.2.0
- **Note**: Uses `custom.ini` config file for reliable port and path settings

### Grafana Plugins
- **Infinity Datasource**: `C:\Grafana\grafana-v11.2.0\data\plugins\yesoreyeram-infinity-datasource\`
- **Infinity Plugin ID**: `yesoreyeram-infinity-datasource`
- **Infinity Executable**: `C:\Grafana\grafana-v11.2.0\data\plugins\yesoreyeram-infinity-datasource\gpx_infinity_windows_amd64.exe`

## Python Environment

### G6 Virtual Environment
- **Virtual Environment**: `C:\Users\Asus\Desktop\g6_reorganized\.venv\`
- **Python Executable**: `C:\Users\Asus\Desktop\g6_reorganized\.venv\Scripts\python.exe`
- **Pip Executable**: `C:\Users\Asus\Desktop\g6_reorganized\.venv\Scripts\pip.exe`
- **Activate Script**: `C:\Users\Asus\Desktop\g6_reorganized\.venv\Scripts\Activate.ps1`

## G6 Project Structure

### Repository Root
- **Root Directory**: `C:\Users\Asus\Desktop\g6_reorganized\`

### Key Directories
- **Scripts**: `C:\Users\Asus\Desktop\g6_reorganized\scripts\`
- **Source Code**: `C:\Users\Asus\Desktop\g6_reorganized\src\`
- **Web API**: `C:\Users\Asus\Desktop\g6_reorganized\src\web\`
- **CSV Data**: `C:\Users\Asus\Desktop\g6_reorganized\data\csv\live\`
- **Grafana Dashboards**: `C:\Users\Asus\Desktop\g6_reorganized\grafana\dashboards\generated\`
- **Provisioning Config**: `C:\Users\Asus\Desktop\g6_reorganized\grafana\provisioning\`

### Key Files
- **Environment Config**: `C:\Users\Asus\Desktop\g6_reorganized\.env`
- **Prometheus Config**: `C:\Users\Asus\Desktop\g6_reorganized\prometheus.yml`
- **Dashboard API Script**: `C:\Users\Asus\Desktop\g6_reorganized\scripts\start_dashboard_api.py`
- **Stack Launcher**: `C:\Users\Asus\Desktop\g6_reorganized\scripts\start_stack.ps1`
- **Auto Stack Script**: `C:\Users\Asus\Desktop\g6_reorganized\scripts\auto_stack.ps1`

## Service Endpoints

### Prometheus
- **Web UI**: `http://127.0.0.1:9090`
- **API**: `http://127.0.0.1:9090/api/v1/`
- **Health Check**: `http://127.0.0.1:9090/api/v1/status/runtimeinfo`

### Grafana
- **Web UI**: `http://127.0.0.1:3002`
- **Login**: `admin` / `admin`
- **API**: `http://127.0.0.1:3002/api/`
- **Health Check**: `http://127.0.0.1:3002/api/health`

### G6 Web API (Dashboard API)
- **Base URL**: `http://127.0.0.1:9500`
- **Live CSV Data**: `http://127.0.0.1:9500/api/live_csv`
  - Query Parameters: `?symbol=NIFTY&expiry=this_week&offset=0&include_greeks=1`
- **Overlay Data**: `http://127.0.0.1:9500/api/overlay`
- **Health Check**: `http://127.0.0.1:9500/health`

## Quick Reference Commands

### Start All Services
```powershell
.\scripts\start_stack.ps1 -OpenBrowser
```

### Start Specific Services
```powershell
# Skip Prometheus
.\scripts\start_stack.ps1 -SkipPrometheus

# Skip Grafana
.\scripts\start_stack.ps1 -SkipGrafana

# Skip Web API
.\scripts\start_stack.ps1 -SkipWebApi
```

### Manual Service Start

#### Prometheus
```powershell
cd "C:\Program Files\Prometheus"
.\prometheus.exe --config.file="C:\Users\Asus\Desktop\g6_reorganized\prometheus.yml" --storage.tsdb.path="C:\Users\Asus\Desktop\g6_reorganized\data\prometheus"
```

#### Grafana
```powershell
$env:GF_PATHS_DATA = "C:\GrafanaData"
$env:GF_PATHS_LOGS = "C:\GrafanaData\log"
$env:GF_PATHS_PLUGINS = "C:\GrafanaData\plugins"
$env:GF_PATHS_PROVISIONING = "C:\GrafanaData\provisioning_baseline"
$env:GF_SERVER_HTTP_PORT = "3002"
& "C:\Grafana\grafana-v11.2.0\bin\grafana-server.exe"
```

#### Web API
```powershell
cd C:\Users\Asus\Desktop\g6_reorganized
.\.venv\Scripts\python.exe .\scripts\start_dashboard_api.py --reload
```

### Stop All Services
```powershell
# Stop Grafana
Get-Process | Where-Object {$_.ProcessName -like "*grafana*"} | Stop-Process -Force

# Stop Prometheus
Get-Process | Where-Object {$_.ProcessName -like "*prometheus*"} | Stop-Process -Force

# Stop Web API
Get-Process | Where-Object {$_.Name -eq "python"} | ForEach-Object {
    $cmd = (Get-WmiObject Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine
    if ($cmd -like "*dashboard*") { Stop-Process -Id $_.Id -Force }
}
```

## Dashboard Files

### Analytics Dashboard (Main)
- **File**: `C:\Users\Asus\Desktop\g6_reorganized\grafana\dashboards\generated\analytics_infinity_v3.json`
- **UID**: `g6-analytics-infinity-v3`
- **Title**: "G6 Analytics – Infinity v3"
- **Panels**: 14 (2 Index Price, 2 IV, 10 Greeks)
- **Time Range**: Last 12 hours
- **Refresh**: 15 seconds

## Notes

### Port Auto-Discovery
- **Prometheus**: Tries ports 9090-9100 in sequence
- **Grafana**: Tries ports 3000-3010 in sequence
- **Web API**: Fixed on port 9500

### Timezone
- **All Services**: Asia/Kolkata (IST = UTC+5:30)
- **CSV Timestamps**: IST
- **API Response Timestamps**: Epoch milliseconds + ISO 8601 with timezone

### Data Flow
```
CSV Files (IST timestamps)
    ↓
Web API (/api/live_csv?include_greeks=1)
    ↓
Infinity Datasource (Grafana)
    ↓
Analytics Dashboard (14 panels)
```

### Greek Data Fields
- **Call Options**: `ce_delta`, `ce_gamma`, `ce_theta`, `ce_vega`, `ce_rho`
- **Put Options**: `pe_delta`, `pe_gamma`, `pe_theta`, `pe_vega`, `pe_rho`
- **Requirement**: API parameter `include_greeks=1` must be set

---

**Last Updated**: 2025-10-29  
**Maintained By**: Development Team  
**Version**: 1.0
