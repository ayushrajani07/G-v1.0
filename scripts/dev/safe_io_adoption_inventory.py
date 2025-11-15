"""Safe I/O Adoption Inventory Script

Scans the repository for direct filesystem I/O usage that should
prefer the centralized safe_* wrappers (safe_write_text, safe_append_line,
safe_read_json) defined in error handling.

Heuristics (simple substring matching):
  - open( with mode containing w, a, x
  - Path.write_text(
  - Path.open( with w/a/x
  - json.dump(
  - json.load( (to encourage centralization via safe_read_json where appropriate)

Exclusions:
  - Any lines already calling safe_* wrappers
  - The error handling module itself (defines wrappers)
  - Test files under tests/ unless --include-tests specified

Outputs:
  - Prints a human readable summary to stdout
  - Optionally writes a JSON report (pass --output path)

Usage examples:
  python scripts/dev/safe_io_adoption_inventory.py
  python scripts/dev/safe_io_adoption_inventory.py --output inventory/safe_io_report.json
  python scripts/dev/safe_io_adoption_inventory.py --include-tests
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]

SAFE_WRAPPER_NAMES = {"safe_write_text", "safe_append_line", "safe_read_json"}
EXCLUDE_FILES = {"error_handling.py"}
DEFAULT_SCAN_DIRS = ["src", "scripts"]

IO_PATTERNS = {
    "open_write": re.compile(r"open\([^)]*['\"](w|a|x)['\"]"),
    "path_write_text": re.compile(r"\.write_text\("),
    "path_open_write": re.compile(r"\.open\([^)]*['\"](w|a|x)['\"]"),
    "json_dump": re.compile(r"json\.dump\("),
    "json_load": re.compile(r"json\.load\("),
}


def should_skip(path: Path, include_tests: bool) -> bool:
    if any(part in {"venv", "__pycache__", ".git"} for part in path.parts):
        return True
    if path.name in EXCLUDE_FILES:
        return True
    if not include_tests and "tests" in path.parts:
        return True
    if path.suffix != ".py":
        return True
    return False


def line_has_wrapper(line: str) -> bool:
    return any(name in line for name in SAFE_WRAPPER_NAMES)


def scan_file(path: Path):
    results = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return results
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line_has_wrapper(line):
            continue
        for key, pattern in IO_PATTERNS.items():
            if pattern.search(line):
                results.append(
                    {
                        "file": str(path.relative_to(REPO_ROOT)),
                        "line": lineno,
                        "pattern": key,
                        "code": line.strip(),
                    }
                )
    return results


def build_report(include_tests: bool) -> dict:
    all_matches = []
    for root_name in DEFAULT_SCAN_DIRS:
        root_dir = REPO_ROOT / root_name
        if not root_dir.exists():
            continue
        for path in root_dir.rglob("*.py"):
            if should_skip(path, include_tests):
                continue
            matches = scan_file(path)
            if matches:
                all_matches.extend(matches)
    summary = {
        "total_matches": len(all_matches),
        "by_pattern": {},
    }
    for m in all_matches:
        summary["by_pattern"].setdefault(m["pattern"], 0)
        summary["by_pattern"][m["pattern"]] += 1
    return {"summary": summary, "matches": all_matches}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inventory direct file I/O usage not using safe wrappers.")
    parser.add_argument("--output", help="Optional path to write JSON report.")
    parser.add_argument(
        "--include-tests", action="store_true", help="Include test files in scan (off by default)."
    )
    args = parser.parse_args(argv)

    report = build_report(include_tests=args.include_tests)

    summary = report["summary"]
    print("Safe I/O Adoption Inventory")
    print("Root:", REPO_ROOT)
    print("Total I/O candidates:", summary["total_matches"])
    for pattern, count in sorted(summary["by_pattern"].items()):
        print(f"  {pattern}: {count}")

    if summary["total_matches"]:
        print("\nFirst 20 candidates:")
        for entry in report["matches"][:20]:
            print(f"  {entry['file']}:{entry['line']} [{entry['pattern']}] {entry['code']}")
    else:
        print("\nNo direct I/O candidates found outside safe wrappers.")

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nReport written to {out_path}")


if __name__ == "__main__":  # pragma: no cover
    main()
