#!/usr/bin/env python3
"""
Demonstrate Phase 9 Ensemble API features.

This script shows how to:
1. Check Phase 9 feature flags
2. Fetch cache metrics
3. Monitor cache performance

Usage:
    python scripts/ml/demo_phase9_api.py --host localhost --port 9210
"""
import argparse
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def fetch_cache_metrics(host: str, port: int) -> dict:
    """Fetch cache metrics from API."""
    url = f"http://{host}:{port}/api/ml/ensemble/cache_metrics"
    
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            return data
    except urllib.error.URLError as e:
        print(f"Error: Could not connect to API at {url}")
        print(f"Make sure the API server is running.")
        print(f"Details: {e}")
        return {}
    except Exception as e:
        print(f"Error fetching cache metrics: {e}")
        return {}


def fetch_diagnostics(host: str, port: int, index: str) -> dict:
    """Fetch diagnostics for an index."""
    url = f"http://{host}:{port}/api/ml/ensemble/diagnostics?index={index}"
    
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            return data
    except Exception as e:
        print(f"Error fetching diagnostics: {e}")
        return {}


def print_section(title: str):
    """Print a section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_feature_flags(flags: dict):
    """Print feature flag status."""
    print_section("Phase 9 Feature Flags")
    
    flag_status = {
        'ann_window_cache': 'ANN Window Cache',
        'ann_disk_cache': 'ANN Disk Cache',
        'profiling': 'Profiling',
        'prom_metrics': 'Prometheus Metrics',
        'disable_weighted': 'Disable Weighted Quantiles'
    }
    
    for key, name in flag_status.items():
        enabled = flags.get(key, False)
        status = "✓ ENABLED" if enabled else "✗ DISABLED"
        print(f"  {name:30} {status}")


def print_cache_stats(cache_metrics: dict):
    """Print cache statistics."""
    window_cache = cache_metrics.get('window_cache', {})
    disk_cache = cache_metrics.get('disk_cache', {})
    
    # Window Cache
    print_section("ANN Window Cache Statistics")
    if window_cache.get('enabled'):
        print(f"  Status:        ENABLED")
        print(f"  Hit Ratio:     {window_cache.get('hit_ratio', 0):.2%}")
        print(f"  Cache Size:    {window_cache.get('size', 0)} entries")
        print(f"  Hits:          {window_cache.get('hits', 0)}")
        print(f"  Misses:        {window_cache.get('misses', 0)}")
        print(f"  Evictions:     {window_cache.get('evictions', 0)}")
    else:
        print("  Status:        DISABLED")
        print("  Enable with:   ENABLE_ANN_WINDOW_CACHE=1")
    
    # Disk Cache
    print_section("ANN Disk Cache Statistics")
    if disk_cache.get('enabled'):
        print(f"  Status:        ENABLED")
        print(f"  Hits:          {disk_cache.get('hits', 0)}")
        print(f"  Misses:        {disk_cache.get('misses', 0)}")
        print(f"  Saves:         {disk_cache.get('saves', 0)}")
        
        total = disk_cache.get('hits', 0) + disk_cache.get('misses', 0)
        if total > 0:
            hit_ratio = disk_cache.get('hits', 0) / total
            print(f"  Hit Ratio:     {hit_ratio:.2%}")
    else:
        print("  Status:        DISABLED")
        print("  Enable with:   ENABLE_ANN_DISK_CACHE=1")
        print("                 ANN_CACHE_DIR=/path/to/cache")


def print_diagnostics(diag: dict):
    """Print diagnostics information."""
    print_section(f"Diagnostics for {diag.get('index', 'N/A')}")
    
    print(f"\nOverall Status: {diag.get('status', 'unknown').upper()}")
    
    # Components
    print("\nComponents:")
    components = diag.get('components', {})
    for name, enabled in components.items():
        status = "✓" if enabled else "✗"
        print(f"  {status} {name}")
    
    # Metrics
    metrics = diag.get('metrics', {})
    print("\nMetrics:")
    print(f"  Forecast Count (24h): {metrics.get('forecast_count_24h', 0)}")
    print(f"  Avg Latency:          {metrics.get('avg_latency_ms', 0):.0f}ms")
    print(f"  Error Rate (24h):     {metrics.get('error_rate_24h', 0):.3%}")
    
    # Cache metrics if available
    if 'window_cache_enabled' in metrics:
        print("\n  Phase 9 Cache Metrics:")
        if metrics.get('window_cache_enabled'):
            print(f"    Window Cache Hit Ratio: {metrics.get('window_cache_hit_ratio', 0):.2%}")
        if metrics.get('disk_cache_enabled'):
            print(f"    Disk Cache Hits:        {metrics.get('disk_cache_hits', 0)}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Demonstrate Phase 9 Ensemble API features"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="localhost",
        help="API host (default: localhost)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9210,
        help="API port (default: 9210)"
    )
    parser.add_argument(
        "--index",
        type=str,
        default="NIFTY",
        help="Index for diagnostics (default: NIFTY)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of formatted display"
    )
    
    args = parser.parse_args()
    
    # Fetch data
    print(f"Fetching Phase 9 metrics from {args.host}:{args.port}...")
    cache_metrics = fetch_cache_metrics(args.host, args.port)
    
    if not cache_metrics:
        print("\nFailed to fetch cache metrics. Exiting.")
        return 1
    
    if args.json:
        # Output raw JSON
        output = {
            'timestamp': datetime.now().isoformat(),
            'cache_metrics': cache_metrics
        }
        
        # Optionally include diagnostics
        diag = fetch_diagnostics(args.host, args.port, args.index)
        if diag:
            output['diagnostics'] = diag
        
        print(json.dumps(output, indent=2))
    else:
        # Formatted display
        print_feature_flags(cache_metrics.get('feature_flags', {}))
        print_cache_stats(cache_metrics)
        
        # Fetch and display diagnostics
        print(f"\nFetching diagnostics for {args.index}...")
        diag = fetch_diagnostics(args.host, args.port, args.index)
        if diag:
            print_diagnostics(diag)
        
        # Summary
        print_section("Summary")
        flags = cache_metrics.get('feature_flags', {})
        enabled_count = sum(1 for v in flags.values() if v)
        print(f"  Phase 9 Features Enabled: {enabled_count}/{len(flags)}")
        
        window_cache = cache_metrics.get('window_cache', {})
        if window_cache.get('enabled'):
            hit_ratio = window_cache.get('hit_ratio', 0)
            if hit_ratio >= 0.7:
                print(f"  Window Cache Performance: ✓ GOOD ({hit_ratio:.1%} hit ratio)")
            else:
                print(f"  Window Cache Performance: ⚠ LOW ({hit_ratio:.1%} hit ratio - target: >70%)")
        
        print("\nFor more information:")
        print("  - API Docs: docs/ml/PHASE9_DEVELOPER_GUIDE.md")
        print(f"  - Cache Metrics: http://{args.host}:{args.port}/api/ml/ensemble/cache_metrics")
        print(f"  - Diagnostics:   http://{args.host}:{args.port}/api/ml/ensemble/diagnostics?index={args.index}")
        print("=" * 70)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
