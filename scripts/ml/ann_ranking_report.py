#!/usr/bin/env python
"""Generate a Markdown report from ann_ranking.csv.

Produces a readable summary with top-N by score and by effectiveness, plus per-mode best picks.

Usage:
  python scripts/ml/ann_ranking_report.py --ranking results/ann_large_tuned/combined/ann_ranking.csv --out results/ann_large_tuned/combined/ann_ranking_report.md --top 20
"""
from __future__ import annotations
import argparse, csv
from pathlib import Path
from typing import List, Dict, Any, Tuple

KEY_FIELDS = ['index','expiry_tag','offset','horizon','window','k','mode']

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ranking', required=True, help='Path to ann_ranking.csv')
    ap.add_argument('--out', required=True, help='Path to write Markdown report')
    ap.add_argument('--top', type=int, default=20)
    return ap.parse_args()

def load_ranking(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open('r', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
    return rows

def to_float(v):
    try:
        if v in (None,'','nan'): return None
        return float(v)
    except Exception:
        return None

def fmt_row(r: Dict[str, Any]) -> str:
    return f"{r.get('index')} {r.get('expiry_tag')} off={r.get('offset')} w={r.get('window')} h={r.get('horizon')} k={r.get('k')} [{r.get('mode')}]"

def main():
    ns = parse_args()
    path = Path(ns.ranking)
    rows = load_ranking(path)
    # sorters
    top_by_score = sorted(rows, key=lambda r: to_float(r.get('score')) or -1e9, reverse=True)[:ns.top]
    top_by_eff = sorted(rows, key=lambda r: to_float(r.get('effectiveness_score_adjusted')) or to_float(r.get('effectiveness_score')) or -1e9, reverse=True)[:ns.top]
    # per-mode best picks per (index,tag,offset,horizon,window,k)
    from collections import defaultdict
    group_best: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for r in rows:
        key = '|'.join([str(r.get('index') or ''), str(r.get('expiry_tag') or ''), str(r.get('offset') or ''), str(r.get('horizon') or ''), str(r.get('window') or ''), str(r.get('k') or '')])
        mode = str(r.get('mode'))
        prev = group_best[key].get(mode)
        if prev is None or (to_float(r.get('score')) or -1e9) > (to_float(prev.get('score')) or -1e9):
            group_best[key][mode] = r
    # build markdown
    lines: List[str] = []
    lines.append('# ANN Ranking Report')
    lines.append('')
    lines.append(f'Source: `{ns.ranking}`')
    lines.append('')
    lines.append('## Top by Score')
    lines.append('')
    lines.append('| rank | config | speedup | prune | MAD | lat | eff_adj | guard_rate | score |')
    lines.append('|---:|---|---:|---:|---:|---:|---:|---:|---:|')
    for i, r in enumerate(top_by_score, 1):
        def f(name, dp=4):
            v = to_float(r.get(name))
            return f"{v:.{dp}f}" if v is not None else ''
        lines.append(f"| {i} | {fmt_row(r)} | {f('speedup_avg')} | {f('prune_ratio_avg')} | {f('q50_mad_avg')} | {f('latency_ms_avg',2)} | {f('effectiveness_score_adjusted')} | {f('ann_guard_trigger_rate')} | {f('score',2)} |")
    lines.append('')
    lines.append('## Top by Adjusted Effectiveness')
    lines.append('')
    lines.append('| rank | config | speedup | prune | MAD | eff_adj | eff_raw | score |')
    lines.append('|---:|---|---:|---:|---:|---:|---:|---:|')
    for i, r in enumerate(top_by_eff, 1):
        def f(name, dp=4):
            v = to_float(r.get(name))
            return f"{v:.{dp}f}" if v is not None else ''
        lines.append(f"| {i} | {fmt_row(r)} | {f('speedup_avg')} | {f('prune_ratio_avg')} | {f('q50_mad_avg')} | {f('effectiveness_score_adjusted')} | {f('effectiveness_score')} | {f('score',2)} |")
    lines.append('')
    lines.append('## Per-Mode Best Picks')
    lines.append('')
    lines.append('| group | retrieval | auto | hybrid |')
    lines.append('|---|---|---|---|')
    for gkey, modes in sorted(group_best.items()):
        def fmt(m):
            r = modes.get(m)
            if not r: return ''
            return f"{r.get('mode')} sc={to_float(r.get('score')) or 0:.2f} eff={to_float(r.get('effectiveness_score_adjusted')) or to_float(r.get('effectiveness_score')) or 0:.4f}"
        parts = gkey.split('|')
        index, tag, off, hor, win, k = (parts + ['','','','','',''])[:6]
        group_name = f"{index} {tag} off={off} w={win} h={hor} k={k}"
        lines.append(f"| {group_name} | {fmt('retrieval')} | {fmt('auto')} | {fmt('hybrid')} |")
    out_path = Path(ns.out)
    out_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f'[write] {out_path}')

if __name__ == '__main__':
    main()
