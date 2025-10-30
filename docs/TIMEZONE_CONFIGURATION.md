# G6 Platform Timezone Configuration

**Date:** October 28, 2025  
**Status:** Implemented and Active

## Overview

The G6 Platform is configured to display all timestamps in **Indian Standard Time (IST / Asia/Kolkata)** across all frontend interfaces, while maintaining proper UTC timestamps in backend data storage.

## Configuration Layers

### 1. Grafana Server Default (Global)

**Location:** `scripts/auto_stack.ps1`

```powershell
[Environment]::SetEnvironmentVariable('GF_DEFAULT_TIMEZONE','Asia/Kolkata')
```

This sets the default timezone for all Grafana dashboards and panels. Takes effect when Grafana starts.

**Scope:** All dashboards, all users  
**Priority:** Base level (overridden by dashboard-specific settings)

### 2. Dashboard-Level Timezone

**Location:** Individual dashboard JSON files

```json
{
  "timezone": "Asia/Kolkata",
  ...
}
```

Each dashboard can explicitly set its timezone. This overrides the Grafana server default.

**Scope:** Specific dashboard  
**Priority:** Overrides server default

### 3. Panel-Level Time Display

Grafana automatically applies the dashboard timezone to:
- Time series X-axis labels
- Table columns with time data
- Stat panels showing timestamps
- Annotations and alerts

## Backend Data Storage

### CSV Files

**Location:** `data/g6_data/{index}/{expiry_tag}/{offset}/`

CSV files store timestamps in **Unix epoch milliseconds** which are timezone-agnostic. The `time_str` field shows ISO 8601 format with explicit timezone:

```csv
time,ts,time_str,tp,avg_tp,ce,pe,index_price
1761653160000,1761653160000,"2025-10-28T12:06:00Z",91.95,116.12,49.3,42.65,25847.75
```

**Important:** The `time_str` field uses `Z` suffix (UTC), but timestamps are actually in IST. This is a known quirk of the data generation process.

### InfluxDB

InfluxDB stores all timestamps internally as UTC (nanoseconds since epoch). The Grafana Prometheus/InfluxDB datasource automatically converts these to the configured display timezone.

## Time Range Filters

When Grafana dashboards use time range filters like `"from": "now-6h"`, the "now" refers to:

1. **Browser local time** if timezone is set to "browser"
2. **Asia/Kolkata (IST)** if timezone is set to "Asia/Kolkata"
3. **UTC** if timezone is set to "UTC" or empty

## Applying Changes

### Update Grafana Server Timezone

1. Edit `scripts/auto_stack.ps1` (already done)
2. **Restart Grafana** for changes to take effect:

```powershell
# Stop Grafana
Get-Process grafana* | Stop-Process -Force

# Restart stack
.\scripts\auto_stack.ps1 -StartGrafana $true
```

### Update All Dashboards

Run the bulk update script:

```powershell
python scripts\set_dashboard_timezone.py
```

This updates all dashboard JSON files in:
- `grafana/dashboards/*.json`
- `grafana/dashboards/generated/*.json`

### Update Single Dashboard

Edit the JSON file and set:

```json
"timezone": "Asia/Kolkata"
```

Or use Grafana UI:
1. Open dashboard
2. Settings (gear icon)
3. General → Timezone → Select "Asia/Kolkata"
4. Save dashboard

## Verification

### Check Grafana Server Timezone

```powershell
$env:GF_DEFAULT_TIMEZONE
# Should output: Asia/Kolkata
```

### Check Dashboard Timezone

Open any dashboard JSON file and verify:

```powershell
Get-Content grafana\dashboards\generated\analytics_infinity_v3.json | Select-String '"timezone"'
```

Expected output:
```json
  "timezone": "Asia/Kolkata",
```

### Test Time Display

1. Open Grafana dashboard
2. Check X-axis labels on time series
3. Hover over data points
4. Verify times match IST (UTC+5:30)

## Troubleshooting

### Dashboard Still Shows UTC

**Cause:** Grafana not restarted after configuration change

**Solution:**
```powershell
Get-Process grafana* | Stop-Process -Force
.\scripts\auto_stack.ps1 -StartGrafana $true
```

### Time Range "No Data" Issues

**Cause:** Time range filter doesn't match data timestamps

**Solution:** 
- Expand time range to "Last 12 hours" or "Today"
- Check CSV data timestamps match expected IST values
- Verify `from_ms` and `to_ms` query parameters in API calls

### Mixed Timezones in Dashboard

**Cause:** Dashboard timezone not explicitly set, falling back to browser timezone

**Solution:**
```powershell
python scripts\set_dashboard_timezone.py
```

## Timezone Values

Valid timezone strings for Grafana:

- `Asia/Kolkata` - Indian Standard Time (IST) **[Current]**
- `UTC` - Coordinated Universal Time
- `browser` - Use browser's local timezone
- `America/New_York` - Eastern Time
- `Europe/London` - British Time
- `Asia/Tokyo` - Japan Standard Time

Full list: [IANA Time Zone Database](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)

## Related Files

- `scripts/auto_stack.ps1` - Grafana startup with timezone config
- `scripts/set_dashboard_timezone.py` - Bulk dashboard timezone updater
- `grafana/dashboards/**/*.json` - Dashboard definitions
- `provisioning/datasources/g6_datasources.yml` - Datasource configs (timezone-agnostic)

## Future Improvements

1. **Add timezone parameter to Web API** - Allow client to request specific timezone in responses
2. **Dashboard timezone selector** - Add template variable for user timezone preference
3. **Multi-timezone support** - Display multiple timezones side-by-side for global teams

---

**Last Updated:** 2025-10-28  
**Author:** G6 Platform Team
