#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Grafana Dashboard Management Script

Manage dashboard visibility and organization in Grafana based on dashboard_config.json.
Makes it easy to show/hide dashboards and organize them into folders.

Usage:
    # List all dashboards and their status
    python scripts/manage_grafana_dashboards.py --list

    # Enable a dashboard
    python scripts/manage_grafana_dashboards.py --enable analytics_pct_change

    # Disable a dashboard
    python scripts/manage_grafana_dashboards.py --disable miscellaneous_dashboards

    # Archive a dashboard (preserve but hide)
    python scripts/manage_grafana_dashboards.py --archive old_dashboard

    # Unarchive a dashboard
    python scripts/manage_grafana_dashboards.py --unarchive old_dashboard

    # Enable multiple dashboards
    python scripts/manage_grafana_dashboards.py --enable ml_ensemble_overview ml_conformal_metrics

    # Apply current configuration (sync with Grafana)
    python scripts/manage_grafana_dashboards.py --apply

    # Show dashboards by folder
    python scripts/manage_grafana_dashboards.py --list --folder ML

    # List archived dashboards
    python scripts/manage_grafana_dashboards.py --list-archived

    # Interactive mode
    python scripts/manage_grafana_dashboards.py --interactive
"""

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional


class DashboardManager:
    """Manage Grafana dashboard visibility and organization."""

    def __init__(self, config_path: Optional[Path] = None):
        """Initialize dashboard manager."""
        self.repo_root = Path(__file__).parent.parent
        self.config_path = config_path or self.repo_root / "grafana" / "dashboard_config.json"
        self.config = self._load_config()
        
        self.base_path = Path(self.config["settings"]["base_path"])
        self.hidden_dir = self.base_path / ".hidden"
        self.archive_dir = Path(self.config["settings"].get(
            "archive_path", 
            str(self.base_path / ".archive")
        ))
        
        # Create directories if they don't exist
        self.hidden_dir.mkdir(exist_ok=True)
        self.archive_dir.mkdir(exist_ok=True)

    def _load_config(self) -> Dict:
        """Load dashboard configuration."""
        if not self.config_path.exists():
            print(f"Error: Config file not found: {self.config_path}")
            sys.exit(1)
        
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_config(self):
        """Save dashboard configuration."""
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2)
        print(f"✅ Configuration saved to {self.config_path}")

    def _is_archived(self, dashboard_name: str) -> bool:
        """Check if a dashboard is archived."""
        archived_path = self.archive_dir / f"{dashboard_name}.json"
        return archived_path.exists()

    def _get_dashboard_path(self, dashboard_name: str) -> Optional[Path]:
        """Get the path to a dashboard JSON file."""
        dashboard_info = self.config["dashboards"].get(dashboard_name, {})
        
        # Check if it's in a subdirectory
        if "source_dir" in dashboard_info:
            source_dir = dashboard_info["source_dir"]
            path = self.base_path / source_dir / f"{dashboard_name}.json"
        elif "source_file" in dashboard_info:
            path = Path(dashboard_info["source_file"])
        else:
            path = self.base_path / f"{dashboard_name}.json"
        
        # Check if hidden
        hidden_path = self.hidden_dir / f"{dashboard_name}.json"
        if hidden_path.exists():
            return hidden_path
        
        # Check if archived
        archived_path = self.archive_dir / f"{dashboard_name}.json"
        if archived_path.exists():
            return archived_path
        
        return path if path.exists() else None

    def list_dashboards(self, folder: Optional[str] = None, show_archived: bool = False):
        """List all dashboards with their status."""
        print("\n" + "="*80)
        print("📊 GRAFANA DASHBOARD STATUS")
        print("="*80 + "\n")

        dashboards_by_folder: Dict[str, List[tuple]] = {}
        
        for name, info in self.config["dashboards"].items():
            if folder and info.get("folder") != folder:
                continue
            
            folder_name = info.get("folder", "Uncategorized")
            enabled = info.get("enabled", False)
            archived = self._is_archived(name)
            description = info.get("description", "No description")
            note = info.get("note", "")
            
            if folder_name not in dashboards_by_folder:
                dashboards_by_folder[folder_name] = []
            
            dashboards_by_folder[folder_name].append((name, enabled, archived, description, note))

        # Sort folders by priority
        folder_priorities = {
            name: info.get("priority", 50)
            for name, info in self.config.get("folders", {}).items()
        }
        
        for folder_name in sorted(dashboards_by_folder.keys(), 
                                   key=lambda x: folder_priorities.get(x, 50)):
            folder_info = self.config.get("folders", {}).get(folder_name, {})
            folder_desc = folder_info.get("description", "")
            
            print(f"📁 {folder_name}")
            if folder_desc:
                print(f"   {folder_desc}")
            print()

            for name, enabled, archived, description, note in sorted(dashboards_by_folder[folder_name]):
                if archived:
                    status = "📦 ARCHIVED"
                elif enabled:
                    status = "✅ ENABLED "
                else:
                    status = "❌ DISABLED"
                print(f"   {status} | {name}")
                print(f"              {description}")
                if note:
                    print(f"              Note: {note}")
                print()

        print("="*80)
        
        # Summary
        total = len(self.config["dashboards"])
        enabled_count = sum(1 for d in self.config["dashboards"].values() if d.get("enabled", False))
        archived_count = sum(1 for name in self.config["dashboards"].keys() if self._is_archived(name))
        disabled_count = total - enabled_count - archived_count
        
        print(f"\n📈 Summary: {enabled_count} enabled, {disabled_count} disabled, {archived_count} archived, {total} total\n")

    def enable_dashboard(self, dashboard_name: str) -> bool:
        """Enable a dashboard."""
        if dashboard_name not in self.config["dashboards"]:
            print(f"❌ Dashboard '{dashboard_name}' not found in config")
            return False
        
        # Update config
        self.config["dashboards"][dashboard_name]["enabled"] = True
        
        # Move from hidden if needed
        hidden_path = self.hidden_dir / f"{dashboard_name}.json"
        if hidden_path.exists():
            dashboard_info = self.config["dashboards"][dashboard_name]
            
            if "source_dir" in dashboard_info:
                target_dir = self.base_path / dashboard_info["source_dir"]
                target_dir.mkdir(exist_ok=True)
                target_path = target_dir / f"{dashboard_name}.json"
            else:
                target_path = self.base_path / f"{dashboard_name}.json"
            
            shutil.move(str(hidden_path), str(target_path))
            print(f"✅ Moved {dashboard_name} from hidden to visible location")
        
        print(f"✅ Enabled: {dashboard_name}")
        return True

    def disable_dashboard(self, dashboard_name: str) -> bool:
        """Disable a dashboard."""
        if dashboard_name not in self.config["dashboards"]:
            print(f"❌ Dashboard '{dashboard_name}' not found in config")
            return False
        
        # Update config
        self.config["dashboards"][dashboard_name]["enabled"] = False
        
        # Move to hidden directory
        source_path = self._get_dashboard_path(dashboard_name)
        if source_path and source_path.exists() and source_path.parent != self.hidden_dir:
            target_path = self.hidden_dir / f"{dashboard_name}.json"
            shutil.move(str(source_path), str(target_path))
            print(f"✅ Moved {dashboard_name} to hidden location")
        
        print(f"✅ Disabled: {dashboard_name}")
        return True

    def archive_dashboard(self, dashboard_name: str) -> bool:
        """Archive a dashboard (preserve but hide from Grafana)."""
        if dashboard_name not in self.config["dashboards"]:
            print(f"❌ Dashboard '{dashboard_name}' not found in config")
            return False
        
        # Move to archive directory
        source_path = self._get_dashboard_path(dashboard_name)
        if source_path and source_path.exists() and source_path.parent != self.archive_dir:
            target_path = self.archive_dir / f"{dashboard_name}.json"
            shutil.move(str(source_path), str(target_path))
            print(f"📦 Archived: {dashboard_name} -> {target_path}")
        elif self._is_archived(dashboard_name):
            print(f"ℹ️  Dashboard '{dashboard_name}' is already archived")
        else:
            print(f"⚠️  Warning: Dashboard file not found for '{dashboard_name}'")
        
        # Update config - mark as archived in the archived section
        if "archived" not in self.config:
            self.config["archived"] = {}
        
        self.config["archived"][dashboard_name] = {
            "archived_date": "2025-11-17",
            "original_folder": self.config["dashboards"][dashboard_name].get("folder", "Unknown"),
            "description": self.config["dashboards"][dashboard_name].get("description", "")
        }
        
        print(f"✅ Archived: {dashboard_name}")
        return True

    def unarchive_dashboard(self, dashboard_name: str) -> bool:
        """Unarchive a dashboard (restore to visible location)."""
        if not self._is_archived(dashboard_name):
            print(f"❌ Dashboard '{dashboard_name}' is not archived")
            return False
        
        if dashboard_name not in self.config["dashboards"]:
            print(f"❌ Dashboard '{dashboard_name}' not found in config")
            return False
        
        # Move from archive
        archived_path = self.archive_dir / f"{dashboard_name}.json"
        dashboard_info = self.config["dashboards"][dashboard_name]
        
        if "source_dir" in dashboard_info:
            target_dir = self.base_path / dashboard_info["source_dir"]
            target_dir.mkdir(exist_ok=True)
            target_path = target_dir / f"{dashboard_name}.json"
        else:
            target_path = self.base_path / f"{dashboard_name}.json"
        
        shutil.move(str(archived_path), str(target_path))
        print(f"📤 Unarchived: {dashboard_name} -> {target_path}")
        
        # Remove from archived section
        if "archived" in self.config and dashboard_name in self.config["archived"]:
            del self.config["archived"][dashboard_name]
        
        # Enable it
        self.config["dashboards"][dashboard_name]["enabled"] = True
        
        print(f"✅ Unarchived and enabled: {dashboard_name}")
        return True

    def list_archived(self):
        """List all archived dashboards."""
        print("\n" + "="*80)
        print("📦 ARCHIVED DASHBOARDS")
        print("="*80 + "\n")
        
        archived_items = self.config.get("archived", {})
        if not archived_items or len(archived_items) <= 2:  # Exclude comment fields
            print("   No archived dashboards\n")
            return
        
        for name, info in sorted(archived_items.items()):
            if name.startswith("_"):  # Skip comment fields
                continue
            
            description = info.get("description", "No description")
            original_folder = info.get("original_folder", "Unknown")
            archived_date = info.get("archived_date", "Unknown")
            
            print(f"   📦 {name}")
            print(f"      Description: {description}")
            print(f"      Original Folder: {original_folder}")
            print(f"      Archived: {archived_date}")
            print()
        
        print("="*80 + "\n")

    def apply_config(self):
        """Apply current configuration to filesystem."""
        print("\n🔄 Applying dashboard configuration...\n")
        
        changes_made = False
        
        for name, info in self.config["dashboards"].items():
            enabled = info.get("enabled", False)
            current_path = self._get_dashboard_path(name)
            
            if not current_path:
                print(f"⚠️  Warning: Dashboard '{name}' not found on filesystem")
                continue
            
            is_hidden = current_path.parent == self.hidden_dir
            
            if enabled and is_hidden:
                # Should be visible but is hidden - move it
                self.enable_dashboard(name)
                changes_made = True
            elif not enabled and not is_hidden:
                # Should be hidden but is visible - move it
                self.disable_dashboard(name)
                changes_made = True
        
        if not changes_made:
            print("✅ All dashboards already match configuration")
        else:
            print("\n✅ Configuration applied successfully")
        
        print("\n⚠️  Remember to restart Grafana for changes to take effect!")

    def interactive_mode(self):
        """Interactive dashboard management."""
        while True:
            print("\n" + "="*80)
            print("🎛️  INTERACTIVE DASHBOARD MANAGER")
            print("="*80)
            print("\n1. List all dashboards")
            print("2. List by folder")
            print("3. Enable dashboard")
            print("4. Disable dashboard")
            print("5. Archive dashboard")
            print("6. Unarchive dashboard")
            print("7. List archived dashboards")
            print("8. Apply configuration")
            print("9. Show folders")
            print("0. Exit")
            print()
            
            choice = input("Select option: ").strip()
            
            if choice == "0":
                print("👋 Goodbye!")
                break
            elif choice == "1":
                self.list_dashboards()
            elif choice == "2":
                folder = input("Enter folder name: ").strip()
                self.list_dashboards(folder=folder)
            elif choice == "3":
                name = input("Enter dashboard name to enable: ").strip()
                if self.enable_dashboard(name):
                    self._save_config()
            elif choice == "4":
                name = input("Enter dashboard name to disable: ").strip()
                if self.disable_dashboard(name):
                    self._save_config()
            elif choice == "5":
                name = input("Enter dashboard name to archive: ").strip()
                if self.archive_dashboard(name):
                    self._save_config()
            elif choice == "6":
                name = input("Enter dashboard name to unarchive: ").strip()
                if self.unarchive_dashboard(name):
                    self._save_config()
            elif choice == "7":
                self.list_archived()
            elif choice == "8":
                self.apply_config()
            elif choice == "9":
                self._show_folders()
            else:
                print("❌ Invalid option")
            
            input("\nPress Enter to continue...")

    def _show_folders(self):
        """Show available folders."""
        print("\n📁 Available Folders:\n")
        
        folders = self.config.get("folders", {})
        for name, info in sorted(folders.items(), key=lambda x: x[1].get("priority", 50)):
            priority = info.get("priority", "N/A")
            description = info.get("description", "No description")
            print(f"   {name} (Priority: {priority})")
            print(f"      {description}\n")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Manage Grafana dashboard visibility and organization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # List all dashboards
    python scripts/manage_grafana_dashboards.py --list

    # Enable a dashboard
    python scripts/manage_grafana_dashboards.py --enable analytics_pct_change

    # Disable multiple dashboards
    python scripts/manage_grafana_dashboards.py --disable misc1 misc2

    # Apply current configuration
    python scripts/manage_grafana_dashboards.py --apply

    # Interactive mode
    python scripts/manage_grafana_dashboards.py --interactive
        """
    )
    
    parser.add_argument("--list", action="store_true", help="List all dashboards")
    parser.add_argument("--list-archived", action="store_true", help="List archived dashboards")
    parser.add_argument("--folder", help="Filter by folder when listing")
    parser.add_argument("--enable", nargs="+", help="Enable dashboard(s)")
    parser.add_argument("--disable", nargs="+", help="Disable dashboard(s)")
    parser.add_argument("--archive", nargs="+", help="Archive dashboard(s)")
    parser.add_argument("--unarchive", nargs="+", help="Unarchive dashboard(s)")
    parser.add_argument("--apply", action="store_true", help="Apply current configuration")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    parser.add_argument("--config", help="Path to dashboard config file")
    
    args = parser.parse_args()
    
    # Create manager
    config_path = Path(args.config) if args.config else None
    manager = DashboardManager(config_path)
    
    # Execute commands
    if args.interactive:
        manager.interactive_mode()
    elif args.list:
        manager.list_dashboards(folder=args.folder)
    elif args.list_archived:
        manager.list_archived()
    elif args.enable:
        for name in args.enable:
            manager.enable_dashboard(name)
        manager._save_config()
    elif args.disable:
        for name in args.disable:
            manager.disable_dashboard(name)
        manager._save_config()
    elif args.archive:
        for name in args.archive:
            manager.archive_dashboard(name)
        manager._save_config()
    elif args.unarchive:
        for name in args.unarchive:
            manager.unarchive_dashboard(name)
        manager._save_config()
    elif args.apply:
        manager.apply_config()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
