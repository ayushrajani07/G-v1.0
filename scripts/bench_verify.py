#!/usr/bin/env python
"""DEPRECATED WRAPPER: bench_verify.py -> bench_tools.py verify

Unified command:
    python scripts/bench_tools.py verify <artifact_dir>
"""
from __future__ import annotations

import os
import os
import subprocess
import sys

from pathlib import Path
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config.env_config import EnvConfig


def main(argv: list[str] | None = None) -> int:  # noqa: D401
    if argv is None:
        argv = sys.argv[1:]
    if not EnvConfig.get_bool('G6_SUPPRESS_DEPRECATIONS', False):
        print('[DEPRECATED] bench_verify.py -> use bench_tools.py verify', file=sys.stderr)
    return subprocess.call([sys.executable, 'scripts/bench_tools.py', 'verify', *argv])

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
