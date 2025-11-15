#!/usr/bin/env python
"""Auto-tune ANN candidate counts per mode.

Logic:
  Reads an existing combined ann_summary.csv (or multiple) and determines the
  smallest ann_max_candidates per mode satisfying:
    prune_gain >= --min-prune-gain  (where prune_gain = 1 - prune_ratio_avg)
    q50_mad_avg <= --target-mad

  Falls back to highest candidate if none satisfy constraints.

Usage:
  python scripts/ml/ann_auto_tune_candidates.py \
    --comparison results/ann_large_extended_comparison.csv \
    --target-mad 0.1 --min-prune-gain 0.05

Outputs a JSON mapping and prints a suggested CLI snippet.
"""
from __future__ import annotations
import argparse, csv, json, math
from src.error_handling import safe_write_json, safe_write_text  # type: ignore
from pathlib import Path


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--comparison', required=True, help='CSV with columns including ann_max_candidates, prune_ratio_avg, q50_mad_avg, speedup_avg; may include per-mode columns like retrieval_q50_mad_avg')
    ap.add_argument('--target-mad', type=float, default=0.1, help='Upper bound for acceptable q50_mad_avg')
    ap.add_argument('--min-prune-gain', type=float, default=0.05, help='Minimum (1 - prune_ratio_avg) required')
    ap.add_argument('--output', default='results/ann_auto_tune.json')
    ap.add_argument('--emit-overrides', action='store_true', help='Also emit a CLI-friendly overrides string file alongside JSON')
    return ap.parse_args()


def load_rows(path: Path):
    rows = []
    with path.open('r', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            # Safely parse ann_max_candidates
            raw_cand = row.get('ann_max_candidates')
            if raw_cand in (None, '', 'nan'):
                continue
            try:
                row['ann_max_candidates'] = int(str(raw_cand))
            except Exception:
                continue
            for k in ('prune_ratio_avg','q50_mad_avg','speedup_avg'):
                raw_val = row.get(k)
                if raw_val in (None, '', 'nan'):
                    row[k] = math.nan
                    continue
                try:
                    row[k] = float(str(raw_val))
                except Exception:
                    row[k] = math.nan
        rows.append(row)
    return rows


def pick(rows, target_mad: float, min_prune_gain: float, *, prefer_speedup: bool = True):
    # Sort candidate counts ascending so we select smallest meeting constraints
    rows_sorted = sorted(rows, key=lambda r: r['ann_max_candidates'])
    valid = []
    for r in rows_sorted:
        prune_ratio = r.get('prune_ratio_avg')
        mad = r.get('q50_mad_avg')
        if prune_ratio is None or mad is None:
            continue
        prune_gain = 1.0 - prune_ratio
        if prune_gain >= min_prune_gain and mad <= target_mad:
            valid.append(r)
    if not valid:
        # fallback: largest candidate (quality priority)
        return rows_sorted[-1]
    if prefer_speedup:
        # choose best speedup among valid
        return max(valid, key=lambda r: (r.get('speedup_avg') or 0.0))
    return valid[0]


def pick_per_mode(rows, target_mad: float, min_prune_gain: float, modes=('retrieval','auto','hybrid')):
    """If per-mode columns exist, compute per-mode suggestions; else fallback to global pick.

    Expects columns like '{mode}_q50_mad_avg' and '{mode}_prune_ratio_avg'.
    """
    by_cand = {}
    for r in rows:
        by_cand.setdefault(int(r['ann_max_candidates']), []).append(r)
    # Use the first row per candidate (ladder comparison has one row per candidate)
    first_by_cand = {c: rs[0] for c, rs in by_cand.items()}
    result = {}
    for m in modes:
        mad_key = f'{m}_q50_mad_avg'
        pr_key = f'{m}_prune_ratio_avg'
        have = all((mad_key in row or pr_key in row) for row in first_by_cand.values())
        if not have:
            result[m] = None
            continue
        candidates_sorted = sorted(first_by_cand.keys())
        chosen = None
        best_speed = None
        for c in candidates_sorted:
            row = first_by_cand[c]
            mad = row.get(mad_key)
            pr = row.get(pr_key)
            try:
                mad = float(mad) if mad is not None else float('nan')
                pr = float(pr) if pr is not None else float('nan')
            except Exception:
                mad = float('nan'); pr = float('nan')
            if not (mad == mad and pr == pr):
                continue
            prune_gain = 1.0 - pr
            if prune_gain >= min_prune_gain and mad <= target_mad:
                sp = float(first_by_cand[c].get('speedup_avg') or 0.0)
                if chosen is None or sp > (best_speed or 0.0):
                    chosen = c
                    best_speed = sp
        if chosen is None:
            chosen = max(candidates_sorted)
        result[m] = chosen
    return result


def main():
    ns = parse_args()
    path = Path(ns.comparison)
    if not path.exists():
        raise SystemExit(f'Comparison CSV not found: {path}')
    rows = load_rows(path)
    if not rows:
        raise SystemExit('No rows loaded from comparison CSV')
    # We operate globally (modes aggregated). In future extend to per-mode if separate files exist.
    per_mode = pick_per_mode(rows, ns.target_mad, ns.min_prune_gain)
    if all(v is None for v in per_mode.values()):
        pick_row = pick(rows, ns.target_mad, ns.min_prune_gain)
        suggestion = {
            'retrieval': pick_row['ann_max_candidates'],
            'auto': pick_row['ann_max_candidates'],
            'hybrid': pick_row['ann_max_candidates'],
            'source': path.as_posix(),
            'criteria': {'target_mad': ns.target_mad, 'min_prune_gain': ns.min_prune_gain},
            'mode': 'global'
        }
    else:
        # Replace missing with global pick fallback
        for k, v in per_mode.items():
            if v is None:
                per_mode[k] = pick(rows, ns.target_mad, ns.min_prune_gain)['ann_max_candidates']
        suggestion = {
            'retrieval': per_mode.get('retrieval'),
            'auto': per_mode.get('auto'),
            'hybrid': per_mode.get('hybrid'),
            'source': path.as_posix(),
            'criteria': {'target_mad': ns.target_mad, 'min_prune_gain': ns.min_prune_gain},
            'mode': 'per-mode'
        }
    out_path = Path(ns.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    safe_write_json(out_path, suggestion, function_name='ann_auto_tune_suggestion_write')
    print('[auto-tune] suggestion written to', out_path)
    cli_str = f"--ann-max-candidates-per-mode retrieval={suggestion['retrieval']},auto={suggestion['auto']},hybrid={suggestion['hybrid']}"
    print('[auto-tune] per-mode overrides CLI: ' + cli_str)
    if bool(getattr(ns, 'emit_overrides', False)):
        ov_path = out_path.with_suffix('.txt')
        safe_write_text(ov_path, cli_str + '\n', function_name='ann_auto_tune_overrides_write')
        print('[auto-tune] overrides written to', ov_path)

if __name__ == '__main__':
    main()
