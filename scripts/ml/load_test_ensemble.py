#!/usr/bin/env python3
"""
Unified Load Test Harness for Ensemble Forecast API.

Consolidates functionality from:
- load_test_ensemble_simple.py (Basic load testing)
- load_test_ensemble_multi.py (Multi-index, detailed metrics)
- load_test_ensemble_async.py (Async support - future)

Features:
- Multi-index support
- Configurable QPS and duration
- Detailed latency metrics (p50, p90, p95)
- Cache hit ratio tracking
- JSON and HTML reporting
- Thread-based execution (requests)

Usage:
    python scripts/ml/load_test_ensemble.py --indices NIFTY,BANKNIFTY --qps 20 --duration 30
"""

import argparse
import json
import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import median
from typing import Dict, List, Tuple, Optional, Any

import requests

# -----------------------------------------------------------------------------
# Statistics Helpers
# -----------------------------------------------------------------------------

def calculate_percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(round(p * (len(s) - 1))))
    return float(s[idx])

def p50(values: List[float]) -> float:
    return float(median(values)) if values else 0.0

def p90(values: List[float]) -> float:
    return calculate_percentile(values, 0.90)

def p95(values: List[float]) -> float:
    return calculate_percentile(values, 0.95)

def p99(values: List[float]) -> float:
    return calculate_percentile(values, 0.99)

# -----------------------------------------------------------------------------
# Request Execution
# -----------------------------------------------------------------------------

def fetch_forecast(
    base: str,
    index: str,
    horizon: int,
    detail: str,
    recent_window_size: int,
    session: requests.Session,
) -> Tuple[str, bool, float, Dict, str]:
    """Fetch forecast and return (index, success, latency_ms, response_data, error_msg)."""
    params = {
        "index": index,
        "horizon": horizon,
        "recent_window_size": recent_window_size,
    }
    if detail == "full":
        params["detail"] = "full"
        
    url = f"{base.rstrip('/')}/api/ml/ensemble/forecast"
    t0 = time.perf_counter()
    try:
        r = session.get(url, params=params, timeout=10)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        if r.status_code == 200:
            try:
                data = r.json()
                return index, True, latency_ms, data, ""
            except ValueError:
                return index, False, latency_ms, {}, "Invalid JSON"
        else:
            return index, False, latency_ms, {}, f"HTTP {r.status_code}: {r.text[:100]}"
    except Exception as e:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return index, False, latency_ms, {}, str(e)

def rate_limited_executor(
    qps: int,
    duration: int,
    func,
    args_list: List[Tuple],
    max_workers: int = 64,
):
    """Submit tasks at approximately QPS for a given duration."""
    end_time = time.time() + duration
    interval = 1.0 / max(1, qps)
    results = []
    
    print(f"Starting load test: {qps} QPS for {duration}s using {max_workers} workers...")
    
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        next_at = time.time()
        i = 0
        while time.time() < end_time:
            if not args_list:
                break
                
            if i >= len(args_list):
                i = 0
            
            args = args_list[i]
            results.append(ex.submit(func, *args))
            i += 1
            
            next_at += interval
            now = time.time()
            sleep = next_at - now
            if sleep > 0:
                time.sleep(sleep)
                
        # Wait for completion
        print("Waiting for pending requests...")
        for f in as_completed(results):
            yield f

def get_cache_stats(base: str) -> Dict:
    url = f"{base.rstrip('/')}/api/ml/ensemble/cache/stats"
    try:
        r = requests.get(url, timeout=5)
        return r.json() if r.ok else {}
    except Exception:
        return {}

# -----------------------------------------------------------------------------
# Reporting
# -----------------------------------------------------------------------------

def generate_html_report(metrics: Dict[str, Any], output_path: str):
    """Generate a simple HTML report."""
    html = f"""
    <html>
    <head>
        <title>Ensemble Load Test Report</title>
        <style>
            body {{ font-family: sans-serif; margin: 20px; }}
            table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
            .metric-card {{ border: 1px solid #ccc; padding: 15px; margin-bottom: 15px; border-radius: 5px; }}
            .success {{ color: green; }}
            .failure {{ color: red; }}
        </style>
    </head>
    <body>
        <h1>Ensemble Load Test Report</h1>
        <div class="metric-card">
            <h2>Summary</h2>
            <p><strong>Total Requests:</strong> {metrics['total_requests']}</p>
            <p><strong>Duration:</strong> {metrics['duration_sec']}s</p>
            <p><strong>Actual QPS:</strong> {metrics['actual_qps']:.2f}</p>
            <p><strong>Error Rate:</strong> {metrics['error_rate_pct']:.2f}%</p>
        </div>

        <h2>Per-Index Metrics</h2>
        <table>
            <tr>
                <th>Index</th>
                <th>Requests</th>
                <th>Errors</th>
                <th>Latency p50 (ms)</th>
                <th>Latency p95 (ms)</th>
                <th>Cache Hit %</th>
            </tr>
    """
    
    for idx, data in metrics.get('per_index', {}).items():
        html += f"""
            <tr>
                <td>{idx}</td>
                <td>{data['count']}</td>
                <td>{data['errors']}</td>
                <td>{data['latency_p50']:.2f}</td>
                <td>{data['latency_p95']:.2f}</td>
                <td>{data['cache_hit_pct']:.1f}%</td>
            </tr>
        """
        
    html += """
        </table>
    </body>
    </html>
    """
    
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"HTML report written to {output_path}")
    except Exception as e:
        print(f"Failed to write HTML report: {e}")

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Unified Load Test Harness")
    ap.add_argument("--base", default="http://127.0.0.1:9500", help="Base URL for API")
    ap.add_argument("--indices", default="NIFTY,BANKNIFTY,SENSEX", help="Comma-separated indices")
    ap.add_argument("--horizon", type=int, default=60)
    ap.add_argument("--detail", choices=["snapshot", "full"], default="snapshot")
    ap.add_argument("--recent-window-size", type=int, default=60)
    ap.add_argument("--qps", type=int, default=20)
    ap.add_argument("--duration", type=int, default=30)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--output", default="", help="Write JSON summary to this path")
    ap.add_argument("--html-output", default="", help="Write HTML report to this path")
    args = ap.parse_args()

    indices = [i.strip().upper() for i in args.indices.split(",") if i.strip()]
    if not indices:
        print("No indices specified.")
        sys.exit(1)

    # Prepare request arguments
    # Round-robin indices
    req_args = []
    session = requests.Session()
    
    # Pre-warm session
    try:
        session.get(f"{args.base.rstrip('/')}/docs", timeout=2)
    except:
        pass

    for i in range(args.qps * args.duration + 100): # Buffer
        idx = indices[i % len(indices)]
        req_args.append((args.base, idx, args.horizon, args.detail, args.recent_window_size, session))

    # Run load test
    start_time = time.time()
    latencies: Dict[str, List[float]] = {idx: [] for idx in indices}
    errors: Dict[str, int] = {idx: 0 for idx in indices}
    cache_hits: Dict[str, int] = {idx: 0 for idx in indices}
    counts: Dict[str, int] = {idx: 0 for idx in indices}
    
    total_reqs = 0
    
    for future in rate_limited_executor(args.qps, args.duration, fetch_forecast, req_args, max_workers=args.workers):
        total_reqs += 1
        try:
            idx, ok, lat, data, err = future.result()
            
            # If we can't determine index, skip per-index attribution or log to global
            if idx not in latencies:
                latencies[idx] = []
                errors[idx] = 0
                cache_hits[idx] = 0
                counts[idx] = 0

            counts[idx] += 1
            latencies[idx].append(lat)
            
            if not ok:
                errors[idx] += 1
            else:
                meta = data.get('metadata', {})
                if meta.get('cache_hit'):
                    cache_hits[idx] += 1
                    
        except Exception as e:
            print(f"Worker exception: {e}")

    actual_duration = time.time() - start_time
    
    # Aggregate results
    results = {
        "timestamp": int(time.time()),
        "config": vars(args),
        "duration_sec": round(actual_duration, 2),
        "total_requests": total_reqs,
        "actual_qps": round(total_reqs / actual_duration, 2) if actual_duration > 0 else 0,
        "per_index": {}
    }
    
    total_errors = sum(errors.values())
    results["error_rate_pct"] = (total_errors / total_reqs * 100) if total_reqs > 0 else 0.0
    
    all_latencies = []
    for idx in latencies:
        all_latencies.extend(latencies[idx])
        
    results["aggregate_latency"] = {
        "p50": p50(all_latencies),
        "p90": p90(all_latencies),
        "p95": p95(all_latencies),
        "p99": p99(all_latencies),
        "max": max(all_latencies) if all_latencies else 0.0
    }
    
    for idx in indices:
        # Handle UNKNOWN if present
        lats = latencies.get(idx, [])
        cnt = counts.get(idx, 0)
        err = errors.get(idx, 0)
        hits = cache_hits.get(idx, 0)
        
        results["per_index"][idx] = {
            "count": cnt,
            "errors": err,
            "error_rate_pct": (err / cnt * 100) if cnt > 0 else 0.0,
            "latency_p50": p50(lats),
            "latency_p95": p95(lats),
            "cache_hit_pct": (hits / cnt * 100) if cnt > 0 else 0.0
        }

    # Print summary
    print("\n--- Load Test Summary ---")
    print(json.dumps(results, indent=2))
    
    # Write outputs
    if args.output:
        try:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"JSON summary written to {args.output}")
        except Exception as e:
            print(f"Failed to write JSON output: {e}")
            
    if args.html_output:
        generate_html_report(results, args.html_output)

if __name__ == "__main__":
    main()
