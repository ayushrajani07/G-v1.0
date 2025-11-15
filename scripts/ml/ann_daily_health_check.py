#!/usr/bin/env python
"""Daily ANN health check.

Runs a narrow harness slice (typically last 1 trading day) for key retrieval configs and
compares against a stored baseline JSON. Emits exit codes and a summary if regression
thresholds are crossed.

Baseline file schema (JSON):
{
  "retrieval_60_k10": {"speedup_avg": 0.93, "prune_ratio_avg": 0.83, "q50_mad_avg": 0.0},
  "retrieval_120_k10": {"speedup_avg": 0.89, "prune_ratio_avg": 0.87, "q50_mad_avg": 0.0}
}

Exit codes:
  0 = OK
  2 = Regression detected (any threshold breached)
  3 = Data/run error (no rows collected)

Usage example:
  python scripts/ml/ann_daily_health_check.py --index NIFTY --tag this_week --offset 0 \
    --start 2025-11-06 --end 2025-11-06 --baseline baselines/ann_daily_baseline.json
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, datetime
from src.error_handling import safe_write_json, safe_read_json, safe_write_text  # type: ignore
from pathlib import Path
from typing import Dict, Any

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS = REPO_ROOT / 'scripts' / 'ml' / 'ann_harness_large.py'

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--index', required=True)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--offset', default='0')
    ap.add_argument('--start', required=True)
    ap.add_argument('--end', required=True)
    ap.add_argument('--baseline', required=True, help='Path to baseline JSON')
    ap.add_argument('--out-root', default='results/ann_daily_check')
    ap.add_argument('--speedup-min-drop', type=float, default=0.05, help='Allowable speedup drop before alert')
    ap.add_argument('--mad-max', type=float, default=0.05, help='Max acceptable q50 MAD')
    ap.add_argument('--prune-max', type=float, default=0.90, help='Max acceptable prune ratio before pruning deemed weak')
    ap.add_argument('--min-rows', type=int, default=5, help='Minimum rows required per key to judge speedup drop (skip if below)')
    ap.add_argument('--history-dir', default='results/ann_daily_check/history', help='Directory to write per-run history JSON (empty to disable)')
    ap.add_argument('--refresh-baseline-if-ok', action='store_true', help='If health-check OK and all keys meet min_rows, update baseline with live metrics')
    ap.add_argument('--baseline-backup-dir', default='baselines/backups', help='Where to back up previous baseline before refresh')
    ap.add_argument('--python', default=sys.executable)
    return ap.parse_args()

def run_slice(ns) -> Path:
    out_root = REPO_ROOT / ns.out_root
    cmd = [
        ns.python, str(HARNESS),
        '--indices', ns.index,
        '--tags', ns.tag,
        '--offsets', ns.offset,
        '--start', ns.start,
        '--end', ns.end,
        '--windows', '60,120',
        '--horizons', '60',
        '--k', '10',
        '--modes', 'retrieval',
        '--ann-max-candidates', '20',
        '--metrics-minimal',
        '--out-root', ns.out_root,
    ]
    env = os.environ.copy()
    env['PYTHONPATH'] = str(REPO_ROOT)
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, text=True)
    if res.returncode != 0:
        print('[error] harness run failed')
        sys.exit(3)
    return out_root / 'combined' / 'ann_ranking.csv'

def read_ranking(path: Path) -> Dict[str, Dict[str, Any]]:
    import csv
    if not path.exists():
        print('[error] ranking not found:', path)
        sys.exit(3)
    rows = []
    with path.open('r', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r: rows.append(row)
    if not rows:
        print('[error] empty ranking')
        sys.exit(3)
    # Map key configs
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        try:
            if str(r.get('mode')) != 'retrieval':
                continue
            w = str(r.get('window'))
            k = str(r.get('k'))
            key = f'retrieval_{w}_k{k}'
            sp = float(r.get('speedup_avg') or 0.0)
            pr = float(r.get('prune_ratio_avg') or 1.0)
            md = float(r.get('q50_mad_avg') or 0.0)
            cnt = int(r.get('rows') or 0)
            out[key] = {'speedup_avg': sp, 'prune_ratio_avg': pr, 'q50_mad_avg': md, 'rows': cnt}
        except Exception:
            continue
    return out

def main():
    ns = parse_args()
    ranking_csv = run_slice(ns)
    live = read_ranking(ranking_csv)
    baseline_path = Path(ns.baseline)
    if not baseline_path.exists():
        print('[error] baseline file missing:', baseline_path)
        sys.exit(3)
    # Support flat and nested (multi-index) baseline documents.
    baseline_doc = safe_read_json(baseline_path, default={}, function_name='ann_daily_baseline_read')
    if isinstance(baseline_doc, dict) and baseline_doc and any(k.startswith('retrieval_') for k in baseline_doc.keys()):
        baseline = baseline_doc
        is_nested = False
    else:
        is_nested = True
        idx_branch = baseline_doc.get(ns.index) if isinstance(baseline_doc, dict) else None
        if not isinstance(idx_branch, dict):
            print(f"[error] baseline missing index branch: {ns.index}")
            sys.exit(3)
        baseline = idx_branch
    regressions = []
    skipped = []
    for key, bvals in baseline.items():
        lvals = live.get(key)
        if not lvals:
            regressions.append(f'missing live metrics for {key}')
            continue
        # Skip small samples to avoid warmup noise
        if (lvals.get('rows') or 0) < ns.min_rows:
            note = f'skipping checks for {key}: rows={lvals.get("rows", 0)} < min_rows={ns.min_rows}'
            print(f'[note] {note}')
            skipped.append(key)
            continue
        # Speedup drop
        if (bvals.get('speedup_avg') or 0) - (lvals.get('speedup_avg') or 0) > ns.speedup_min_drop:
            regressions.append(f'speedup regression {key}: baseline {bvals.get("speedup_avg"):.3f} live {lvals.get("speedup_avg"):.3f}')
        # MAD threshold
        if (lvals.get('q50_mad_avg') or 0) > ns.mad_max:
            regressions.append(f'MAD too high {key}: {lvals.get("q50_mad_avg"):.3f} > {ns.mad_max}')
        # Prune ratio threshold
        if (lvals.get('prune_ratio_avg') or 1) > ns.prune_max:
            regressions.append(f'Prune ratio high {key}: {lvals.get("prune_ratio_avg"):.3f} > {ns.prune_max}')
    # Prepare history payload
    # timezone-aware UTC timestamp for history (avoids naive now)
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    history_payload = {
        'timestamp': now,
        'params': {
            'index': ns.index,
            'tag': ns.tag,
            'offset': ns.offset,
            'start': ns.start,
            'end': ns.end,
            'speedup_min_drop': ns.speedup_min_drop,
            'mad_max': ns.mad_max,
            'prune_max': ns.prune_max,
            'min_rows': ns.min_rows,
        },
        'baseline_keys': list(baseline.keys()),
        'live': live,
        'skipped': skipped,
        'regressions': regressions,
    }
    # Write history if enabled
    if ns.history_dir:
        hist_dir = REPO_ROOT / ns.history_dir
        try:
            hist_dir.mkdir(parents=True, exist_ok=True)
            fname = f"{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}_{ns.index}_{ns.tag}_{ns.offset}.json"
            safe_write_json(hist_dir / fname, history_payload, function_name='ann_daily_history_write')
        except Exception as e:
            print('[warn] failed to write history:', e)

    if regressions:
        print('[health-check] FAIL')
        for r in regressions: print(' -', r)
        sys.exit(2)
    print('[health-check] OK')
    for key, vals in live.items():
        print(f'  {key}: speedup={vals["speedup_avg"]:.3f} prune={vals["prune_ratio_avg"]:.3f} mad={vals["q50_mad_avg"]:.3f}')

    # Optionally refresh baseline when OK and all keys met min_rows
    if ns.refresh_baseline_if_ok:
        all_keys_present = all(k in live for k in baseline.keys())
        all_met_rows = all((live[k].get('rows') or 0) >= ns.min_rows for k in baseline.keys() if k in live)
        if all_keys_present and all_met_rows:
            try:
                backup_dir = REPO_ROOT / ns.baseline_backup_dir
                backup_dir.mkdir(parents=True, exist_ok=True)
                backup_name = f"{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}_baseline_backup.json"
                # Backup the full document to preserve other indices
                safe_write_json(backup_dir / backup_name, baseline_doc, function_name='ann_daily_baseline_backup_write')
                # Build refreshed baseline dict from live for matching keys
                new_baseline = {}
                for k in baseline.keys():
                    lv = live.get(k, {})
                    new_baseline[k] = {
                        'speedup_avg': float(lv.get('speedup_avg') or 0.0),
                        'prune_ratio_avg': float(lv.get('prune_ratio_avg') or 0.0),
                        'q50_mad_avg': float(lv.get('q50_mad_avg') or 0.0),
                    }
                # Write back either entire file (flat) or nested branch (multi-index)
                if is_nested:
                    updated_doc = dict(baseline_doc)
                    updated_doc[ns.index] = new_baseline
                    safe_write_json(baseline_path, updated_doc, function_name='ann_daily_baseline_refresh_nested')
                else:
                    safe_write_json(baseline_path, new_baseline, function_name='ann_daily_baseline_refresh_flat')
                print('[baseline] refreshed from live metrics')
            except Exception as e:
                print('[warn] failed to refresh baseline:', e)
        else:
            print('[baseline] not refreshed: keys_present=', all_keys_present, ' all_met_rows=', all_met_rows)
    sys.exit(0)

if __name__ == '__main__':
    main()
