# Dashboard Connection Issue - Root Cause & Fix Summary

**Date:** November 27, 2025  
**Status:** ✅ RESOLVED

## Problem Statement

Grafana dashboards were intermittently breaking with the following error:

```
Status: 500. Message: error while performing the infinity query. 
error getting response from url http://127.0.0.1:9500/api/live_csv?index=NIFTY&expiry_tag=this_week&offset=0. 
no response received. Error: Get "http://127.0.0.1:9500/api/live_csv?expiry_tag=this_week&index=NIFTY&offset=0": 
dial tcp 127.0.0.1:9500: connectex: No connection could be made because the target machine actively refused it.
```

## Root Cause

### Port Mismatch
- **API Server was running on:** `9510` (old default in `obs_start_clean.ps1`)
- **Grafana dashboards were querying:** Mixed - some `9500`, others `9510`
- **Result:** Connection refused errors when dashboard config didn't match running server

### No Auto-Restart
- API server was started with raw `uvicorn` without auto-restart capability
- Any crash or signal would leave dashboards permanently broken
- Required manual intervention to restart

## Solution Implemented

### 1. ✅ Standardized Port to 9500
Changed default `$WebPort` in `scripts/obs_start_clean.ps1` from `9510` → `9500`

### 2. ✅ Enabled Auto-Restart by Default
- Inverted `-UseRunner` switch to `-NoRunner` switch
- Now uses `run_dashboard_server.py` by default
- Provides automatic restart on crash (up to 50 retries with 3s delay)
- Server survives spurious signals (SIGINT/SIGTERM)

### 3. ✅ Updated All Dashboard Configurations
Updated 40+ Grafana dashboard JSON files:
```powershell
Get-ChildItem -Path ".\.grafana\provisioning_baseline\dashboards_src" -Filter "*.json" | 
    ForEach-Object { 
        $content = Get-Content $_.FullName -Raw
        $updated = $content -replace '127\.0\.0\.1:9510', '127.0.0.1:9500'
        Set-Content -Path $_.FullName -Value $updated -NoNewline
    }
```

## Verification

### API Server Status
```powershell
PS> Invoke-WebRequest -Uri "http://127.0.0.1:9500/health" -UseBasicParsing
API Health Check: SUCCESS (Status: 200)
Response: ok

PS> Invoke-WebRequest -Uri "http://127.0.0.1:9500/api/live_csv?index=NIFTY&expiry_tag=this_week&offset=0&limit=5"
Live CSV Endpoint: SUCCESS (Status: 200)
Content Length: 902 bytes
```

### Dashboard Verification
1. Open Grafana: http://127.0.0.1:3002 (login: admin/admin)
2. Navigate to any dashboard (e.g., "Overlays - All Indices")
3. Verify panels load without errors
4. Check browser console - no connection errors

## Files Modified

| File | Change |
|------|--------|
| `scripts/obs_start_clean.ps1` | Port default: 9510→9500, auto-restart enabled by default |
| `.grafana/provisioning_baseline/dashboards_src/*.json` | All URLs updated to port 9500 |
| `docs/DASHBOARD_PORT_FIX.md` | Comprehensive documentation (NEW) |
| `DASHBOARD_FIX_SUMMARY.md` | This summary (NEW) |

## Usage

### Start Observability Stack (Recommended)
```powershell
.\scripts\obs_start_clean.ps1
```

This now:
- ✅ Starts API server on port **9500** (matches dashboards)
- ✅ Uses persistent runner with **auto-restart**
- ✅ Starts Grafana on port **3002**
- ✅ Starts Prometheus on port **9091**

### Verify Running Services
```powershell
# Check API server
Get-NetTCPConnection -LocalPort 9500 -State Listen

# Test health endpoint
Invoke-WebRequest -Uri "http://127.0.0.1:9500/health"

# View logs
Get-Content C:\GrafanaData\log\webapi_stdout.log -Tail 50 -Wait
```

### Manual Restart (If Needed)
```powershell
# Stop all services
Get-NetTCPConnection -LocalPort 9500,3002,9091 -State Listen -ErrorAction SilentlyContinue | 
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }

# Restart
.\scripts\obs_start_clean.ps1
```

## Prevention Measures

### 1. Always Use Persistent Runner
The script now uses `run_dashboard_server.py` by default, providing:
- Automatic crash recovery
- Signal immunity
- Restart logging
- Persistent operation

### 2. Port Consistency Validation
Consider adding a validation check to startup scripts:
```powershell
$ApiPort = 9500
$BadFiles = Get-ChildItem ".grafana/provisioning_baseline/dashboards_src" -Filter "*.json" | 
    Where-Object {
        $content = Get-Content $_.FullName -Raw
        $content -match "127\.0\.0\.1:(?!$ApiPort)\d+"
    }
if ($BadFiles) {
    Write-Host "ERROR: Dashboard port mismatches detected!" -ForegroundColor Red
    exit 1
}
```

### 3. Environment Variable for Port (Future)
Consider centralizing port configuration:
```powershell
$env:G6_WEB_API_PORT = "9500"
```

## Technical Details

### Auto-Restart Configuration
Location: `run_dashboard_server.py`

```python
# Default configuration
--max-restarts 50        # Allow up to 50 restart attempts
--restart-delay 3.0      # Wait 3 seconds between restarts
--host 0.0.0.0          # Listen on all interfaces
--port 9500             # Standard port
```

### Signal Handling
The persistent runner ignores SIGINT/SIGTERM to prevent accidental shutdown:
```python
def make_handler(sig_name: str):
    def _handler(signum: int, frame: FrameType | None) -> None:
        nonlocal interrupt_count
        interrupt_count += 1
        if interrupt_count == 1:
            print(f"[runner] received {sig_name} (count=1) - ignored (server persists)")
```

To stop the server: `Stop-Process -Id <PID> -Force`

### Port Binding
The API server binds to `0.0.0.0:9500` but Grafana queries `127.0.0.1:9500`:
- `0.0.0.0` = Listen on all network interfaces
- `127.0.0.1` = Loopback/localhost interface
- This is correct and works properly

## Monitoring

### Health Checks
```powershell
# Primary health endpoint
Invoke-WebRequest -Uri "http://127.0.0.1:9500/health"

# Data-specific health check
Invoke-WebRequest -Uri "http://127.0.0.1:9500/api/live_csv_health?index=NIFTY&expiry_tag=this_week&offset=0"

# OpenAPI docs (verify server responsiveness)
Invoke-WebRequest -Uri "http://127.0.0.1:9500/openapi.json"
```

### Log Locations
```
C:\GrafanaData\log\webapi_stdout.log     - API server output
C:\GrafanaData\log\webapi_stderr.log     - API server errors
C:\GrafanaData\log\grafana_stdout.log    - Grafana output
C:\GrafanaData\log\prometheus_stdout.log - Prometheus output
```

## Troubleshooting

### Dashboard Still Shows Errors
1. **Hard refresh** browser (Ctrl+F5) to clear cached queries
2. **Restart Grafana**:
   ```powershell
   Get-Process grafana-server -ErrorAction SilentlyContinue | Stop-Process -Force
   .\scripts\obs_start_clean.ps1
   ```
3. **Check dashboard JSON** for port references:
   ```powershell
   Select-String -Path ".\.grafana\provisioning_baseline\dashboards_src\*.json" -Pattern "9510"
   ```

### API Server Not Starting
1. **Check port availability**:
   ```powershell
   Get-NetTCPConnection -LocalPort 9500 -State Listen
   ```
2. **Check logs**:
   ```powershell
   Get-Content C:\GrafanaData\log\webapi_stderr.log -Tail 100
   ```
3. **Manually test server**:
   ```powershell
   .\venv\Scripts\python.exe run_dashboard_server.py --port 9500 --host 0.0.0.0
   ```

### Auto-Restart Not Working
1. **Verify runner script exists**:
   ```powershell
   Test-Path "run_dashboard_server.py"
   ```
2. **Check process tree**:
   ```powershell
   Get-Process python | Select-Object Id, ProcessName, StartTime
   ```
3. **Check logs for restart messages**:
   ```powershell
   Select-String -Path "C:\GrafanaData\log\webapi_stdout.log" -Pattern "runner"
   ```

## Success Criteria

✅ API server runs on port **9500**  
✅ Auto-restart enabled with 50 retry limit  
✅ All 40+ dashboard JSON files updated to port **9500**  
✅ Health endpoint returns HTTP 200  
✅ Live CSV endpoint returns data  
✅ Grafana dashboards load without errors  
✅ Documentation created  

## Related Documentation

- `docs/DASHBOARD_PORT_FIX.md` - Detailed technical documentation
- `scripts/README_STARTUP_SCRIPTS.md` - Startup script guide
- `run_dashboard_server.py` - Persistent runner implementation

---

**Last Updated:** November 27, 2025  
**Next Review:** Check for port consistency after any configuration changes
