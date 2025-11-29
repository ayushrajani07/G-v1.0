"""Prometheus rule latency profiler.

Queries a set of expressions repeatedly and computes latency percentiles.
Requires PROMETHEUS_URL (or --prom-url) pointing to a Prometheus HTTP API.
Skips profiling if no endpoint available (outputs status=skipped and exits 0).

Usage:
  python scripts/monitor/prom_rule_latency_profiler.py --expressions g6_forecast_norm_error_drift_ratio:adaptive_threshold --iterations 30 --threshold-p95-ms 250
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from statistics import median
from typing import List, Dict
import requests

DEFAULT_EXPRESSIONS = [
    "g6_forecast_norm_error_drift_ratio:adaptive_threshold",
    "g6_forecast_norm_error_drift_ratio:quantile95_6h",
    "g6_forecast_norm_error_drift_ratio:quantile99_6h",
    "g6_forecast_coverage_drift_delta_pct:adaptive_threshold",
    "g6_forecast_coverage_drift_delta_pct:quantile95_6h",
]


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = int(round(p * (len(s) - 1)))
    return s[idx]


def profile(prom_url: str, expressions: List[str], iterations: int, timeout: int) -> Dict:
    lat_map: Dict[str, List[float]] = {e: [] for e in expressions}
    session = requests.Session()
    for e in expressions:
        for _ in range(iterations):
            t0 = time.perf_counter()
            try:
                r = session.get(f"{prom_url.rstrip('/')}/api/v1/query", params={"query": e}, timeout=timeout)
                _ = r.status_code
            except Exception:
                pass
            lat_ms = (time.perf_counter() - t0) * 1000.0
            lat_map[e].append(lat_ms)
    all_lats = [l for lst in lat_map.values() for l in lst]
    return {
        "expressions": expressions,
        "iterations": iterations,
        "per_expression": {
            e: {
                "count": len(lat_map[e]),
                "p50_ms": round(median(lat_map[e]), 2) if lat_map[e] else 0.0,
                "p95_ms": round(percentile(lat_map[e], 0.95), 2) if lat_map[e] else 0.0,
                "max_ms": round(max(lat_map[e]), 2) if lat_map[e] else 0.0,
            } for e in expressions
        },
        "aggregate": {
            "p50_ms": round(median(all_lats), 2) if all_lats else 0.0,
            "p95_ms": round(percentile(all_lats, 0.95), 2) if all_lats else 0.0,
            "max_ms": round(max(all_lats), 2) if all_lats else 0.0,
        }
    }


def main():
    ap = argparse.ArgumentParser(description="Prometheus rule latency profiler")
    ap.add_argument("--prom-url", default=os.environ.get("PROMETHEUS_URL", ""))
    ap.add_argument("--expressions", default=",".join(DEFAULT_EXPRESSIONS))
    ap.add_argument("--iterations", type=int, default=20)
    ap.add_argument("--timeout", type=int, default=10)
    ap.add_argument("--threshold-p95-ms", type=float, default=250.0)
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    if not args.prom_url:
        summary = {"status": "skipped", "reason": "PROMETHEUS_URL not set"}
        print(json.dumps(summary, indent=2))
        sys.exit(0)

    exprs = [e.strip() for e in args.expressions.split(',') if e.strip()]
    summary = profile(args.prom_url, exprs, args.iterations, args.timeout)
    summary["status"] = "ok"
    print(json.dumps(summary, indent=2))

    if args.output:
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(summary, f, indent=2)
        except Exception as e:
            print(f"Failed writing output: {e}")

    p95 = summary['aggregate']['p95_ms']
    if p95 > args.threshold_p95_ms:
        print(f"ERROR: aggregate p95 {p95}ms > threshold {args.threshold_p95_ms}ms", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
