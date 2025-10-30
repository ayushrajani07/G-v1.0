import os
import sys
import subprocess
import shutil
from pathlib import Path
import pytest


@pytest.mark.skipif(shutil.which("vulture") is None, reason="vulture not installed; skip dead code guard")
def test_no_dead_code_in_src_via_vulture():
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"
    assert src_dir.exists(), f"src directory not found at {src_dir}"

    allowlist_file = repo_root / "dead_code_allowlist.txt"
    allow_patterns = []
    if allowlist_file.exists():
        for line in allowlist_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            allow_patterns.append(line.lower())

    # Run vulture only on src/ to avoid scanning archived or tests
    cmd = ["vulture", str(src_dir)]
    # Confidence threshold can be tuned; 60 is a reasonable default to avoid noise
    cmd += ["--min-confidence", "60"]

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(repo_root))
    stdout = proc.stdout

    findings = []
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Typical vulture line: path:lineno: message (confidence%)
        # Filter any line that matches an allowlist substring
        lower = line.lower()
        if any(pat in lower for pat in allow_patterns):
            continue
        # Keep only Python paths from src/
        if "src" + os.sep in line or "/src/" in line:
            findings.append(line)

    if findings:
        sample = "\n".join(findings[:30])
        more = "" if len(findings) <= 30 else f"\n... and {len(findings)-30} more"
        pytest.fail(
            "Dead code detected by vulture (src/ only). Review or add to dead_code_allowlist.txt if intentional.\n"
            + sample + more
        )
