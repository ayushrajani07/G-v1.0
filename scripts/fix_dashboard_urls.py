"""
Fix dashboard URLs to use hardcoded values instead of variables
"""
import json
import sys
from pathlib import Path

dashboard_file = Path(r"C:\GrafanaData\dashboards_live\g6_live_from_csv.json")
output_file = Path(r"C:\GrafanaData\dashboards_live\g6_live_from_csv_fixed.json")

print("Loading dashboard...")
with open(dashboard_file, 'r', encoding='utf-8') as f:
    dashboard = json.load(f)

print("Fixing panel URLs...")
for panel in dashboard.get('panels', []):
    if not panel.get('targets'):
        continue
    
    for target in panel['targets']:
        url = target.get('url', '')
        
        # Replace variables with actual values
        if 'NIFTY' in url:
            target['url'] = 'http://127.0.0.1:9500/api/live_csv?index=NIFTY&expiry_tag=this_week&offset=0'
            print(f"  ✓ Fixed NIFTY panel")
        elif 'SENSEX' in url:
            target['url'] = 'http://127.0.0.1:9500/api/live_csv?index=SENSEX&expiry_tag=this_month&offset=0'
            print(f"  ✓ Fixed SENSEX panel")
        elif 'BANKNIFTY' in url:
            target['url'] = 'http://127.0.0.1:9500/api/live_csv?index=BANKNIFTY&expiry_tag=this_week&offset=0'
            print(f"  ✓ Fixed BANKNIFTY panel")
        elif 'FINNIFTY' in url:
            target['url'] = 'http://127.0.0.1:9500/api/live_csv?index=FINNIFTY&expiry_tag=this_month&offset=0'
            print(f"  ✓ Fixed FINNIFTY panel")

# Change dashboard UID to avoid conflict
dashboard['uid'] = 'g6-live-csv-fixed'
dashboard['title'] = 'G6 Overlays (Live from CSV - Fixed)'

print("Saving fixed dashboard...")
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(dashboard, f, indent=2)

print(f"\n✓ Dashboard saved to: {output_file}")
print("\nNow import this dashboard in Grafana:")
print(f"  1. Go to: http://127.0.0.1:3002/dashboard/import")
print(f"  2. Upload: {output_file}")
print(f"  3. Click Import")
