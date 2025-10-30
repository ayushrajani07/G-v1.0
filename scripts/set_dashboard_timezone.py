#!/usr/bin/env python3
"""Set timezone to Asia/Kolkata (IST) in all Grafana dashboard JSON files.

This ensures all dashboard timestamps are displayed in Indian Standard Time.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def set_timezone_in_dashboard(file_path: Path, timezone: str = "Asia/Kolkata") -> bool:
    """Set or update timezone in a dashboard JSON file.
    
    Returns True if the file was modified, False otherwise.
    """
    try:
        content = file_path.read_text(encoding='utf-8')
        data = json.loads(content)
        
        # Check if timezone already set to the target value
        current_tz = data.get('timezone', '')
        if current_tz == timezone:
            return False
        
        # Set timezone
        data['timezone'] = timezone
        
        # Write back with nice formatting
        new_content = json.dumps(data, indent=2, ensure_ascii=False)
        file_path.write_text(new_content, encoding='utf-8')
        
        print(f"✓ Updated: {file_path.name} (was: '{current_tz}' → now: '{timezone}')")
        return True
        
    except json.JSONDecodeError as e:
        print(f"✗ Skipped {file_path.name}: Invalid JSON - {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"✗ Error processing {file_path.name}: {e}", file=sys.stderr)
        return False


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    
    # Process all dashboard directories
    dashboard_dirs = [
        root / "grafana" / "dashboards",
        root / "grafana" / "dashboards" / "generated",
    ]
    
    modified_count = 0
    skipped_count = 0
    error_count = 0
    
    for dash_dir in dashboard_dirs:
        if not dash_dir.exists():
            continue
            
        for json_file in dash_dir.glob("*.json"):
            if json_file.name.startswith('.'):
                continue
                
            try:
                if set_timezone_in_dashboard(json_file):
                    modified_count += 1
                else:
                    skipped_count += 1
            except Exception:
                error_count += 1
    
    print(f"\n{'='*60}")
    print(f"Summary:")
    print(f"  Modified:  {modified_count} dashboards")
    print(f"  Unchanged: {skipped_count} dashboards (already IST)")
    print(f"  Errors:    {error_count} dashboards")
    print(f"{'='*60}")
    
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
