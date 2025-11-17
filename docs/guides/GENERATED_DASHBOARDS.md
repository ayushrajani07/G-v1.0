# Generated Dashboards - Source & Management

## 📊 What Are Generated Dashboards?

The **11 dashboards** in `grafana/dashboards/generated/` are **automatically created** by the modular dashboard generator script. They are NOT hand-crafted JSON files.

## 🔨 How They're Created

### Generator Script
**Location:** `scripts/gen_dashboards_modular.py`  
**Implementation:** `scripts/gen_dashboards_modular_recovery.py`

### Source of Dashboard Content
Dashboards are generated from:

1. **Metrics Specification** (`docs/metrics_spec.yaml`)
   - Defines metrics, their types, labels
   - Specifies panel definitions for each metric
   - Groups metrics into families

2. **Dashboard Plans** (in generator script)
   - Maps families to dashboards
   - Defines dashboard titles, tags, descriptions

### Current Generated Dashboards

```python
DEFAULT_PLANS = [
    "core_overview"                    # Core system metrics
    "greeks_overview"                  # Options Greeks
    "adaptive_controller"              # Adaptive controller metrics
    "ann_health"                       # ANN health monitoring
    "bus_health"                       # Message bus health
    "system_overview_minimal"          # Minimal system view
    "multi_pane_explorer"              # Explorer (standard)
    "multi_pane_explorer_compact"      # Explorer (compact)
    "multi_pane_explorer_ultra"        # Explorer (detailed)
    "path_forecast_overview"           # Path forecasting
    "contracts_timeseries"             # Contracts data
]
```

## 🎯 How to Regenerate Dashboards

### Full Regeneration
```powershell
# Regenerate all dashboards
python scripts/gen_dashboards_modular.py --output grafana/dashboards/generated

# Verify (no changes)
python scripts/gen_dashboards_modular.py --output grafana/dashboards/generated --verify
```

### Regenerate Single Dashboard
```powershell
# Regenerate only one dashboard
python scripts/gen_dashboards_modular.py --output grafana/dashboards/generated --only bus_health

# Or multiple
python scripts/gen_dashboards_modular.py --output grafana/dashboards/generated --only multi_pane_explorer multi_pane_explorer_compact
```

## 🎨 Key Features

### 1. **Deterministic Generation**
- Panels have stable IDs (hash-based)
- Reproducible across regenerations
- Version control friendly

### 2. **Auto-Synthesis**
Automatically creates panels for:
- **Counter rates** - `rate()` calculations
- **Histogram quantiles** - p95, p99
- **Label splits** - topK breakdowns
- **Cross-metric efficiency** - computed ratios

### 3. **Drift Detection**
```powershell
# Check if generated dashboards are up-to-date
python scripts/gen_dashboards_modular.py --output grafana/dashboards/generated --verify

# Exit code 6 = drift detected (changes needed)
# Exit code 0 = no changes
```

Set `G6_DASHBOARD_DIFF_VERBOSE=1` for detailed change report.

### 4. **Manifest Tracking**
`grafana/dashboards/generated/manifest.json` contains:
- Panel counts per dashboard
- Spec hash (detects metrics changes)
- Generation timestamp

## ⚠️ Important Notes

### DO NOT Edit Generated Dashboards Manually!
**Why?** Changes will be lost on next regeneration.

**Instead:**
1. **Modify metrics spec** (`docs/metrics_spec.yaml`)
2. **Update generator code** (`scripts/gen_dashboards_modular_recovery.py`)
3. **Regenerate** dashboards

### When to Regenerate

Regenerate when:
- ✅ Adding/removing metrics
- ✅ Changing metric definitions
- ✅ Updating panel layouts
- ✅ Modifying dashboard structure
- ✅ After pulling changes that affect metrics

### CI Integration

CI can verify dashboards are up-to-date:
```powershell
python scripts/gen_dashboards_modular.py --output grafana/dashboards/generated --verify
if ($LASTEXITCODE -eq 6) {
    Write-Error "Dashboards out of date - regenerate with gen_dashboards_modular.py"
}
```

## 📂 File Structure

```
scripts/
├── gen_dashboards_modular.py          # Main entrypoint
├── gen_dashboards_modular_recovery.py # Implementation
└── gen_dashboards.py                  # Legacy simple generator

docs/
└── metrics_spec.yaml                  # Metrics definitions

grafana/dashboards/generated/
├── manifest.json                      # Generation metadata
├── adaptive_controller.json           # Generated dashboard
├── ann_health.json                    # Generated dashboard
├── bus_health.json                    # Generated dashboard
├── contracts_timeseries.json          # Generated dashboard
├── core_overview.json                 # Generated dashboard
├── greeks_overview.json               # Generated dashboard
├── multi_pane_explorer.json           # Generated dashboard
├── multi_pane_explorer_compact.json   # Generated dashboard
├── multi_pane_explorer_ultra.json     # Generated dashboard
├── path_forecast_overview.json        # Generated dashboard
└── system_overview_minimal.json       # Generated dashboard
```

## 🔧 Customization

### Add a New Generated Dashboard

1. **Edit the generator** (`scripts/gen_dashboards_modular_recovery.py`):
```python
DEFAULT_PLANS = [
    # ... existing plans ...
    DashboardPlan(
        slug="my_new_dashboard",
        title="My New Dashboard",
        families=["my_metric_family"],
        tags=["custom", "monitoring"]
    ),
]
```

2. **Regenerate:**
```powershell
python scripts/gen_dashboards_modular.py --output grafana/dashboards/generated
```

3. **Add to config:**
```powershell
python scripts/manage_grafana_dashboards.py --list
# If not auto-detected, add to grafana/dashboard_config.json
```

### Modify Existing Dashboard

**Option 1: Change metrics spec**
```yaml
# docs/metrics_spec.yaml
- name: my_metric
  type: counter
  family: core
  panels:
    - title: "My Panel"
      promql: "rate(my_metric[5m])"
      panel_type: "timeseries"
```

**Option 2: Modify generator code**
Edit `scripts/gen_dashboards_modular_recovery.py` functions:
- `_convert_spec_panel()` - Panel conversion
- `_auto_extra_panels()` - Auto-generated panels
- `layout_panels()` - Panel layout

Then regenerate.

## 🆚 Generated vs. Manual Dashboards

| Aspect | Generated | Manual |
|--------|-----------|--------|
| Location | `grafana/dashboards/generated/` | `grafana/dashboards/*.json` |
| Source | Metrics spec + generator | Hand-crafted JSON |
| Editing | Modify spec → regenerate | Direct JSON editing |
| Maintenance | Automatic consistency | Manual updates |
| Best for | System metrics, repetitive | Custom visualizations, complex layouts |

## 📚 See Also

- **Main README:** Dashboard generation section (line 433+)
- **Metrics Spec:** `docs/metrics_spec.yaml`
- **Generator Code:** `scripts/gen_dashboards_modular_recovery.py`
- **Dashboard Management:** `docs/guides/GRAFANA_DASHBOARD_MANAGEMENT.md`

## Quick Commands

```powershell
# Regenerate all
python scripts/gen_dashboards_modular.py --output grafana/dashboards/generated

# Verify up-to-date
python scripts/gen_dashboards_modular.py --output grafana/dashboards/generated --verify

# Regenerate one
python scripts/gen_dashboards_modular.py --output grafana/dashboards/generated --only bus_health

# List all dashboards
python scripts/manage_grafana_dashboards.py --list --folder Generated

# Enable/disable in Grafana
python scripts/manage_grafana_dashboards.py --interactive
```
