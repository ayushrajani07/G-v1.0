# Dashboard Port Mismatch Fix

**Date**: November 27, 2025  
**Issue**: Grafana dashboards intermittently failing with "connection refused" errors

## Root Cause

The dashboards were breaking due to a **port mismatch** between:

1. **API Server Default Port**: `9510` (old default in `obs_start_clean.ps1`)
2. **Dashboard JSON Configuration**: Mixed - some files used `9500`, others used `9510`

When Grafana Infinity datasource queries attempted to connect to `127.0.0.1:9500`, but the API server was running on `9510`, the connection would fail with:

```
Status: 500. Message: error while performing the infinity query. error getting response from url 
http://127.0.0.1:9500/api/live_csv?index=NIFTY&expiry_tag=this_week&offset=0. no response received. 
Error: Get "http://127.0.0.1:9500/api/live_csv?expiry_tag=this_week&index=NIFTY&offset=0": 
dial tcp 127.0.0.1:9500: connectex: No connection could be made because the target machine actively refused it.
```

## Changes Made

### 1. Standardized Port to 9500

**File**: `scripts/obs_start_clean.ps1`

- Changed default `$WebPort` parameter from `9510` to `9500`
- This aligns with historical convention and majority of dashboard configurations

### 2. Enabled Auto-Restart by Default

**File**: `scripts/obs_start_clean.ps1`

- Changed `-UseRunner` switch to `-NoRunner` switch (inverted logic)
- Now uses `run_dashboard_server.py` by default, which provides:
  - Automatic restart on crash (up to 50 retries)
  - Signal immunity (survives spurious SIGINT/SIGTERM)
  - 3-second restart delay between attempts
  - Persistent operation without manual intervention

**Before**:
```powershell
.\scripts\obs_start_clean.ps1  # Used raw uvicorn (no auto-restart)
.\scripts\obs_start_clean.ps1 -UseRunner  # Enabled auto-restart
```

**After**:
```powershell
.\scripts\obs_start_clean.ps1  # Uses persistent runner with auto-restart (RECOMMENDED)
.\scripts\obs_start_clean.ps1 -NoRunner  # Raw uvicorn (not recommended)
```

### 3. Updated All Grafana Dashboard JSON Files

**Directory**: `.grafana/provisioning_baseline/dashboards_src/`

Updated all dashboard JSON files to use `127.0.0.1:9500` consistently:
- `analytics_infinity_v3*.json`
- `ml_*.json` 
- And 40+ other dashboard files

## Why This Happened

1. **Port Evolution**: The project started with port 9500, then experimented with 9510 to avoid conflicts
2. **Inconsistent Updates**: When the default port changed, not all dashboard JSON files were updated
3. **No Validation**: No automated check to ensure dashboard URLs matched the running API port
4. **Manual Restarts**: Without auto-restart, any crash or signal would leave dashboards broken

## Prevention Measures

### 1. Environment Variable for Port (Future Enhancement)

Consider adding an environment variable:

```powershell
$env:G6_WEB_API_PORT = "9500"  # Centralized port configuration
```

Then reference it in:
- Startup scripts
- Dashboard provisioning templates
- Health checks

### 2. Port Validation Health Check

Add a startup validation that:
1. Reads the configured API port from the startup script
2. Verifies all dashboard JSON files reference that port
3. Fails loudly if mismatches are detected

Example PowerShell snippet:
```powershell
$ApiPort = 9500
$DashboardDir = ".grafana/provisioning_baseline/dashboards_src"
$BadFiles = Get-ChildItem $DashboardDir -Filter "*.json" | Where-Object {
    $content = Get-Content $_.FullName -Raw
    $content -match "127\.0\.0\.1:(?!$ApiPort)\d+"
}
if ($BadFiles) {
    Write-Host "ERROR: Dashboard port mismatches detected!" -ForegroundColor Red
    $BadFiles | ForEach-Object { Write-Host "  - $($_.Name)" }
    exit 1
}
```

### 3. Always Use Persistent Runner

The `run_dashboard_server.py` script provides critical reliability:

**Benefits**:
- Automatically restarts on crash
- Survives spurious signals
- Logs restart attempts
- Prevents "dashboard goes dark" scenarios

**Usage**:
```powershell
# Start with auto-restart (default, recommended)
.\scripts\obs_start_clean.ps1

# Check if running
Get-NetTCPConnection -LocalPort 9500 -State Listen -ErrorAction SilentlyContinue

# View logs
Get-Content C:\GrafanaData\log\webapi_stdout.log -Tail 50 -Wait
```

### 4. Monitoring and Alerts

Set up monitoring for:
- API server availability on port 9500
- HTTP health endpoint: `http://127.0.0.1:9500/health`
- Data endpoint: `http://127.0.0.1:9500/api/live_csv_health?index=NIFTY&expiry_tag=this_week&offset=0`

## Testing the Fix

### 1. Stop Current Processes

```powershell
# Kill any existing API servers
Get-NetTCPConnection -LocalPort 9500,9510 -State Listen -ErrorAction SilentlyContinue | 
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

### 2. Start with New Configuration

```powershell
.\scripts\obs_start_clean.ps1
```

### 3. Verify API Server

```powershell
# Check port listener
Get-NetTCPConnection -LocalPort 9500 -State Listen

# Test health endpoint
Invoke-WebRequest -Uri "http://127.0.0.1:9500/health" -UseBasicParsing

# Test live data endpoint
Invoke-WebRequest -Uri "http://127.0.0.1:9500/api/live_csv?index=NIFTY&expiry_tag=this_week&offset=0&limit=10" -UseBasicParsing
```

### 4. Verify Grafana Dashboards

1. Open Grafana: `http://127.0.0.1:3002` (login: admin/admin)
2. Navigate to "Overlays - All Indices" dashboard
3. Verify data loads without errors
4. Check browser console for connection errors (should be none)
5. Inspect panel queries (click panel → Edit → Query tab)
6. Verify URL shows `http://127.0.0.1:9500/api/live_csv...`

## Rollback (If Needed)

If the new configuration causes issues:

```powershell
# Revert to raw uvicorn on original port
.\scripts\obs_start_clean.ps1 -WebPort 9510 -NoRunner
```

Then manually update dashboard JSON files back to 9510 (not recommended).

## Related Files

- `scripts/obs_start_clean.ps1` - Main startup script
- `run_dashboard_server.py` - Persistent runner with auto-restart
- `.grafana/provisioning_baseline/dashboards_src/*.json` - Dashboard configurations
- `src/web/dashboard/app.py` - FastAPI application

## Summary

✅ **Port standardized to 9500**  
✅ **Auto-restart enabled by default**  
✅ **All dashboards updated to 9500**  
✅ **Documentation created**  

The dashboards should now remain stable and automatically recover from crashes.
