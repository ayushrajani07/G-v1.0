# Finding Grafana Dashboard Locations

## Quick Answer

If you see dashboards in Grafana that aren't in your project folder, they could be in:

1. **Grafana's Database** - Dashboards created/edited in Grafana UI
2. **Other Provisioning Sources** - Additional paths configured in Grafana
3. **Grafana Plugins** - Some plugins include dashboards

## How to Find Them

### Method 1: Check Grafana Database (When Grafana is Running)

```powershell
# Run the dashboard finder
python scripts/find_grafana_dashboards.py --check-grafana

# Or manually check Grafana API
Invoke-WebRequest http://localhost:3000/api/search?type=dash-db | ConvertFrom-Json | Format-Table title, uid, url
```

### Method 2: Find Grafana's SQLite Database

```powershell
# Search for grafana.db
Get-ChildItem -Path "C:\ProgramData\Grafana" -Recurse -Filter "grafana.db" -ErrorAction SilentlyContinue
Get-ChildItem -Path "$env:LOCALAPPDATA\Grafana" -Recurse -Filter "grafana.db" -ErrorAction SilentlyContinue
Get-ChildItem -Path "C:\Program Files\GrafanaLabs" -Recurse -Filter "grafana.db" -ErrorAction SilentlyContinue
```

Once found, you can:
- Open with SQLite browser to see dashboards
- Export dashboards from the `dashboard` table
- Copy the JSON from the `data` column

### Method 3: Check Grafana Configuration

Look in Grafana's config file (usually `grafana.ini`):

```ini
[paths]
data = C:/path/to/grafana/data   # Contains grafana.db

[dashboards]
# May have additional provisioning paths
```

Common config locations:
- `C:\Program Files\GrafanaLabs\grafana\conf\grafana.ini`
- `C:\ProgramData\Grafana\conf\grafana.ini`

### Method 4: Check All Provisioning Sources

```powershell
# Check your provisioning config
Get-Content provisioning/dashboards/dashboards.yml

# Look for all 'path:' entries
Select-String -Path provisioning/dashboards/*.yml -Pattern "path:"
```

## Export Dashboards from Grafana UI

If Grafana is running and you see dashboards:

1. Open dashboard in Grafana
2. Click ⚙️ (Settings) → JSON Model
3. Copy the entire JSON
4. Save to `grafana/dashboards/your_dashboard.json`
5. Add to `grafana/dashboard_config.json`

## Using the Finder Script

### Basic scan:
```powershell
python scripts/find_grafana_dashboards.py
```

### Check Grafana when it's running:
```powershell
python scripts/find_grafana_dashboards.py --check-grafana
```

### Find orphan dashboards:
```powershell
python scripts/find_grafana_dashboards.py --find-orphans
```

### Custom Grafana URL:
```powershell
python scripts/find_grafana_dashboards.py --check-grafana --grafana-url http://localhost:3001
```

## Common Scenarios

### Scenario 1: Dashboard created in Grafana UI
**Location:** Grafana database (`grafana.db`)  
**Solution:** Export from UI and save to project

### Scenario 2: Dashboard from plugin
**Location:** Plugin directory  
**Solution:** Usually can't move, managed by plugin

### Scenario 3: Dashboard from another provisioning path
**Location:** Check `dashboards.yml` for other `path:` entries  
**Solution:** Add to your config or consolidate locations

### Scenario 4: Duplicate dashboards
**Location:** Multiple folders (e.g., root and `ml/`)  
**Solution:** Archive duplicates using `manage_grafana_dashboards.py --archive`

## Current Project Structure

Your dashboards are in:
```
grafana/dashboards/
├── *.json (13 files) - Root level dashboards
├── ml/*.json (7 files) - ML dashboards  
├── generated/*.json (11 files) - Auto-generated
├── miscellaneous/*.json (4 files) - Misc/duplicates
└── snippets/*.json (1 file) - Code examples
```

**Note:** Some dashboards appear twice (e.g., `advisor_detail` in both root and `miscellaneous/`). You may want to archive duplicates.

## Troubleshooting

### "Dashboard not found but shows in Grafana"

1. **Start Grafana**
2. **Run:** `python scripts/find_grafana_dashboards.py --check-grafana`
3. **Check output** for dashboard UID
4. **Export from Grafana UI** using the UID

### "Can't connect to Grafana API"

- Ensure Grafana is running: `Get-Service grafana`
- Start if needed: `Start-Service grafana`
- Check URL (default: http://localhost:3000)

### "Database not found"

Grafana might be using a different data directory:
```powershell
# Check Grafana service
Get-WmiObject win32_service | Where-Object {$_.Name -like "*grafana*"} | Select-Object PathName

# Look for --homepath or data path in the command
```

## Quick Commands Cheat Sheet

```powershell
# Find all dashboards in project
python scripts/manage_grafana_dashboards.py --list

# Find where dashboards are located
python scripts/find_grafana_dashboards.py

# Check Grafana (when running)
python scripts/find_grafana_dashboards.py --check-grafana

# Find orphans
python scripts/find_grafana_dashboards.py --find-orphans

# Search for Grafana database
Get-ChildItem -Path "C:\" -Recurse -Filter "grafana.db" -ErrorAction SilentlyContinue | Select-Object FullName
```
