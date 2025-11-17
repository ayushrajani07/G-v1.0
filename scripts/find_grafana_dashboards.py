#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Find Grafana Dashboard Locations

Helps locate where Grafana dashboards are stored, including:
- Dashboards in project folders
- Dashboards in Grafana's database
- Dashboards from other provisioning sources

Usage:
    python scripts/find_grafana_dashboards.py
    python scripts/find_grafana_dashboards.py --check-grafana
    python scripts/find_grafana_dashboards.py --find-orphans
"""

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set
import urllib.request
import urllib.error


class DashboardFinder:
    """Find and locate Grafana dashboards from various sources."""

    def __init__(self, repo_root: Optional[Path] = None):
        """Initialize dashboard finder."""
        self.repo_root = repo_root or Path(__file__).parent.parent
        self.config_path = self.repo_root / "grafana" / "dashboard_config.json"
        self.provisioning_path = self.repo_root / "provisioning" / "dashboards" / "dashboards.yml"
        
        # Load config
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
        
        # Common Grafana locations
        self.grafana_locations = self._get_grafana_locations()

    def _get_grafana_locations(self) -> List[Path]:
        """Get common Grafana installation locations."""
        locations = []
        
        # Windows locations
        if os.name == 'nt':
            locations.extend([
                Path(os.environ.get('ProgramData', 'C:\\ProgramData')) / 'Grafana',
                Path(os.environ.get('LOCALAPPDATA', '')) / 'Grafana',
                Path(os.environ.get('ProgramFiles', 'C:\\Program Files')) / 'GrafanaLabs' / 'grafana',
                Path('C:\\GrafanaData\\dashboards_live'),  # External live dashboards
            ])
        # Linux/Mac locations
        else:
            locations.extend([
                Path('/var/lib/grafana'),
                Path('/usr/share/grafana'),
                Path.home() / '.grafana',
            ])
        
        return [loc for loc in locations if loc.exists()]

    def find_project_dashboards(self) -> Dict[str, Path]:
        """Find all dashboards in project folders."""
        print("\n" + "="*80)
        print("📁 DASHBOARDS IN PROJECT")
        print("="*80 + "\n")
        
        dashboards = {}
        base_path = self.repo_root / "grafana" / "dashboards"
        
        # Find all JSON files
        for json_file in base_path.rglob("*.json"):
            if '.hidden' in json_file.parts or '.archive' in json_file.parts:
                continue
            
            name = json_file.stem
            rel_path = json_file.relative_to(self.repo_root)
            dashboards[name] = json_file
            
            in_config = name in self.config.get('dashboards', {})
            status = "✅ In config" if in_config else "⚠️  Not in config"
            
            print(f"   {status} | {name}")
            print(f"              {rel_path}")
            print()
        
        print(f"Total: {len(dashboards)} dashboards found\n")
        return dashboards

    def find_external_dashboards(self, external_path: Path) -> Dict[str, Path]:
        """Find dashboards in external directory."""
        print("\n" + "="*80)
        print(f"📂 DASHBOARDS IN {external_path}")
        print("="*80 + "\n")
        
        dashboards = {}
        
        if not external_path.exists():
            print(f"⚠️  Directory not found: {external_path}\n")
            return dashboards
        
        # Find all JSON files
        for json_file in external_path.glob("*.json"):
            name = json_file.stem
            size_kb = json_file.stat().st_size / 1024
            dashboards[name] = json_file
            
            # Categorize
            if 'backup' in name.lower() or 'BACKUP' in name:
                category = "🗂️  Backup"
            elif name in self.config.get('dashboards', {}):
                category = "✅ In config"
            else:
                category = "📊 External"
            
            print(f"   {category} | {name}")
            print(f"              Size: {size_kb:.1f} KB")
            print()
        
        print(f"Total: {len(dashboards)} dashboards found\n")
        return dashboards

    def find_grafana_database(self) -> Optional[Path]:
        """Find Grafana's SQLite database."""
        print("\n" + "="*80)
        print("🔍 SEARCHING FOR GRAFANA DATABASE")
        print("="*80 + "\n")
        
        for location in self.grafana_locations:
            db_path = location / "grafana.db"
            if db_path.exists():
                print(f"✅ Found: {db_path}\n")
                return db_path
            
            # Check data subdirectory
            data_db = location / "data" / "grafana.db"
            if data_db.exists():
                print(f"✅ Found: {data_db}\n")
                return data_db
        
        print("❌ Grafana database not found in common locations\n")
        print("Common locations checked:")
        for loc in self.grafana_locations:
            print(f"   - {loc}")
        print()
        
        return None

    def query_grafana_database(self, db_path: Path) -> List[Dict]:
        """Query Grafana database for stored dashboards."""
        print("\n" + "="*80)
        print("💾 DASHBOARDS IN GRAFANA DATABASE")
        print("="*80 + "\n")
        
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            
            # Query dashboard table
            cursor.execute("""
                SELECT id, uid, title, slug, folder_id, created, updated, 
                       data, is_folder, version
                FROM dashboard
                WHERE is_folder = 0
                ORDER BY title
            """)
            
            dashboards = []
            for row in cursor.fetchall():
                dash_id, uid, title, slug, folder_id, created, updated, data_json, is_folder, version = row
                
                dashboards.append({
                    'id': dash_id,
                    'uid': uid,
                    'title': title,
                    'slug': slug,
                    'folder_id': folder_id,
                    'created': created,
                    'updated': updated,
                    'version': version
                })
                
                print(f"   📊 {title}")
                print(f"      ID: {dash_id} | UID: {uid} | Slug: {slug}")
                print(f"      Version: {version} | Updated: {updated}")
                print()
            
            conn.close()
            
            print(f"Total: {len(dashboards)} dashboards in database\n")
            return dashboards
            
        except sqlite3.Error as e:
            print(f"❌ Error querying database: {e}\n")
            return []

    def query_grafana_api(self, url: str = "http://localhost:3000") -> List[Dict]:
        """Query Grafana API for dashboards."""
        print("\n" + "="*80)
        print("🌐 DASHBOARDS FROM GRAFANA API")
        print("="*80 + "\n")
        
        try:
            req = urllib.request.Request(f"{url}/api/search?type=dash-db")
            with urllib.request.urlopen(req, timeout=5) as response:
                dashboards = json.loads(response.read().decode())
                
                for dash in dashboards:
                    print(f"   📊 {dash.get('title', 'Untitled')}")
                    print(f"      UID: {dash.get('uid', 'N/A')} | URL: {dash.get('url', 'N/A')}")
                    print(f"      Folder: {dash.get('folderTitle', 'General')}")
                    print()
                
                print(f"Total: {len(dashboards)} dashboards from API\n")
                return dashboards
                
        except urllib.error.URLError:
            print("❌ Cannot connect to Grafana API")
            print(f"   Make sure Grafana is running at {url}\n")
            return []
        except Exception as e:
            print(f"❌ Error querying API: {e}\n")
            return []

    def find_orphan_dashboards(self, project_dashboards: Dict[str, Path], 
                                api_dashboards: List[Dict]) -> Set[str]:
        """Find dashboards in Grafana but not in project."""
        print("\n" + "="*80)
        print("🔍 ORPHAN DASHBOARDS (In Grafana but not in project)")
        print("="*80 + "\n")
        
        project_names = set(project_dashboards.keys())
        api_names = set(dash.get('title', '').replace(' ', '_').lower() 
                       for dash in api_dashboards)
        
        orphans = api_names - project_names
        
        if orphans:
            print("Found dashboards that may not be in your project:\n")
            for name in sorted(orphans):
                # Find the original dashboard
                orig_dash = next((d for d in api_dashboards 
                                 if d.get('title', '').replace(' ', '_').lower() == name), None)
                if orig_dash:
                    print(f"   ⚠️  {orig_dash.get('title')}")
                    print(f"      UID: {orig_dash.get('uid')}")
                    print(f"      URL: {orig_dash.get('url')}")
                    print(f"      Folder: {orig_dash.get('folderTitle', 'General')}")
                    print()
            
            print(f"Total: {len(orphans)} orphan dashboards\n")
            print("These dashboards might be:")
            print("  1. Created directly in Grafana UI (stored in database)")
            print("  2. From another provisioning source")
            print("  3. From a Grafana plugin")
            print("  4. Named differently than their file names\n")
        else:
            print("✅ No orphan dashboards found\n")
        
        return orphans

    def suggest_locations(self):
        """Suggest where to look for dashboards."""
        print("\n" + "="*80)
        print("💡 WHERE TO LOOK FOR DASHBOARDS")
        print("="*80 + "\n")
        
        print("1. **Project Folders:**")
        print(f"   - {self.repo_root / 'grafana' / 'dashboards'}")
        print(f"   - {self.repo_root / 'grafana' / 'dashboards' / 'ml'}")
        print(f"   - {self.repo_root / 'grafana' / 'dashboards' / 'generated'}")
        print()
        
        print("2. **Grafana Installation:**")
        for loc in self.grafana_locations:
            print(f"   - {loc}")
            if (loc / "data").exists():
                print(f"     └─ {loc / 'data' / 'grafana.db'} (database)")
        print()
        
        print("3. **Grafana Data Directory:**")
        print("   - Check Grafana config for 'data' path")
        print("   - Usually contains grafana.db with dashboard JSON")
        print()
        
        print("4. **Provisioning Paths:**")
        if self.provisioning_path.exists():
            with open(self.provisioning_path, 'r') as f:
                content = f.read()
                if 'path:' in content:
                    print(f"   - Check: {self.provisioning_path}")
                    print(f"     (Contains provisioning paths)")
        print()

    def run_full_scan(self):
        """Run complete dashboard location scan."""
        print("\n" + "="*80)
        print("GRAFANA DASHBOARD LOCATION FINDER")
        print("="*80)
        
        # Find project dashboards
        project_dashboards = self.find_project_dashboards()
        
        # Find external dashboards
        external_path = Path('C:\\GrafanaData\\dashboards_live')
        external_dashboards = self.find_external_dashboards(external_path)
        
        # Try to find Grafana database
        db_path = self.find_grafana_database()
        if db_path:
            db_dashboards = self.query_grafana_database(db_path)
        
        # Try Grafana API
        api_dashboards = self.query_grafana_api()
        
        # Find orphans
        if api_dashboards:
            self.find_orphan_dashboards(project_dashboards, api_dashboards)
        
        # Suggest locations
        self.suggest_locations()
        
        # Summary
        print("="*80)
        print("📊 SUMMARY")
        print("="*80 + "\n")
        print(f"  Project dashboards: {len(project_dashboards)}")
        print(f"  External dashboards (C:\\GrafanaData): {len(external_dashboards)}")
        if api_dashboards:
            print(f"  Grafana API dashboards: {len(api_dashboards)}")
        print(f"\n  📈 Total unique dashboard files: {len(project_dashboards) + len(external_dashboards)}")
        print()


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Find and locate Grafana dashboards",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument("--check-grafana", action="store_true", 
                       help="Check Grafana database and API")
    parser.add_argument("--find-orphans", action="store_true",
                       help="Find dashboards in Grafana but not in project")
    parser.add_argument("--external", action="store_true",
                       help="Check external dashboard locations (C:\\GrafanaData)")
    parser.add_argument("--grafana-url", default="http://localhost:3000",
                       help="Grafana URL (default: http://localhost:3000)")
    
    args = parser.parse_args()
    
    finder = DashboardFinder()
    
    if args.check_grafana or args.find_orphans or args.external:
        if args.check_grafana:
            finder.query_grafana_api(args.grafana_url)
            db_path = finder.find_grafana_database()
            if db_path:
                finder.query_grafana_database(db_path)
        
        if args.external:
            external_path = Path('C:\\GrafanaData\\dashboards_live')
            finder.find_external_dashboards(external_path)
        
        if args.find_orphans:
            project_dashboards = finder.find_project_dashboards()
            api_dashboards = finder.query_grafana_api(args.grafana_url)
            if api_dashboards:
                finder.find_orphan_dashboards(project_dashboards, api_dashboards)
    else:
        finder.run_full_scan()


if __name__ == "__main__":
    main()
