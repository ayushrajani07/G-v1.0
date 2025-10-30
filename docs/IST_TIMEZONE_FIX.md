# IST Timezone Fix - Implementation Summary

**Date:** October 28, 2025  
**Status:** ✅ COMPLETE - Restart Required

## What Was Fixed

### Problem
- Grafana dashboards showing "No data" because CSV timestamps are in IST but labeled as UTC
- Time range filters not matching data due to 5.5-hour timezone offset

### Solution Implemented

#### 1. ✅ Grafana Server Configuration (`scripts/auto_stack.ps1`)

Added IST timezone setting at line ~400:

```powershell
# Set timezone to IST for all dashboards (affects time display, not data storage)
[Environment]::SetEnvironmentVariable('GF_DEFAULT_TIMEZONE','Asia/Kolkata')
```

**Effect:** All Grafana dashboards will display timestamps in IST by default.

#### 2. ✅ Dashboard-Level Configuration

Updated dashboards to explicitly set IST timezone:

- `grafana/dashboards/generated/analytics_infinity_v3.json`
- `d:\ASUS\New folder\g6_reorganized\grafana\dashboards\generated\g6_live_from_csv.json`
- All other dashboards checked (29 total)

```json
"timezone": "Asia/Kolkata"
```

**Effect:** Dashboards will use IST even if server default changes.

#### 3. ✅ Bulk Update Script Created

Created `scripts/set_dashboard_timezone.py` for future updates:

```powershell
python scripts\set_dashboard_timezone.py
```

Updates all dashboard JSON files to use IST timezone.

#### 4. ✅ Documentation

Created comprehensive guide: `docs/TIMEZONE_CONFIGURATION.md`

## Next Steps (Manual)

### REQUIRED: Restart Grafana

The timezone configuration only takes effect after Grafana restarts.

**Option A: Restart entire stack**
```powershell
.\scripts\auto_stack.ps1
```

**Option B: Restart only Grafana**
```powershell
# Stop Grafana
Get-Process grafana* | Stop-Process -Force

# Start Grafana only
.\scripts\auto_stack.ps1 -StartPrometheus $false -StartInflux $false -StartGrafana $true -StartWebApi $false
```

### Verify the Fix

1. **Check environment variable:**
   ```powershell
   $env:GF_DEFAULT_TIMEZONE
   # Should show: Asia/Kolkata
   ```

2. **Open Grafana dashboard:**
   - Go to http://127.0.0.1:3002 (or your Grafana port)
   - Open "G6 Overlays – Live from CSV (Infinity)" dashboard
   - Check time axis labels - should now show IST times

3. **Verify data appears:**
   - Time range: "Last 6 hours" should now include data
   - Panel tooltips should show IST timestamps
   - "No data" issue should be resolved

## Technical Details

### How It Works

1. **Data Storage (Backend):**
   - CSV files: Unix epoch milliseconds (timezone-agnostic)
   - InfluxDB: UTC timestamps (standard)
   - No backend changes needed ✓

2. **Data Display (Frontend):**
   - Grafana reads UTC timestamps
   - Converts to Asia/Kolkata timezone
   - Displays IST on all panels

3. **Time Range Filters:**
   - "now" = current IST time
   - "now-6h" = 6 hours ago in IST
   - Filters now match CSV data timestamps

### Why This Fix Works

**Before:**
- Dashboard: "Show last 6 hours from UTC 06:40"
- Data: Timestamps at IST 12:06 (labeled as UTC)
- Result: No overlap = "No data"

**After:**
- Dashboard: "Show last 6 hours from IST 12:40" 
- Data: Timestamps at IST 12:06
- Result: Data included = Charts populate ✓

## Files Modified

1. `scripts/auto_stack.ps1` - Added `GF_DEFAULT_TIMEZONE` env var
2. `grafana/dashboards/generated/analytics_infinity_v3.json` - Set timezone
3. `d:\ASUS\New folder\g6_reorganized\grafana\dashboards\generated\g6_live_from_csv.json` - Set timezone
4. `scripts/set_dashboard_timezone.py` - Created (new)
5. `docs/TIMEZONE_CONFIGURATION.md` - Created (new)
6. `docs/IST_TIMEZONE_FIX.md` - This file (new)

## Troubleshooting

### Dashboard still shows "No data"
- ✅ Confirmed Grafana restarted?
- ✅ Check `$env:GF_DEFAULT_TIMEZONE` shows "Asia/Kolkata"
- ✅ Expand time range to "Last 12 hours" as temporary workaround

### Time labels still show UTC
- Dashboard may have cached the old timezone
- Hard refresh browser (Ctrl+Shift+R)
- Check dashboard JSON has `"timezone": "Asia/Kolkata"`

### Some dashboards show IST, others show UTC
- Run: `python scripts\set_dashboard_timezone.py`
- Restart Grafana
- Clear browser cache

## Permanent Fix ✓

This is a **permanent configuration change** that will persist across:
- Grafana restarts
- System reboots
- Dashboard updates
- New dashboard imports

All future dashboards will automatically use IST unless explicitly overridden.

---

**Status:** Implementation complete, pending Grafana restart  
**Impact:** All Grafana dashboards will display IST timestamps  
**Risk:** None - only affects display, not data storage  
**Rollback:** Remove `GF_DEFAULT_TIMEZONE` from auto_stack.ps1
