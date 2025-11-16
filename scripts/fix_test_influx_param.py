"""Remove obsolete influx_sink parameter from test files.

Part of pytest error fixes (2025-11-16)

The influx_sink parameter was removed from run_unified_collectors()
and related functions. This script removes all occurrences.

Usage:
    python scripts/fix_test_influx_param.py --dry-run
    python scripts/fix_test_influx_param.py --execute
"""
import argparse
import re
import sys
from pathlib import Path

def fix_influx_sink_calls(file_path: Path, dry_run: bool = True) -> tuple[int, list[str]]:
    """Remove influx_sink parameter from function calls.
    
    Returns:
        Tuple of (num_changes, list_of_changes)
    """
    content = file_path.read_text(encoding='utf-8')
    original = content
    changes = []
    
    # Pattern 1: influx_sink=value, (with trailing comma)
    pattern1 = r',\s*influx_sink=[^,)]+,\s*'
    matches1 = list(re.finditer(pattern1, content))
    for match in matches1:
        content = content.replace(match.group(), ', ', 1)
        changes.append(f"  Removed: {match.group().strip()}")
    
    # Pattern 2: influx_sink=value) (at end of call)
    pattern2 = r',\s*influx_sink=[^)]+\)'
    matches2 = list(re.finditer(pattern2, content))
    for match in matches2:
        content = content.replace(match.group(), ')', 1)
        changes.append(f"  Removed: {match.group().strip()[:-1]}")
    
    # Pattern 3: (influx_sink=value, (at start with other params)
    pattern3 = r'\(influx_sink=[^,)]+,\s*'
    matches3 = list(re.finditer(pattern3, content))
    for match in matches3:
        content = content.replace(match.group(), '(', 1)
        changes.append(f"  Removed: {match.group().strip()[1:]}")
    
    # Pattern 4: (influx_sink=value) (only parameter)
    pattern4 = r'\(influx_sink=[^)]+\)'
    matches4 = list(re.finditer(pattern4, content))
    for match in matches4:
        content = content.replace(match.group(), '()', 1)
        changes.append(f"  Removed: {match.group().strip()[1:-1]}")
    
    num_changes = len(changes)
    
    if num_changes > 0 and not dry_run:
        file_path.write_text(content, encoding='utf-8')
    
    return num_changes, changes


def main():
    parser = argparse.ArgumentParser(description='Remove influx_sink parameter from tests')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes')
    parser.add_argument('--execute', action='store_true', help='Apply changes')
    
    args = parser.parse_args()
    
    if not args.dry_run and not args.execute:
        print("ERROR: Must specify --dry-run or --execute")
        return 1
    
    dry_run = args.dry_run
    root = Path('tests')
    
    print("=" * 80)
    print("INFLUX_SINK PARAMETER REMOVAL")
    print("=" * 80)
    
    total_changes = 0
    files_modified = []
    
    for test_file in root.rglob('*.py'):
        content = test_file.read_text(encoding='utf-8', errors='ignore')
        if 'influx_sink=' in content:
            num_changes, changes = fix_influx_sink_calls(test_file, dry_run)
            if num_changes > 0:
                rel_path = test_file.relative_to('.')
                print(f"\n{rel_path} ({num_changes} changes):")
                for change in changes:
                    print(change)
                total_changes += num_changes
                files_modified.append(str(rel_path))
    
    print("\n" + "=" * 80)
    if dry_run:
        print(f"DRY RUN: Would modify {len(files_modified)} files ({total_changes} changes)")
        print("Run with --execute to apply changes")
    else:
        print(f"COMPLETE: Modified {len(files_modified)} files ({total_changes} changes)")
    print("=" * 80)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
