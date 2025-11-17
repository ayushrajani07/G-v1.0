#!/usr/bin/env python3
"""
Load Test Ensemble Forecaster - Phase 9 Async Edition

Async load tester with httpx for the ML ensemble API.
Supports concurrent requests, QPS control, warm-up, CSV output, and cache-busting.

Usage:
    python scripts/ml/load_test_ensemble_async.py \
        --indices NIFTY BANKNIFTY \
        --qps 20 \
        --concurrency 10 \
        --duration 60 \
        --warmup 10 \
        --csv-out latency.csv \
        --output results.json
        
Features:
    - Async/await with httpx connection pooling
    - QPS rate limiting and concurrency control
    - Warm-up period (excluded from results)
    - Per-index breakdown (latency p50/p95, error rate)
    - CSV output for latency samples
    - Cache-bust mode for no-cache testing
    - Detail mode (snapshot/full)
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    import httpx
    import numpy as np
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install httpx numpy")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def _sanitize_json(value):
    """Recursively convert numpy / Path types to JSON-safe primitives."""
    if isinstance(value, dict):
        return {str(k): _sanitize_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_json(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    return value


class AsyncLoadTester:
    """Async load tester for ML ensemble API with httpx."""
    
    def __init__(
        self,
        api_host: str,
        api_port: int,
        indices: List[str],
        qps: float,
        concurrency: int,
        duration: int,
        warmup: int = 0,
        horizons: List[int] = None,
        detail: str = "snapshot",
        cache_bust: bool = False,
    ):
        """
        Initialize async load tester.
        
        Args:
            api_host: API host
            api_port: API port
            indices: List of index names to test
            qps: Target queries per second (rate limit)
            concurrency: Maximum concurrent requests
            duration: Test duration in seconds (excluding warmup)
            warmup: Warm-up period in seconds (excluded from results)
            horizons: List of forecast horizons (default: [30, 60, 120])
            detail: Response detail level ("snapshot" or "full")
            cache_bust: Add random parameter to bust cache
        """
        self.api_host = api_host
        self.api_port = api_port
        self.base_url = f"http://{api_host}:{api_port}"
        self.indices = indices
        self.qps = qps
        self.concurrency = concurrency
        self.duration = duration
        self.warmup = warmup
        self.horizons = horizons or [30, 60, 120]
        self.detail = detail
        self.cache_bust = cache_bust
        
        # Results storage
        self.warmup_results: List[Dict] = []
        self.test_results: List[Dict] = []
        
        # Rate limiting
        self.request_interval = 1.0 / qps if qps > 0 else 0
        
    async def make_forecast_request(
        self,
        client: httpx.AsyncClient,
        index: str,
        horizon: int,
        is_warmup: bool = False
    ) -> Dict:
        """
        Make a single async forecast request.
        
        Args:
            client: httpx async client
            index: Index name
            horizon: Forecast horizon
            is_warmup: Whether this is a warmup request
            
        Returns:
            Dictionary with request results
        """
        url = f"{self.base_url}/api/ml/ensemble/forecast"
        params = {
            "index": index,
            "horizon": horizon,
            "detail": self.detail
        }
        
        # Cache busting: add timestamp parameter
        if self.cache_bust:
            params["_cache_bust"] = str(time.time())
        
        start_time = time.time()
        
        try:
            response = await client.get(url, params=params, timeout=30.0)
            latency = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                forecast_block = data.get("forecast", data)
                
                return {
                    "status": "success",
                    "latency": latency,
                    "index": index,
                    "horizon": horizon,
                    "timestamp": datetime.now().isoformat(),
                    "is_warmup": is_warmup,
                    "has_p10": "p10" in forecast_block,
                    "has_p50": "p50" in forecast_block,
                    "has_p90": "p90" in forecast_block,
                }
            else:
                return {
                    "status": "http_error",
                    "error_code": response.status_code,
                    "latency": latency,
                    "index": index,
                    "horizon": horizon,
                    "timestamp": datetime.now().isoformat(),
                    "is_warmup": is_warmup,
                }
                
        except httpx.TimeoutException:
            latency = time.time() - start_time
            return {
                "status": "timeout",
                "latency": latency,
                "index": index,
                "horizon": horizon,
                "timestamp": datetime.now().isoformat(),
                "is_warmup": is_warmup,
            }
        except Exception as e:
            latency = time.time() - start_time
            return {
                "status": "error",
                "error": str(e),
                "latency": latency,
                "index": index,
                "horizon": horizon,
                "timestamp": datetime.now().isoformat(),
                "is_warmup": is_warmup,
            }
    
    async def worker(
        self,
        client: httpx.AsyncClient,
        worker_id: int,
        end_time: float,
        semaphore: asyncio.Semaphore,
        is_warmup: bool = False
    ) -> List[Dict]:
        """
        Worker coroutine that makes requests with rate limiting.
        
        Args:
            client: httpx async client
            worker_id: Worker identifier
            end_time: Timestamp when test should end
            semaphore: Concurrency limiter
            is_warmup: Whether this is the warmup phase
            
        Returns:
            List of request results
        """
        results = []
        request_count = 0
        
        while time.time() < end_time:
            async with semaphore:
                # Round-robin through indices and horizons
                index = self.indices[request_count % len(self.indices)]
                horizon = self.horizons[request_count % len(self.horizons)]
                
                result = await self.make_forecast_request(
                    client, index, horizon, is_warmup
                )
                result["worker_id"] = worker_id
                results.append(result)
                
                request_count += 1
                
                # Rate limiting: sleep to achieve target QPS
                if self.request_interval > 0:
                    await asyncio.sleep(self.request_interval)
        
        return results
    
    async def fetch_cache_metrics(self, client: httpx.AsyncClient) -> Dict:
        """
        Fetch Phase 9 cache metrics from API.
        
        Args:
            client: httpx async client
            
        Returns:
            Dictionary with cache metrics or empty dict on error
        """
        url = f"{self.base_url}/api/ml/ensemble/cache_metrics"
        try:
            response = await client.get(url, timeout=5.0)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.debug(f"Could not fetch cache metrics: {e}")
        return {}
    
    async def run_phase(
        self,
        duration: int,
        is_warmup: bool = False
    ) -> List[Dict]:
        """
        Run a test phase (warmup or actual test).
        
        Args:
            duration: Phase duration in seconds
            is_warmup: Whether this is the warmup phase
            
        Returns:
            List of all results from this phase
        """
        phase_name = "Warm-up" if is_warmup else "Load Test"
        logger.info(f"{phase_name} starting for {duration}s...")
        
        # Calculate end time
        start_time = time.time()
        end_time = start_time + duration
        
        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(self.concurrency)
        
        # Create httpx client with connection pooling
        limits = httpx.Limits(
            max_keepalive_connections=self.concurrency,
            max_connections=self.concurrency * 2
        )
        
        async with httpx.AsyncClient(limits=limits) as client:
            # Create worker tasks
            tasks = [
                self.worker(client, i, end_time, semaphore, is_warmup)
                for i in range(self.concurrency)
            ]
            
            # Wait for all workers to complete
            results_lists = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Flatten results
            all_results = []
            for results in results_lists:
                if isinstance(results, Exception):
                    logger.error(f"Worker failed: {results}")
                else:
                    all_results.extend(results)
        
        actual_duration = time.time() - start_time
        logger.info(f"{phase_name} completed in {actual_duration:.1f}s")
        logger.info(f"Total requests: {len(all_results)}")
        
        return all_results
    
    async def run_load_test(self) -> Dict:
        """
        Run full load test with optional warmup.
        
        Returns:
            Dictionary with test results
        """
        logger.info("=" * 70)
        logger.info(f"Load Test Configuration")
        logger.info(f"  Indices: {', '.join(self.indices)}")
        logger.info(f"  QPS: {self.qps}")
        logger.info(f"  Concurrency: {self.concurrency}")
        logger.info(f"  Duration: {self.duration}s")
        logger.info(f"  Warm-up: {self.warmup}s")
        logger.info(f"  Horizons: {self.horizons}")
        logger.info(f"  Detail: {self.detail}")
        logger.info(f"  Cache Bust: {self.cache_bust}")
        logger.info("=" * 70)
        
        # Run warmup phase if requested
        if self.warmup > 0:
            self.warmup_results = await self.run_phase(self.warmup, is_warmup=True)
        
        # Run actual test phase
        self.test_results = await self.run_phase(self.duration, is_warmup=False)
        
        # Fetch cache metrics after test
        async with httpx.AsyncClient() as client:
            cache_metrics = await self.fetch_cache_metrics(client)
        
        return self.analyze_results(cache_metrics)
    
    def analyze_results(self, cache_metrics: Dict = None) -> Dict:
        """
        Analyze test results and compute metrics.
        
        Args:
            cache_metrics: Phase 9 cache metrics (optional)
            
        Returns:
            Dictionary with analysis results
        """
        logger.info("\n" + "=" * 70)
        logger.info("Results Analysis")
        logger.info("=" * 70)
        
        # Display cache metrics if available
        if cache_metrics:
            logger.info("\nPhase 9 Cache Metrics:")
            window_cache = cache_metrics.get('window_cache', {})
            disk_cache = cache_metrics.get('disk_cache', {})
            if window_cache.get('enabled'):
                logger.info(f"  Window Cache Hit Ratio: {window_cache.get('hit_ratio', 0):.2%}")
                logger.info(f"  Window Cache Size: {window_cache.get('size', 0)}")
                logger.info(f"  Window Cache Evictions: {window_cache.get('evictions', 0)}")
            if disk_cache.get('enabled'):
                total_disk = disk_cache.get('hits', 0) + disk_cache.get('misses', 0)
                if total_disk > 0:
                    disk_hit_rate = disk_cache.get('hits', 0) / total_disk
                    logger.info(f"  Disk Cache Hit Rate: {disk_hit_rate:.2%}")
                logger.info(f"  Disk Cache Hits: {disk_cache.get('hits', 0)}")
                logger.info(f"  Disk Cache Misses: {disk_cache.get('misses', 0)}")
        
        if not self.test_results:
            logger.error("No test results to analyze")
            return {"status": "error", "message": "No results"}
        
        # Overall statistics
        successful = [r for r in self.test_results if r["status"] == "success"]
        failed = [r for r in self.test_results if r["status"] != "success"]
        
        total_requests = len(self.test_results)
        success_count = len(successful)
        error_count = len(failed)
        success_rate = success_count / total_requests if total_requests > 0 else 0
        error_rate = error_count / total_requests if total_requests > 0 else 0
        
        logger.info(f"\nOverall Statistics:")
        logger.info(f"  Total requests: {total_requests}")
        logger.info(f"  Successful: {success_count} ({success_rate:.1%})")
        logger.info(f"  Failed: {error_count} ({error_rate:.1%})")
        
        # Compute latency statistics
        if successful:
            latencies = [r["latency"] for r in successful]
            latencies_ms = [l * 1000 for l in latencies]
            
            overall_stats = {
                "mean": np.mean(latencies_ms),
                "p50": np.percentile(latencies_ms, 50),
                "p95": np.percentile(latencies_ms, 95),
                "p99": np.percentile(latencies_ms, 99),
                "min": np.min(latencies_ms),
                "max": np.max(latencies_ms),
            }
            
            logger.info(f"\nOverall Latency (successful requests):")
            logger.info(f"  Mean: {overall_stats['mean']:.0f}ms")
            logger.info(f"  P50: {overall_stats['p50']:.0f}ms")
            logger.info(f"  P95: {overall_stats['p95']:.0f}ms")
            logger.info(f"  P99: {overall_stats['p99']:.0f}ms")
        else:
            overall_stats = {"mean": 0, "p50": 0, "p95": 0, "p99": 0, "min": 0, "max": 0}
        
        # Per-index breakdown
        logger.info(f"\nPer-Index Breakdown:")
        per_index_stats = {}
        
        for index in self.indices:
            index_results = [r for r in self.test_results if r.get("index") == index]
            index_successful = [r for r in index_results if r["status"] == "success"]
            index_failed = [r for r in index_results if r["status"] != "success"]
            
            if not index_results:
                continue
            
            index_total = len(index_results)
            index_success_count = len(index_successful)
            index_error_count = len(index_failed)
            index_error_rate = index_error_count / index_total if index_total > 0 else 0
            
            if index_successful:
                index_latencies_ms = [r["latency"] * 1000 for r in index_successful]
                index_p50 = np.percentile(index_latencies_ms, 50)
                index_p95 = np.percentile(index_latencies_ms, 95)
            else:
                index_p50 = 0
                index_p95 = 0
            
            per_index_stats[index] = {
                "total_requests": index_total,
                "successful": index_success_count,
                "failed": index_error_count,
                "error_rate": index_error_rate,
                "latency_p50_ms": index_p50,
                "latency_p95_ms": index_p95,
            }
            
            logger.info(f"  {index}:")
            logger.info(f"    Requests: {index_total}")
            logger.info(f"    Error Rate: {index_error_rate:.1%}")
            logger.info(f"    P50: {index_p50:.0f}ms")
            logger.info(f"    P95: {index_p95:.0f}ms")
        
        # Throughput calculation
        throughput = total_requests / self.duration if self.duration > 0 else 0
        logger.info(f"\nThroughput: {throughput:.1f} requests/second")
        
        # Performance targets
        target_p95_ms = 1000
        target_error_rate = 0.05
        
        p95_ok = overall_stats["p95"] <= target_p95_ms if overall_stats["p95"] > 0 else False
        error_rate_ok = error_rate <= target_error_rate
        overall_pass = p95_ok and error_rate_ok
        
        logger.info(f"\nPerformance Targets:")
        logger.info(f"  P95 < {target_p95_ms}ms: {'✓ PASS' if p95_ok else '✗ FAIL'} (actual: {overall_stats['p95']:.0f}ms)")
        logger.info(f"  Error rate < {target_error_rate:.1%}: {'✓ PASS' if error_rate_ok else '✗ FAIL'} (actual: {error_rate:.1%})")
        
        logger.info("\n" + "=" * 70)
        if overall_pass:
            logger.info("✓ LOAD TEST PASSED")
        else:
            logger.error("✗ LOAD TEST FAILED")
        logger.info("=" * 70)
        
        # Build result dictionary
        result = {
            "timestamp": datetime.now().isoformat(),
            "test_config": {
                "indices": self.indices,
                "qps": self.qps,
                "concurrency": self.concurrency,
                "duration": self.duration,
                "warmup": self.warmup,
                "horizons": self.horizons,
                "detail": self.detail,
                "cache_bust": self.cache_bust,
            },
            "summary": {
                "total_requests": total_requests,
                "successful": success_count,
                "failed": error_count,
                "success_rate": success_rate,
                "error_rate": error_rate,
                "throughput": throughput,
            },
            "latency_ms": overall_stats,
            "per_index": per_index_stats,
            "targets": {
                "p95_target_ms": target_p95_ms,
                "p95_pass": p95_ok,
                "error_rate_target": target_error_rate,
                "error_rate_pass": error_rate_ok,
                "overall_pass": overall_pass,
            },
        }
        
        # Add cache metrics if available
        if cache_metrics:
            result["phase9_cache_metrics"] = cache_metrics
        
        # Add warmup summary if available
        if self.warmup_results:
            result["warmup_summary"] = {
                "total_requests": len(self.warmup_results),
                "successful": len([r for r in self.warmup_results if r["status"] == "success"]),
            }
        
        return result
    
    def save_csv(self, csv_path: Path):
        """
        Save latency samples to CSV file.
        
        Args:
            csv_path: Path to CSV output file
        """
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "index", "horizon", "latency_ms",
                "status", "is_warmup", "worker_id"
            ])
            
            # Write warmup results
            for result in self.warmup_results:
                writer.writerow([
                    result.get("timestamp", ""),
                    result.get("index", ""),
                    result.get("horizon", ""),
                    result.get("latency", 0) * 1000,
                    result.get("status", ""),
                    True,
                    result.get("worker_id", ""),
                ])
            
            # Write test results
            for result in self.test_results:
                writer.writerow([
                    result.get("timestamp", ""),
                    result.get("index", ""),
                    result.get("horizon", ""),
                    result.get("latency", 0) * 1000,
                    result.get("status", ""),
                    False,
                    result.get("worker_id", ""),
                ])
        
        logger.info(f"CSV saved to: {csv_path}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Async load test for ML ensemble API (Phase 9)"
    )
    parser.add_argument(
        "--api-host",
        type=str,
        default="localhost",
        help="API host (default: localhost)"
    )
    parser.add_argument(
        "--api-port",
        type=int,
        default=9210,
        help="API port (default: 9210)"
    )
    parser.add_argument(
        "--indices",
        type=str,
        nargs="+",
        default=["NIFTY"],
        help="Index names (default: NIFTY)"
    )
    parser.add_argument(
        "--qps",
        type=float,
        default=20.0,
        help="Target queries per second (default: 20)"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Maximum concurrent requests (default: 10)"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Test duration in seconds (default: 60)"
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=0,
        help="Warm-up period in seconds (default: 0)"
    )
    parser.add_argument(
        "--horizons",
        type=str,
        default="30,60,120",
        help="Comma-separated forecast horizons (default: 30,60,120)"
    )
    parser.add_argument(
        "--detail",
        type=str,
        choices=["snapshot", "full"],
        default="snapshot",
        help="Response detail level (default: snapshot)"
    )
    parser.add_argument(
        "--cache-bust",
        action="store_true",
        help="Add random parameter to bust cache"
    )
    parser.add_argument(
        "--csv-out",
        type=Path,
        help="CSV output file for latency samples"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="JSON output file for test results"
    )
    
    args = parser.parse_args()
    
    # Parse horizons
    horizons = [int(h.strip()) for h in args.horizons.split(',')]
    
    # Create load tester
    tester = AsyncLoadTester(
        api_host=args.api_host,
        api_port=args.api_port,
        indices=args.indices,
        qps=args.qps,
        concurrency=args.concurrency,
        duration=args.duration,
        warmup=args.warmup,
        horizons=horizons,
        detail=args.detail,
        cache_bust=args.cache_bust,
    )
    
    # Run load test
    results = asyncio.run(tester.run_load_test())
    
    # Save CSV if requested
    if args.csv_out:
        tester.save_csv(args.csv_out)
    
    # Save JSON results if requested
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        safe_results = _sanitize_json(results)
        with open(args.output, 'w') as f:
            json.dump(safe_results, f, indent=2)
        logger.info(f"Results saved to: {args.output}")
    
    # Exit based on results
    if results.get("targets", {}).get("overall_pass", False):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
