#!/usr/bin/env python3
"""
Metrics Validation Script - Phase 9

Scrape /metrics endpoint and validate presence of key Prometheus metrics.
Outputs a JSON file with current metric values for CI artifacts.

Usage:
    python scripts/ml/validate_metrics.py --host localhost --port 9210
    python scripts/ml/validate_metrics.py --host localhost --port 9210 --output metrics.json
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

try:
    import httpx
except ImportError:
    print("Error: httpx not installed")
    print("Install with: pip install httpx")
    sys.exit(1)


REQUIRED_METRICS = [
    "g6_forecast_latency_ms",
    "g6_forecast_cache_hits_total",
    "g6_forecast_cache_misses_total",
]

OPTIONAL_METRICS = [
    "g6_ml_ann_cache_hit_ratio",
    "g6_ml_ann_cache_size",
    "g6_ml_ann_cache_evictions",
    "g6_ml_ann_disk_cache_hits",
    "g6_ml_ann_disk_cache_load_ms",
    "g6_ml_stage_latency_seconds",
]


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
            
        except (ValueError, IndexError) as e:
            # Skip malformed lines
            continue
    
    return metrics


def validate_metrics(
    host: str,
    port: int,
    timeout: float = 10.0
) -> Dict:
    """
    Scrape and validate Prometheus metrics from the API.
    
    Args:
        host: API host
        port: API port
        timeout: Request timeout in seconds
        
    Returns:
        Validation results dictionary
    """
    url = f"http://{host}:{port}/metrics"
    
    print(f"Scraping metrics from {url}...")
    
    try:
        response = httpx.get(url, timeout=timeout)
        
        if response.status_code != 200:
            return {
                "status": "error",
                "message": f"HTTP {response.status_code}: {response.text[:200]}",
                "timestamp": datetime.now().isoformat(),
            }
        
        metrics_text = response.text
        metrics = parse_prometheus_metrics(metrics_text)
        
        print(f"Found {len(metrics)} unique metric types")
        
        # Check required metrics
        required_found = {}
        required_missing = []
        
        for metric_name in REQUIRED_METRICS:
            if metric_name in metrics:
                required_found[metric_name] = metrics[metric_name]
                print(f"  ✓ {metric_name}: {len(metrics[metric_name])} samples")
            else:
                required_missing.append(metric_name)
                print(f"  ✗ {metric_name}: MISSING")
        
        # Check optional metrics
        optional_found = {}
        optional_missing = []
        
        for metric_name in OPTIONAL_METRICS:
            if metric_name in metrics:
                optional_found[metric_name] = metrics[metric_name]
                print(f"  ℹ {metric_name}: {len(metrics[metric_name])} samples")
            else:
                optional_missing.append(metric_name)
        
        # Calculate current counters
        counters = {}
        for metric_name, samples in required_found.items():
            if samples:
                # Sum all samples (counters are cumulative)
                total = sum(s["value"] for s in samples)
                counters[metric_name] = {
                    "total": total,
                    "samples": len(samples),
                }
        
        for metric_name, samples in optional_found.items():
            if samples:
                total = sum(s["value"] for s in samples)
                counters[metric_name] = {
                    "total": total,
                    "samples": len(samples),
                }
        
        # Determine overall status
        if required_missing:
            status = "failed"
            message = f"Missing required metrics: {', '.join(required_missing)}"
        else:
            status = "passed"
            message = "All required metrics present"
        
        print(f"\nValidation: {status.upper()}")
        print(f"  {message}")
        
        return {
            "status": status,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "required_metrics": {
                "found": list(required_found.keys()),
                "missing": required_missing,
            },
            "optional_metrics": {
                "found": list(optional_found.keys()),
                "missing": optional_missing,
            },
            "counters": counters,
            "total_metrics": len(metrics),
        }
        
    except httpx.TimeoutException:
        return {
            "status": "error",
            "message": f"Timeout connecting to {url}",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error: {str(e)}",
            "timestamp": datetime.now().isoformat(),
        }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Validate Prometheus metrics from ML ensemble API"
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
        "--timeout",
        type=float,
        default=10.0,
        help="Request timeout in seconds (default: 10.0)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="JSON output file for validation results"
    )
    
    args = parser.parse_args()
    
    # Run validation
    results = validate_metrics(args.host, args.port, args.timeout)
    
    # Save output if requested
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to: {args.output}")
    
    # Exit with appropriate code
    if results["status"] == "passed":
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
