#!/usr/bin/env python3
"""
Simple load test harness for Ensemble Forecast API.

- Uses threads + requests (stdlib + widely available) for portability.
- Remote agent can upgrade to asyncio+httpx as needed.

Usage:
  python scripts/ml/load_test_ensemble.py --qps 20 --duration 30 --indices NIFTY,BANKNIFTY --horizon 60 --base http://127.0.0.1:9500 --detail snapshot

Outputs JSON summary to stdout; use --out to write to file as well.
"""
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def fetch(base: str, index: str, horizon: int, detail: str, recent_window_size: int, session: requests.Session) -> Tuple[bool, float, str]:
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
        ok = r.status_code == 200
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return ok, latency_ms, r.text[:200]
    except Exception as e:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return False, latency_ms, str(e)


def rate_limited_executor(qps: int, duration: int, func, args_list: List[Tuple], max_workers: int = 64):
    """Submit tasks at approximately QPS for a given duration."""
    end_time = time.time() + duration
    interval = 1.0 / max(1, qps)
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        next_at = time.time()
        i = 0
        while time.time() < end_time:
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
        # drain
        for f in as_completed(results):
            yield f


def get_cache_stats(base: str) -> Dict:
    url = f"{base.rstrip('/')}/api/ml/ensemble/cache/stats"
    try:
        r = requests.get(url, timeout=5)
        return r.json() if r.ok else {}
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:9500", help="Base URL for API")
    ap.add_argument("--indices", default="NIFTY", help="Comma-separated indices")
    ap.add_argument("--horizon", type=int, default=60)
    ap.add_argument("--detail", choices=["snapshot", "full"], default="snapshot")
    ap.add_argument("--recent-window-size", type=int, default=60)
    ap.add_argument("--qps", type=int, default=20)
    ap.add_argument("--duration", type=int, default=30)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--out", default="", help="Write JSON summary to this path as well")
    args = ap.parse_args()

    indices = [s.strip() for s in args.indices.split(",") if s.strip()]

    # Prepare argument tuples for workers
    sess = requests.Session()
    arg_list = []
    for idx in indices:
        arg_list.append((args.base, idx, args.horizon, args.detail, args.recent_window_size, sess))

    total = 0
    ok = 0
    errs = 0
    latencies: List[float] = []
    samples: List[str] = []

    start = time.time()
    for fut in rate_limited_executor(args.qps, args.duration, fetch, arg_list, max_workers=args.workers):
        success, latency_ms, sample = fut.result()
        total += 1
        latencies.append(latency_ms)
        if success:
            ok += 1
        else:
            errs += 1
            if len(samples) < 5:
                samples.append(sample)
    elapsed = time.time() - start

    stats = get_cache_stats(args.base)
    hit_ratio = stats.get("hit_ratio")

    summary = {
        "base": args.base,
        "indices": indices,
        "horizon": args.horizon,
        "detail": args.detail,
        "qps": args.qps,
        "duration_sec": args.duration,
        "workers": args.workers,
        "total_requests": total,
        "success": ok,
        "errors": errs,
        "error_rate": (errs / total) if total else 0.0,
        "latency_ms_p50": round(p50(latencies), 3),
        "latency_ms_p95": round(p95(latencies), 3),
        "cache_hit_ratio": hit_ratio,
        "cache_stats": stats,
        "error_samples": samples,
        "elapsed_sec": round(elapsed, 3),
        "timestamp": int(time.time() * 1000),
    }

    print(json.dumps(summary, indent=2))
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
        except Exception as e:
            print(f"Failed to write summary to {args.out}: {e}")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
Load Test Ensemble Forecaster - Phase 8 Production Validation

Stress test the ML ensemble API to validate performance under load.
Simulates concurrent requests and measures latency, throughput, and error rates.

Usage:
    python scripts/ml/load_test_ensemble.py \
        --concurrent-requests 100 \
        --duration 300 \
        --index NIFTY
        
Expected Performance:
    - P95 latency < 1s
    - Error rate < 5%
    - Throughput > 50 requests/second
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import os
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict

import numpy as np
from pathlib import Path as _Path

# ------------------------------------------------------------------
# Serialization helpers (Phase 9: robust JSON output)
# ------------------------------------------------------------------
def _sanitize_json(value):
    """Recursively convert numpy / Path / set / tuple types to JSON-safe primitives."""
    import numpy as _np
    if isinstance(value, dict):
        return {str(k): _sanitize_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [ _sanitize_json(v) for v in value ]
    if isinstance(value, (_np.integer,)):
        return int(value)
    if isinstance(value, (_np.floating,)):
        return float(value)
    if isinstance(value, (_np.bool_,)):
        return bool(value)
    if isinstance(value, _Path):
        return str(value)
    return value

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class LoadTester:
    """Load tester for ML ensemble API.

    Note: Forecast endpoint returns a JSON object with a nested
    'forecast' dict containing p10/p50/p90. We normalize detection
    accordingly so success detection is resilient to future schema
    extensions.
    """
    
    def __init__(
        self,
        api_host: str,
        api_port: int,
        index: str,
        concurrent_requests: int,
        duration: int,
        horizons: List[int] = None
    ):
        """
        Initialize load tester.
        
        Args:
            api_host: API host
            api_port: API port
            index: Index name
            concurrent_requests: Number of concurrent requests
            duration: Test duration in seconds
            horizons: List of forecast horizons to test (default: [30, 60, 120])
        """
        self.api_host = api_host
        self.api_port = api_port
        self.index = index
        self.concurrent_requests = concurrent_requests
        self.duration = duration
        self.horizons = horizons or [30, 60, 120]
        
        self.results: List[Dict] = []
        self.errors: List[Dict] = []
        
    def make_forecast_request(self, horizon: int) -> Dict:
        """
        Make a single forecast request and measure performance.
        
        Args:
            horizon: Forecast horizon
            
        Returns:
            Dictionary with request results
        """
        url = f"http://{self.api_host}:{self.api_port}/api/ml/ensemble/forecast?index={self.index}&horizon={horizon}"
        
        start_time = time.time()
        
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'LoadTester/1.0'})
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
                latency = time.time() - start_time
                
                forecast_block = data.get("forecast", data)
                return {
                    "status": "success",
                    "latency": latency,
                    "horizon": horizon,
                    "timestamp": datetime.now().isoformat(),
                    "has_p10": "p10" in forecast_block,
                    "has_p50": "p50" in forecast_block,
                    "has_p90": "p90" in forecast_block,
                }
                
        except urllib.error.HTTPError as e:
            latency = time.time() - start_time
            return {
                "status": "http_error",
                "error_code": e.code,
                "latency": latency,
                "horizon": horizon,
                "timestamp": datetime.now().isoformat(),
            }
        except urllib.error.URLError as e:
            latency = time.time() - start_time
            return {
                "status": "connection_error",
                "error": str(e),
                "latency": latency,
                "horizon": horizon,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            latency = time.time() - start_time
            return {
                "status": "error",
                "error": str(e),
                "latency": latency,
                "horizon": horizon,
                "timestamp": datetime.now().isoformat(),
            }
    
    def worker(self, worker_id: int, end_time: float) -> List[Dict]:
        """
        Worker thread that makes requests until test duration elapses.
        
        Args:
            worker_id: Worker ID
            end_time: Timestamp when test should end
            
        Returns:
            List of request results
        """
        results = []
        request_count = 0
        
        logger.info(f"Worker {worker_id} started")
        
        while time.time() < end_time:
            # Rotate through horizons
            horizon = self.horizons[request_count % len(self.horizons)]
            
            result = self.make_forecast_request(horizon)
            result["worker_id"] = worker_id
            results.append(result)
            
            request_count += 1
            
            # Small delay to avoid overwhelming the server
            time.sleep(0.01)
        
        logger.info(f"Worker {worker_id} completed {request_count} requests")
        return results
    
    def run_load_test(self) -> Dict:
        """
        Run load test with concurrent workers.
        
        Returns:
            Dictionary with test results
        """
        logger.info("=" * 70)
        logger.info(f"Load Test Starting - {self.index}")
        logger.info(f"Concurrent requests: {self.concurrent_requests}")
        logger.info(f"Duration: {self.duration}s")
        logger.info(f"Horizons: {self.horizons}")
        logger.info("=" * 70)
        
        # Calculate end time
        start_time = time.time()
        end_time = start_time + self.duration
        
        # Run concurrent workers
        with ThreadPoolExecutor(max_workers=self.concurrent_requests) as executor:
            futures = [
                executor.submit(self.worker, worker_id, end_time)
                for worker_id in range(self.concurrent_requests)
            ]
            
            # Collect results
            for future in as_completed(futures):
                try:
                    worker_results = future.result()
                    self.results.extend(worker_results)
                except Exception as e:
                    logger.error(f"Worker failed: {e}")
        
        actual_duration = time.time() - start_time
        
        logger.info(f"\nTest completed in {actual_duration:.1f}s")
        logger.info(f"Total requests: {len(self.results)}")
        
        return self.analyze_results(actual_duration)
    
    def analyze_results(self, duration: float) -> Dict:
        """
        Analyze test results and compute metrics.
        
        Args:
            duration: Actual test duration
            
        Returns:
            Dictionary with analysis results
        """
        logger.info("\n" + "=" * 70)
        logger.info("Results Analysis")
        logger.info("=" * 70)
        
        if not self.results:
            logger.error("No results to analyze")
            return {"status": "error", "message": "No results"}
        
        # Separate successful and failed requests
        successful = [r for r in self.results if r["status"] == "success"]
        failed = [r for r in self.results if r["status"] != "success"]
        
        total_requests = len(self.results)
        success_count = len(successful)
        error_count = len(failed)
        
        # Calculate success rate
        success_rate = success_count / total_requests if total_requests > 0 else 0
        error_rate = error_count / total_requests if total_requests > 0 else 0
        
        logger.info(f"Total requests: {total_requests}")
        logger.info(f"Successful: {success_count} ({success_rate:.1%})")
        logger.info(f"Failed: {error_count} ({error_rate:.1%})")
        
        # Calculate latency statistics
        if successful:
            latencies = [r["latency"] for r in successful]
            latencies_ms = [l * 1000 for l in latencies]
            
            p50 = np.percentile(latencies_ms, 50)
            p95 = np.percentile(latencies_ms, 95)
            p99 = np.percentile(latencies_ms, 99)
            mean = np.mean(latencies_ms)
            
            logger.info(f"\nLatency Statistics (successful requests):")
            logger.info(f"  Mean: {mean:.0f}ms")
            logger.info(f"  P50: {p50:.0f}ms")
            logger.info(f"  P95: {p95:.0f}ms")
            logger.info(f"  P99: {p99:.0f}ms")
            
            # Check against targets
            target_p95_ms = 1000  # 1 second
            target_error_rate = 0.05  # 5%
            
            p95_ok = p95 <= target_p95_ms
            error_rate_ok = error_rate <= target_error_rate
            
            logger.info(f"\nPerformance Targets:")
            logger.info(f"  P95 < {target_p95_ms}ms: {'✓ PASS' if p95_ok else '✗ FAIL'} (actual: {p95:.0f}ms)")
            logger.info(f"  Error rate < {target_error_rate:.1%}: {'✓ PASS' if error_rate_ok else '✗ FAIL'} (actual: {error_rate:.1%})")
            
        else:
            logger.error("No successful requests to analyze")
            mean = p50 = p95 = p99 = 0
            p95_ok = False
            error_rate_ok = False
        
        # Calculate throughput
        throughput = total_requests / duration if duration > 0 else 0
        logger.info(f"\nThroughput: {throughput:.1f} requests/second")
        
        # Error breakdown
        if failed:
            logger.info(f"\nError Breakdown:")
            error_types = defaultdict(int)
            for result in failed:
                error_types[result["status"]] += 1
            for error_type, count in error_types.items():
                logger.info(f"  {error_type}: {count}")
        
        # Overall status
        overall_pass = p95_ok and error_rate_ok
        
        logger.info("\n" + "=" * 70)
        if overall_pass:
            logger.info("✓ LOAD TEST PASSED")
        else:
            logger.error("✗ LOAD TEST FAILED")
        logger.info("=" * 70)
        
        return {
            "timestamp": datetime.now().isoformat(),
            "test_config": {
                "index": self.index,
                "concurrent_requests": self.concurrent_requests,
                "duration": duration,
                "horizons": self.horizons
            },
            "summary": {
                "total_requests": total_requests,
                "successful": success_count,
                "failed": error_count,
                "success_rate": success_rate,
                "error_rate": error_rate,
                "throughput": throughput
            },
            "latency_ms": {
                "mean": mean,
                "p50": p50,
                "p95": p95,
                "p99": p99
            },
            "targets": {
                "p95_target_ms": 1000,
                "p95_pass": p95_ok,
                "error_rate_target": 0.05,
                "error_rate_pass": error_rate_ok,
                "overall_pass": overall_pass
            },
            "errors": [
                {
                    "type": r["status"],
                    "horizon": r.get("horizon"),
                    "error": r.get("error", r.get("error_code"))
                }
                for r in failed[:10]  # First 10 errors
            ]
        }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Load test ML ensemble API"
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
        default=None,
        help="API port (default: 9500 if dashboard running else 9210)"
    )
    parser.add_argument(
        "--index",
        type=str,
        required=True,
        help="Index name (NIFTY, BANKNIFTY)"
    )
    parser.add_argument(
        "--concurrent-requests",
        type=int,
        default=100,
        help="Number of concurrent requests (default: 100)"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=300,
        help="Test duration in seconds (default: 300)"
    )
    parser.add_argument(
        "--horizons",
        type=str,
        default="30,60,120",
        help="Comma-separated forecast horizons (default: 30,60,120)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file for results JSON"
    )
    
    args = parser.parse_args()
    
    # Parse horizons
    horizons = [int(h.strip()) for h in args.horizons.split(',')]
    
    # Create load tester
    # Auto-select port if not provided
    if args.api_port is None:
        # Prefer dashboard port if health responds
        dash_port = int(os.environ.get("DASHBOARD_API_PORT", "9500"))
        legacy_port = int(os.environ.get("ML_API_PORT", "9210"))
        # Simple probe
        def _probe(port: int) -> bool:
            try:
                with urllib.request.urlopen(f"http://localhost:{port}/health", timeout=2):
                    return True
            except Exception:
                return False
        if _probe(dash_port):
            args.api_port = dash_port
        elif _probe(legacy_port):
            args.api_port = legacy_port
        else:
            args.api_port = dash_port  # fall back to dashboard default

    tester = LoadTester(
        api_host=args.api_host,
        api_port=args.api_port,
        index=args.index,
        concurrent_requests=args.concurrent_requests,
        duration=args.duration,
        horizons=horizons
    )
    
    # Run load test
    results = tester.run_load_test()
    
    # Save results if requested
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        safe_results = _sanitize_json(results)
        with open(args.output, 'w') as f:
            json.dump(safe_results, f, indent=2)
        logger.info(f"\nResults saved to: {args.output}")
    
    # Exit based on results
    if results.get("targets", {}).get("overall_pass", False):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
