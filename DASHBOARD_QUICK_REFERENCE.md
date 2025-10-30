# G6 Essential Metrics Dashboard - Quick Reference

**Dashboard UID:** `g6_essential_metrics`  
**URL:** `http://127.0.0.1:3002/d/g6_essential_metrics`  
**Refresh Rate:** 5 seconds  
**Time Range:** Last 15 minutes

---

## Panel Descriptions

### 1. **Kite API Success Rate** (Gauge)
- **Metric:** `g6_api_success_rate_percent`
- **Range:** 0-100%
- **Thresholds:**
  - 🔴 Red: < 90%
  - 🟡 Yellow: 90-95%
  - 🟢 Green: > 95%
- **Purpose:** Monitor Kite Connect API reliability

### 2. **Collection Cycles Completed** (Time Series)
- **Metric:** `rate(g6_collection_cycles[5m])`
- **Unit:** Cycles per second
- **Purpose:** Track collection cycle frequency over time

### 3. **Active Indices** (Table)
- **Query:** `sum by (index) (g6_options_collected)`
- **Columns:**
  - Index name (NIFTY, BANKNIFTY, FINNIFTY, SENSEX)
  - Options count (total instruments)
- **Purpose:** See which indices have active data collection

### 4. **ATM Strike & Offset Range** (Table)
- **Metric:** `g6_index_atm_strike`
- **Columns:**
  - Index name
  - ATM Strike price
- **Purpose:** View current at-the-money strikes (basis for offset calculations)

### 5. **Option Instruments Collected** (Time Series)
- **Query:** `sum by (index) (g6_options_collected)`
- **Legend:** Shows last value per index
- **Purpose:** Track total option instruments collected per index over time

### 6. **ATM Option Instruments** (Bars/Time Series)
- **Query:** `sum by (index, expiry) (g6_options_collected{expiry=~".*0[CPMN]E"})`
- **Filter:** Only options at offset=0 (ATM)
- **Display:** Stacked bars
- **Purpose:** See ATM option counts separately from OTM

### 7. **CSV Files Created** (Gauge)
- **Metric:** `g6_csv_files_created_total`
- **Unit:** Files
- **Purpose:** Total CSV files written since process start

### 8. **Total CSV Records Written** (Gauge)
- **Metric:** `g6_csv_records_written_total`
- **Unit:** Records
- **Purpose:** Total CSV record count written

### 9. **Errors, Warnings & Exceptions** (Time Series)
- **Queries:**
  - 🔴 Collection Errors: `rate(g6_collection_errors_total[5m])` (by index + type)
  - 🟠 API Errors: `rate(g6_api_errors_total[5m])`
  - 🟡 Network Errors: `rate(g6_network_errors_total[5m])`
  - 🟣 Data Errors: `rate(g6_data_errors_total[5m])`
- **Legend:** Shows last, max, mean per error type
- **Purpose:** Comprehensive error monitoring for production

---

## Metrics Reference

| Dashboard Panel | Prometheus Metric | Type | Labels |
|----------------|-------------------|------|--------|
| API Success Rate | `g6_api_success_rate_percent` | Gauge | none |
| Collection Cycles | `g6_collection_cycles` | Counter | none |
| Active Indices | `g6_options_collected` | Gauge | `index`, `expiry` |
| ATM Strike | `g6_index_atm_strike` | Gauge | `index` |
| CSV Files | `g6_csv_files_created_total` | Counter | none |
| CSV Records | `g6_csv_records_written_total` | Counter | none |
| Collection Errors | `g6_collection_errors_total` | Counter | `index`, `error_type` |
| API Errors | `g6_api_errors_total` | Counter | none |
| Network Errors | `g6_network_errors_total` | Counter | none |
| Data Errors | `g6_data_errors_total` | Counter | none |

---

## Common Operations

### Access Dashboard
```
http://127.0.0.1:3002/d/g6_essential_metrics
```

### Restart Grafana with New Dashboard
```powershell
& 'scripts\auto_stack.ps1' -StartGrafana -OpenBrowser
```

### Clear Old Dashboards
```powershell
# Stop Grafana first
& 'scripts\obs_stop.ps1'

# Remove database
Remove-Item 'C:\GrafanaData\data\grafana.db' -Force

# Restart
& 'scripts\auto_stack.ps1' -StartGrafana -OpenBrowser
```

### Edit Dashboard
1. Open `grafana/dashboards/g6_essential_metrics.json`
2. Modify panel configurations
3. Restart Grafana to reload

### Add More Metrics
Example: Add memory usage panel:
```json
{
  "datasource": {"type": "prometheus", "uid": "PROM"},
  "targets": [{
    "expr": "g6_memory_usage_mb",
    "refId": "A"
  }],
  "title": "Memory Usage (MB)",
  "type": "gauge"
}
```

---

## Troubleshooting

### Dashboard Not Showing
- **Check:** Grafana running? `http://127.0.0.1:3002/api/health`
- **Check:** Dashboard file exists? `ls grafana/dashboards/g6_essential_metrics.json`
- **Check:** Provisioning enabled in `auto_stack.ps1` (not using `-SkipProvisioning`)

### No Data in Panels
- **Check:** Prometheus running? `http://127.0.0.1:9091/-/ready`
- **Check:** Metrics server running? `http://127.0.0.1:9108/metrics`
- **Check:** Datasource configured in Grafana → Configuration → Data Sources

### Panels Show "No Data"
- **Reason:** Metrics not emitted yet (process just started)
- **Wait:** Run 1-2 collection cycles, panels will populate
- **Verify:** Check `http://127.0.0.1:9108/metrics` for metric presence

---

## Related Documentation

- **Migration Guide:** `DASHBOARD_CHANGES.md`
- **Metrics Catalog:** `docs/METRICS_CATALOG.md`
- **Metrics Reference:** `docs/METRICS.md`
- **Auto Stack Script:** `scripts/auto_stack.ps1`

---

**Dashboard Version:** 1.0  
**Created:** October 25, 2025  
**Purpose:** Essential production monitoring (replaces 20+ auto-generated dashboards)
