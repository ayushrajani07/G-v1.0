"""Dashboard Guard Script

Usage:
  python scripts/grafana/dashboard_guard.py --scan --out grafana/dashboard_hashes.json
  python scripts/grafana/dashboard_guard.py --check --baseline grafana/dashboard_hashes.json

Purpose:
  Prevent silent regression of Grafana dashboards (panel drops, minimal resets).

Logic:
  - Load all *.json under baseline dashboards directory.
  - Normalize panel definitions (remove volatile fields like position timestamps if any).
  - Compute SHA256 per file and record panel_count.
  - In check mode, compare against baseline hash file; fail (exit code 2) if:
      * panel_count decreased
      * hash matches a known minimal hash (optional list)
      * file missing
"""
from __future__ import annotations

import argparse
import json
import hashlib
import sys
from pathlib import Path
from typing import Any, Dict

BASELINE_DIR = Path('.grafana/provisioning_baseline/dashboards_src')
MINIMAL_PANEL_THRESHOLD = 2  # heuristic: consider <=2 panels suspicious for complex dashboards

def _load_json(path: Path) -> Dict[str, Any] | None:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def _norm_panels(d: Dict[str, Any]) -> Any:
    panels = d.get('panels')
    if not isinstance(panels, list):
        return []
    # Keep only stable fields per panel
    slim = []
    for p in panels:
        if not isinstance(p, dict):
            continue
        slim.append({
            'title': p.get('title'),
            'type': p.get('type'),
            'datasource': p.get('datasource'),
            'targets': p.get('targets'),
        })
    return slim

def compute_hash(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(blob).hexdigest()

def scan(out_file: Path) -> None:
    result: Dict[str, Dict[str, Any]] = {}
    for path in sorted(BASELINE_DIR.glob('*.json')):
        data = _load_json(path)
        if not data:
            continue
        slim = _norm_panels(data)
        h = compute_hash(slim)
        result[path.name] = {
            'hash': h,
            'panel_count': len(slim),
            'title': data.get('title'),
        }
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, sort_keys=True)
    print(f"Baseline written: {out_file} ({len(result)} dashboards)")

def check(baseline_file: Path) -> int:
    if not baseline_file.is_file():
        print(f"Baseline missing: {baseline_file}", file=sys.stderr)
        return 3
    baseline = json.loads(baseline_file.read_text(encoding='utf-8'))
    failed = False
    for fname, meta in baseline.items():
        cur_path = BASELINE_DIR / fname
        data = _load_json(cur_path)
        if not data:
            print(f"MISSING: {fname}")
            failed = True
            continue
        slim = _norm_panels(data)
        cur_hash = compute_hash(slim)
        cur_count = len(slim)
        base_hash = meta.get('hash')
        base_count = meta.get('panel_count', -1)
        if cur_count < base_count:
            print(f"REGRESSION panels {fname}: {cur_count} < {base_count}")
            failed = True
        if cur_count <= MINIMAL_PANEL_THRESHOLD and base_count > MINIMAL_PANEL_THRESHOLD:
            print(f"SUSPICIOUS minimal panel count {fname}: {cur_count}")
            failed = True
        if cur_hash == base_hash and cur_count <= MINIMAL_PANEL_THRESHOLD and base_count > MINIMAL_PANEL_THRESHOLD:
            print(f"HASH_MATCH_MINIMAL {fname}: hash unchanged but now minimal")
            failed = True
    return 2 if failed else 0

def main() -> None:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--scan', action='store_true')
    mode.add_argument('--check', action='store_true')
    ap.add_argument('--out', type=Path, default=Path('grafana/dashboard_hashes.json'))
    ap.add_argument('--baseline', type=Path, default=Path('grafana/dashboard_hashes.json'))
    args = ap.parse_args()
    if args.scan:
        scan(args.out)
        sys.exit(0)
    rc = check(args.baseline)
    sys.exit(rc)

if __name__ == '__main__':
    main()
