#!/usr/bin/env python3
"""
Batch Migration Script for Phase 3: Late Import Elimination

This script systematically migrates late imports to use the new facade pattern.
Targets files with < 15 late imports for quick wins.

Usage:
    python scripts/batch_migrate_imports.py --dry-run
    python scripts/batch_migrate_imports.py --execute
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Migration patterns: old import -> new import
MIGRATION_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    # Metrics imports
    (
        re.compile(r'^\s+from src\.metrics import get_metrics\s*$', re.MULTILINE),
        'from src.metrics import get_metrics',
        '# Migrated to facade (Phase 3)\n    from src.metrics.facade import get_metrics_lazy as get_metrics'
    ),
    (
        re.compile(r'^\s+from src\.metrics import get_metrics_singleton\s*$', re.MULTILINE),
        'from src.metrics import get_metrics_singleton',
        '# Migrated to facade (Phase 3)\n    from src.metrics.facade import get_metrics_lazy as get_metrics_singleton'
    ),
    
    # Error handling imports
    (
        re.compile(r'^\s+from src\.error_handling import handle_api_error\s*$', re.MULTILINE),
        'from src.error_handling import handle_api_error',
        '# Migrated to facade (Phase 3)\n    from src.errors import handle_error, ErrorCategory, ErrorSeverity\n    # Note: Update function call to use handle_error(e, ErrorCategory.API, ErrorSeverity.MEDIUM)'
    ),
    (
        re.compile(r'^\s+from src\.error_handling import handle_data_error\s*$', re.MULTILINE),
        'from src.error_handling import handle_data_error',
        '# Migrated to facade (Phase 3)\n    from src.errors import handle_error, ErrorCategory, ErrorSeverity\n    # Note: Update function call to use handle_error(e, ErrorCategory.DATA, ErrorSeverity.MEDIUM)'
    ),
    (
        re.compile(r'^\s+from src\.error_handling import handle_collector_error\s*$', re.MULTILINE),
        'from src.error_handling import handle_collector_error',
        '# Migrated to facade (Phase 3)\n    from src.errors import handle_error, ErrorCategory, ErrorSeverity\n    # Note: Update function call to use handle_error(e, ErrorCategory.COLLECTOR, ErrorSeverity.MEDIUM)'
    ),
]

def count_late_imports(file_path: Path) -> int:
    """Count late imports in a file."""
    try:
        content = file_path.read_text(encoding='utf-8')
        # Pattern: 4+ spaces + "from src." (inside function/method)
        pattern = re.compile(r'^\s{4,}from src\.', re.MULTILINE)
        matches = pattern.findall(content)
        return len(matches)
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return 0

def find_migration_candidates(src_dir: Path, max_imports: int = 15) -> Dict[Path, int]:
    """Find files with late imports <= max_imports."""
    candidates = {}
    for py_file in src_dir.rglob('*.py'):
        if 'external' in str(py_file) or '__pycache__' in str(py_file):
            continue
        count = count_late_imports(py_file)
        if 0 < count <= max_imports:
            candidates[py_file] = count
    return dict(sorted(candidates.items(), key=lambda x: x[1]))

def migrate_file(file_path: Path, dry_run: bool = True) -> Tuple[int, List[str]]:
    """Migrate a single file. Returns (replacements_made, changes_list)."""
    try:
        content = file_path.read_text(encoding='utf-8')
        original_content = content
        changes = []
        replacements = 0
        
        for pattern, old_text, new_text in MIGRATION_PATTERNS:
            matches = pattern.findall(content)
            if matches:
                content = pattern.sub(new_text, content)
                replacements += len(matches)
                changes.append(f"  - Replaced {len(matches)}x: {old_text}")
        
        if replacements > 0 and not dry_run:
            file_path.write_text(content, encoding='utf-8')
            changes.append(f"  ✅ File updated: {file_path.relative_to(Path.cwd())}")
        elif replacements > 0:
            changes.append(f"  📋 Would update: {file_path.relative_to(Path.cwd())}")
        
        return replacements, changes
    except Exception as e:
        return 0, [f"  ❌ Error: {e}"]

def main():
    """Main migration script."""
    import argparse
    parser = argparse.ArgumentParser(description='Batch migrate late imports to facade pattern')
    parser.add_argument('--dry-run', action='store_true', default=True,
                        help='Show what would be changed without making changes')
    parser.add_argument('--execute', action='store_true',
                        help='Actually perform the migration')
    parser.add_argument('--max-imports', type=int, default=15,
                        help='Maximum late imports per file to migrate (default: 15)')
    args = parser.parse_args()
    
    dry_run = not args.execute
    src_dir = Path('src')
    
    print("="*80)
    print("Phase 3: Batch Late Import Migration")
    print("="*80)
    print(f"Mode: {'DRY RUN' if dry_run else 'EXECUTE'}")
    print(f"Max imports per file: {args.max_imports}")
    print()
    
    # Find candidates
    print("Scanning for migration candidates...")
    candidates = find_migration_candidates(src_dir, args.max_imports)
    print(f"Found {len(candidates)} files with 1-{args.max_imports} late imports\n")
    
    if not candidates:
        print("No migration candidates found!")
        return 0
    
    # Show top candidates
    print("Top 10 candidates:")
    for i, (file_path, count) in enumerate(list(candidates.items())[:10], 1):
        rel_path = file_path.relative_to(Path.cwd())
        print(f"  {i:2d}. {rel_path} ({count} late imports)")
    print()
    
    if dry_run:
        print("Run with --execute to apply changes\n")
        return 0
    
    # Confirm execution
    response = input("Proceed with migration? [y/N]: ")
    if response.lower() != 'y':
        print("Migration cancelled")
        return 1
    
    # Migrate files
    print("\nMigrating files...")
    total_replacements = 0
    migrated_files = 0
    
    for file_path, late_import_count in candidates.items():
        replacements, changes = migrate_file(file_path, dry_run=False)
        if replacements > 0:
            print(f"\n{file_path.relative_to(Path.cwd())} ({late_import_count} late imports):")
            for change in changes:
                print(change)
            total_replacements += replacements
            migrated_files += 1
    
    print("\n" + "="*80)
    print(f"Migration complete!")
    print(f"  Files migrated: {migrated_files}")
    print(f"  Total replacements: {total_replacements}")
    print("="*80)
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
