from __future__ import annotations

import os
import sys
import glob
import time
from zipfile import ZipFile, ZIP_DEFLATED
from typing import Iterable, List, Optional


def _ensure_dir(path: str) -> None:
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def _gather_existing(patterns: Iterable[str]) -> List[str]:
    files: List[str] = []
    for pat in patterns:
        # Use glob with recursive for ** patterns
        matches = glob.glob(pat, recursive=True)
        for m in matches:
            if os.path.isfile(m):
                files.append(m)
    # Deduplicate while preserving order
    seen = set()
    out: List[str] = []
    for f in files:
        if f not in seen:
            out.append(f)
            seen.add(f)
    return out


def collect(defaults: bool = True, extra_patterns: Optional[List[str]] = None) -> Optional[str]:
    """
    Collect pytest artifacts into a timestamped zip under artifacts/.

    Returns the zip path if any files were collected; otherwise None.
    """
    cwd = os.getcwd()
    artifacts_dir = os.path.join(cwd, "artifacts")
    _ensure_dir(artifacts_dir)

    patterns: List[str] = []
    if defaults:
        patterns.extend(
            [
                # Primary captures
                "pytest_core_out.txt",
                os.path.join("artifacts", "pytest_core_junit.xml"),
                # Common diagnostics
                "diag_summary.txt",
                "remaining_failures.txt",
                "pytest_*.txt",
                "test_results*.txt",
                # Logs
                "collector_debug*.log",
                os.path.join("logs", "**", "*.log"),
            ]
        )
    if extra_patterns:
        patterns.extend(extra_patterns)

    files = _gather_existing(patterns)
    if not files:
        return None

    ts = time.strftime("%Y%m%d_%H%M%S")
    zip_path = os.path.join(artifacts_dir, f"pytest_artifacts_{ts}.zip")

    # Write files with relative paths to keep zip tidy
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as zf:
        for f in files:
            try:
                arcname = os.path.relpath(f, cwd)
                zf.write(f, arcname=arcname)
            except Exception:
                # Skip problematic files, continue
                continue

    return zip_path


def main() -> None:  # pragma: no cover - CLI convenience
    zip_path = collect(defaults=True)
    if zip_path:
        print(zip_path)
    else:
        print("No artifacts found to collect.")


if __name__ == "__main__":
    main()
