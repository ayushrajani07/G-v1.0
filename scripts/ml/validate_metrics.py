#!/usr/bin/env python3
"""
Metrics Validation Script

Scrape /metrics endpoint and validate presence of required Prometheus metrics.
Outputs a JSON file with validation results for CI artifacts.

Usage:
    python scripts/ml/validate_metrics.py --url http://localhost:9500/metrics --required g6_forecast_latency_ms,g6_forecast_cache_hits_total
    python scripts/ml/validate_metrics.py --url http://localhost:9500/metrics --required g6_forecast_latency_ms --out metrics_validation.json
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

try:
    import httpx
except ImportError:
    print("Error: httpx not installed")
    print("Install with: pip install httpx")
    sys.exit(1)


def parse_prometheus_metrics(text: str) -> Dict[str, List[Dict]]:
    """
    Parse Prometheus text format metrics.
    
    Args:
        text: Prometheus metrics text
        
    Returns:
        Dictionary mapping metric names to list of sample dicts
    """
    metrics = {}
    
    for line in text.split('\n'):
        line = line.strip()
        
        # Skip comments and empty lines
        if not line or line.startswith('#'):
            continue
        
        # Parse metric line: metric_name{labels} value timestamp
        try:
            if '{' in line:
                # Metric with labels
                name_part, rest = line.split('{', 1)
                labels_part, value_part = rest.split('}', 1)
                metric_name = name_part.strip()
                labels_str = labels_part.strip()
                value = float(value_part.strip().split()[0])
                
                # Parse labels
                labels = {}
                if labels_str:
                    for label_pair in labels_str.split(','):
                        key, val = label_pair.split('=', 1)
                        labels[key.strip()] = val.strip().strip('"')
                
                sample = {"labels": labels, "value": value}
            else:
                # Metric without labels
                parts = line.split()
                metric_name = parts[0]
                value = float(parts[1])
                sample = {"labels": {}, "value": value}
            
            if metric_name not in metrics:
                metrics[metric_name] = []
            metrics[metric_name].append(sample)
            
        except (ValueError, IndexError):
            # Skip malformed lines
            continue
    
    return metrics


def extract_histogram_sample(metrics: Dict[str, List[Dict]], base_metric_name: str) -> Optional[Dict]:
    """
    Extract histogram sample data for a given base metric name.
    
    For a histogram metric, Prometheus exposes:
    - metric_name_sum: cumulative sum of observed values
    - metric_name_count: total count of observations
    
    Args:
        metrics: Parsed metrics dictionary
        base_metric_name: Base name of the histogram metric
        
    Returns:
        Dict with 'count' and 'sum' fields if found, None otherwise
    """
    sum_key = f"{base_metric_name}_sum"
    count_key = f"{base_metric_name}_count"
    
    histogram_sample = {}
    
    if sum_key in metrics and metrics[sum_key]:
        # Sum all samples for the _sum metric
        total_sum = sum(s["value"] for s in metrics[sum_key])
        histogram_sample["sum"] = total_sum
    
    if count_key in metrics and metrics[count_key]:
        # Sum all samples for the _count metric
        total_count = sum(s["value"] for s in metrics[count_key])
        histogram_sample["count"] = int(total_count)
    
    return histogram_sample if histogram_sample else None


def validate_metrics(
    url: str,
    required_metrics: List[str],
    timeout: float = 10.0
) -> Dict:
    """
    Scrape and validate Prometheus metrics from the specified URL.
    
    Args:
        url: Full URL to metrics endpoint
        required_metrics: List of required metric names
        timeout: Request timeout in seconds
        
    Returns:
        Validation results dictionary
    """
    print(f"Scraping metrics from {url}...")
    
    try:
        response = httpx.get(url, timeout=timeout)
        
        if response.status_code != 200:
            print(f"Warning: HTTP {response.status_code} received")
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "found": [],
                "missing": required_metrics,
                "error": f"HTTP {response.status_code}: {response.text[:200]}",
            }
        
        metrics_text = response.text
        metrics = parse_prometheus_metrics(metrics_text)
        
        print(f"Found {len(metrics)} unique metric types")
        
        # Check which required metrics are present
        found = []
        missing = []
        
        for metric_name in required_metrics:
            # Check for the base metric name or any variant (_sum, _count, _bucket)
            base_found = metric_name in metrics
            sum_found = f"{metric_name}_sum" in metrics
            count_found = f"{metric_name}_count" in metrics
            bucket_found = f"{metric_name}_bucket" in metrics
            
            if base_found or sum_found or count_found or bucket_found:
                found.append(metric_name)
                print(f"  ✓ {metric_name}: found")
            else:
                missing.append(metric_name)
                print(f"  ✗ {metric_name}: MISSING")
        
        # Build result
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "found": found,
            "missing": missing,
        }
        
        # Try to extract histogram sample for latency metric if present
        # Look for any metric containing 'latency' in the name
        latency_metrics = [m for m in found if 'latency' in m.lower()]
        if latency_metrics:
            # Use the first latency metric found
            histogram_sample = extract_histogram_sample(metrics, latency_metrics[0])
            if histogram_sample:
                result["latency_histogram_sample"] = histogram_sample
                print(f"  ℹ Histogram sample: {histogram_sample}")
        
        if missing:
            print(f"\nValidation FAILED: Missing {len(missing)} required metric(s)")
        else:
            print(f"\nValidation PASSED: All {len(found)} required metrics present")
        
        return result
        
    except httpx.TimeoutException:
        print(f"Warning: Timeout connecting to {url}")
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "found": [],
            "missing": required_metrics,
            "error": f"Timeout connecting to {url}",
        }
    except httpx.ConnectError as e:
        print(f"Warning: Cannot connect to {url}: {e}")
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "found": [],
            "missing": required_metrics,
            "error": f"Cannot connect to {url}: {str(e)}",
        }
    except Exception as e:
        print(f"Error: {e}")
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "found": [],
            "missing": required_metrics,
            "error": str(e),
        }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Validate required Prometheus metrics from a metrics endpoint"
    )
    parser.add_argument(
        "--url",
        type=str,
        required=True,
        help="Full URL to metrics endpoint (e.g., http://localhost:9500/metrics)"
    )
    parser.add_argument(
        "--required",
        type=str,
        required=True,
        help="Comma-separated list of required metric names (e.g., g6_forecast_latency_ms,g6_forecast_cache_hits_total)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Request timeout in seconds (default: 10.0)"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("metrics_validation.json"),
        help="JSON output file for validation results (default: metrics_validation.json)"
    )
    
    args = parser.parse_args()
    
    # Parse required metrics list
    required_metrics = [m.strip() for m in args.required.split(',') if m.strip()]
    
    if not required_metrics:
        print("Error: No required metrics specified")
        sys.exit(1)
    
    print(f"Required metrics: {', '.join(required_metrics)}")
    
    # Run validation
    results = validate_metrics(args.url, required_metrics, args.timeout)
    
    # Save output
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to: {args.out}")
    
    # Exit with appropriate code based on whether any metrics are missing
    if results.get("missing"):
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
