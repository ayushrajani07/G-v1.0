# Grafana Dashboard Management

Simple system to show/hide dashboards in Grafana menu using configuration.

## Quick Start

### List All Dashboards
```bash
python scripts/manage_grafana_dashboards.py --list
```

### Enable a Dashboard
```bash
python scripts/manage_grafana_dashboards.py --enable analytics_pct_change
```

### Disable a Dashboard
```bash
python scripts/manage_grafana_dashboards.py --disable miscellaneous_dashboards
```

### Archive a Dashboard (Preserve but Hide)
```bash
python scripts/manage_grafana_dashboards.py --archive old_dashboard_v1
```

### Unarchive a Dashboard
```bash
python scripts/manage_grafana_dashboards.py --unarchive old_dashboard_v1
```

### List Archived Dashboards
```bash
python scripts/manage_grafana_dashboards.py --list-archived
```

### Interactive Mode (Easiest!)
```bash
python scripts/manage_grafana_dashboards.py --interactive
```

## Dashboard States

Dashboards can be in three states:

1. **Enabled** ✅ - Visible in Grafana menu
2. **Disabled** ❌ - Hidden in `.hidden/` directory  
3. **Archived** 📦 - Preserved in `.archive/` directory (for old/obsolete dashboards)

**Difference between Disabled and Archived:**
- **Disabled**: Temporary hide, easy to re-enable
- **Archived**: Permanent storage, preserves history, removes from active management

## How It Works

### 1. Configuration File
Edit `grafana/dashboard_config.json` to control dashboard visibility:

```json
{
  "dashboards": {
    "analytics_pct_change": {
      "enabled": true,           // Show in Grafana menu
      "folder": "Analytics",     // Organize into folder
      "description": "Analytics percentage change"
    },
    "miscellaneous_dashboards": {
      "enabled": false,          // Hidden from Grafana menu
      "folder": "Miscellaneous"
    }
  }
}
```

### 2. Management Script
Use `scripts/manage_grafana_dashboards.py` to:
- Enable/disable dashboards
- Archive/unarchive dashboards
- List dashboard status (including archived)
- Apply configuration changes
- Interactive menu for easy management

### 3. Dashboard Organization
Dashboards are organized into folders:
- **Core** - System health and advisor dashboards
- **Analytics** - Analytics and percentage change
- **Forecasting** - Path forecasting dashboards
- **ML** - Machine learning dashboards
- **Performance** - Performance metrics
- **Miscellaneous** - Experimental/test dashboards

## Common Tasks

### Show ML Dashboards Only
```bash
python scripts/manage_grafana_dashboards.py --list --folder ML
```

### Enable Multiple Dashboards
```bash
python scripts/manage_grafana_dashboards.py --enable \
    ml_ensemble_overview \
    ml_conformal_metrics \
    ml_prediction_bands
```

### Disable Multiple Dashboards
```bash
python scripts/manage_grafana_dashboards.py --disable \
    miscellaneous_dashboards \
    old_dashboard_1 \
    old_dashboard_2
```

### Archive Old Dashboards
```bash
# Archive obsolete dashboards (preserve but hide)
python scripts/manage_grafana_dashboards.py --archive \
    old_ml_dashboard_v1 \
    experimental_viz_2024 \
    deprecated_metrics

# List what's archived
python scripts/manage_grafana_dashboards.py --list-archived

# Unarchive if needed
python scripts/manage_grafana_dashboards.py --unarchive old_ml_dashboard_v1
```

### Apply Configuration
After manually editing `dashboard_config.json`:
```bash
python scripts/manage_grafana_dashboards.py --apply
```

## File Locations

- **Config:** `grafana/dashboard_config.json`
- **Dashboards:** `grafana/dashboards/`
- **Hidden Dashboards:** `grafana/dashboards/.hidden/` (temporarily disabled)
- **Archived Dashboards:** `grafana/dashboards/.archive/` (permanently stored)
- **Management Script:** `scripts/manage_grafana_dashboards.py`

## Adding New Dashboards

1. Create your dashboard JSON in `grafana/dashboards/`
2. Add entry to `dashboard_config.json`:
```json
{
  "my_new_dashboard": {
    "enabled": true,
    "folder": "Analytics",
    "description": "My awesome new dashboard"
  }
}
```
3. Run: `python scripts/manage_grafana_dashboards.py --apply`
4. Restart Grafana

## Important Notes

⚠️ **Always restart Grafana after making changes!**

```powershell
# Windows Service
Restart-Service grafana

# Or restart manually
```

🔍 **Hidden dashboards** are in `.hidden/` directory (temporarily disabled)

📦 **Archived dashboards** are in `.archive/` directory (permanently stored)

✅ **Enabled dashboards** are in their proper locations and visible in Grafana menu

## Interactive Mode

The easiest way to manage dashboards:

```bash
python scripts/manage_grafana_dashboards.py --interactive
```

Interactive menu provides:
1. List all dashboards
2. List by folder
3. Enable dashboard
4. Disable dashboard
5. Archive dashboard
6. Unarchive dashboard
7. List archived dashboards
8. Apply configuration
9. Show folders

## Troubleshooting

### Dashboards not appearing?
1. Check configuration: `python scripts/manage_grafana_dashboards.py --list`
2. Apply config: `python scripts/manage_grafana_dashboards.py --apply`
3. Restart Grafana
4. Check Grafana logs for errors

### Dashboard in wrong folder?
Edit `folder` field in `dashboard_config.json` and restart Grafana.

### Want to reset?
Run: `python scripts/manage_grafana_dashboards.py --apply`
This syncs filesystem with configuration.

## Examples

### Enable all ML dashboards
```powershell
# Edit dashboard_config.json - set all ML dashboards enabled: true
# Then:
python scripts/manage_grafana_dashboards.py --apply
Restart-Service grafana
```

### Hide experimental dashboards
```bash
python scripts/manage_grafana_dashboards.py --disable \
    test_dashboard_1 test_dashboard_2 experimental_viz
```

### Archive old versions
```bash
# Archive obsolete dashboard versions
python scripts/manage_grafana_dashboards.py --archive \
    ml_ensemble_v1 ml_ensemble_v2

# Check what's archived
python scripts/manage_grafana_dashboards.py --list-archived
```

### Check what's enabled
```bash
python scripts/manage_grafana_dashboards.py --list
```

## Configuration Reference

### Dashboard Entry
```json
{
  "dashboard_name": {
    "enabled": true,              // Required: show in Grafana?
    "folder": "FolderName",       // Required: Grafana folder
    "description": "...",         // Optional: description
    "note": "...",                // Optional: additional notes
    "source_dir": "ml",           // Optional: subdirectory location
    "source_file": "path/..."     // Optional: custom file path
  }
}
```

### Folder Definition
```json
{
  "folders": {
    "FolderName": {
      "description": "Folder description",
      "priority": 1               // Sort order (lower = higher)
    }
  }
}
```

## Tips

💡 Use interactive mode for quick changes
💡 Keep configuration in version control
💡 Document why dashboards are disabled (use "note" field)
💡 Use folders to organize related dashboards
💡 Set priority to control folder order
💡 **Archive old dashboards** instead of deleting them (preserves history)
💡 **Disable** for temporary hide, **Archive** for permanent storage
💡 Review archived dashboards periodically (`--list-archived`)
