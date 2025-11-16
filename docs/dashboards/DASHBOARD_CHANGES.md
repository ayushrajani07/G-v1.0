# Dashboard Configuration Changes

**Date:** October 25, 2025  
**Change Type:** Dashboard provisioning simplification  
**Impact:** Removes auto-generated dashboards, adds single custom essential metrics dashboard

---

## Summary

Removed mandatory auto-generated Grafana dashboards and replaced them with a single focused custom dashboard (`g6_essential_metrics.json`) containing only the essential production metrics.

## Changes Made

### 1. **Disabled Auto-Generated Dashboard Provisioning**

**File:** `scripts/auto_stack.ps1` (lines ~449-460)

**Change:**
```powershell
# OLD: Provisioned all dashboards from generated/ directory
$exclude = @('manifest.json','g6_spec_panels_dashboard.json','g6_generated_spec_dashboard.json')
Get-ChildItem -Path $repoDashGen -Filter *.json -File |
  Where-Object { $exclude -notcontains $_.Name } |
  ForEach-Object { Copy-Item ... }

# NEW: Skip ALL generated dashboards
$exclude = @('manifest.json','g6_spec_panels_dashboard.json','g6_generated_spec_dashboard.json','*.json')
# Commented out provisioning of generated/ directory entirely
```

**Rationale:** Auto-generated dashboards created noise and were not actively used for production monitoring. The generator (`scripts/gen_dashboards_modular_recovery.py`) still exists but dashboards are no longer auto-provisioned.

### 2. **Created Custom Essential Metrics Dashboard**

**File:** `grafana/dashboards/g6_essential_metrics.json`

**Panels:**

| # | Panel Title | Metric(s) | Type | Description |
|---|-------------|-----------|------|-------------|
| 1 | Kite API Success Rate | `g6_api_success_rate_percent` | Gauge | Shows API call success rate (0-100%) with thresholds: red <90, yellow 90-95, green >95 |
| 2 | Collection Cycles Completed | `rate(g6_collection_cycles[5m])` | Time Series | Rate of collection cycles per second |
| 3 | Active Indices | `sum by (index) (g6_options_collected)` | Table | Lists all indices with option data collection active |
| 4 | ATM Strike & Offset Range | `g6_index_atm_strike` | Table | ATM strike prices per index (basis for offset ranges) |
| 5 | Option Instruments Collected | `sum by (index) (g6_options_collected)` | Time Series | Total option instruments collected per index over time |
| 6 | ATM Option Instruments | `sum by (index, expiry) (g6_options_collected{expiry=~".*0[CPMN]E"})` | Time Series (Bars) | Option instruments at offset=0 (ATM) by index |
| 7 | CSV Files Created | `g6_csv_files_created_total` | Gauge | Total CSV files written |
| 8 | Total CSV Records Written | `g6_csv_records_written_total` | Gauge | Total CSV record count |
| 9 | Errors, Warnings & Exceptions | `rate(g6_collection_errors_total[5m])`<br>`rate(g6_api_errors_total[5m])`<br>`rate(g6_network_errors_total[5m])`<br>`rate(g6_data_errors_total[5m])` | Time Series | All production errors/warnings with distinct colors: Collection (red), API (orange), Network (yellow), Data (purple) |

**Dashboard Properties:**
- **UID:** `g6_essential_metrics`
- **Refresh:** 5s
- **Time Range:** Last 15 minutes
- **Tags:** `g6`, `essential`, `custom`
- **Datasource:** Prometheus (UID: `PROM`)

### 3. **Preserved Legacy Dashboards**

**Location:** `grafana/dashboards/generated/`

**Status:** Still exist on disk but **NOT provisioned** to Grafana by default.

**Dashboards retained (not provisioned):**
- `core_overview.json`
- `greeks_overview.json`
- `adaptive_controller.json`
- `bus_health.json`
- `system_overview.json`
- `multi_pane_explorer*.json`
- `option_chain.json`
- `governance.json`
- ~20 other generated dashboards

**Access:** Users can manually import these if needed via Grafana UI (Dashboards → Import → Upload JSON).

---

## Migration Path

### For Existing Users

1. **Stop Grafana:**
   ```powershell
   & 'c:\Users\Asus\Desktop\g6_reorganized\scripts\obs_stop.ps1'
   ```

2. **Clear Grafana database (optional, removes old dashboards):**
   ```powershell
   Remove-Item 'C:\GrafanaData\data\grafana.db' -Force
   ```

3. **Restart with new provisioning:**
   ```powershell
   & 'c:\Users\Asus\Desktop\g6_reorganized\scripts\auto_stack.ps1' -StartGrafana -OpenBrowser
   ```

4. **Verify:** Only `G6 Essential Metrics` dashboard should be provisioned automatically.

### To Re-Enable Specific Generated Dashboards

If you need a specific generated dashboard:

1. **Option A - Modify exclude list** in `scripts/auto_stack.ps1`:
   ```powershell
   # Change line ~456 from:
   $exclude = @('manifest.json','g6_spec_panels_dashboard.json','g6_generated_spec_dashboard.json','*.json')
   
   # To (example: allow core_overview.json):
   $exclude = @('manifest.json','g6_spec_panels_dashboard.json','g6_generated_spec_dashboard.json',
                '!(core_overview.json)')
   ```

2. **Option B - Manual import:**
   - Open Grafana → Dashboards → Import
   - Upload `grafana/dashboards/generated/<dashboard_name>.json`

---

## Metrics Covered

### Included in Essential Dashboard

✅ **Kite API Success Rate** (`g6_api_success_rate_percent`)  
✅ **Collection Cycles** (`g6_collection_cycles`)  
✅ **Indices Names** (via `g6_options_collected` labels)  
✅ **Offset Range** (via `g6_index_atm_strike`)  
✅ **Option Instrument Counts** (by index, via `g6_options_collected`)  
✅ **ATM Instruments** (offset=0, via expiry label filtering)  
✅ **CSV Files Created** (`g6_csv_files_created_total`)  
✅ **CSV Records Written** (`g6_csv_records_written_total`)  
✅ **All Errors/Warnings** (`g6_collection_errors`, `g6_api_errors_total`, `g6_network_errors_total`, `g6_data_errors_total`)

### Not Included (Available in Generated Dashboards)

- Greeks analytics (`greeks_overview.json`)
- Adaptive controller metrics (`adaptive_controller.json`)
- Panel integrity checks (`bus_health.json`)
- Detailed option chain visualization (`option_chain.json`)
- Governance/compliance metrics (`governance.json`)
- SSE streaming metrics (`sse_latency.json`)
- Column store pipeline (`column_store.json`)

---

## Benefits

1. **Reduced Complexity:** Single focused dashboard instead of 20+ auto-generated ones
2. **Faster Load Times:** Grafana startup faster without provisioning many dashboards
3. **Production Focus:** Only essential metrics for day-to-day monitoring
4. **Maintainability:** Custom dashboard can be hand-tuned without generator conflicts
5. **Preserved Flexibility:** Generated dashboards still available for manual import

---

## Rollback

To restore auto-generated dashboard provisioning:

1. Edit `scripts/auto_stack.ps1` line ~456:
   ```powershell
   # Change:
   $exclude = @('manifest.json','g6_spec_panels_dashboard.json','g6_generated_spec_dashboard.json','*.json')
   
   # Back to:
   $exclude = @('manifest.json','g6_spec_panels_dashboard.json','g6_generated_spec_dashboard.json')
   ```

2. Uncomment lines ~458-462 (dashboard copy loop)

3. Restart Grafana

---

## Related Files

- **Custom Dashboard:** `grafana/dashboards/g6_essential_metrics.json`
- **Provisioning Script:** `scripts/auto_stack.ps1`
- **Generated Dashboards (archived):** `grafana/dashboards/generated/*.json`
- **Generator Script:** `scripts/gen_dashboards_modular_recovery.py` (still functional if needed)

---

## Questions?

- **Q:** Can I still generate dashboards from the spec?
  - **A:** Yes, run `python scripts/gen_dashboards_modular_recovery.py` to regenerate. Import manually to Grafana.

- **Q:** What if I need more metrics?
  - **A:** Edit `grafana/dashboards/g6_essential_metrics.json` directly or create additional custom dashboards in the same directory.

- **Q:** Are Prometheus datasources still auto-configured?
  - **A:** Yes, `auto_stack.ps1` still provisions Prometheus datasource automatically (UID: `PROM`).

---

**Change completed as part of Phase 2 Optimization follow-up.**
