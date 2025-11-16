"""Pytest marker validation and migration tool.

Part of Phase 2.1: Test Infrastructure Enhancement (2025-11-16)

Validates and suggests migrations for pytest markers to align with
the simplified 3-marker strategy: unit, integration, slow.

Usage:
    python scripts/validate_test_markers.py --check    # Check current usage
    python scripts/validate_test_markers.py --suggest  # Suggest improvements
"""
from __future__ import annotations

import argparse
import ast
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

# Recommended marker strategy
CORE_MARKERS = {'unit', 'integration', 'slow'}
LEGACY_MARKERS = {'optional', 'perf', 'serial', 'asyncio', 'metrics_no_reset'}
PYTEST_BUILTIN = {'parametrize', 'skip', 'skipif', 'timeout', 'xfail'}


def find_markers_in_file(file_path: Path) -> List[Tuple[str, int]]:
    """Find all pytest markers in a file.
    
    Args:
        file_path: Path to Python test file
        
    Returns:
        List of (marker_name, line_number) tuples
    """
    markers = []
    
    try:
        content = file_path.read_text(encoding='utf-8')
        
        # Find @pytest.mark.marker_name
        import re
        pattern = r'@pytest\.mark\.(\w+)'
        
        for line_num, line in enumerate(content.splitlines(), 1):
            matches = re.findall(pattern, line)
            for marker in matches:
                if marker not in PYTEST_BUILTIN:
                    markers.append((marker, line_num))
    
    except Exception as e:
        print(f"Warning: Could not parse {file_path}: {e}")
    
    return markers


def analyze_test_markers(tests_dir: Path) -> Dict[str, List[Tuple[Path, int]]]:
    """Analyze all test markers in tests directory.
    
    Args:
        tests_dir: Path to tests directory
        
    Returns:
        Dictionary mapping marker names to list of (file, line) tuples
    """
    marker_usage = defaultdict(list)
    
    for test_file in tests_dir.rglob('test_*.py'):
        markers = find_markers_in_file(test_file)
        for marker, line_num in markers:
            marker_usage[marker].append((test_file, line_num))
    
    return dict(marker_usage)


def categorize_markers(marker_usage: Dict[str, List]) -> Dict[str, List[str]]:
    """Categorize markers by type.
    
    Args:
        marker_usage: Marker usage dictionary
        
    Returns:
        Dictionary with categories: core, legacy, unknown
    """
    categories = {
        'core': [],
        'legacy': [],
        'unknown': []
    }
    
    for marker in marker_usage.keys():
        if marker in CORE_MARKERS:
            categories['core'].append(marker)
        elif marker in LEGACY_MARKERS:
            categories['legacy'].append(marker)
        else:
            categories['unknown'].append(marker)
    
    return categories


def print_analysis(marker_usage: Dict[str, List], tests_dir: Path):
    """Print marker usage analysis."""
    print("\n" + "=" * 80)
    print("TEST MARKER ANALYSIS")
    print("=" * 80)
    
    categories = categorize_markers(marker_usage)
    
    # Print summary
    print(f"\nTotal unique markers: {len(marker_usage)}")
    print(f"  Core markers: {len(categories['core'])} {categories['core']}")
    print(f"  Legacy markers: {len(categories['legacy'])} {categories['legacy']}")
    print(f"  Unknown markers: {len(categories['unknown'])} {categories['unknown']}")
    
    # Print detailed usage
    for category in ['core', 'legacy', 'unknown']:
        if not categories[category]:
            continue
        
        print(f"\n{category.upper()} MARKERS:")
        for marker in sorted(categories[category]):
            occurrences = marker_usage[marker]
            print(f"  @pytest.mark.{marker} ({len(occurrences)} uses)")
            
            # Show first 5 occurrences
            for file_path, line_num in sorted(occurrences)[:5]:
                rel_path = file_path.relative_to(tests_dir.parent)
                print(f"    {rel_path}:{line_num}")
            
            if len(occurrences) > 5:
                print(f"    ... and {len(occurrences) - 5} more")


def suggest_migrations(marker_usage: Dict[str, List], tests_dir: Path):
    """Suggest marker migrations."""
    print("\n" + "=" * 80)
    print("MIGRATION SUGGESTIONS")
    print("=" * 80)
    
    # Check for tests without core markers
    all_test_files = set(tests_dir.rglob('test_*.py'))
    files_with_markers = set()
    
    for occurrences in marker_usage.values():
        for file_path, _ in occurrences:
            files_with_markers.add(file_path)
    
    unmarked_files = all_test_files - files_with_markers
    
    if unmarked_files:
        print(f"\n⚠️  {len(unmarked_files)} test files without markers:")
        print("Consider adding @pytest.mark.unit or @pytest.mark.integration\n")
        for file_path in sorted(unmarked_files)[:10]:
            rel_path = file_path.relative_to(tests_dir.parent)
            print(f"  {rel_path}")
        if len(unmarked_files) > 10:
            print(f"  ... and {len(unmarked_files) - 10} more")
    
    # Suggest migrations for legacy markers
    if 'optional' in marker_usage:
        print(f"\n💡 'optional' marker ({len(marker_usage['optional'])} uses):")
        print("  → Migrate to 'slow' if tests are long-running")
        print("  → Remove if tests should run by default")
    
    if 'perf' in marker_usage:
        print(f"\n💡 'perf' marker ({len(marker_usage['perf'])} uses):")
        print("  → Consider adding 'slow' marker as well")
        print("  → Keep 'perf' for documentation purposes")
    
    # Summary
    print("\n" + "=" * 80)
    print("RECOMMENDATIONS:")
    print("=" * 80)
    print("✅ Use '@pytest.mark.unit' for fast, isolated unit tests")
    print("✅ Use '@pytest.mark.integration' for multi-component tests")
    print("✅ Use '@pytest.mark.slow' for tests taking >2 seconds")
    print("📝 Legacy markers (optional, perf) can remain for backward compatibility")
    print("🔧 'serial' marker is required for tests with global mutable state")


def main():
    parser = argparse.ArgumentParser(description='Validate pytest markers')
    parser.add_argument('--check', action='store_true',
                       help='Check current marker usage')
    parser.add_argument('--suggest', action='store_true',
                       help='Suggest marker improvements')
    parser.add_argument('--tests-dir', type=Path, default=Path('tests'),
                       help='Path to tests directory')
    
    args = parser.parse_args()
    
    if not args.check and not args.suggest:
        print("ERROR: Must specify --check or --suggest")
        return 1
    
    tests_dir = args.tests_dir
    if not tests_dir.exists():
        print(f"ERROR: Tests directory not found: {tests_dir}")
        return 1
    
    # Analyze markers
    marker_usage = analyze_test_markers(tests_dir)
    
    if args.check:
        print_analysis(marker_usage, tests_dir)
    
    if args.suggest:
        suggest_migrations(marker_usage, tests_dir)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
