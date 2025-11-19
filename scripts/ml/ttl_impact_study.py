#!/usr/bin/env python
"""Adaptive TTL Impact Study

Runs comparative load scenarios against the forecast endpoint to measure latency,
cache hit ratio, and error rate under different static TTLs vs adaptive TTL mode.

Usage (PowerShell):
  python scripts/ml/ttl_impact_study.py --endpoint http://localhost:9500/api/ml/ensemble/forecast \
    --indices NIFTY --horizon 60 --qps 20 --duration 25 \
    --static-ttls 5,15,30 --adaptive-min 10 --adaptive-max 60 --output metrics/ttl_study/latest.json

Notes:
- If the running service does not apply TTL changes dynamically, restart it between scenarios
  with appropriate env vars before running this script per scenario.
- For adaptive scenario, ensure env vars:
    G6_FORECAST_CACHE_ADAPTIVE_TTL=1
    G6_FORECAST_CACHE_ADAPTIVE_MIN=<adaptive-min>
    G6_FORECAST_CACHE_ADAPTIVE_MAX=<adaptive-max>
  (and unset G6_FORECAST_CACHE_TTL or set a baseline fallback.)
- Script itself does NOT mutate service env vars; it only measures.
- Output JSON structure:
  {
    "endpoint": "...",
    "horizon": 60,
    "qps": 20,
    "duration": 25,
    "scenarios": [
      {"name": "static_ttl_5", "ttl": 5, "adaptive": false, "requests": N, "errors": E,
       "hit_ratio": 0.64, "latency_ms_p50": 12.3, "latency_ms_p95": 32.1}, ...,
      {"name": "adaptive_10_60", "adaptive": true, "min": 10, "max": 60, ...}
    ],
    "baseline": "static_ttl_30",
    "deltas_vs_baseline": {
       "static_ttl_5": {"p95_delta_ms": -15.2, "hit_ratio_delta": 0.02}, ...
    },
    "generated_at": "ISO8601Z"
  }

Infinity / FastAPI endpoint can expose this file via a simple route.
"""
from __future__ import annotations

import argparse, time, json, statistics, threading
from datetime import datetime
from typing import List, Dict, Any
import requests

class ScenarioResult:
    def __init__(self, name: str):
        self.name = name
        self.latencies: List[float] = []
        self.cache_hits = 0
        self.errors = 0
        self.request_count = 0

    def record(self, latency_ms: float, cache_hit: bool):
        self.request_count += 1
        self.latencies.append(latency_ms)
        if cache_hit:
            self.cache_hits += 1

    def record_error(self):
        self.request_count += 1
        self.errors += 1

    def finalize(self) -> Dict[str, Any]:
        if self.latencies:
            p50 = statistics.quantiles(self.latencies, n=100)[49]
            p95 = statistics.quantiles(self.latencies, n=100)[94]
        else:
            p50 = p95 = 0.0
        hit_ratio = (self.cache_hits / self.request_count) if self.request_count else 0.0
        return {
            "name": self.name,
            "requests": self.request_count,
            "errors": self.errors,
            "hit_ratio": round(hit_ratio, 4),
            "latency_ms_p50": round(p50, 3),
            "latency_ms_p95": round(p95, 3)
        }

def worker(endpoint: str, index: str, horizon: int, result: ScenarioResult, stop_time: float):
    params = {
        "index": index,
        "horizon": str(horizon),
        "quantiles": "0.1,0.5,0.9",
        "recent_window_size": "60"
    }
    while time.time() < stop_time:
        start = time.perf_counter()
        try:
            r = requests.get(endpoint, params=params, timeout=5)
            elapsed_ms = (time.perf_counter() - start) * 1000
            if r.status_code == 200:
                data = r.json()
                meta = data.get("metadata", {})
                cache_hit = bool(meta.get("cache_hit"))
                result.record(elapsed_ms, cache_hit)
            else:
                result.record_error()
        except Exception:
            result.record_error()


def run_scenario(name: str, endpoint: str, indices: List[str], horizon: int, qps: int, duration: int) -> ScenarioResult:
    result = ScenarioResult(name)
    # Distribute QPS across indices
    per_index_qps = max(1, qps // max(1, len(indices)))
    threads: List[threading.Thread] = []
    stop_time = time.time() + duration
    for idx in indices:
        for _ in range(per_index_qps):
            t = threading.Thread(target=worker, args=(endpoint, idx, horizon, result, stop_time), daemon=True)
            t.start()
            threads.append(t)
    for t in threads:
        t.join()
    return result


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Adaptive TTL impact study load generator")
    ap.add_argument("--endpoint", required=True, help="Forecast endpoint URL")
    ap.add_argument("--indices", required=True, help="Comma-separated indices")
    ap.add_argument("--horizon", type=int, default=60)
    ap.add_argument("--qps", type=int, default=20, help="Total QPS target (approximate)")
    ap.add_argument("--duration", type=int, default=25, help="Seconds per scenario")
    ap.add_argument("--static-ttls", default="5,15,30", help="Comma-separated static TTL values to label scenarios")
    ap.add_argument("--adaptive-min", type=int, default=10)
    ap.add_argument("--adaptive-max", type=int, default=60)
    ap.add_argument("--baseline", default="30", help="Static TTL value to treat as baseline for deltas")
    ap.add_argument("--output", default="metrics/ttl_study/latest.json")
    ap.add_argument("--json", action="store_true", help="Print JSON to stdout as well")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    indices = [x.strip().upper() for x in args.indices.split(',') if x.strip()]
    static_ttls = [int(x) for x in args.static_ttls.split(',') if x.strip()]
    scenarios: List[Dict[str, Any]] = []

    # Run static TTL scenarios (measurement only; assumes service configured accordingly per run)
    for ttl in static_ttls:
        name = f"static_ttl_{ttl}"
        res = run_scenario(name, args.endpoint, indices, args.horizon, args.qps, args.duration)
        entry = res.finalize()
        entry.update({"ttl": ttl, "adaptive": False})
        scenarios.append(entry)

    # Adaptive scenario (service must be in adaptive mode externally)
    adaptive_name = f"adaptive_{args.adaptive_min}_{args.adaptive_max}"
    adaptive_res = run_scenario(adaptive_name, args.endpoint, indices, args.horizon, args.qps, args.duration)
    adaptive_entry = adaptive_res.finalize()
    adaptive_entry.update({"adaptive": True, "min": args.adaptive_min, "max": args.adaptive_max})
    scenarios.append(adaptive_entry)

    baseline_name = f"static_ttl_{args.baseline}"
    baseline = next((s for s in scenarios if s['name'] == baseline_name), None)
    deltas: Dict[str, Any] = {}
    if baseline:
        for s in scenarios:
            if s is baseline:
                continue
            deltas[s['name']] = {
                "p95_delta_ms": round(s['latency_ms_p95'] - baseline['latency_ms_p95'], 3),
                "hit_ratio_delta": round(s['hit_ratio'] - baseline['hit_ratio'], 4),
                "p50_delta_ms": round(s['latency_ms_p50'] - baseline['latency_ms_p50'], 3)
            }

    output = {
        "endpoint": args.endpoint,
        "indices": indices,
        "horizon": args.horizon,
        "qps": args.qps,
        "duration": args.duration,
        "scenarios": scenarios,
        "baseline": baseline_name,
        "deltas_vs_baseline": deltas,
        "generated_at": datetime.utcnow().isoformat() + "Z"
    }

    # Ensure output directory exists
    import os
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, sort_keys=True)

    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))

    # Simple text summary
    print(f"TTL impact study completed: {len(scenarios)} scenarios baseline={baseline_name}")
    for s in scenarios:
        print(f"{s['name']}: p95={s['latency_ms_p95']}ms hit_ratio={s['hit_ratio']} errors={s['errors']}")
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
