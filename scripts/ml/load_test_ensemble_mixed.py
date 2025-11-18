#!/usr/bin/env python3
"""Mixed Horizon & Volatility Load Test for Ensemble Forecast API.

Goal: Stress cache key diversity to evaluate adaptive TTL effectiveness.

Differences vs load_test_ensemble_multi.py:
 - Randomizes horizon per request from supplied list.
 - Randomizes avg_iv (volatility proxy) within a range.
 - Optional random quantile set selection (wider keys).
 - Periodic cache stats sampling to record entry count & (if present) per-entry TTL.

Outputs:
 - JSON summary with latency percentiles, hit ratio, unique key estimate.
 - Optional HTML report.

Usage:
  python scripts/ml/load_test_ensemble_mixed.py \
    --indices NIFTY,BANKNIFTY \
    --horizons 15,30,60,120 \
    --qps 50 --duration 120 \
    --avg-iv-range 0.15,0.45 \
    --quantile-sets 0.1,0.5,0.9;0.05,0.25,0.5,0.75,0.95 \
    --base http://127.0.0.1:9500 \
    --output reports/loadtest/mixed_adaptive_on.json
"""

from __future__ import annotations

import argparse
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import median
from typing import Dict, List, Tuple

import requests


def p50(values: List[float]) -> float:
    return float(median(values)) if values else 0.0


def p95(values: List[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(round(0.95 * (len(s) - 1))))
    return float(s[idx])


def p90(values: List[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(round(0.90 * (len(s) - 1))))
    return float(s[idx])


def parse_float_range(spec: str) -> Tuple[float, float]:
    parts = [p.strip() for p in spec.split(',') if p.strip()]
    if len(parts) != 2:
        raise ValueError(f"Invalid range spec: {spec}")
    lo, hi = map(float, parts)
    if lo >= hi:
        raise ValueError("Range lower must be < upper")
    return lo, hi


def parse_quantile_sets(spec: str) -> List[List[float]]:
    sets = []
    for chunk in spec.split(';'):
        chunk = chunk.strip()
        if not chunk:
            continue
        q_list = []
        for q in chunk.split(','):
            q = q.strip()
            if q:
                q_list.append(float(q))
        if q_list:
            sets.append(q_list)
    return sets


def fetch_forecast(base: str, params: Dict[str, str], session: requests.Session) -> Tuple[bool, float, Dict]:
    url = f"{base.rstrip('/')}/api/ml/ensemble/forecast"
    t0 = time.perf_counter()
    try:
        r = session.get(url, params=params, timeout=10)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        if r.status_code == 200:
            return True, latency_ms, r.json()
        return False, latency_ms, {}
    except Exception:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return False, latency_ms, {}


def rate_limited(qps: int, duration: int, arg_builder, submit_func, max_workers: int = 128):
    end = time.time() + duration
    interval = 1.0 / max(1, qps)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        next_at = time.time()
        futures = []
        while time.time() < end:
            params = arg_builder()
            futures.append(ex.submit(submit_func, params))
            next_at += interval
            sleep = next_at - time.time()
            if sleep > 0:
                time.sleep(sleep)
        for f in as_completed(futures):
            yield f


def sample_cache_stats(base: str) -> Dict:
    url = f"{base.rstrip('/')}/api/ml/ensemble/cache/stats"
    try:
        r = requests.get(url, timeout=5)
        if r.ok:
            return r.json()
    except Exception:
        pass
    return {}


def main():
    ap = argparse.ArgumentParser(description="Mixed horizon & volatility load test")
    ap.add_argument("--base", default="http://127.0.0.1:9500", help="Base API URL")
    ap.add_argument("--indices", default="NIFTY,BANKNIFTY", help="Comma-separated indices")
    ap.add_argument("--horizons", default="60", help="Comma-separated horizons (minutes)")
    ap.add_argument("--qps", type=int, default=40, help="Target queries per second")
    ap.add_argument("--duration", type=int, default=120, help="Duration in seconds")
    ap.add_argument("--avg-iv-range", default="0.15,0.45", help="Range for avg_iv randomization")
    ap.add_argument("--quantile-sets", default="0.1,0.5,0.9", help="Semicolon-separated quantile sets")
    ap.add_argument("--recent-window", type=int, default=60, help="recent_window_size param")
    ap.add_argument("--output", default="", help="Path to JSON output")
    ap.add_argument("--html-output", default="", help="Path to HTML report")
    ap.add_argument("--cache-sample-interval", type=int, default=30, help="Seconds between cache stats samples")
    args = ap.parse_args()

    indices = [i.strip().upper() for i in args.indices.split(',') if i.strip()]
    horizons = [int(h.strip()) for h in args.horizons.split(',') if h.strip()]
    iv_lo, iv_hi = parse_float_range(args.avg_iv_range)
    quantile_sets = parse_quantile_sets(args.quantile_sets)
    if not quantile_sets:
        raise SystemExit("At least one quantile set required")

    print("Mixed Load Test Configuration:")
    print(f"  Base URL: {args.base}")
    print(f"  Indices: {indices}")
    print(f"  Horizons: {horizons}")
    print(f"  QPS: {args.qps}")
    print(f"  Duration: {args.duration}s")
    print(f"  avg_iv range: {iv_lo} - {iv_hi}")
    print(f"  Quantile Sets: {['+'.join(map(str, s)) for s in quantile_sets]}")
    print()

    session = requests.Session()

    rng = random.Random(42)

    # Metrics containers
    latencies: List[float] = []
    errors = 0
    successes = 0
    cache_hits = 0
    cache_misses = 0
    normalized_errors: List[float] = []
    unique_key_fingerprint = set()
    cache_samples: List[Dict] = []
    next_cache_sample = time.time() + args.cache_sample_interval

    def build_args():
        index = rng.choice(indices)
        horizon = rng.choice(horizons)
        avg_iv = rng.uniform(iv_lo, iv_hi)
        qset = rng.choice(quantile_sets)
        quantiles_param = ','.join(f"{q:.2f}" for q in qset)
        # Underlying omitted -> server may infer
        params = {
            "index": index,
            "horizon": str(horizon),
            "avg_iv": f"{avg_iv:.4f}",
            "quantiles": quantiles_param,
            "recent_window_size": str(args.recent_window),
        }
        return params

    def submit(params):
        return fetch_forecast(args.base, params, session)

    print("Running mixed load test...")
    start = time.time()
    for fut in rate_limited(args.qps, args.duration, build_args, submit):
        success, latency_ms, data = fut.result()
        latencies.append(latency_ms)
        if success:
            successes += 1
            md = data.get("metadata", {})
            if md.get("cache_hit"):
                cache_hits += 1
            else:
                cache_misses += 1
            # Build a fingerprint of key-ish fields for uniqueness approximation
            fp = (
                data.get("index"),
                str(data.get("horizon")),
                md.get("recent_count"),
                # quantiles represented in forecast keys present
                tuple(sorted(k for k in (data.get("forecast", {}) or {}).keys() if k.startswith("p"))),
            )
            unique_key_fingerprint.add(fp)
            # Mock normalized error same as earlier harness (band width proxy)
            fc = data.get("forecast", {})
            band_low = fc.get("band_low", 0.0)
            band_high = fc.get("band_high", 0.0)
            p50_val = fc.get("p50", 0.0)
            width = band_high - band_low
            if width > 0:
                actual = p50_val + width * 0.1
                norm_err = abs(p50_val - actual) / width
                normalized_errors.append(norm_err)
        else:
            errors += 1

        if time.time() >= next_cache_sample:
            cs = sample_cache_stats(args.base)
            if cs:
                cache_samples.append({
                    "t": int(time.time()),
                    "forecast_cache_size": cs.get("forecast_cache", {}).get("size"),
                    "recent_file_cache_entries": cs.get("recent_file_cache", {}).get("current_entries"),
                })
            next_cache_sample = time.time() + args.cache_sample_interval

    elapsed = time.time() - start
    total_requests = successes + errors
    cache_total = cache_hits + cache_misses
    hit_ratio = cache_hits / cache_total if cache_total else 0.0

    results = {
        "generated_at": time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()),
        "config": {
            "base_url": args.base,
            "indices": indices,
            "horizons": horizons,
            "qps": args.qps,
            "duration": args.duration,
            "avg_iv_range": [iv_lo, iv_hi],
            "recent_window_size": args.recent_window,
            "quantile_sets": quantile_sets,
        },
        "requests": total_requests,
        "successes": successes,
        "errors": errors,
        "error_rate_pct": 100.0 * errors / total_requests if total_requests else 0.0,
        "latency_p50_ms": p50(latencies),
        "latency_p95_ms": p95(latencies),
        "cache_hit_ratio": hit_ratio,
        "normalized_error_p90": p90(normalized_errors),
        "unique_key_fingerprint_count": len(unique_key_fingerprint),
        "actual_qps": total_requests / elapsed if elapsed > 0 else 0.0,
        "elapsed_seconds": elapsed,
        "cache_samples": cache_samples,
    }

    print("\n=== MIXED LOAD TEST COMPLETE ===")
    print(f"Requests: {total_requests}")
    print(f"Successes: {successes} Errors: {errors} (error rate {results['error_rate_pct']:.2f}%)")
    print(f"Latency P50: {results['latency_p50_ms']:.2f}ms P95: {results['latency_p95_ms']:.2f}ms")
    print(f"Cache Hit Ratio: {hit_ratio:.2%}")
    print(f"Unique Key Fingerprints: {results['unique_key_fingerprint_count']}")
    print(f"Normalized Error P90 (mock): {results['normalized_error_p90']:.3f}")
    if cache_samples:
        print(f"Cache Samples Collected: {len(cache_samples)}")

    summary_json = json.dumps(results, indent=2)
    print("\nJSON Summary:\n" + summary_json)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(summary_json)
        print(f"\nJSON written to: {args.output}")

    if args.html_output:
        # Minimal HTML for quick view
        html = f"""<html><head><title>Mixed Load Test</title></head><body>
        <h1>Mixed Load Test Summary</h1>
        <pre>{summary_json}</pre>
        </body></html>"""
        html_path = Path(args.html_output)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(html)
        print(f"HTML report written to: {args.html_output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
