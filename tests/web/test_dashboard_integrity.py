
import pytest
import json
from pathlib import Path

DASHBOARD_DIR = Path("grafana/dashboards/dashboards_live")
PCT_DASHBOARDS = ["contracts_pct_change.json", "analytics_pct_change.json"]

def test_pct_dashboards_exist():
    for db_name in PCT_DASHBOARDS:
        path = DASHBOARD_DIR / db_name
        assert path.exists(), f"Dashboard {db_name} not found at {path}"

def test_pct_dashboards_api_usage():
    for db_name in PCT_DASHBOARDS:
        path = DASHBOARD_DIR / db_name
        if not path.exists():
            continue
            
        with open(path, "r") as f:
            data = json.load(f)
            
        panels = data.get("panels", [])
        for panel in panels:
            targets = panel.get("targets", [])
            for target in targets:
                url = target.get("url", "")
                
                # Skip if not using the live_csv API
                if "/api/live_csv" not in url:
                    continue
                
                # Check Port 9500
                assert "9500" in url, f"Dashboard {db_name} panel '{panel.get('title')}' target '{target.get('refId')}' is not using port 9500"
                
                # Check pct=1
                assert "pct=1" in url, f"Dashboard {db_name} panel '{panel.get('title')}' target '{target.get('refId')}' missing pct=1"
                
                # Check pct_fields
                assert "pct_fields=" in url, f"Dashboard {db_name} panel '{panel.get('title')}' target '{target.get('refId')}' missing pct_fields"

def test_pct_dashboards_transformations():
    for db_name in PCT_DASHBOARDS:
        path = DASHBOARD_DIR / db_name
        if not path.exists():
            continue
            
        with open(path, "r") as f:
            data = json.load(f)
            
        panels = data.get("panels", [])
        for panel in panels:
            # Check if transformations exist
            transformations = panel.get("transformations", [])
            
            # We expect at least some transformations for pct dashboards to handle the fields
            # Specifically filterFieldsByName or organize to select _pct fields
            
            has_pct_field_handling = False
            for t in transformations:
                if t["id"] == "filterFieldsByName":
                    names = t.get("options", {}).get("include", {}).get("names", [])
                    if any("_pct" in n for n in names):
                        has_pct_field_handling = True
                if t["id"] == "organize":
                    # Check if we are renaming or excluding
                    # Just checking existence of organize is a weak signal, but checking if it handles _pct is better
                    renames = t.get("options", {}).get("renameByName", {})
                    if any("_pct" in k for k in renames.keys()):
                        has_pct_field_handling = True
            
            # Only enforce this if the panel actually targets the API (some might be text panels etc)
            targets = panel.get("targets", [])
            has_api_target = any("/api/live_csv" in t.get("url", "") for t in targets)
            
            if has_api_target:
                assert has_pct_field_handling, f"Dashboard {db_name} panel '{panel.get('title')}' does not appear to handle _pct fields in transformations"

