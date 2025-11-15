#!/usr/bin/env python
r"""Large-slice ANN Harness

Purpose:
  Automate a multi-index / multi-expiry large-slice evaluation to surface ANN diagnostics
  (speedup, prune ratio, q50 MAD, effectiveness) over a deeper historical range so that
  ANN indexing vs exact scan meaningfully diverges.

Features:
  - Iterates indices / expiry tags / offsets / (window,horizon,k) triples.
  - For each combo: runs `path_forecast_grid_eval.py` in direct (non-discovery) mode with
    --use-ann and --ann-compare enabled across a date span.
  - Aggregates resulting per-config rows into a unified CSV plus a JSON summary with
    heuristic recommendations (e.g., increase history if prune_ratio ~1.0, adjust ann_max_candidates).
  - Optional minimal metrics mode to accelerate repeated harness runs.

Usage (PowerShell example):
    cmd /c "cd /d C:\path\to\repo && set PYTHONPATH=C:\path\to\repo ^
        && C:\path\to\repo\.venv\Scripts\python.exe scripts\ml\ann_harness_large.py ^
       --indices NIFTY,BANKNIFTY ^
       --tags this_week ^
       --offsets 0 ^
       --start 2025-10-01 --end 2025-11-06 ^
       --windows 60 --horizons 60 --k 15 ^
       --ann-max-candidates 50 ^
       --out-root results/ann_large ^
       --metrics-minimal"

Outputs:
  - <out_root>/raw/<INDEX>_<TAG>_<OFFSET>_<WIN>w_<HOR>h_k<K>.csv  (per combo eval rows)
  - <out_root>/combined/ann_summary.csv  (stacked rows + selected diagnostic columns)
  - <out_root>/combined/ann_summary.json (JSON with aggregate statistics + recommendations)

Exit code non-zero if any invoked run fails (missing data or script error) unless --continue-on-error.

"""
from __future__ import annotations
import argparse
import csv
import json
from src.error_handling import safe_write_json  # type: ignore
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / 'scripts' / 'ml' / 'path_forecast_grid_eval.py'

@dataclass
class Combo:
    index: str
    tag: str
    offset: str
    window: int
    horizon: int
    k: int
    mode: str


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--indices', required=True, help='Comma separated indices (e.g. NIFTY,BANKNIFTY)')
    ap.add_argument('--tags', required=True, help='Comma separated expiry tags (e.g. this_week,this_month)')
    ap.add_argument('--offsets', default='0', help='Comma separated offsets')
    ap.add_argument('--start', required=True)
    ap.add_argument('--end', required=True)
    ap.add_argument('--windows', default='60')
    ap.add_argument('--horizons', default='60')
    ap.add_argument('--k', default='15')
    ap.add_argument('--ann-max-candidates', type=int, default=50)
    ap.add_argument('--ann-max-candidates-per-mode', default=None, help='Overrides per mode, e.g. retrieval=10,auto=30,hybrid=30')
    ap.add_argument('--ann-mad-guard', type=float, default=None, help='If q50 MAD exceeds threshold, fallback to exact baseline path')
    ap.add_argument('--ann-candidate-ladder', default=None, help='Run sequential evaluations over candidate counts (e.g. 50,30,20,10) producing comparison CSV')
    ap.add_argument('--modes', default='retrieval', help='Comma separated modes (retrieval,auto,hybrid)')
    ap.add_argument('--distance-metric', default='l2')
    ap.add_argument('--weight-mode', default=None)
    ap.add_argument('--recent-gamma', type=float, default=0.9)
    ap.add_argument('--regime-tolerance', type=float, default=None)
    ap.add_argument('--regime-penalty', type=float, default=1.25)
    ap.add_argument('--bucket-ms', type=int, default=60000)
    ap.add_argument('--at', default='mid', choices=['mid','end'])
    ap.add_argument('--out-root', default='results/ann_large')
    ap.add_argument('--metrics-minimal', action='store_true')
    ap.add_argument('--effect-tolerance', type=float, default=None, help='ann_effect_tolerance value')
    ap.add_argument('--python', default=str((REPO_ROOT / '.venv' / 'Scripts' / 'python.exe')))  # Windows path
    ap.add_argument('--continue-on-error', action='store_true')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--disable-ann-cache', action='store_true', help='Disable in-process ANN index cache (sets G6_DISABLE_ANN_CACHE=1)')
    # Auto-tuner integration
    ap.add_argument('--auto-tune', action='store_true', help='After ladder run, invoke ann_auto_tune_candidates to suggest per-mode candidates')
    ap.add_argument('--auto-tune-target-mad', type=float, default=0.1, help='Target q50 MAD upper bound for auto-tuner')
    ap.add_argument('--auto-tune-min-prune', type=float, default=0.05, help='Minimum pruning gain (1 - prune_ratio) for auto-tuner')
    # Ranking weights
    ap.add_argument('--rank-w-speedup', type=float, default=1.0, help='Weight for ann_speedup contribution')
    ap.add_argument('--rank-w-prune', type=float, default=1.0, help='Weight for pruning gain contribution (1 - prune_ratio)')
    ap.add_argument('--rank-w-mad', type=float, default=0.2, help='Penalty weight per q50_mad unit')
    ap.add_argument('--rank-w-latency', type=float, default=0.001, help='Penalty weight per ms of latency')
    return ap.parse_args()


def build_combos(ns) -> List[Combo]:
    indices = [s.strip().upper() for s in ns.indices.split(',') if s.strip()]
    tags = [s.strip() for s in ns.tags.split(',') if s.strip()]
    offsets = [s.strip() for s in ns.offsets.split(',') if s.strip()]
    windows = [int(s) for s in ns.windows.split(',') if s.strip()]
    horizons = [int(s) for s in ns.horizons.split(',') if s.strip()]
    ks = [int(s) for s in ns.k.split(',') if s.strip()]
    modes = [s.strip() for s in ns.modes.split(',') if s.strip()]
    combos: List[Combo] = []
    for idx in indices:
        for tag in tags:
            for off in offsets:
                for w in windows:
                    for h in horizons:
                        for k in ks:
                            for m in modes:
                                combos.append(Combo(idx, tag, off, w, h, k, m))
    return combos


def run_eval(ns, combo: Combo, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    eval_csv = out_dir / f"{combo.index}_{combo.tag}_{combo.offset}_{combo.window}w_{combo.horizon}h_k{combo.k}_{combo.mode}.csv"
    summary_csv = out_dir / f"{combo.index}_{combo.tag}_{combo.offset}_{combo.window}w_{combo.horizon}h_k{combo.k}_{combo.mode}_summary.csv"
    cmd = [
        ns.python,
        str(SCRIPT),
        '--index', combo.index,
        '--expiry-tag', combo.tag,
        '--offset', combo.offset,
        '--start', ns.start,
        '--end', ns.end,
        '--horizons', str(combo.horizon),
        '--windows', str(combo.window),
        '--k', str(combo.k),
    '--modes', combo.mode,
        '--bucket-ms', str(ns.bucket_ms),
        '--at', ns.at,
        '--use-ann',
        '--ann-compare',
        '--ann-max-candidates', str(ns.ann_max_candidates),
        '--distance-metric', ns.distance_metric,
        '--regime-penalty', str(ns.regime_penalty),
        '--out', str(eval_csv),
        '--summary', str(summary_csv),
        '--scales', '1.0',
    ]
    if ns.weight_mode:
        cmd += ['--weight-mode', ns.weight_mode]
    if ns.regime_tolerance is not None:
        cmd += ['--regime-tolerance', str(ns.regime_tolerance)]
    if ns.recent_gamma is not None:
        cmd += ['--recent-gamma', str(ns.recent_gamma)]
    if ns.metrics_minimal:
        cmd += ['--metrics-minimal']
    if ns.ann_max_candidates_per_mode:
        cmd += ['--ann-max-candidates-per-mode', ns.ann_max_candidates_per_mode]
    if ns.ann_mad_guard is not None:
        # ensure baseline available for guard
        if '--ann-compare' not in cmd:
            cmd.append('--ann-compare')
        cmd += ['--ann-mad-guard', str(ns.ann_mad_guard)]
    if ns.effect_tolerance is not None:
        cmd += ['--ann-effect-tolerance', str(ns.effect_tolerance)]
    if ns.verbose:
        print('[run]', ' '.join(cmd))
    env = dict(**dict(**{}), **dict(**{k: v for k, v in dict(**{}) .items()}))  # placeholder for future env injection
    # Ensure PYTHONPATH set
    import os
    env.update(os.environ)
    env['PYTHONPATH'] = str(REPO_ROOT)
    if bool(getattr(ns, 'disable_ann_cache', False)):
        env['G6_DISABLE_ANN_CACHE'] = '1'
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, capture_output=not ns.verbose, text=True)
    if res.returncode != 0:
        if not ns.verbose:
            print('[error]', res.stderr.strip())
        if not ns.continue_on_error:
            raise SystemExit(f"Eval failed for {combo} (code {res.returncode})")
    return eval_csv


def parse_eval_rows(csv_path: Path) -> List[Dict[str, Any]]:
    if not csv_path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with csv_path.open('r', encoding='utf-8') as f:
        import csv as _csv
        r = _csv.DictReader(f)
        for row in r:
            rows.append(row)
    return rows


def aggregate(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate key ANN diagnostics into global stats."""
    n = 0
    speedups = []
    mad = []
    prune = []
    build_ms = []
    latency = []
    base_latency = []
    guard_flags: List[int] = []
    # For adjusted metrics, exclude likely warmup/build-spike rows
    speedups_adj = []
    mad_adj = []
    prune_adj = []
    latency_adj = []
    mode_breakdown: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        try:
            n += 1
            if r.get('ann_speedup') not in (None, '', 'nan'): speedups.append(float(r['ann_speedup']))
            if r.get('ann_q50_mad') not in (None, '', 'nan'): mad.append(float(r['ann_q50_mad']))
            if r.get('ann_prune_ratio') not in (None, '', 'nan'): prune.append(float(r['ann_prune_ratio']))
            if r.get('ann_build_ms') not in (None, '', 'nan'): build_ms.append(float(r['ann_build_ms']))
            if r.get('latency_ms') not in (None, '', 'nan'): latency.append(float(r['latency_ms']))
            if r.get('baseline_latency_ms') not in (None, '', 'nan'): base_latency.append(float(r['baseline_latency_ms']))
            # guard flags
            try:
                gf = int(str(r.get('ann_guard_triggered') or 0))
                guard_flags.append(gf)
            except Exception:
                pass
            mode = r.get('mode','')
            if mode:
                mb = mode_breakdown.setdefault(mode, {'rows':0,'speedups':[],'prune':[],'lat':[],'base':[],'mad':[]})
                mb['rows'] += 1
                try:
                    if r.get('ann_speedup') not in (None,'','nan'): mb['speedups'].append(float(r['ann_speedup']))
                    if r.get('ann_prune_ratio') not in (None,'','nan'): mb['prune'].append(float(r['ann_prune_ratio']))
                    if r.get('latency_ms') not in (None,'','nan'): mb['lat'].append(float(r['latency_ms']))
                    if r.get('baseline_latency_ms') not in (None,'','nan'): mb['base'].append(float(r['baseline_latency_ms']))
                    if r.get('ann_q50_mad') not in (None,'','nan'): mb['mad'].append(float(r['ann_q50_mad']))
                except Exception:
                    pass
            # adjusted filter: exclude suspected warmup/build spikes
            try:
                is_warm = False
                bms = r.get('ann_build_ms')
                lat_ms = r.get('latency_ms')
                if bms not in (None, '', 'nan'):
                    try:
                        if float(bms) > 100.0:
                            is_warm = True
                    except Exception:
                        pass
                if not is_warm and lat_ms not in (None, '', 'nan'):
                    try:
                        if float(lat_ms) > 100.0:
                            is_warm = True
                    except Exception:
                        pass
                if not is_warm:
                    if r.get('ann_speedup') not in (None, '', 'nan'): speedups_adj.append(float(r['ann_speedup']))
                    if r.get('ann_q50_mad') not in (None, '', 'nan'): mad_adj.append(float(r['ann_q50_mad']))
                    if r.get('ann_prune_ratio') not in (None, '', 'nan'): prune_adj.append(float(r['ann_prune_ratio']))
                    if r.get('latency_ms') not in (None, '', 'nan'): latency_adj.append(float(r['latency_ms']))
            except Exception:
                pass
        except Exception:
            continue
    import statistics as stats
    def _avg(a): return (sum(a)/len(a)) if a else None
    def _p95(a):
        if not a: return None
        a_sorted = sorted(a)
        pos = int(0.95*(len(a_sorted)-1))
        return a_sorted[pos]
    summary = {
        'rows': n,
        'speedup_avg': _avg(speedups),
        'speedup_p95': _p95(speedups),
        'q50_mad_avg': _avg(mad),
        'prune_ratio_avg': _avg(prune),
        'build_ms_avg': _avg(build_ms),
        'latency_ms_avg': _avg(latency),
        'baseline_latency_ms_avg': _avg(base_latency),
        # adjusted (ex-warmup)
        'speedup_avg_adjusted': _avg(speedups_adj),
        'q50_mad_avg_adjusted': _avg(mad_adj),
        'prune_ratio_avg_adjusted': _avg(prune_adj),
        'latency_ms_avg_adjusted': _avg(latency_adj),
        # guard metrics
        'ann_guard_triggered_count': sum(guard_flags) if guard_flags else 0,
        'ann_guard_triggered_rate': (sum(guard_flags)/float(n)) if (guard_flags and n > 0) else 0.0,
    }
    # Mode breakdown summarized
    mb_out = {}
    for m, v in mode_breakdown.items():
        mb_out[m] = {
            'rows': v['rows'],
            'speedup_avg': _avg(v['speedups']),
            'prune_ratio_avg': _avg(v['prune']),
            'latency_ms_avg': _avg(v['lat']),
            'baseline_latency_ms_avg': _avg(v['base']),
            'q50_mad_avg': _avg(v['mad']),
        }
    summary['mode_breakdown'] = mb_out
    # Heuristic recommendations
    recs = []
    if summary['prune_ratio_avg'] is not None and summary['prune_ratio_avg'] > 0.9:
        recs.append('Prune ratio ~1.0: increase historical corpus or tighten ANN distance to gain pruning.')
    if summary['speedup_avg'] is not None and summary['speedup_avg'] < 1.2:
        recs.append('Speedup <1.2: consider larger window set, reducing ann_max_candidates, or pre-filtering low-variance days.')
    if summary['q50_mad_avg'] is not None and summary['q50_mad_avg'] > 1.0:
        recs.append('High q50 MAD: raise ann_max_candidates or adjust distance metric (try cosine vs l2).')
    if summary['build_ms_avg'] and summary['build_ms_avg'] > 1000:
        recs.append('ANN build >1s: persist index across runs or reduce total windows scanned.')
    summary['recommendations'] = recs
    return summary


def write_outputs(out_root: Path, stacked: List[Dict[str, Any]], summary: Dict[str, Any]):
    combined_dir = out_root / 'combined'
    combined_dir.mkdir(parents=True, exist_ok=True)
    csv_path = combined_dir / 'ann_summary.csv'
    if stacked:
        # Unified field order (include only selected columns + raw for inspection)
        keep = [
            'date','index','expiry_tag','offset','horizon','window','k','mode','latency_ms','baseline_latency_ms',
            'ann_speedup','ann_q50_mad','ann_total_windows','ann_shortlisted','ann_prune_ratio','ann_build_ms','ann_index_mem_bytes',
            'ann_guard_triggered','ann_guard_original_mad'
        ]
        # Add any missing keys gracefully
        with csv_path.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=keep)
            w.writeheader()
            for r in stacked:
                w.writerow({k: r.get(k) for k in keep})
    json_path = combined_dir / 'ann_summary.json'
    safe_write_json(json_path, summary, function_name='ann_harness_summary_write')
    print(f'[write] {csv_path}')
    print(f'[write] {json_path}')


def group_and_rank(rows: Sequence[Dict[str, Any]], *, w_speedup: float = 1.0, w_prune: float = 1.0, w_mad: float = 0.2, w_latency: float = 0.001) -> List[Dict[str, Any]]:
    # Accumulate per (index,tag,offset,horizon,window,k,mode)
    def key_of(r: Dict[str, Any]) -> str:
        return '|'.join([
            str(r.get('index','')),
            str(r.get('expiry_tag','')),
            str(r.get('offset','')),
            str(r.get('horizon','')),
            str(r.get('window','')),
            str(r.get('k','')),
            str(r.get('mode','')),
        ])
    acc: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        k = key_of(r)
        if k not in acc:
            acc[k] = {
                'rows': 0,
                'speedups': [],
                'prunes': [],
                'mads': [],
                'lat': [],
                'base': [],
                'guards': [],
                # adjusted (ex-warmup) collections
                'speedups_adj': [],
                'prunes_adj': [],
                'mads_adj': [],
                'meta': None,
            }
        a = acc[k]
        a['rows'] += 1
        a['meta'] = {
            'index': r.get('index'),
            'expiry_tag': r.get('expiry_tag'),
            'offset': r.get('offset'),
            'horizon': r.get('horizon'),
            'window': r.get('window'),
            'k': r.get('k'),
            'mode': r.get('mode'),
        }
        try:
            if r.get('ann_speedup') not in (None,'','nan'): a['speedups'].append(float(r['ann_speedup']))
            if r.get('ann_prune_ratio') not in (None,'','nan'): a['prunes'].append(float(r['ann_prune_ratio']))
            if r.get('ann_q50_mad') not in (None,'','nan'): a['mads'].append(float(r['ann_q50_mad']))
            if r.get('latency_ms') not in (None,'','nan'): a['lat'].append(float(r['latency_ms']))
            if r.get('baseline_latency_ms') not in (None,'','nan'): a['base'].append(float(r['baseline_latency_ms']))
            # guard flag
            try:
                a['guards'].append(int(str(r.get('ann_guard_triggered') or 0)))
            except Exception:
                pass
            # adjusted filter: exclude warmup/build spikes for adjusted aggregates
            try:
                is_warm = False
                bms = r.get('ann_build_ms')
                lat_ms = r.get('latency_ms')
                if bms not in (None, '', 'nan'):
                    try:
                        if float(bms) > 100.0:
                            is_warm = True
                    except Exception:
                        pass
                if not is_warm and lat_ms not in (None, '', 'nan'):
                    try:
                        if float(lat_ms) > 100.0:
                            is_warm = True
                    except Exception:
                        pass
                if not is_warm:
                    if r.get('ann_speedup') not in (None,'','nan'): a['speedups_adj'].append(float(r['ann_speedup']))
                    if r.get('ann_prune_ratio') not in (None,'','nan'): a['prunes_adj'].append(float(r['ann_prune_ratio']))
                    if r.get('ann_q50_mad') not in (None,'','nan'): a['mads_adj'].append(float(r['ann_q50_mad']))
            except Exception:
                pass
        except Exception:
            pass
    def _avg(a): return (sum(a)/len(a)) if a else None
    ranked: List[Dict[str, Any]] = []
    for gkey, a in acc.items():
        sp = _avg(a['speedups']) or 0.0
        pr = _avg(a['prunes'])
        pr = pr if pr is not None else 1.0
        md = _avg(a['mads']) or 0.0
        lat = _avg(a['lat'])
        base = _avg(a['base'])
        # adjusted
        sp_adj = _avg(a['speedups_adj']) or 0.0
        pr_adj = _avg(a['prunes_adj'])
        pr_adj = pr_adj if pr_adj is not None else 1.0
        md_adj = _avg(a['mads_adj']) or 0.0
        # Score: reward speedup and pruning, penalize MAD
        prune_gain = max(0.0, 1.0 - min(1.0, max(0.0, pr)))
        # Latency penalty uses absolute latency if available
        lat_pen = (lat if lat is not None else 0.0) * float(w_latency)
        score = (float(w_speedup) * sp) * (1.0 + float(w_prune) * prune_gain) - float(w_mad) * md - lat_pen
        # Parse group key back into fields
        try:
            idx_s, tag_s, off_s, hor_s, win_s, k_s, mode_s = gkey.split('|')
        except Exception:
            idx_s = tag_s = off_s = mode_s = ''
            hor_s = win_s = k_s = ''
        eff = sp * (1.0 - pr) - md
        eff_adj = sp_adj * (1.0 - pr_adj) - md_adj
        guard_rate = (sum(a['guards'])/a['rows']) if a['guards'] and a['rows'] else 0.0
        row = {
            'index': idx_s,
            'expiry_tag': tag_s,
            'offset': off_s,
            'horizon': hor_s,
            'window': win_s,
            'k': k_s,
            'mode': mode_s,
            'rows': a['rows'],
            'speedup_avg': round(sp, 4) if a['speedups'] else None,
            'prune_ratio_avg': round(pr, 4) if a['prunes'] else None,
            'q50_mad_avg': round(md, 4) if a['mads'] else None,
            'latency_ms_avg': round(lat, 2) if lat is not None else None,
            'baseline_latency_ms_avg': round(base, 2) if base is not None else None,
            'effectiveness_score': round(eff, 6),
            'effectiveness_score_adjusted': round(eff_adj, 6),
            'ann_guard_trigger_rate': round(guard_rate, 6),
            'score': round(score, 4),
        }
        ranked.append(row)
    ranked.sort(key=lambda r: (r['score'] if r['score'] is not None else -1e9), reverse=True)
    return ranked


def write_ranking(out_root: Path, ranked: Sequence[Dict[str, Any]]):
    combined_dir = out_root / 'combined'
    combined_dir.mkdir(parents=True, exist_ok=True)
    csv_path = combined_dir / 'ann_ranking.csv'
    fields = ['index','expiry_tag','offset','horizon','window','k','mode','rows','speedup_avg','prune_ratio_avg','q50_mad_avg','latency_ms_avg','baseline_latency_ms_avg','effectiveness_score','effectiveness_score_adjusted','ann_guard_trigger_rate','score']
    with csv_path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in ranked:
            w.writerow({k: r.get(k) for k in fields})
    print(f'[write] {csv_path}')


def main():
    ns = parse_args()
    def run_once(candidate: int) -> Dict[str, Any]:
        prev = ns.ann_max_candidates
        ns.ann_max_candidates = candidate
        combos = build_combos(ns)
        out_root = REPO_ROOT / (ns.out_root + f"_{candidate}") if ladder else REPO_ROOT / ns.out_root
        raw_dir = out_root / 'raw'
        all_rows: List[Dict[str, Any]] = []
        for combo in combos:
            combo_dir = raw_dir
            try:
                eval_csv = run_eval(ns, combo, combo_dir)
                rows = parse_eval_rows(eval_csv)
                for r in rows:
                    r['mode'] = combo.mode
                all_rows.extend(rows)
            except SystemExit:
                raise
            except Exception as e:
                print('[warn] combo failed', combo, e)
                if not ns.continue_on_error:
                    raise SystemExit(1)
        summary = aggregate(all_rows)
        write_outputs(out_root, all_rows, summary)
        ranked = group_and_rank(
            all_rows,
            w_speedup=float(getattr(ns, 'rank_w_speedup', 1.0)),
            w_prune=float(getattr(ns, 'rank_w_prune', 1.0)),
            w_mad=float(getattr(ns, 'rank_w_mad', 0.2)),
            w_latency=float(getattr(ns, 'rank_w_latency', 0.001)),
        )
        write_ranking(out_root, ranked)
        if not all_rows:
            print('[error] no rows collected; verify data availability / date range')
        ns.ann_max_candidates = prev
        out_obj: Dict[str, Any] = {
            'candidate': candidate,
            'rows': summary.get('rows'),
            'speedup_avg': summary.get('speedup_avg'),
            'prune_ratio_avg': summary.get('prune_ratio_avg'),
            'q50_mad_avg': summary.get('q50_mad_avg'),
            'build_ms_avg': summary.get('build_ms_avg'),
            'latency_ms_avg': summary.get('latency_ms_avg'),
        }
        # Flatten per-mode breakdown for ladder comparison (if available)
        mb = summary.get('mode_breakdown') or {}
        for mode_name, stats in mb.items():
            out_obj[f'{mode_name}_speedup_avg'] = stats.get('speedup_avg')
            out_obj[f'{mode_name}_prune_ratio_avg'] = stats.get('prune_ratio_avg')
            out_obj[f'{mode_name}_q50_mad_avg'] = stats.get('q50_mad_avg')
        return out_obj

    ladder = None
    if ns.ann_candidate_ladder:
        ladder = [int(x) for x in ns.ann_candidate_ladder.split(',') if x.strip()]
    if ladder:
        comparison: List[Dict[str, Any]] = []
        for c in ladder:
            print(f'[ladder] running ann_max_candidates={c}')
            comparison.append(run_once(c))
        # Write comparison CSV in base out_root
        base_root = REPO_ROOT / ns.out_root
        combined_dir = base_root / 'combined'
        combined_dir.mkdir(parents=True, exist_ok=True)
        comp_csv = combined_dir / 'ann_candidate_ladder_comparison.csv'
        import csv as _csv
        # Determine per-mode column set
        mode_cols = set()
        for r in comparison:
            for k in list(r.keys()):
                if k.endswith('_speedup_avg') or k.endswith('_prune_ratio_avg') or k.endswith('_q50_mad_avg'):
                    mode_cols.add(k)
        base_fields = ['ann_max_candidates','rows','speedup_avg','prune_ratio_avg','q50_mad_avg','build_ms_avg','latency_ms_avg','effectiveness_score']
        all_fields = base_fields + sorted(mode_cols)
        with comp_csv.open('w', newline='', encoding='utf-8') as f:
            w = _csv.DictWriter(f, fieldnames=all_fields)
            w.writeheader()
            for row in comparison:
                sp = row.get('speedup_avg') or 0.0
                pr = row.get('prune_ratio_avg')
                pr = pr if pr is not None else 1.0
                md = row.get('q50_mad_avg') or 0.0
                eff = sp * (1.0 - pr) - md
                out_line = {
                    'ann_max_candidates': row.get('candidate'),
                    'rows': row.get('rows'),
                    'speedup_avg': row.get('speedup_avg'),
                    'prune_ratio_avg': row.get('prune_ratio_avg'),
                    'q50_mad_avg': row.get('q50_mad_avg'),
                    'build_ms_avg': row.get('build_ms_avg'),
                    'latency_ms_avg': row.get('latency_ms_avg'),
                    'effectiveness_score': round(eff, 6),
                }
                for mc in mode_cols:
                    out_line[mc] = row.get(mc)
                w.writerow(out_line)
        print(f'[write] {comp_csv}')
        # Optional: invoke auto-tuner on the comparison CSV
        if bool(getattr(ns, 'auto_tune', False)):
            tuner = REPO_ROOT / 'scripts' / 'ml' / 'ann_auto_tune_candidates.py'
            out_json = combined_dir / 'ann_auto_tune.json'
            cmd = [
                ns.python,
                str(tuner),
                '--comparison', str(comp_csv),
                '--target-mad', str(float(getattr(ns, 'auto_tune_target_mad', 0.1))),
                '--min-prune-gain', str(float(getattr(ns, 'auto_tune_min_prune', 0.05))),
                '--output', str(out_json),
            ]
            env = dict(**__import__('os').environ)
            env['PYTHONPATH'] = str(REPO_ROOT)
            print('[auto-tune] running', ' '.join(cmd))
            res = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, capture_output=not ns.verbose, text=True)
            if res.returncode != 0:
                if not ns.verbose:
                    print('[auto-tune:error]', res.stderr.strip())
                else:
                    print(res.stdout)
                    print(res.stderr)
                # Do not hard fail the harness
                print('[auto-tune] tuner failed (continuing)')
            else:
                if not ns.verbose:
                    # print key line from stdout if present
                    for line in res.stdout.splitlines():
                        if line.strip().startswith('[auto-tune]'):
                            print(line)
                print(f'[auto-tune] suggestion at {out_json}')
    else:
        run_once(ns.ann_max_candidates)

if __name__ == '__main__':
    main()
