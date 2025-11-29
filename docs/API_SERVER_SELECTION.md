# API Server Selection in Grafana Dashboards

## Problem

The system needs to support multiple API server ports (9500, 9510, 8003) without breaking dashboards. Previously switching default ports would break some services due to deadlocks or conflicts.

## Solution ✅ ALREADY IMPLEMENTED

All Grafana dashboards already have an `api_server` variable that allows dynamic endpoint selection **without editing JSON files**.

### How It Works

1. **Variable Definition**: Each dashboard has an `api_server` variable in the templating section
2. **URL Template**: All API URLs use `http://${api_server}/api/...` instead of hardcoded hosts
3. **Runtime Substitution**: Grafana substitutes the selected value when making requests

### Available Options

The `api_server` variable provides these options:

| Option | Value | Purpose |
|--------|-------|---------|
| **127.0.0.1:9500 (default)** | `127.0.0.1:9500` | Standard port (recommended) |
| **127.0.0.1:9510 (alt)** | `127.0.0.1:9510` | Alternative port (avoids deadlock issues) |
| **127.0.0.1:8003 (dev)** | `127.0.0.1:8003` | Development/testing port |
| **localhost:9500** | `localhost:9500` | Localhost alias for 9500 |
| **localhost:9510** | `localhost:9510` | Localhost alias for 9510 |

## How to Use

### 1. Open Any Dashboard

Navigate to a dashboard in Grafana (e.g., "G6 Analytics – Infinity v3"):
```
http://127.0.0.1:3002/d/g6-analytics-infinity-v3
```

### 2. Locate the API Server Variable

At the top of the dashboard, you'll see a dropdown labeled **"API Server"**:

```
API Server: [ 127.0.0.1:9500 (default) ▼ ]
```

### 3. Select Your Running API Port

Click the dropdown and select the port where your API server is actually running:

- If running on **9500** → Select `127.0.0.1:9500 (default)`
- If running on **9510** → Select `127.0.0.1:9510 (alt)`
- If running on **8003** → Select `127.0.0.1:8003 (dev)`

### 4. Verify Data Loads

After selecting the correct port:
- Panels should immediately start loading data
- No manual refresh needed (Grafana auto-applies variable changes)
- Check browser console for any remaining connection errors

## Verification

### Check Current API Server Port

```powershell
# See which ports have Python processes listening
Get-NetTCPConnection -LocalPort 9500,9510,8003 -State Listen -ErrorAction SilentlyContinue | 
    Select-Object LocalPort, State, @{Name='PID';Expression={$_.OwningProcess}}
```

### Test API Endpoint Manually

```powershell
# Test health endpoint
Invoke-WebRequest -Uri "http://127.0.0.1:9510/health" -UseBasicParsing

# Test live data endpoint  
Invoke-WebRequest -Uri "http://127.0.0.1:9510/api/live_csv?index=NIFTY&expiry_tag=this_week&offset=0&limit=5"
```

### Inspect Dashboard URLs

To verify the variable is being used:

1. Open any panel in edit mode (click panel → Edit)
2. Go to the **Query** tab
3. Look at the URL field - it should show: `http://${api_server}/api/live_csv?...`
4. The `${api_server}` will be replaced with your selected value at runtime

## Starting API Server on Different Ports

### Port 9500 (Default)

```powershell
.\scripts\obs_start_clean.ps1 -WebPort 9500
```

### Port 9510 (Alternative - Avoids Deadlock)

```powershell
.\scripts\obs_start_clean.ps1 -WebPort 9510
```

Then select `127.0.0.1:9510 (alt)` in the dashboard variable.

### Port 8003 (Development)

```powershell
.\scripts\start_dashboard_api.py --ports 8003
```

Then select `127.0.0.1:8003 (dev)` in the dashboard variable.

## Why Multiple Ports?

### Port 9500
- **Standard default** for most scripts and documentation
- **Recommended** for new installations
- May conflict with some services

### Port 9510  
- **Alternative port** when 9500 has issues
- **Avoids deadlocks** mentioned in history
- Used when port 9500 is occupied or causes conflicts

### Port 8003
- **Development port** for testing
- Separate from production services
- Useful for running multiple API instances

## Troubleshooting

### Dashboard Shows "No Data"

**Cause**: Selected `api_server` doesn't match running API port

**Solution**:
1. Check which port your API is actually on (see verification above)
2. Select matching port in dashboard `API Server` variable
3. Wait for panels to refresh (or refresh manually)

### Dashboard Still Broken After Selection

**Cause**: Grafana caching or API not running

**Solution**:
```powershell
# 1. Verify API is actually running
Get-NetTCPConnection -LocalPort 9500,9510 -State Listen

# 2. Test API directly
Invoke-WebRequest -Uri "http://127.0.0.1:<PORT>/health"

# 3. Hard refresh browser (Ctrl+F5)

# 4. Restart Grafana if needed
Get-Process grafana-server | Stop-Process -Force
.\scripts\obs_start_clean.ps1
```

### Want to Change Default Selection

**Option 1**: Edit dashboard and change default value

1. Dashboard Settings (gear icon) → Variables → `api_server`
2. Change "Default" value to desired port
3. Save dashboard

**Option 2**: Use URL parameter

Add `?var-api_server=127.0.0.1:9510` to dashboard URL:
```
http://127.0.0.1:3002/d/g6-analytics-infinity-v3?var-api_server=127.0.0.1:9510
```

## Summary

✅ **No code changes needed** - variable already exists  
✅ **No JSON editing needed** - use the UI dropdown  
✅ **Works across all dashboards** - variable is standard  
✅ **Port flexibility** - run API on any port without breaking dashboards  
✅ **User-friendly** - just select from dropdown  

The solution is **already implemented and ready to use**. Simply select the correct API server port from the dashboard variable dropdown to match your running service.

## For Script/Automation Use

If you want to provision dashboards with a different default port:

```powershell
# Set environment variable before starting observability stack
$env:G6_API_SERVER_DEFAULT = "127.0.0.1:9510"
.\scripts\obs_start_clean.ps1 -WebPort 9510
```

Or edit the dashboard JSON directly:
```json
{
  "name": "api_server",
  "current": {
    "selected": true,
    "text": "127.0.0.1:9510 (alt)",
    "value": "127.0.0.1:9510"
  }
}
```

---

**Created**: November 27, 2025  
**Status**: Solution already implemented, documentation added
