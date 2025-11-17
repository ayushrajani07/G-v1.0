# Dashboard Inventory Summary

## 📊 Complete Dashboard Inventory

**Total:** 71 dashboard files across 2 locations

### Location 1: Project Repository (28 dashboards)
**Path:** `C:\Users\Asus\Desktop\g6_reorganized\grafana\dashboards\`

All 28 dashboards are tracked in `dashboard_config.json` and managed by the dashboard management system.

#### Root Level (6 dashboards)
- `advisor_detail.json` → **Advisor Detail**
- `advisor_unified_health.json` → **Advisor Unified Health**
- `analytics_pct_change.json` → **Analytics % Change**
- `contracts_pct_change.json` → **Contracts % Change - All Indices**
- `g6_orchestrator_cycle_performance.json` → **G6 Orchestrator Cycle Performance**
- `path_forecast_metrics.json` → **Path Forecast Metrics**

#### ML Folder (8 dashboards)
- `ml_conformal_alert_overview.json` → **ML Conformal Alert Overview**
- `ml_conformal_metrics.json` → **ML Conformal Metrics**
- `ml_ensemble_monitoring.json` *(root level only - not in ml/ folder)*
- `ml_ensemble_overview.json` → **Ensemble Consensus & Disagreement (TP)**
- `ml_hybrid_vs_quantile.json` → **Hybrid vs Quantile (TP)**
- `ml_move_signals.json` → **Move Signals (TP)**
- `ml_move_trends.json` → **Move Signal Trends**
- `ml_prediction_bands.json` → **ML Prediction Bands**

#### Generated Folder (11 dashboards - Auto-generated)
These are created by `scripts/gen_dashboards_modular.py`:
- `adaptive_controller.json` → **Adaptive Controller**
- `ann_health.json` → **ANN Health**
- `bus_health.json` → **Bus Health**
- `contracts_timeseries.json` → **Contracts – Index / OI / Volume (Time Series)**
- `core_overview.json` → **Core Overview**
- `greeks_overview.json` → **Greeks Overview**
- `manifest.json` *(metadata, not a dashboard)*
- `multi_pane_explorer.json` → **Multi-Pane Explorer**
- `multi_pane_explorer_compact.json` → **Multi-Pane Explorer (Compact)**
- `multi_pane_explorer_ultra.json` → **Multi-Pane Explorer (Ultra)**
- `path_forecast_overview.json` → **Path Forecast Overview**
- `system_overview_minimal.json` → **System Overview (Minimal)**

#### Miscellaneous Folder (4 dashboards - Disabled)
- `advisor_detail.json` *(duplicate)*
- `advisor_unified_health.json` *(duplicate)*
- `g6_essential_metrics.json`
- `g6_health_check.json`

#### Snippets Folder (1 file)
- `pf_meta_metrics_example.json` → **PF Meta Metrics (Example)** *(code example)*

---

### Location 2: External GrafanaData (43 dashboards)
**Path:** `C:\GrafanaData\dashboards_live\`

These are external/development dashboards not in version control.

#### Category Breakdown

**✅ Also in Config (8 dashboards)**
These match dashboards in the project:
- `adaptive_controller.json` → **Adaptive Controller** (2.2 KB)
- `bus_health.json` → **Bus Health** (6.1 KB)
- `core_overview.json` → **Core Overview** (10.0 KB)
- `greeks_overview.json` → **Greeks Overview** (2.9 KB)
- `multi_pane_explorer.json` → **Multi-Pane Explorer** (7.3 KB)
- `multi_pane_explorer_compact.json` → **Multi-Pane Explorer (Compact)** (6.6 KB)
- `multi_pane_explorer_ultra.json` → **Multi-Pane Explorer (Ultra)** (6.1 KB)
- `system_overview_minimal.json` → **System Overview (Minimal)** (10.0 KB)

**📊 External Only (32 dashboards)**
Dashboards unique to this location:
- `analytics.json` → **G6 Analytics – Infinity v3** (127.3 KB) - *Large analytics dashboard*
- `analytics_base.json` (3.6 KB) - *No title in file*
- `bus_stream.json` → **Bus & Stream** (17.0 KB)
- `column_store.json` → **Column Store** (22.2 KB)
- `contracts_from_csv.json` → **G6 Contracts – Live from CSV (Infinity)** (37.0 KB)
- `data_quality.json` → **Data Quality & Staleness** (8.8 KB)
- `emission_pipeline.json` → **Emission Pipeline** (9.9 KB)
- `g6_analytics_infinity_v3.json` → **G6 Analytics – Infinity v3** (245.8 KB) - *Very large*
- `g6_analytics_infinity_v3_patched.json` → **G6 Analytics – Infinity v3** (254.9 KB) - *Very large*
- `g6_grouped_expiry_overlays.json` → **G6 Overlays – Grouped Expiry Toggles** (6.9 KB)
- `g6_live_from_csv.json` (12.5 KB) - *No title in file*
- `g6_live_from_csv_fixed.json` → **G6 Overlays (Live from CSV - Fixed)** (21.5 KB)
- `g6_live_from_csv_simple.json` → **G6 Overlays – Live from CSV (Infinity)** (61.5 KB)
- `g6_live_simple_working.json` → **G6 Live - Simple Working** (6.7 KB)
- `governance.json` → **Metrics Governance** (13.3 KB)
- `health_core.json` → **Core Health** (23.4 KB)
- `lifecycle_storage.json` → **Lifecycle & Storage** (31.3 KB)
- `minimal_test_fixed.json` → **Minimal Test - Fixed** (4.6 KB)
- `multi_pane_explorer_minimal.json` → **Multi-Pane Explorer (Minimal)** (37.5 KB)
- `nifty_final.json` → **NIFTY Final Test** (2.7 KB)
- `nifty_fresh_import.json` → **NIFTY Live (Fresh Import)** (4.1 KB)
- `nifty_table.json` → **NIFTY Table Test** (0.9 KB)
- `nifty_working.json` → **NIFTY Working Test** (1.6 KB)
- `option_chain.json` → **Option Chain** (18.6 KB)
- `overlays.json` → **Overlays - All Indices** (37.3 KB)
- `overlays_new.json` (1.1 KB) - *No title in file*
- `overlays_v11.json` (2.7 KB) - *No title in file*
- `panels_efficiency.json` → **Panels Efficiency** (14.8 KB)
- `panels_summary.json` → **Panels Summary** (11.4 KB)
- `price_overlay.json` → **Price Overlay Explorer** (3.0 KB)
- `provider_ingestion.json` → **Provider / Ingestion** (24.3 KB)
- `sse_latency.json` → **SSE Latency & Trace** (4.3 KB)

**🗂️ Backup Files (3 dashboards)**
- `g6_live_from_csv_BACKUP_120253.json` → **G6 Analytics – Infinity v3** (61.4 KB)
- `overlays_backup.json` → **Overlays** (3.3 KB)
- `overlays_v13_backup.json` → **Overlays - All Indices** (26.0 KB)

---

## 🎯 Key Insights

### 1. Dashboard Overlap
**8 dashboards** exist in both locations:
- These are likely generated dashboards that were copied to GrafanaData for testing
- Consider consolidating to avoid confusion

### 2. Large Dashboards
**3 dashboards** over 100 KB:
- analytics.json (127.3 KB)
- g6_analytics_infinity_v3.json (245.8 KB)
- g6_analytics_infinity_v3_patched.json (254.9 KB)

These may contain many panels or large configurations.

### 3. Test/Working Versions
Several dashboards with development suffixes:
- `*_working`, `*_fixed`, `*_simple`, `*_final`
- These suggest active development/testing
- Consider archiving old versions

### 4. External-Only Dashboards
**32 unique dashboards** in GrafanaData not in the project:
- May be experimental or development dashboards
- Consider adding important ones to the project repository
- Consider archiving or removing obsolete ones

---

## 📋 Recommendations

### 1. Clean Up GrafanaData
```powershell
# Archive backup files
Move-Item "C:\GrafanaData\dashboards_live\*backup*.json" "C:\GrafanaData\dashboards_archive\"

# Review and consolidate test versions
# Keep only the final working versions
```

### 2. Add Important External Dashboards to Project
If dashboards like `analytics.json`, `overlays.json`, or `option_chain.json` are important:
```powershell
# Copy to project
Copy-Item "C:\GrafanaData\dashboards_live\analytics.json" "grafana\dashboards\"

# Add to config
python scripts/manage_grafana_dashboards.py --interactive
# Then enable in the menu
```

### 3. Consolidate Duplicates
For the 8 dashboards that exist in both locations:
- Determine which is the "source of truth"
- Generated dashboards should come from project
- Remove copies from GrafanaData

### 4. Document External Location
Update Grafana provisioning to include GrafanaData:
```yaml
# provisioning/dashboards/dashboards.yml
providers:
  - name: External Dashboards
    type: file
    options:
      path: "C:/GrafanaData/dashboards_live"
```

---

## 🔧 Tools Available

### Find All Dashboards
```powershell
# Full scan including external
python scripts/find_grafana_dashboards.py

# Just external
python scripts/find_grafana_dashboards.py --external
```

### Manage Project Dashboards
```powershell
# Interactive management
python scripts/manage_grafana_dashboards.py --interactive

# List all
python scripts/manage_grafana_dashboards.py --list
```

### Compare Locations
```powershell
# Get list of dashboards in each location
$project = Get-ChildItem "grafana\dashboards" -Recurse -Filter "*.json" | Select-Object -ExpandProperty BaseName
$external = Get-ChildItem "C:\GrafanaData\dashboards_live" -Filter "*.json" | Select-Object -ExpandProperty BaseName

# Find external-only
$external | Where-Object { $_ -notin $project }

# Find duplicates
$external | Where-Object { $_ -in $project }
```

---

## 📈 Statistics

| Location | Count | Total Size | Avg Size |
|----------|-------|------------|----------|
| Project (all folders) | 38 files | ~1.2 MB | 31.6 KB |
| Project (unique) | 28 dashboards | ~800 KB | 28.6 KB |
| GrafanaData | 43 dashboards | ~1.4 MB | 32.6 KB |
| **Total Unique** | **63 dashboards** | **~2.2 MB** | **35.0 KB** |

*Note: Total unique = 71 files - 8 duplicates = 63 unique dashboards*

---

## 📝 Next Steps

1. ✅ Review external dashboards and identify important ones
2. ✅ Archive backup files and test versions
3. ✅ Add important external dashboards to project
4. ✅ Update Grafana provisioning if needed
5. ✅ Document which dashboards are actively used
6. ✅ Consider archiving obsolete dashboards

Use the dashboard finder tool periodically to keep track of all dashboard locations!
