#!/usr/bin/env python
"""Seed or update nested ANN baseline JSON from a ranking CSV.

- Reads ann_ranking.csv (from a harness run) and extracts metrics for retrieval k=10
  windows (default: 60,120).
- Updates baselines/ann_daily_baseline.json under the specified index branch.
- Creates a timestamped backup of the full baseline document before writing.

Usage examples:
  python scripts/ml/seed_ann_baseline_from_ranking.py --index BANKNIFTY \
    --ranking results/ann_health_exporter_tmp/combined/ann_ranking.csv

  python scripts/ml/seed_ann_baseline_from_ranking.py --index NIFTY \
    --from-results results/ann_large_tuned/combined
"""
from __future__ import annotations
import argparse, csv, json, sys
from pathlib import Path
import datetime

REPO_ROOT = Path(__file__).resolve().parents[2]

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--index', required=True, help='Index symbol, e.g., NIFTY or BANKNIFTY')
    ap.add_argument('--ranking', help='Path to ann_ranking.csv (takes precedence)')
    ap.add_argument('--from-results', help='Directory containing ann_ranking.csv (defaults to results/ann_health_exporter_tmp/combined)')
    ap.add_argument('--baseline', default=str(REPO_ROOT / 'baselines' / 'ann_daily_baseline.json'))
    ap.add_argument('--windows', default='60,120', help='Windows to include, comma-separated')
    ap.add_argument('--k', default='10', help='k value to filter (default 10)')
    return ap.parse_args()

def load_ranking_csv(path: Path) -> dict:
    out = {}
    with path.open('r', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                if str(row.get('mode')) != 'retrieval':
                    continue
                w = str(row.get('window'))
                k = str(row.get('k'))
                key = f'retrieval_{w}_k{k}'
                out[key] = {
                    'speedup_avg': float(row.get('speedup_avg') or 0.0),
                    'prune_ratio_avg': float(row.get('prune_ratio_avg') or 0.0),
                    'q50_mad_avg': float(row.get('q50_mad_avg') or 0.0),
                    'rows': int(row.get('rows') or 0),
                }
            except Exception:
                continue
    return out

def main():
    ns = parse_args()
    # Locate ranking
    ranking_path = None
    if ns.ranking:
        ranking_path = Path(ns.ranking)
    else:
        base = Path(ns.from_results) if ns.from_results else REPO_ROOT / 'results' / 'ann_health_exporter_tmp' / 'combined'
        ranking_path = base / 'ann_ranking.csv'
    if not ranking_path.exists():
        print('[error] ranking csv not found:', ranking_path)
        sys.exit(2)
    print('[seed] using ranking:', ranking_path)

    ranking = load_ranking_csv(ranking_path)
    desired_windows = [w.strip() for w in ns.windows.split(',') if w.strip()]
    keys = [f'retrieval_{w}_k{ns.k}' for w in desired_windows]
    # Validate presence and minimal rows
    missing = [k for k in keys if k not in ranking]
    if missing:
        print('[error] missing keys in ranking:', ', '.join(missing))
        sys.exit(2)
    low_rows = {k: ranking[k].get('rows', 0) for k in keys if ranking[k].get('rows', 0) <= 0}
    if low_rows:
        print('[warn] some keys have zero rows; seeding anyway:', low_rows)

    baseline_path = Path(ns.baseline)
    if not baseline_path.exists():
        print('[error] baseline not found:', baseline_path)
        sys.exit(2)
    doc = json.loads(baseline_path.read_text(encoding='utf-8'))

    # Normalize to nested structure if flat
    if isinstance(doc, dict) and any(k.startswith('retrieval_') for k in doc.keys()):
        # Assume existing flat content represents NIFTY if not specified; keep under 'NIFTY'
        doc = {'NIFTY': doc}
        print('[info] converted flat baseline to nested under NIFTY for compatibility')

    # Prepare updated branch for target index
    branch = {}
    for k in keys:
        lv = ranking[k]
        branch[k] = {
            'speedup_avg': float(lv.get('speedup_avg') or 0.0),
            'prune_ratio_avg': float(lv.get('prune_ratio_avg') or 0.0),
            'q50_mad_avg': float(lv.get('q50_mad_avg') or 0.0),
        }

    # Backup full baseline
    backups = baseline_path.parent / 'backups'
    backups.mkdir(parents=True, exist_ok=True)
    # Use timezone-aware UTC timestamp for backup filename determinism
    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')
    (backups / f'{ts}_baseline_backup.json').write_text(json.dumps(doc, indent=2), encoding='utf-8')

    # Merge and write
    if not isinstance(doc, dict):
        print('[error] unexpected baseline structure')
        sys.exit(2)
    new_doc = dict(doc)
    new_doc[ns.index] = branch
    tmp = baseline_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(new_doc, indent=2), encoding='utf-8')
    tmp.replace(baseline_path)
    print(f'[seed] updated baseline for index {ns.index}:', baseline_path)

if __name__ == '__main__':
    main()
