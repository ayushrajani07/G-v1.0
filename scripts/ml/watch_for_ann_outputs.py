#!/usr/bin/env python
"""Watch for ANN harness output CSVs and print a short header preview when they appear.

This is a lightweight file watcher for local use (polling). It checks for:
  1. results/ann_large_extended/combined/ann_candidate_ladder_comparison.csv
  2. results/ann_large_tuned/combined/ann_summary.csv
  3. results/ann_large_tuned/combined/ann_ranking.csv

Once a file is detected, it prints the first N lines (default 15) then marks it as reported.
Run it while the harness is executing to auto-surface the outputs in the terminal/editor.

Usage:
  python scripts/ml/watch_for_ann_outputs.py --interval 5 --lines 15

Can be extended to open in an editor via VS Code command integration if needed.
"""
from __future__ import annotations
import argparse, time
from pathlib import Path

TARGETS = [
    Path('results/ann_large_extended/combined/ann_candidate_ladder_comparison.csv'),
    Path('results/ann_large_tuned/combined/ann_summary.csv'),
    Path('results/ann_large_tuned/combined/ann_ranking.csv'),
]


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--interval', type=float, default=5.0, help='Poll interval seconds')
    ap.add_argument('--lines', type=int, default=15, help='Number of lines to preview when file appears')
    ap.add_argument('--timeout', type=int, default=0, help='Optional max seconds to run (0 = infinite)')
    ap.add_argument('--tuned-only', action='store_true', help='Watch only tuned combined CSVs')
    ap.add_argument('--tail', action='store_true', help='Stream appended lines (like tail -f) after initial preview')
    return ap.parse_args()


def preview(p: Path, max_lines: int):
    try:
        with p.open('r', encoding='utf-8') as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                lines.append(line.rstrip('\n'))
        print(f'\n[announce] {p} (first {len(lines)} lines)')
        for ln in lines:
            print(ln)
    except Exception as e:
        print(f'[warn] failed preview {p}: {e}')


def main():
    ns = parse_args()
    start = time.time()
    reported = set()
    # Convert to absolute paths relative to repo root
    root = Path(__file__).resolve().parents[2]
    targets = TARGETS
    if ns.tuned_only:
        targets = [
            Path('results/ann_large_tuned/combined/ann_summary.csv'),
            Path('results/ann_large_tuned/combined/ann_ranking.csv'),
        ]
    targets_abs = [root / t for t in targets]
    print('[watch] monitoring ANN output CSV targets...')
    # Track last sizes for tailing
    last_sizes = {p: 0 for p in targets_abs}
    while True:
        now = time.time()
        if ns.timeout and (now - start) > ns.timeout:
            print('[watch] timeout reached; exiting')
            break
        for p in targets_abs:
            if p.exists():
                if p not in reported:
                    preview(p, ns.lines)
                    reported.add(p)
                    try:
                        last_sizes[p] = p.stat().st_size
                    except Exception:
                        last_sizes[p] = last_sizes.get(p, 0)
                elif ns.tail:
                    try:
                        size = p.stat().st_size
                        last = last_sizes.get(p, 0)
                        if size > last:
                            with p.open('r', encoding='utf-8') as f:
                                f.seek(last)
                                new_data = f.read()
                            if new_data:
                                print(f"\n[tail] {p} (+{size-last} bytes)")
                                for line in new_data.splitlines():
                                    print(line)
                            last_sizes[p] = size
                    except Exception as e:
                        print(f'[warn] tail failed for {p}: {e}')
        # Exit early if all reported and not tailing
        if not ns.tail and len(reported) == len(targets_abs):
            print('[watch] all targets reported; exiting')
            break
        time.sleep(ns.interval)

if __name__ == '__main__':
    main()
