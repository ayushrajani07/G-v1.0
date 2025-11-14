from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    # Ensure repository root is on sys.path so `src/...` imports work
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        import pytest  # type: ignore
    except Exception as e:  # pragma: no cover
        print("[run_ml_unit_tests] pytest is not installed. Install with: pip install pytest")
        print(f"Import error: {e}")
        return 1

    # Collect the specific tests we want to run
    tests = [
        str(root / "tests" / "test_config_modularization.py"),
        str(root / "tests" / "test_retrieval_mad_guard.py"),
    ]

    print("[run_ml_unit_tests] Running:")
    for t in tests:
        print(f"  - {t}")

    # Quiet mode; user can remove -q for verbose
    args = ["-q", *tests]
    rc = pytest.main(args)
    if rc == 0:
        print("[run_ml_unit_tests] All tests passed.")
    else:
        print(f"[run_ml_unit_tests] Tests failed with exit code {rc}.")
    return int(rc)


if __name__ == "__main__":
    sys.exit(main())
