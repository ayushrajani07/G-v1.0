"""Documentation organization script for Phase 3.1.

Analyzes and categorizes 123+ markdown files in root directory,
then moves them to organized docs/ subdirectories.

Categories:
- architecture/     - System design, pipelines, architecture
- guides/          - User guides, operator manuals, how-tos
- development/     - Dev guidelines, testing, typing
- operations/      - Deployment, monitoring, recovery
- planning/        - Roadmaps, phases, initiatives
- analysis/        - Reports, summaries, investigations
- dashboards/      - Grafana, metrics, visualization
- ml/              - Machine learning, forecasting, ANN
- reference/       - Quick refs, catalogs, changelogs
- archive/         - Historical, obsolete, deprecated

Usage:
    python scripts/organize_docs.py --dry-run   # Preview changes
    python scripts/organize_docs.py --execute   # Execute moves
"""
from __future__ import annotations

import argparse
import shutil
import sys
from collections import defaultdict
from pathlib import Path

# Category mapping (filename patterns -> category)
DOC_CATEGORIES = {
    'architecture': [
        'ADVISOR_ARCHITECTURE', 'PIPELINE_DESIGN', 'PROVIDER_INTERFACE_NOTES',
        'PROVIDER_MODES', 'STREAMING_BUS_PROTOTYPE', 'FILE_STRUCTURE',
        'ERROR_ROUTING', 'COLUMN_STORE_INTEGRATION', 'ENHANCED_COLLECTOR_RETIREMENT',
    ],
    'guides': [
        'OPERATOR_MANUAL', 'USER_GUIDE', 'DEPLOYMENT_GUIDE', 'VERIFICATION_GUIDE',
        'RESTART_GUIDE_WINDOWS', 'PRE_PUSH_CHECKLIST', 'RECOVERY_CHECKLIST',
        'ANN_RUNBOOK', 'TESTS_RUNBOOK', 'QUICK_RESUME', 'REMEDIATION_EXECUTION_GUIDE',
    ],
    'development': [
        'DEVELOPMENT_GUIDELINES', 'TESTING', 'TYPING_ROLLOUT_PLAN',
        'GITHUB_SETUP', 'CODE_HEALTH_ROADMAP', 'TECH_DEBT_HOTSPOTS',
        'TEST_COVERAGE_PROGRESS', 'DEPENDENCIES',
    ],
    'operations': [
        'ADVISOR_OBSERVABILITY', 'MARKET_CLOSE_SHUTDOWN', 'BACKOFF_SCHEDULING_MODERNIZATION',
        'CYCLE_ENV_SETTINGS', 'ENV_FLAGS_TABLES', 'LOCAL_PATHS', 'EGRESS_FREEZE',
        'METRICS_GOVERNANCE',
    ],
    'planning': [
        'ANALYSIS_ACTION_PLAN', 'LONG_TERM_TODO', 'DEFERRED_ENHANCEMENTS',
        'CLEANUP_PLAN', 'MIGRATION', 'Q4_2025_INITIATIVE',
        'PHASE1_COMPLETION', 'PHASE2_PLAN', 'PHASE2_MIGRATION_GUIDE', 'PHASE6_SCOPE',
        'PHASE7_SCOPE', 'PHASE10_SCOPE', 'WAVE_3_SUMMARY', 'WAVE3_SUMMARY', 'WAVE4_TRACKING',
        'EFFICIENCY_MUST_HAVES', 'HIGH_IMPACT_OPTIMIZATION', 'OPTIMIZATION_OPPORTUNITIES',
        'CYCLE_PERFORMANCE_ROADMAP', 'CYCLE_PERFORMANCE_IMPLEMENTATION',
    ],
    'analysis': [
        'ANALYSIS_SUMMARY', 'ANALYSIS_INDEX', 'CORE_PROJECT_ANALYSIS',
        'COMPLETION_SUMMARY', 'PROGRESS_SUMMARY', 'INEFFICIENCIES_REPORT',
        'REMEDIATION_ACTIONS', 'REMEDIATION_IMPLEMENTATION_PLAN', 'REMEDIATION_EXECUTION_SUMMARY',
        'PUBLISHER_TRANSFORMATION_SUMMARY', 'PYTHON_RUNTIME_UNIFICATION',
        'PANELS_BRIDGE_SUMMARY_UNIFICATION', 'PANEL_RENAME_SUMMARY',
        'EMITTERS_REPORT_TEMP',
    ],
    'dashboards': [
        'GRAFANA_', 'DASHBOARD_', 'METRICS_CATALOG', 'METRICS_PANELS_HINTS',
        'ALERTS_PANEL_ENHANCEMENT', 'FOOTER_', 'PANEL_SEPARATOR_ENHANCEMENT',
        'OVERLAY_VISUALIZATION', 'TIME_SERIES_MULTI_PANE_PANEL',
        'ISSUE_REMOVE_LEGACY_PANELS_BRIDGE', 'SSE_METRICS_DEFERRAL_BOOKMARK',
        'grafna', 'EMISSION_BATCHER_ENHANCEMENTS',
    ],
    'ml': [
        'ML_', 'ANN_', 'GRID_EVAL_ANN', 'CALIBRATION_K_GUIDE',
    ],
    'reference': [
        'QUICK_REFERENCE', 'CHANGELOG', 'DEPRECATIONS', 'DEPRECATION_SUMMARY',
        'PERFORMANCE', 'RATIONAL',
    ],
    'archive': [
        'README_2025', 'README_COMPREHENSIVE', 'README_CONSOLIDATED', 'README_HYBRID',
        'README_QUANTILE', 'README_web_dashboard', 'PHASE2_TASK', 'FOOTER_SCREENSHOT_MATCH',
        'ANALYSIS_ACTION_PLAN_EXTENDED',
    ],
}


def categorize_file(filename: str) -> str:
    """Categorize a markdown file by filename patterns.
    
    Args:
        filename: Filename without extension
        
    Returns:
        Category name or 'uncategorized'
    """
    filename_upper = filename.upper()
    
    for category, patterns in DOC_CATEGORIES.items():
        for pattern in patterns:
            if pattern.upper() in filename_upper:
                return category
    
    return 'uncategorized'


def analyze_docs(root: Path) -> dict[str, list[str]]:
    """Analyze all markdown files in root directory.
    
    Args:
        root: Root directory path
        
    Returns:
        Dictionary mapping categories to list of filenames
    """
    categorized = defaultdict(list)
    
    for md_file in root.glob('*.md'):
        if md_file.name == 'README.md':
            continue  # Keep main README in root
        
        filename_no_ext = md_file.stem
        category = categorize_file(filename_no_ext)
        categorized[category].append(md_file.name)
    
    return dict(categorized)


def print_analysis(categorized: dict[str, list[str]]) -> None:
    """Print analysis results."""
    print("\n" + "=" * 80)
    print("DOCUMENTATION ORGANIZATION ANALYSIS")
    print("=" * 80)
    
    total_files = sum(len(files) for files in categorized.values())
    print(f"\nTotal files to organize: {total_files}")
    print(f"Categories: {len(categorized)}")
    
    for category in sorted(categorized.keys()):
        files = categorized[category]
        print(f"\n{category.upper()} ({len(files)} files):")
        for filename in sorted(files)[:10]:  # Show first 10
            print(f"  - {filename}")
        if len(files) > 10:
            print(f"  ... and {len(files) - 10} more")


def create_directory_structure(root: Path, dry_run: bool = True) -> None:
    """Create docs/ directory structure.
    
    Args:
        root: Root directory path
        dry_run: If True, only print what would be created
    """
    docs_dir = root / 'docs'
    
    categories = [
        'architecture', 'guides', 'development', 'operations',
        'planning', 'analysis', 'dashboards', 'ml', 'reference', 'archive'
    ]
    
    print("\n" + "=" * 80)
    print("CREATING DIRECTORY STRUCTURE")
    print("=" * 80)
    
    for category in categories:
        category_dir = docs_dir / category
        if dry_run:
            print(f"Would create: {category_dir}")
        else:
            category_dir.mkdir(parents=True, exist_ok=True)
            print(f"Created: {category_dir}")


def move_files(root: Path, categorized: dict[str, list[str]], dry_run: bool = True) -> None:
    """Move files to categorized directories.
    
    Args:
        root: Root directory path
        categorized: Dictionary mapping categories to filenames
        dry_run: If True, only print what would be moved
    """
    docs_dir = root / 'docs'
    
    print("\n" + "=" * 80)
    print("MOVING FILES")
    print("=" * 80)
    
    moved_count = 0
    
    for category, files in sorted(categorized.items()):
        category_dir = docs_dir / category
        
        print(f"\n{category.upper()}:")
        for filename in sorted(files):
            source = root / filename
            dest = category_dir / filename
            
            if dry_run:
                print(f"  {filename} -> docs/{category}/")
            else:
                if source.exists():
                    shutil.move(str(source), str(dest))
                    print(f"  Moved: {filename}")
                    moved_count += 1
                else:
                    print(f"  SKIP: {filename} (not found)")
    
    if not dry_run:
        print(f"\nTotal files moved: {moved_count}")


def create_docs_index(root: Path, categorized: dict[str, list[str]], dry_run: bool = True) -> None:
    """Create docs/README.md index file.
    
    Args:
        root: Root directory path
        categorized: Dictionary mapping categories to filenames
        dry_run: If True, only print what would be created
    """
    docs_dir = root / 'docs'
    index_file = docs_dir / 'README.md'
    
    category_descriptions = {
        'architecture': 'System design, pipelines, and architectural decisions',
        'guides': 'User guides, operator manuals, and how-to documentation',
        'development': 'Development guidelines, testing, and code quality',
        'operations': 'Deployment, monitoring, and operational procedures',
        'planning': 'Roadmaps, phases, and project planning documents',
        'analysis': 'Analysis reports, summaries, and investigations',
        'dashboards': 'Grafana dashboards, metrics, and visualization',
        'ml': 'Machine learning, forecasting, and ANN documentation',
        'reference': 'Quick references, catalogs, and changelogs',
        'archive': 'Historical and deprecated documentation',
        'uncategorized': 'Uncategorized documentation (needs review)',
    }
    
    content = [
        "# G6 Platform Documentation",
        "",
        "_Organized documentation for the G6 Options Trading Platform._",
        "",
        "## Quick Links",
        "",
        "- [Main README](../README.md) - Platform overview and quick start",
        "- [Operator Manual](guides/OPERATOR_MANUAL.md) - Production operations",
        "- [Development Guidelines](development/DEVELOPMENT_GUIDELINES.md) - Contributing guide",
        "- [Testing Guide](development/TESTING.md) - Running tests",
        "",
        "## Documentation Categories",
        "",
    ]
    
    for category in sorted(categorized.keys()):
        files = categorized[category]
        description = category_descriptions.get(category, 'Documentation files')
        
        content.append(f"### {category.title()}")
        content.append(f"_{description}_")
        content.append("")
        content.append(f"**{len(files)} documents:**")
        content.append("")
        
        for filename in sorted(files):
            title = filename.replace('.md', '').replace('_', ' ').title()
            content.append(f"- [{title}]({category}/{filename})")
        
        content.append("")
    
    content.append("---")
    content.append("")
    content.append("_Documentation organized: 2025-11-16 (Phase 3.1)_")
    
    index_content = '\n'.join(content)
    
    if dry_run:
        print("\n" + "=" * 80)
        print("DOCS INDEX PREVIEW")
        print("=" * 80)
        print(index_content[:500] + "\n... (truncated)")
    else:
        index_file.write_text(index_content, encoding='utf-8')
        print(f"\nCreated: {index_file}")


def main():
    parser = argparse.ArgumentParser(description='Organize G6 documentation')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Preview changes without executing')
    parser.add_argument('--execute', action='store_true',
                       help='Execute the reorganization')
    parser.add_argument('--root', type=Path, default=Path.cwd(),
                       help='Repository root path')
    
    args = parser.parse_args()
    
    if not args.dry_run and not args.execute:
        print("ERROR: Must specify either --dry-run or --execute")
        return 1
    
    dry_run = args.dry_run
    root = args.root
    
    # Analyze
    categorized = analyze_docs(root)
    print_analysis(categorized)
    
    # Create structure
    create_directory_structure(root, dry_run=dry_run)
    
    # Move files
    move_files(root, categorized, dry_run=dry_run)
    
    # Create index
    create_docs_index(root, categorized, dry_run=dry_run)
    
    if dry_run:
        print("\n" + "=" * 80)
        print("DRY RUN COMPLETE - No files were modified")
        print("Run with --execute to perform the reorganization")
        print("=" * 80)
    else:
        print("\n" + "=" * 80)
        print("REORGANIZATION COMPLETE")
        print("=" * 80)
        print("\nNext steps:")
        print("1. Review docs/README.md")
        print("2. Update internal documentation links")
        print("3. Commit changes to version control")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
