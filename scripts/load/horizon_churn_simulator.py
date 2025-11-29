"""Synthetic horizon churn simulator.

Estimates relative scrape size growth from dynamic horizon expansion/contraction.
Baseline series count approximation:
    series = indices * metrics * horizons
We treat each metric base as producing one series per (index,horizon) pair.

Outputs JSON summary with max_growth_pct and cycles detail.
Exits non-zero if max_growth_pct exceeds --threshold-pct.

Usage:
    python scripts/load/horizon_churn_simulator.py --indices NIFTY,BANKNIFTY --baseline-horizons 15,30,60 --candidate-horizons 5,10,15,30,45,60,90 --cycles 40 --threshold-pct 15 --seed 42
"""
from __future__ import annotations
import argparse
import json
import random
import sys
from dataclasses import dataclass
from typing import List, Dict

METRIC_BASES = [
    "g6_forecast_norm_error_drift_ratio",
    "g6_forecast_coverage_drift_delta_pct",
]

@dataclass
class CycleResult:
    cycle: int
    horizons: List[int]
    series_count: int
    growth_pct: float


def estimate_series(indices: List[str], metrics: List[str], horizons: List[int]) -> int:
    return len(indices) * len(metrics) * len(horizons)


def simulate_churn(indices: List[str], baseline_horizons: List[int], candidate_horizons: List[int], cycles: int, seed: int | None = None) -> Dict:
    rng = random.Random(seed)
    current = set(baseline_horizons)
    baseline_series = estimate_series(indices, METRIC_BASES, sorted(current))
    results: List[CycleResult] = []
    for c in range(1, cycles + 1):
        # Randomly decide add/remove horizon (biased to small change)
        action = rng.random()
        if action < 0.4 and len(current) < len(candidate_horizons):  # add
            addable = [h for h in candidate_horizons if h not in current]
            if addable:
                current.add(rng.choice(addable))
        elif action < 0.8 and len(current) > 1:  # remove
            removable = [h for h in current if h in candidate_horizons and h not in baseline_horizons]
            if removable:
                current.remove(rng.choice(removable))
        else:  # swap
            if len(current) >= 1 and len(current) < len(candidate_horizons):
                addable = [h for h in candidate_horizons if h not in current]
                removable = [h for h in current if h not in baseline_horizons]
                if addable and removable:
                    current.remove(rng.choice(removable))
                    current.add(rng.choice(addable))
        horizons_sorted = sorted(current)
        series = estimate_series(indices, METRIC_BASES, horizons_sorted)
        growth_pct = (series - baseline_series) / baseline_series * 100.0
        results.append(CycleResult(c, horizons_sorted, series, round(growth_pct, 2)))
    max_growth = max(r.growth_pct for r in results) if results else 0.0
    return {
        "indices": indices,
        "baseline_horizons": baseline_horizons,
        "candidate_horizons": candidate_horizons,
        "baseline_series": baseline_series,
        "cycles": [r.__dict__ for r in results],
        "max_growth_pct": round(max_growth, 2),
        "metric_bases_count": len(METRIC_BASES),
    }


def main():
    ap = argparse.ArgumentParser(description="Synthetic horizon churn simulator")
    ap.add_argument("--indices", default="NIFTY,BANKNIFTY")
    ap.add_argument("--baseline-horizons", default="15,30,60")
    ap.add_argument("--candidate-horizons", default="5,10,15,30,45,60,90,120")
    ap.add_argument("--cycles", type=int, default=40)
    ap.add_argument("--threshold-pct", type=float, default=15.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    indices = [s.strip().upper() for s in args.indices.split(',') if s.strip()]
    baseline = [int(s) for s in args.baseline_horizons.split(',') if s]
    candidates = [int(s) for s in args.candidate_horizons.split(',') if s]

    summary = simulate_churn(indices, baseline, candidates, args.cycles, args.seed)
    print(json.dumps(summary, indent=2))

    if args.output:
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(summary, f, indent=2)
        except Exception as e:
            print(f"Failed writing output: {e}")

    if summary['max_growth_pct'] > args.threshold_pct:
        print(f"ERROR: max growth {summary['max_growth_pct']} > threshold {args.threshold_pct}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
