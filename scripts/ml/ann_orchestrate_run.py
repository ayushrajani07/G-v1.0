#!/usr/bin/env python
"""One-click pipeline: extended -> tuned -> diff -> report

Runs the large-slice ANN harness in two passes and produces a consolidated run folder.

Steps:
  1) Extended pass (candidates=50)
  2) Tuned pass (per-mode candidates 20/20/20)
  3) Generate tuned ranking report (Markdown)
  4) Generate tuned-vs-extended diff (CSV + Markdown)
  5) Collect artifacts into results/ann_runs/<timestamp> for easy sharing

Usage (PowerShell example):
  python scripts/ml/ann_orchestrate_run.py \
    --indices NIFTY,BANKNIFTY \
    --tags this_week,next_week \
    --offsets 0,+50 \
    --start 2025-09-30 --end 2025-11-06 \
    --windows 60,120 --horizons 60 --k 10,15 --modes retrieval,auto,hybrid

Notes:
  - PYTHONPATH is set to repo root for all subprocesses.
  - Uses the same Python interpreter as this process.
"""
from __future__ import annotations
import argparse, os, shutil, subprocess, sys, time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--indices', required=True)
    ap.add_argument('--tags', required=True)
    ap.add_argument('--offsets', required=True)
    ap.add_argument('--start', required=True)
    ap.add_argument('--end', required=True)
    ap.add_argument('--windows', default='60,120')
    ap.add_argument('--horizons', default='60')
    ap.add_argument('--k', default='10,15')
    ap.add_argument('--modes', default='retrieval,auto,hybrid')
    ap.add_argument('--out-base', default='results/ann_runs')
    ap.add_argument('--extended-root', default='results/ann_large_extended')
    ap.add_argument('--tuned-root', default='results/ann_large_tuned')
    ap.add_argument('--diff-root', default='results/ann_large_diff')
    ap.add_argument('--run-name', default='')
    ap.add_argument('--verbose', action='store_true')
    return ap.parse_args()

def run_cmd(args: list[str], *, cwd: Path) -> None:
    env = os.environ.copy()
    env['PYTHONPATH'] = str(REPO_ROOT)
    if os.name == 'nt':
        # Ensure backslashes don't break arguments in PowerShell; we call via python directly.
        pass
    print('[run]', ' '.join(args))
    res = subprocess.run(args, cwd=str(cwd), env=env, text=True)
    if res.returncode != 0:
        raise SystemExit(f'Command failed with code {res.returncode}')

def main():
    ns = parse_args()
    py = sys.executable
    ts = time.strftime('%Y%m%d_%H%M%S')
    run_id = ts + (f"_{ns.run_name}" if ns.run_name else '')
    out_base = REPO_ROOT / ns.out_base / run_id
    out_base.mkdir(parents=True, exist_ok=True)

    # 1) Extended
    run_cmd([
        py, str(REPO_ROOT / 'scripts' / 'ml' / 'ann_harness_large.py'),
        '--indices', ns.indices,
        '--tags', ns.tags,
        '--offsets', ns.offsets,
        '--start', ns.start,
        '--end', ns.end,
        '--windows', ns.windows,
        '--horizons', ns.horizons,
        '--k', ns.k,
        '--modes', ns.modes,
        '--ann-max-candidates', '50',
        '--metrics-minimal',
        '--out-root', ns.extended_root,
    ], cwd=REPO_ROOT)

    # 2) Tuned (per-mode 20)
    run_cmd([
        py, str(REPO_ROOT / 'scripts' / 'ml' / 'ann_harness_large.py'),
        '--indices', ns.indices,
        '--tags', ns.tags,
        '--offsets', ns.offsets,
        '--start', ns.start,
        '--end', ns.end,
        '--windows', ns.windows,
        '--horizons', ns.horizons,
        '--k', ns.k,
        '--modes', ns.modes,
        '--ann-max-candidates-per-mode', 'retrieval=20,auto=20,hybrid=20',
        '--metrics-minimal',
        '--out-root', ns.tuned_root,
    ], cwd=REPO_ROOT)

    # 3) Report (tuned)
    tuned_rank = REPO_ROOT / ns.tuned_root / 'combined' / 'ann_ranking.csv'
    tuned_report = REPO_ROOT / ns.tuned_root / 'combined' / 'ann_ranking_report.md'
    run_cmd([
        py, str(REPO_ROOT / 'scripts' / 'ml' / 'ann_ranking_report.py'),
        '--ranking', str(tuned_rank),
        '--out', str(tuned_report),
        '--top', '30',
    ], cwd=REPO_ROOT)

    # 4) Diff
    diff_dir = REPO_ROOT / ns.diff_root
    diff_dir.mkdir(parents=True, exist_ok=True)
    run_cmd([
        py, str(REPO_ROOT / 'scripts' / 'ml' / 'ann_compare_tuned_vs_extended.py'),
        '--extended', str(REPO_ROOT / ns.extended_root / 'combined' / 'ann_ranking.csv'),
        '--tuned', str(tuned_rank),
        '--out-dir', str(diff_dir),
    ], cwd=REPO_ROOT)

    # 5) Collect artifacts into run folder
    collect = [
        REPO_ROOT / ns.extended_root / 'combined' / 'ann_summary.csv',
        REPO_ROOT / ns.extended_root / 'combined' / 'ann_ranking.csv',
        REPO_ROOT / ns.tuned_root / 'combined' / 'ann_summary.csv',
        tuned_rank,
        tuned_report,
        diff_dir / 'ann_ranking_diff.csv',
        diff_dir / 'ann_ranking_diff.md',
    ]
    for p in collect:
        if p.exists():
            shutil.copy2(p, out_base / p.name)
    print('[done] Orchestrated run artifacts at', out_base)

if __name__ == '__main__':
    main()
