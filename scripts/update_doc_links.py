"""Update internal documentation links after reorganization.

Part of Phase 3.1: Documentation Restructuring (2025-11-16)

Scans all markdown files and updates links to moved documentation files.

Usage:
    python scripts/update_doc_links.py --dry-run   # Preview changes
    python scripts/update_doc_links.py --execute   # Apply changes
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Mapping of old filenames to new paths (relative to repo root)
DOC_MOVES: Dict[str, str] = {}

def build_move_mapping(root: Path) -> Dict[str, str]:
    """Build mapping of moved documentation files.
    
    Args:
        root: Repository root path
        
    Returns:
        Dictionary mapping old filename to new path
    """
    docs_dir = root / 'docs'
    mapping = {}
    
    for category_dir in docs_dir.iterdir():
        if not category_dir.is_dir():
            continue
        
        for md_file in category_dir.glob('*.md'):
            if md_file.name == 'README.md':
                continue
            
            # Old path (in root): FILENAME.md
            # New path: docs/category/FILENAME.md
            old_path = md_file.name
            new_path = f"docs/{category_dir.name}/{md_file.name}"
            mapping[old_path] = new_path
    
    return mapping


def find_doc_links(content: str) -> List[Tuple[str, str]]:
    """Find markdown links in content.
    
    Args:
        content: Markdown file content
        
    Returns:
        List of (full_match, link_target) tuples
    """
    # Match [text](link.md) and [text](link.md#anchor)
    pattern = r'\[([^\]]+)\]\(([^)]+\.md(?:#[^)]*)?)\)'
    matches = []
    
    for match in re.finditer(pattern, content):
        full_match = match.group(0)
        link_target = match.group(2)
        matches.append((full_match, link_target))
    
    return matches


def update_link(link: str, mapping: Dict[str, str], current_file: Path, root: Path) -> str:
    """Update a single link target.
    
    Args:
        link: Original link target (may include anchor)
        mapping: File move mapping
        current_file: Current file being processed
        root: Repository root
        
    Returns:
        Updated link target
    """
    # Split anchor if present
    if '#' in link:
        link_path, anchor = link.split('#', 1)
        has_anchor = True
    else:
        link_path = link
        anchor = ''
        has_anchor = False
    
    # Extract just the filename
    filename = Path(link_path).name
    
    # Check if this file was moved
    if filename not in mapping:
        return link  # Not moved, keep as is
    
    new_path = mapping[filename]
    
    # Calculate relative path from current file to new location
    current_dir = current_file.parent
    target_path = root / new_path
    
    try:
        relative_path = target_path.relative_to(current_dir)
    except ValueError:
        # Can't compute relative path, use absolute from root
        relative_path = Path(new_path)
    
    # Convert to posix path for markdown
    updated_link = str(relative_path).replace('\\', '/')
    
    if has_anchor:
        updated_link = f"{updated_link}#{anchor}"
    
    return updated_link


def update_file_links(file_path: Path, mapping: Dict[str, str], root: Path, dry_run: bool = True) -> Tuple[int, List[str]]:
    """Update links in a single file.
    
    Args:
        file_path: Path to file to update
        mapping: File move mapping
        root: Repository root
        dry_run: If True, don't modify file
        
    Returns:
        Tuple of (num_updates, list of changes)
    """
    content = file_path.read_text(encoding='utf-8')
    original_content = content
    changes = []
    update_count = 0
    
    links = find_doc_links(content)
    
    for full_match, link_target in links:
        updated_link = update_link(link_target, mapping, file_path, root)
        
        if updated_link != link_target:
            # Build new full match
            text_part = full_match[1:full_match.index('](')]
            new_match = f"[{text_part}]({updated_link})"
            
            content = content.replace(full_match, new_match)
            changes.append(f"  {link_target} -> {updated_link}")
            update_count += 1
    
    if update_count > 0 and not dry_run:
        file_path.write_text(content, encoding='utf-8')
    
    return update_count, changes


def process_directory(directory: Path, mapping: Dict[str, str], root: Path, dry_run: bool = True) -> int:
    """Process all markdown files in directory.
    
    Args:
        directory: Directory to process
        mapping: File move mapping
        root: Repository root
        dry_run: If True, don't modify files
        
    Returns:
        Total number of updates
    """
    total_updates = 0
    
    for md_file in directory.rglob('*.md'):
        update_count, changes = update_file_links(md_file, mapping, root, dry_run)
        
        if update_count > 0:
            rel_path = md_file.relative_to(root)
            print(f"\n{rel_path} ({update_count} links updated):")
            for change in changes:
                print(change)
            total_updates += update_count
    
    return total_updates


def main():
    parser = argparse.ArgumentParser(description='Update documentation links')
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview changes without modifying files')
    parser.add_argument('--execute', action='store_true',
                       help='Execute link updates')
    parser.add_argument('--root', type=Path, default=Path.cwd(),
                       help='Repository root path')
    
    args = parser.parse_args()
    
    if not args.dry_run and not args.execute:
        print("ERROR: Must specify either --dry-run or --execute")
        return 1
    
    dry_run = args.dry_run
    root = args.root
    
    print("=" * 80)
    print("DOCUMENTATION LINK UPDATE")
    print("=" * 80)
    
    # Build mapping
    print("\nBuilding file move mapping...")
    mapping = build_move_mapping(root)
    print(f"Found {len(mapping)} moved files")
    
    # Process docs directory
    print("\nProcessing docs/ directory...")
    docs_updates = process_directory(root / 'docs', mapping, root, dry_run)
    
    # Process scripts directory (may have doc references)
    print("\nProcessing scripts/ directory...")
    scripts_updates = process_directory(root / 'scripts', mapping, root, dry_run)
    
    # Process main README
    print("\nProcessing README.md...")
    readme_updates, readme_changes = update_file_links(root / 'README.md', mapping, root, dry_run)
    if readme_updates > 0:
        print(f"README.md ({readme_updates} links updated):")
        for change in readme_changes:
            print(change)
    
    total = docs_updates + scripts_updates + readme_updates
    
    print("\n" + "=" * 80)
    if dry_run:
        print(f"DRY RUN: Would update {total} links")
        print("Run with --execute to apply changes")
    else:
        print(f"COMPLETE: Updated {total} links")
    print("=" * 80)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
