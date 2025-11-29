# Dashboard Port Selection - Quick Start Guide

## ✅ SOLUTION ALREADY IMPLEMENTED

Your dashboards **already support** dynamic API server selection! You don't need to edit any files.

## Quick Fix (30 seconds)

### Step 1: Check Which Port Your API Is On

```powershell
Get-NetTCPConnection -LocalPort 9500,9510,8003 -State Listen -ErrorAction SilentlyContinue
```

### Step 2: Open Grafana Dashboard

```
http://127.0.0.1:3002
```

### Step 3: Select Matching Port

At the top of ANY dashboard, find the **"API Server"** dropdown and select:

- `127.0.0.1:9500 (default)` ← if your API is on 9500
- `127.0.0.1:9510 (alt)` ← if your API is on 9510  
- `127.0.0.1:8003 (dev)` ← if your API is on 8003

**That's it!** Panels will immediately start loading data.

---

## Start API on Specific Port

### For Port 9510 (Avoids Deadlock Issues)

```powershell
.\scripts\obs_start_clean.ps1 -WebPort 9510
```

Then in Grafana dashboards, select `127.0.0.1:9510 (alt)` from the **API Server** dropdown.

### For Port 9500 (Default)

```powershell
.\scripts\obs_start_clean.ps1 -WebPort 9500
```

Then in Grafana dashboards, select `127.0.0.1:9500 (default)`.

---

## How It Works

- All dashboard URLs use `http://${api_server}/api/...` 
- The `${api_server}` variable is substituted at runtime
- No JSON editing required
- Works across all 40+ dashboards

---

## Troubleshooting

**Dashboard shows "No Data"?**

1. Verify API is running: `Get-NetTCPConnection -LocalPort 9500,9510 -State Listen`
2. Check API health: `Invoke-WebRequest http://127.0.0.1:9510/health`
3. Select correct port in dashboard **API Server** dropdown
4. Hard refresh browser (Ctrl+F5)

---

## Full Documentation

- **Complete guide**: `docs/API_SERVER_SELECTION.md`
- **Original port fix**: `docs/DASHBOARD_PORT_FIX.md`

**Status**: ✅ Feature already exists, just use the dashboard variable dropdown!
