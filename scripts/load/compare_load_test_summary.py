"""Compare current load test summary with baseline.

Usage:
  python scripts/load/compare_load_test_summary.py --baseline benchmark/load_test_baseline.json --current load_test_summary.json --max-p95-growth-pct 50

Outputs JSON diff and exits non-zero if p95 growth exceeds threshold.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


def load_json(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description="Load test summary comparator")
    ap.add_argument('--baseline', required=True)
    ap.add_argument('--current', required=True)
    ap.add_argument('--max-p95-growth-pct', type=float, default=50.0)
    ap.add_argument('--output', default='')
    args = ap.parse_args()

    baseline = load_json(args.baseline)
    current = load_json(args.current)

    b_p95 = baseline.get('aggregate_latency', {}).get('p95') or baseline.get('aggregate_latency', {}).get('p95_ms') or baseline.get('aggregate_latency', {}).get('p95')
    c_p95 = current.get('aggregate_latency', {}).get('p95') or current.get('aggregate_latency', {}).get('p95_ms') or current.get('aggregate_latency', {}).get('p95')
    if b_p95 is None or c_p95 is None:
        print(json.dumps({'error': 'Missing p95 in summaries'}, indent=2))
        sys.exit(1)

    growth_pct = ((c_p95 - b_p95) / b_p95 * 100.0) if b_p95 > 0 else 0.0

    diff = {
        'baseline_p95': b_p95,
        'current_p95': c_p95,
        'growth_pct': round(growth_pct, 2),
        'threshold_pct': args.max_p95_growth_pct,
        'status': 'ok' if growth_pct <= args.max_p95_growth_pct else 'fail'
    }

    print(json.dumps(diff, indent=2))

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(diff, f, indent=2)

    if diff['status'] != 'ok':
        sys.exit(1)

if __name__ == '__main__':
    main()
