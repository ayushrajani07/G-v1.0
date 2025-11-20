"""Grafana Dashboard UID Duplicate Checker

Usage:
  python scripts/grafana/uid_checker.py --paths .grafana/provisioning_baseline/dashboards_src grafana/dashboards/miscellaneous

Exit codes:
  0 -> no duplicates
  4 -> duplicates found
  5 -> error scanning

Scans given directories (default: baseline src) for *.json dashboards and reports any duplicate `uid` fields.
Also flags missing or empty uid fields.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

DEFAULT_PATHS = [Path('.grafana/provisioning_baseline/dashboards_src')]

def load_uid(path: Path) -> str | None:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        uid = data.get('uid')
        if isinstance(uid, str) and uid.strip():
            return uid.strip()
        return None
    except Exception:
        return None

def scan(paths: List[Path]) -> int:
    uid_map: Dict[str, List[str]] = {}
    missing: List[str] = []
    for base in paths:
        if not base.is_dir():
            continue
        for file in base.glob('*.json'):
            uid = load_uid(file)
            if not uid:
                missing.append(str(file))
                continue
            uid_map.setdefault(uid, []).append(str(file))
    duplicates = {u: files for u, files in uid_map.items() if len(files) > 1}
    if missing:
        print('MISSING_UID:')
        for f in missing:
            print(f'  - {f}')
    if duplicates:
        print('DUPLICATE_UIDS:')
        for u, files in duplicates.items():
            print(f'  UID {u}:')
            for f in files:
                print(f'    - {f}')
        return 4
    if missing:
        return 4  # treat missing uid also as failure
    print('OK: no duplicate or missing UIDs')
    return 0

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--paths', nargs='*', default=[str(p) for p in DEFAULT_PATHS])
    args = ap.parse_args()
    scan_paths = [Path(p) for p in args.paths]
    rc = scan(scan_paths)
    sys.exit(rc)

if __name__ == '__main__':
    main()
