"""Deprecation audit and enforcement script.

Part of Phase 2.3: Deprecation Cleanup (2025-11-16)

This script:
1. Audits all deprecated items from DEPRECATIONS.md
2. Identifies items past their removal date
3. Checks for remaining code references
4. Generates cleanup tasks
5. Can be used in CI to enforce deprecation policy

Usage:
    python scripts/deprecation_audit.py                  # Full audit
    python scripts/deprecation_audit.py --check-expired  # CI mode (fails if expired items exist)
    python scripts/deprecation_audit.py --cleanup-batch  # Generate cleanup tasks
"""
from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class DeprecatedItem:
    """Represents a deprecated item from DEPRECATIONS.md."""
    
    name: str
    replacement: str
    first_warn: str
    removal_date: str
    status: str  # 'active', 'removed', 'deprecated'
    category: str  # 'script', 'env_var', 'code_path', 'module'
    notes: str = ""
    
    def is_removed(self) -> bool:
        """Check if item is marked as REMOVED."""
        return 'REMOVED' in self.status or 'REMOVED' in self.removal_date
    
    def is_past_removal_date(self) -> bool:
        """Check if item is past its removal date."""
        if self.is_removed():
            return False  # Already removed
        
        # Parse removal date (formats: "2025-11-30", "R+1", "GATED")
        if 'R+' in self.removal_date or 'GATED' in self.removal_date or '—' in self.removal_date:
            return False  # Not a fixed date
        
        try:
            removal = datetime.strptime(self.removal_date, '%Y-%m-%d')
            return datetime.now(timezone.utc).replace(tzinfo=None) > removal
        except (ValueError, TypeError):
            return False
    
    def search_codebase(self, root: Path) -> list[tuple[Path, int]]:
        """Search for references to this item in the codebase.
        
        Returns:
            List of (file_path, line_number) tuples
        """
        references = []
        search_term = self.name
        
        # For env vars, search for the exact string in quotes
        if self.category == 'env_var':
            patterns = [
                f"'{search_term}'",
                f'"{search_term}"',
                f'getenv("{search_term}"',
                f"getenv('{search_term}'",
                f'environ.get("{search_term}"',
                f"environ.get('{search_term}'",
            ]
        else:
            patterns = [search_term]
        
        for pattern in patterns:
            try:
                # Use git grep for speed
                result = subprocess.run(
                    ['git', 'grep', '-n', '-F', pattern],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n'):
                        if not line:
                            continue
                        parts = line.split(':', 2)
                        if len(parts) >= 2:
                            file_path = root / parts[0]
                            line_num = int(parts[1])
                            
                            # Skip DEPRECATIONS.md itself
                            if 'DEPRECATIONS.md' in str(file_path):
                                continue
                            
                            # Skip this audit script
                            if 'deprecation_audit.py' in str(file_path):
                                continue
                            
                            references.append((file_path, line_num))
            except subprocess.TimeoutExpired:
                logger.warning(f"Search timeout for pattern: {pattern}")
            except Exception as e:
                logger.debug(f"Search error for {pattern}: {e}")
        
        return references


class DeprecationAuditor:
    """Audits deprecated items and enforces removal policy."""
    
    # Patterns to parse DEPRECATIONS.md
    REMOVED_PATTERN: ClassVar = re.compile(
        r'\(REMOVED\)\s+`([^`]+)`\s+\|\s+([^|]+)\|\s+([^|]+)\|\s+REMOVED\s+([0-9-]+)'
    )
    ACTIVE_PATTERN: ClassVar = re.compile(
        r'`([^`]+)`.*?\|\s+([^|]+)\|\s+([^|]+)\|\s+([^|]+)\|'
    )
    
    def __init__(self, root: Path):
        self.root = root
        self.deprecations_file = root / 'DEPRECATIONS.md'
        self.items: list[DeprecatedItem] = []
    
    def load_deprecations(self) -> None:
        """Load deprecated items from DEPRECATIONS.md."""
        if not self.deprecations_file.exists():
            logger.error(f"DEPRECATIONS.md not found at {self.deprecations_file}")
            return
        
        content = self.deprecations_file.read_text(encoding='utf-8')
        
        # Parse removed items
        for match in self.REMOVED_PATTERN.finditer(content):
            name = match.group(1).strip()
            replacement = match.group(2).strip()
            first_warn = match.group(3).strip()
            removal_date = match.group(4).strip()
            
            category = self._categorize_item(name)
            
            self.items.append(DeprecatedItem(
                name=name,
                replacement=replacement,
                first_warn=first_warn,
                removal_date=removal_date,
                status='removed',
                category=category
            ))
        
        # Parse active deprecations (more complex due to table format)
        lines = content.split('\n')
        in_active_table = False
        
        for line in lines:
            if '## Active Deprecations' in line:
                in_active_table = True
                continue
            
            if in_active_table and line.startswith('##'):
                in_active_table = False
            
            if in_active_table and '|' in line and not line.startswith('|---'):
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 5 and parts[1] and not parts[1].startswith('Item'):
                    name = parts[1].replace('`', '').strip()
                    if name and name != 'Item':
                        replacement = parts[2]
                        first_warn = parts[3]
                        removal_date = parts[4]
                        
                        category = self._categorize_item(name)
                        
                        self.items.append(DeprecatedItem(
                            name=name,
                            replacement=replacement,
                            first_warn=first_warn,
                            removal_date=removal_date,
                            status='active',
                            category=category
                        ))
        
        logger.info(f"Loaded {len(self.items)} deprecated items")
    
    def _categorize_item(self, name: str) -> str:
        """Categorize a deprecated item by its name."""
        if name.startswith('G6_') or name.startswith('KITE_'):
            return 'env_var'
        elif '.py' in name or 'scripts/' in name:
            return 'script'
        elif '.' in name and not name.endswith('.py'):
            return 'module'
        else:
            return 'code_path'
    
    def audit_expired(self) -> list[DeprecatedItem]:
        """Find items past their removal date."""
        expired = [item for item in self.items if item.is_past_removal_date()]
        
        logger.info(f"Found {len(expired)} items past removal date")
        for item in expired:
            logger.warning(
                f"EXPIRED: {item.name} (removal date: {item.removal_date})"
            )
        
        return expired
    
    def audit_removed_with_references(self) -> list[tuple[DeprecatedItem, list[tuple[Path, int]]]]:
        """Find items marked REMOVED but still referenced in code."""
        removed_with_refs = []
        
        removed_items = [item for item in self.items if item.is_removed()]
        logger.info(f"Checking {len(removed_items)} removed items for lingering references...")
        
        for item in removed_items:
            refs = item.search_codebase(self.root)
            if refs:
                removed_with_refs.append((item, refs))
                logger.warning(
                    f"REMOVED item still referenced: {item.name} ({len(refs)} references)"
                )
        
        return removed_with_refs
    
    def generate_report(self) -> str:
        """Generate comprehensive audit report."""
        lines = [
            "# Deprecation Audit Report",
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
            "",
            "## Summary",
            f"- Total deprecated items: {len(self.items)}",
            f"- Removed: {sum(1 for i in self.items if i.is_removed())}",
            f"- Active: {sum(1 for i in self.items if not i.is_removed())}",
            "",
        ]
        
        # Expired items
        expired = self.audit_expired()
        if expired:
            lines.extend([
                f"## ⚠️ Items Past Removal Date ({len(expired)})",
                "",
                "These items should be removed immediately:",
                ""
            ])
            for item in expired:
                lines.append(f"- `{item.name}` (due: {item.removal_date})")
                lines.append(f"  - Replacement: {item.replacement}")
                lines.append("")
        
        # Removed with references
        removed_refs = self.audit_removed_with_references()
        if removed_refs:
            lines.extend([
                f"## ⚠️ Removed Items Still Referenced ({len(removed_refs)})",
                "",
                "These items are marked REMOVED but still found in code:",
                ""
            ])
            for item, refs in removed_refs:
                lines.append(f"- `{item.name}` ({len(refs)} references)")
                for path, line_num in refs[:5]:  # Show first 5
                    rel_path = path.relative_to(self.root)
                    lines.append(f"  - {rel_path}:{line_num}")
                if len(refs) > 5:
                    lines.append(f"  - ... and {len(refs) - 5} more")
                lines.append("")
        
        # Categories breakdown
        by_category = {}
        for item in self.items:
            by_category.setdefault(item.category, []).append(item)
        
        lines.extend([
            "## Breakdown by Category",
            ""
        ])
        for category, items in sorted(by_category.items()):
            removed = sum(1 for i in items if i.is_removed())
            active = len(items) - removed
            lines.append(f"- **{category}**: {len(items)} total ({active} active, {removed} removed)")
        
        return '\n'.join(lines)
    
    def check_ci(self) -> bool:
        """CI check: fail if expired items exist or removed items are referenced.
        
        Returns:
            True if check passes, False otherwise
        """
        expired = self.audit_expired()
        removed_refs = self.audit_removed_with_references()
        
        if expired:
            logger.error(f"CI CHECK FAILED: {len(expired)} items past removal date")
            for item in expired:
                logger.error(f"  - {item.name} (due: {item.removal_date})")
            return False
        
        if removed_refs:
            logger.error(f"CI CHECK FAILED: {len(removed_refs)} removed items still referenced")
            for item, refs in removed_refs:
                logger.error(f"  - {item.name} ({len(refs)} references)")
            return False
        
        logger.info("✓ CI CHECK PASSED: No policy violations")
        return True


def main():
    parser = argparse.ArgumentParser(description='Audit deprecated items')
    parser.add_argument('--check-expired', action='store_true',
                       help='CI mode: fail if expired items exist')
    parser.add_argument('--report', type=str,
                       help='Output report to file')
    parser.add_argument('--root', type=Path, default=Path.cwd(),
                       help='Repository root path')
    
    args = parser.parse_args()
    
    auditor = DeprecationAuditor(args.root)
    auditor.load_deprecations()
    
    if args.check_expired:
        # CI mode
        if not auditor.check_ci():
            sys.exit(1)
    else:
        # Full audit mode
        report = auditor.generate_report()
        
        if args.report:
            Path(args.report).write_text(report, encoding='utf-8')
            logger.info(f"Report written to {args.report}")
        else:
            print(report)


if __name__ == '__main__':
    main()
