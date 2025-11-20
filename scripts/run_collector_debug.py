#!/usr/bin/env python3
"""Debug runner for unified collectors.

Adds:
- Strict signal handling (Ctrl+C) via G6_COLLECTOR_STRICT_SIGNALS=1
- Watchdog (G6_COLLECTOR_WATCHDOG=1) with timeout env vars
- Optional single pass or continuous loop

Usage (PowerShell):
  $env:G6_COLLECTOR_STRICT_SIGNALS='1'
  $env:G6_COLLECTOR_WATCHDOG='1'
  $env:G6_COLLECTOR_STALL_TIMEOUT_SEC='40'
  python scripts/run_collector_debug.py --loop
"""
from __future__ import annotations
import argparse, os, time, sys, json
from typing import Any

os.environ.setdefault('G6_COLLECTOR_STRICT_SIGNALS','1')
os.environ.setdefault('G6_COLLECTOR_WATCHDOG','1')

from src.collectors.unified_collectors import build_collector_context, CycleContext  # type: ignore

parser = argparse.ArgumentParser()
parser.add_argument('--loop', action='store_true', help='Run continuous cycles')
parser.add_argument('--sleep', type=float, default=2.0, help='Sleep between cycles (s)')
parser.add_argument('--json', action='store_true', help='Print compact JSON summary each cycle')
args = parser.parse_args()

ctx = build_collector_context()  # build base context (Phase 1)

cycle_no = 0
while True:
    cycle_no += 1
    try:
        cctx = CycleContext(cycle_no=cycle_no)  # lightweight instantiation
        result: dict[str, Any] = cctx.run_cycle(ctx)  # type: ignore[attr-defined]
        if args.json:
            core = {
                'cycle': cycle_no,
                'indices': {ix.get('index'): {
                    'strike_coverage_avg': ix.get('strike_coverage_avg'),
                    'field_coverage_avg': ix.get('field_coverage_avg'),
                    'option_count': ix.get('option_count')
                } for ix in result.get('indices', [])},
            }
            print('[debug-cycle]', json.dumps(core, separators=(',',':')), flush=True)
    except KeyboardInterrupt:
        print('Ctrl+C received – stopping collector.', flush=True)
        break
    except Exception as e:
        print(f'[debug-cycle] error: {e}', flush=True)
    if not args.loop:
        break
    time.sleep(args.sleep)

