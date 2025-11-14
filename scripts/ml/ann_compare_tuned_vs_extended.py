#!/usr/bin/env python
"""Compare tuned vs extended ANN aggregated rankings.

Reads ann_ranking.csv from two harness output roots (extended + tuned) and produces:
  - CSV diff with delta columns
  - Markdown summary highlighting top changes

Match rows on (index,expiry_tag,offset,horizon,window,k,mode).
If a row is missing in one side, metrics are left blank and delta omitted.

Usage:
  python scripts/ml/ann_compare_tuned_vs_extended.py \
      --extended results/ann_large_extended/combined/ann_ranking.csv \
      --tuned results/ann_large_tuned/combined/ann_ranking.csv \
      --out-dir results/ann_large_compare
"""
from __future__ import annotations
import argparse, csv, json
from pathlib import Path
from typing import Dict, Any, List

KEY_FIELDS = ['index','expiry_tag','offset','horizon','window','k','mode']
METRIC_FIELDS = [
    'speedup_avg','prune_ratio_avg','q50_mad_avg','latency_ms_avg','baseline_latency_ms_avg',
    'effectiveness_score','effectiveness_score_adjusted','ann_guard_trigger_rate','score'
]

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--extended', required=True, help='Path to extended ann_ranking.csv')
    ap.add_argument('--tuned', required=True, help='Path to tuned ann_ranking.csv')
    ap.add_argument('--out-dir', required=True, help='Directory to write diff artifacts')
    ap.add_argument('--top-n', type=int, default=20, help='Top N rows by tuned score to highlight')
    return ap.parse_args()

def load_csv(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f'Missing file: {path}')
    rows: List[Dict[str, Any]] = []
    with path.open('r', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
    return rows

def key(row: Dict[str, Any]) -> str:
    return '|'.join([str(row.get(k,'')) for k in KEY_FIELDS])

def to_float(v: Any):
    try:
        if v in (None,'','nan'): return None
        return float(v)
    except Exception:
        return None

def main():
    ns = parse_args()
    ext_rows = load_csv(Path(ns.extended))
    tuned_rows = load_csv(Path(ns.tuned))
    ext_map = {key(r): r for r in ext_rows}
    tuned_map = {key(r): r for r in tuned_rows}
    all_keys = sorted(set(ext_map.keys()) | set(tuned_map.keys()))
    out_dir = Path(ns.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    diff_csv = out_dir / 'ann_ranking_diff.csv'
    md_path = out_dir / 'ann_ranking_diff.md'
    fields = KEY_FIELDS + [
        *(f'extended_{m}' for m in METRIC_FIELDS),
        *(f'tuned_{m}' for m in METRIC_FIELDS),
        *(f'delta_{m}' for m in METRIC_FIELDS)
    ]
    diff_rows: List[Dict[str, Any]] = []
    for k in all_keys:
        er = ext_map.get(k, {})
        tr = tuned_map.get(k, {})
        row: Dict[str, Any] = {}
        # key fields
        parts = k.split('|')
        for i, field in enumerate(KEY_FIELDS):
            row[field] = parts[i] if i < len(parts) else ''
        # metrics
        for m in METRIC_FIELDS:
            row[f'extended_{m}'] = er.get(m)
            row[f'tuned_{m}'] = tr.get(m)
            ev = to_float(er.get(m))
            tv = to_float(tr.get(m))
            row[f'delta_{m}'] = (tv - ev) if (ev is not None and tv is not None) else ''
        diff_rows.append(row)
    # write CSV
    with diff_csv.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in diff_rows:
            w.writerow(r)
    # markdown summary (top tuned)
    def score_of(r: Dict[str, Any]):
        v = to_float(r.get('tuned_score'))
        return v if v is not None else -1e9
    tuned_sorted = sorted(diff_rows, key=score_of, reverse=True)
    top = tuned_sorted[:ns.top_n]
    lines = []
    lines.append('# ANN Ranking Diff (Tuned vs Extended)')
    lines.append('')
    lines.append(f'Extended source: `{ns.extended}`')
    lines.append(f'Tuned source: `{ns.tuned}`')
    lines.append('')
    lines.append('## Top Tuned Config Deltas')
    lines.append('')
    header = '| index | tag | off | win | hor | k | mode | Δspeedup | Δprune | ΔMAD | Δlat | Δeffect_adj | Δscore |'
    lines.append(header)
    lines.append('|---|---|---|---|---|---|---|---|---|---|---|---|---|')
    for r in top:
        def fmt_delta(name):
            v = r.get(f'delta_{name}')
            if v in ('', None): return ''
            try:
                return f"{float(v):+.4f}"
            except Exception:
                return ''
        lines.append('| {index} | {expiry_tag} | {offset} | {window} | {horizon} | {k} | {mode} | {ds} | {dp} | {dm} | {dl} | {de} | {sc} |'.format(
            index=r.get('index'), expiry_tag=r.get('expiry_tag'), offset=r.get('offset'), window=r.get('window'), horizon=r.get('horizon'), k=r.get('k'), mode=r.get('mode'),
            ds=fmt_delta('speedup_avg'), dp=fmt_delta('prune_ratio_avg'), dm=fmt_delta('q50_mad_avg'), dl=fmt_delta('latency_ms_avg'), de=fmt_delta('effectiveness_score_adjusted'), sc=fmt_delta('score')
        ))
    md_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f'[write] {diff_csv}')
    print(f'[write] {md_path}')

if __name__ == '__main__':
    main()
