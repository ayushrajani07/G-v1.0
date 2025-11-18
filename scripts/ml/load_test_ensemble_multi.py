#!/usr/bin/env python3
"""
Multi-Index Load Test for Ensemble Forecast API - Phase 10

Extended load test harness supporting multiple indices with aggregate metrics:
- Per-index latency (p50/p95)
- Per-index error rate
- Per-index cache hit ratio
- Per-index normalized error p90
- Overall aggregate metrics

Usage:
  python scripts/ml/load_test_ensemble_multi.py \
    --indices NIFTY,BANKNIFTY,FINNIFTY \
    --qps 40 --duration 120 \
    --base http://127.0.0.1:9500 \
    --output reports/loadtest/multi_$(date +%s).json \
    --html-output reports/loadtest/multi_$(date +%s).html

Outputs:
- JSON summary to stdout and --output file
- Optional HTML report with --html-output
"""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import median
from typing import Dict, List, Tuple, Optional

import requests


def p50(values: List[float]) -> float:
    """Calculate 50th percentile."""
    return float(median(values)) if values else 0.0


def p95(values: List[float]) -> float:
    """Calculate 95th percentile."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(round(0.95 * (len(s) - 1))))
    return float(s[idx])


def p90(values: List[float]) -> float:
    """Calculate 90th percentile."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(round(0.90 * (len(s) - 1))))
    return float(s[idx])


def fetch_forecast(
    base: str,
    index: str,
    horizon: int,
    session: requests.Session,
) -> Tuple[bool, float, Dict, str]:
    """Fetch forecast and return (success, latency_ms, response_data, error_msg)."""
    params = {
        "index": index,
        "horizon": horizon,
        "recent_window_size": 60,
    }
    url = f"{base.rstrip('/')}/api/ml/ensemble/forecast"
    t0 = time.perf_counter()
    try:
        r = session.get(url, params=params, timeout=10)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        
        if r.status_code == 200:
            data = r.json()
            return True, latency_ms, data, ""
        else:
            return False, latency_ms, {}, f"HTTP {r.status_code}"
    except Exception as e:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return False, latency_ms, {}, str(e)


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
    
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        next_at = time.time()
        i = 0
        
        while time.time() < end_time:
            if i >= len(args_list):
                i = 0  # Round-robin through indices
            
            args = args_list[i]
            results.append(ex.submit(func, *args))
            i += 1
            
            next_at += interval
            now = time.time()
            sleep = next_at - now
            if sleep > 0:
                time.sleep(sleep)
        
        # Drain results
        for f in as_completed(results):
            yield f


def get_cache_stats(base: str, index: str) -> Dict:
    """Get cache statistics for a specific index."""
    url = f"{base.rstrip('/')}/api/ml/ensemble/cache/stats"
    try:
        r = requests.get(url, params={"index": index}, timeout=5)
        return r.json() if r.ok else {}
    except Exception:
        return {}


def calculate_normalized_error(forecast_data: Dict) -> Optional[float]:
    """Calculate normalized error from forecast response.
    
    Normalized error = |p50 - actual| / (band_high - band_low)
    For load test, we use a mock actual value (p50 + small noise)
    """
    try:
        forecast = forecast_data.get("forecast", {})
        p50_val = forecast.get("p50", 0.0)
        band_low = forecast.get("band_low", 0.0)
        band_high = forecast.get("band_high", 0.0)
        
        band_width = band_high - band_low
        if band_width <= 0:
            return None
        
        # Mock actual value (in production, would compare with real TP)
        actual = p50_val + (band_width * 0.1)  # Simulate 10% of band width error
        
        error = abs(p50_val - actual)
        normalized_error = error / band_width
        
        return normalized_error
    except Exception:
        return None


def generate_html_report(results: Dict, output_path: str):
    """Generate HTML report from results."""
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Multi-Index Load Test Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        h2 {{ color: #555; margin-top: 30px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #4CAF50; color: white; }}
        tr:nth-child(even) {{ background-color: #f2f2f2; }}
        .metric {{ display: inline-block; margin: 10px 20px 10px 0; }}
        .metric-value {{ font-size: 24px; font-weight: bold; color: #4CAF50; }}
        .metric-label {{ font-size: 14px; color: #666; }}
        .summary {{ background-color: #f9f9f9; padding: 20px; border-radius: 5px; margin: 20px 0; }}
    </style>
</head>
<body>
    <h1>Multi-Index Load Test Report</h1>
    <p>Generated: {results['generated_at']}</p>
    
    <div class="summary">
        <h2>Overall Summary</h2>
        <div class="metric">
            <div class="metric-value">{results['total_requests']}</div>
            <div class="metric-label">Total Requests</div>
        </div>
        <div class="metric">
            <div class="metric-value">{results['aggregate']['error_rate_pct']:.2f}%</div>
            <div class="metric-label">Error Rate</div>
        </div>
        <div class="metric">
            <div class="metric-value">{results['aggregate']['latency_p50_ms']:.1f}ms</div>
            <div class="metric-label">P50 Latency</div>
        </div>
        <div class="metric">
            <div class="metric-value">{results['aggregate']['latency_p95_ms']:.1f}ms</div>
            <div class="metric-label">P95 Latency</div>
        </div>
    </div>
    
    <h2>Per-Index Metrics</h2>
    <table>
        <tr>
            <th>Index</th>
            <th>Requests</th>
            <th>Error Rate</th>
            <th>P50 Latency (ms)</th>
            <th>P95 Latency (ms)</th>
            <th>Cache Hit Ratio</th>
            <th>Norm Error P90</th>
        </tr>
"""
    
    for index, metrics in results['per_index'].items():
        html += f"""
        <tr>
            <td>{index}</td>
            <td>{metrics['request_count']}</td>
            <td>{metrics['error_rate_pct']:.2f}%</td>
            <td>{metrics['latency_p50_ms']:.1f}</td>
            <td>{metrics['latency_p95_ms']:.1f}</td>
            <td>{metrics['cache_hit_ratio']:.2%}</td>
            <td>{metrics['normalized_error_p90']:.3f}</td>
        </tr>
"""
    
    html += """
    </table>
    
    <h2>Test Configuration</h2>
    <table>
        <tr><th>Parameter</th><th>Value</th></tr>
        <tr><td>Base URL</td><td>{base_url}</td></tr>
        <tr><td>Indices</td><td>{indices}</td></tr>
        <tr><td>Target QPS</td><td>{qps}</td></tr>
        <tr><td>Duration</td><td>{duration}s</td></tr>
        <tr><td>Horizon</td><td>{horizon} min</td></tr>
    </table>
    
</body>
</html>
""".format(
        base_url=results['config']['base_url'],
        indices=', '.join(results['config']['indices']),
        qps=results['config']['qps'],
        duration=results['config']['duration'],
        horizon=results['config']['horizon'],
    )
    
    with open(output_path, 'w') as f:
        f.write(html)


def main():
    ap = argparse.ArgumentParser(
        description="Multi-index load test for Ensemble Forecast API"
    )
    ap.add_argument("--base", default="http://127.0.0.1:9500", help="Base URL for API")
    ap.add_argument(
        "--indices",
        default="NIFTY,BANKNIFTY",
        help="Comma-separated indices to test"
    )
    ap.add_argument("--horizon", type=int, default=60, help="Forecast horizon in minutes")
    ap.add_argument("--qps", type=int, default=40, help="Target queries per second")
    ap.add_argument("--duration", type=int, default=120, help="Test duration in seconds")
    ap.add_argument("--workers", type=int, default=64, help="Max concurrent workers")
    ap.add_argument("--output", default="", help="Write JSON summary to this path")
    ap.add_argument("--html-output", default="", help="Write HTML report to this path")
    args = ap.parse_args()
    
    # Parse indices
    indices = [idx.strip().upper() for idx in args.indices.split(',') if idx.strip()]
    
    if not indices:
        print("Error: No indices specified")
        return 1
    
    print(f"Starting multi-index load test:")
    print(f"  Base URL: {args.base}")
    print(f"  Indices: {', '.join(indices)}")
    print(f"  Target QPS: {args.qps}")
    print(f"  Duration: {args.duration}s")
    print(f"  Horizon: {args.horizon}m")
    print()
    
    # Create session for connection pooling
    session = requests.Session()
    
    # Build task arguments (round-robin across indices)
    args_list = []
    for index in indices:
        args_list.append((args.base, index, args.horizon, session))
    
    # Run load test
    print("Running load test...")
    start_time = time.time()
    
    # Per-index metrics
    per_index_metrics = {idx: {
        'latencies': [],
        'errors': 0,
        'successes': 0,
        'cache_hits': 0,
        'cache_misses': 0,
        'normalized_errors': [],
    } for idx in indices}
    
    # Execute requests
    for future in rate_limited_executor(
        args.qps,
        args.duration,
        fetch_forecast,
        args_list,
        args.workers,
    ):
        try:
            success, latency_ms, data, error_msg = future.result()
            
            # Determine which index this was for (from metadata or round-robin)
            index = data.get('index', indices[0]) if data else indices[0]
            
            per_index_metrics[index]['latencies'].append(latency_ms)
            
            if success:
                per_index_metrics[index]['successes'] += 1
                
                # Check cache hit
                metadata = data.get('metadata', {})
                if metadata.get('cache_hit', False):
                    per_index_metrics[index]['cache_hits'] += 1
                else:
                    per_index_metrics[index]['cache_misses'] += 1
                
                # Calculate normalized error
                norm_error = calculate_normalized_error(data)
                if norm_error is not None:
                    per_index_metrics[index]['normalized_errors'].append(norm_error)
            else:
                per_index_metrics[index]['errors'] += 1
        
        except Exception as e:
            print(f"Warning: Exception processing result: {e}")
    
    elapsed = time.time() - start_time
    
    # Calculate aggregate and per-index statistics
    all_latencies = []
    total_requests = 0
    total_errors = 0
    
    per_index_results = {}
    for index, metrics in per_index_metrics.items():
        request_count = metrics['successes'] + metrics['errors']
        total_requests += request_count
        total_errors += metrics['errors']
        
        all_latencies.extend(metrics['latencies'])
        
        cache_total = metrics['cache_hits'] + metrics['cache_misses']
        cache_hit_ratio = metrics['cache_hits'] / cache_total if cache_total > 0 else 0.0
        
        per_index_results[index] = {
            'request_count': request_count,
            'error_count': metrics['errors'],
            'error_rate_pct': 100.0 * metrics['errors'] / request_count if request_count > 0 else 0.0,
            'latency_p50_ms': p50(metrics['latencies']),
            'latency_p95_ms': p95(metrics['latencies']),
            'cache_hit_ratio': cache_hit_ratio,
            'normalized_error_p90': p90(metrics['normalized_errors']),
        }
    
    # Aggregate metrics
    aggregate_results = {
        'latency_p50_ms': p50(all_latencies),
        'latency_p95_ms': p95(all_latencies),
        'error_rate_pct': 100.0 * total_errors / total_requests if total_requests > 0 else 0.0,
        'actual_qps': total_requests / elapsed if elapsed > 0 else 0.0,
    }
    
    # Build final results
    results = {
        'generated_at': time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()),
        'config': {
            'base_url': args.base,
            'indices': indices,
            'qps': args.qps,
            'duration': args.duration,
            'horizon': args.horizon,
        },
        'total_requests': total_requests,
        'elapsed_seconds': elapsed,
        'aggregate': aggregate_results,
        'per_index': per_index_results,
    }
    
    # Print summary
    print()
    print("=" * 60)
    print("LOAD TEST COMPLETE")
    print("=" * 60)
    print(f"Total Requests: {total_requests}")
    print(f"Elapsed Time: {elapsed:.1f}s")
    print(f"Actual QPS: {aggregate_results['actual_qps']:.1f}")
    print()
    print("Aggregate Metrics:")
    print(f"  P50 Latency: {aggregate_results['latency_p50_ms']:.1f}ms")
    print(f"  P95 Latency: {aggregate_results['latency_p95_ms']:.1f}ms")
    print(f"  Error Rate: {aggregate_results['error_rate_pct']:.2f}%")
    print()
    print("Per-Index Metrics:")
    for index, metrics in per_index_results.items():
        print(f"\n  {index}:")
        print(f"    Requests: {metrics['request_count']}")
        print(f"    P50 Latency: {metrics['latency_p50_ms']:.1f}ms")
        print(f"    P95 Latency: {metrics['latency_p95_ms']:.1f}ms")
        print(f"    Error Rate: {metrics['error_rate_pct']:.2f}%")
        print(f"    Cache Hit Ratio: {metrics['cache_hit_ratio']:.2%}")
        print(f"    Normalized Error P90: {metrics['normalized_error_p90']:.3f}")
    
    # Write JSON output
    json_output = json.dumps(results, indent=2)
    print()
    print("JSON Summary:")
    print(json_output)
    
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            f.write(json_output)
        print(f"\nJSON written to: {args.output}")
    
    # Generate HTML report if requested
    if args.html_output:
        html_path = Path(args.html_output)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        generate_html_report(results, str(html_path))
        print(f"HTML report written to: {args.html_output}")
    
    return 0


if __name__ == '__main__':
    exit(main())
