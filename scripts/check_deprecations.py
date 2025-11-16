"""CI check for deprecation policy enforcement.

This script is designed to run in CI to ensure deprecated items
are removed on schedule and no removed items are still referenced.

Usage in CI:
    python scripts/check_deprecations.py

Exit codes:
    0: All checks passed
    1: Policy violations found (expired items or removed items still referenced)
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.deprecation_audit import DeprecationAuditor


def main() -> int:
    """Run CI deprecation check."""
    root = Path(__file__).parent.parent
    auditor = DeprecationAuditor(root)
    auditor.load_deprecations()
    
    if not auditor.check_ci():
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
