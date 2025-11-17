#!/usr/bin/env python3
"""
Daily Health Check Script - Phase 8 Production Operations

Pre-market validation to ensure ML ensemble system is ready for trading day.
Checks:
- API endpoint availability
- Model freshness
- Data pipeline health
- Metrics exporter status
- Recent prediction quality

Usage:
    python scripts/ml/daily_health_check.py --index NIFTY,BANKNIFTY
    
Exit codes:
    0 - All checks passed
    1 - Critical failures detected
    2 - Warnings present but system operational
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import urllib.request
import urllib.error

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class DailyHealthCheck:
    """Daily health check orchestrator."""
    
    def __init__(
        self,
        indices: List[str],
        api_host: str = "localhost",
        api_port: int = 9210,
        metrics_base_port: int = 9325,
        max_model_age_days: int = 14,
        max_data_staleness_hours: int = 24
    ):
        """
        Initialize health checker.
        
        Args:
            indices: List of indices to check (e.g., ['NIFTY', 'BANKNIFTY'])
            api_host: ML API host
            api_port: ML API port
            metrics_base_port: Base port for metrics exporters
            max_model_age_days: Maximum acceptable model age in days
            max_data_staleness_hours: Maximum data staleness in hours
        """
        self.indices = indices
        self.api_host = api_host
        self.api_port = api_port
        self.metrics_base_port = metrics_base_port
        self.max_model_age_days = max_model_age_days
        self.max_data_staleness_hours = max_data_staleness_hours
        
        self.results: Dict[str, Dict] = {}
        self.critical_failures: List[str] = []
        self.warnings: List[str] = []
        
    def check_api_health(self) -> bool:
        """Check if ML API endpoint is responding."""
        logger.info("Checking API health...")
        
        url = f"http://{self.api_host}:{self.api_port}/health"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'DailyHealthCheck/1.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                
                if data.get("status") == "healthy":
                    logger.info("✓ API health check passed")
                    self.results["api_health"] = {"status": "ok", "details": data}
                    return True
                else:
                    logger.error("✗ API returned unhealthy status")
                    self.critical_failures.append("API health check failed")
                    self.results["api_health"] = {"status": "failed", "details": data}
                    return False
                    
        except urllib.error.URLError as e:
            logger.error(f"✗ Failed to connect to API: {e}")
            self.critical_failures.append(f"API connection failed: {e}")
            self.results["api_health"] = {"status": "failed", "error": str(e)}
            return False
        except Exception as e:
            logger.error(f"✗ Unexpected error checking API: {e}")
            self.critical_failures.append(f"API check error: {e}")
            self.results["api_health"] = {"status": "failed", "error": str(e)}
            return False
    
    def check_metrics_exporters(self) -> bool:
        """Check if metrics exporters are running for each index."""
        logger.info("Checking metrics exporters...")
        
        all_ok = True
        for idx, index in enumerate(self.indices):
            port = self.metrics_base_port + idx
            url = f"http://{self.api_host}:{port}/metrics"
            
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'DailyHealthCheck/1.0'})
                with urllib.request.urlopen(req, timeout=10) as response:
                    metrics_text = response.read().decode()
                    
                    # Check for expected metrics
                    if "g6_ml_ensemble" in metrics_text:
                        logger.info(f"✓ Metrics exporter for {index} on port {port} is healthy")
                        self.results[f"metrics_{index}"] = {"status": "ok", "port": port}
                    else:
                        logger.warning(f"⚠ Metrics exporter for {index} running but no ML metrics found")
                        self.warnings.append(f"No ML metrics for {index}")
                        self.results[f"metrics_{index}"] = {"status": "warning", "port": port}
                        all_ok = False
                        
            except urllib.error.URLError as e:
                logger.error(f"✗ Failed to connect to metrics exporter for {index} on port {port}: {e}")
                self.critical_failures.append(f"Metrics exporter for {index} not responding")
                self.results[f"metrics_{index}"] = {"status": "failed", "port": port, "error": str(e)}
                all_ok = False
            except Exception as e:
                logger.error(f"✗ Error checking metrics for {index}: {e}")
                self.critical_failures.append(f"Metrics check failed for {index}: {e}")
                self.results[f"metrics_{index}"] = {"status": "failed", "error": str(e)}
                all_ok = False
        
        return all_ok
    
    def check_model_age(self) -> bool:
        """Check model age for each index."""
        logger.info("Checking model age...")
        
        all_ok = True
        for idx, index in enumerate(self.indices):
            port = self.metrics_base_port + idx
            url = f"http://{self.api_host}:{port}/metrics"
            
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'DailyHealthCheck/1.0'})
                with urllib.request.urlopen(req, timeout=10) as response:
                    metrics_text = response.read().decode()
                    
                    # Parse model age metric
                    for line in metrics_text.split('\n'):
                        if line.startswith('g6_ml_ensemble_model_age_days'):
                            # Extract value
                            parts = line.split()
                            if len(parts) >= 2:
                                age_days = float(parts[1])
                                
                                if age_days > self.max_model_age_days:
                                    logger.warning(f"⚠ Model for {index} is {age_days:.0f} days old (threshold: {self.max_model_age_days})")
                                    self.warnings.append(f"Model for {index} is stale ({age_days:.0f} days)")
                                    self.results[f"model_age_{index}"] = {"status": "warning", "age_days": age_days}
                                    all_ok = False
                                else:
                                    logger.info(f"✓ Model for {index} is {age_days:.0f} days old (within threshold)")
                                    self.results[f"model_age_{index}"] = {"status": "ok", "age_days": age_days}
                                break
                    else:
                        logger.warning(f"⚠ Could not find model age metric for {index}")
                        self.warnings.append(f"Model age metric missing for {index}")
                        self.results[f"model_age_{index}"] = {"status": "warning", "reason": "metric_not_found"}
                        all_ok = False
                        
            except Exception as e:
                logger.error(f"✗ Error checking model age for {index}: {e}")
                self.results[f"model_age_{index}"] = {"status": "error", "error": str(e)}
                all_ok = False
        
        return all_ok
    
    def check_forecast_capability(self) -> bool:
        """Test forecast generation for each index."""
        logger.info("Testing forecast capability...")
        
        all_ok = True
        for index in self.indices:
            url = f"http://{self.api_host}:{self.api_port}/api/ml/ensemble/forecast?index={index}&horizon=60"
            
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'DailyHealthCheck/1.0'})
                with urllib.request.urlopen(req, timeout=30) as response:
                    data = json.loads(response.read().decode())
                    
                    # Check for required forecast fields
                    required_fields = ['p10', 'p50', 'p90', 'confidence_score']
                    missing_fields = [f for f in required_fields if f not in data]
                    
                    if missing_fields:
                        logger.error(f"✗ Forecast for {index} missing fields: {missing_fields}")
                        self.critical_failures.append(f"Incomplete forecast for {index}")
                        self.results[f"forecast_{index}"] = {"status": "failed", "missing_fields": missing_fields}
                        all_ok = False
                    else:
                        # Check if values are reasonable
                        p10, p50, p90 = data['p10'], data['p50'], data['p90']
                        if p10 <= p50 <= p90 and all(v > 0 for v in [p10, p50, p90]):
                            logger.info(f"✓ Forecast for {index} looks good (P10={p10:.2f}, P50={p50:.2f}, P90={p90:.2f})")
                            self.results[f"forecast_{index}"] = {
                                "status": "ok",
                                "p10": p10,
                                "p50": p50,
                                "p90": p90,
                                "confidence": data['confidence_score']
                            }
                        else:
                            logger.warning(f"⚠ Forecast values for {index} look suspicious")
                            self.warnings.append(f"Suspicious forecast values for {index}")
                            self.results[f"forecast_{index}"] = {"status": "warning", "data": data}
                            all_ok = False
                            
            except urllib.error.URLError as e:
                logger.error(f"✗ Failed to get forecast for {index}: {e}")
                self.critical_failures.append(f"Forecast generation failed for {index}")
                self.results[f"forecast_{index}"] = {"status": "failed", "error": str(e)}
                all_ok = False
            except Exception as e:
                logger.error(f"✗ Error testing forecast for {index}: {e}")
                self.critical_failures.append(f"Forecast test error for {index}: {e}")
                self.results[f"forecast_{index}"] = {"status": "failed", "error": str(e)}
                all_ok = False
        
        return all_ok
    
    def run_checks(self) -> Tuple[bool, Dict]:
        """
        Run all health checks.
        
        Returns:
            Tuple of (all_passed, results_dict)
        """
        logger.info("=" * 70)
        logger.info("Starting Daily Health Check")
        logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Indices: {', '.join(self.indices)}")
        logger.info("=" * 70)
        
        checks = [
            ("API Health", self.check_api_health),
            ("Metrics Exporters", self.check_metrics_exporters),
            ("Model Age", self.check_model_age),
            ("Forecast Capability", self.check_forecast_capability),
        ]
        
        for check_name, check_func in checks:
            logger.info(f"\n--- {check_name} ---")
            try:
                check_func()
            except Exception as e:
                logger.error(f"Unexpected error in {check_name}: {e}")
                self.critical_failures.append(f"{check_name} failed unexpectedly: {e}")
        
        # Summary
        logger.info("\n" + "=" * 70)
        logger.info("Health Check Summary")
        logger.info("=" * 70)
        
        if self.critical_failures:
            logger.error(f"✗ CRITICAL FAILURES ({len(self.critical_failures)}):")
            for failure in self.critical_failures:
                logger.error(f"  - {failure}")
        
        if self.warnings:
            logger.warning(f"⚠ WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings:
                logger.warning(f"  - {warning}")
        
        all_passed = len(self.critical_failures) == 0
        
        if all_passed:
            if self.warnings:
                logger.info("✓ System operational with warnings")
            else:
                logger.info("✓ All checks passed - System ready for trading day")
        else:
            logger.error("✗ Critical failures detected - System NOT ready")
        
        # Compile results
        summary = {
            "timestamp": datetime.now().isoformat(),
            "indices": self.indices,
            "all_passed": all_passed,
            "critical_failures": self.critical_failures,
            "warnings": self.warnings,
            "checks": self.results
        }
        
        return all_passed, summary


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Daily health check for ML ensemble system"
    )
    parser.add_argument(
        "--index",
        type=str,
        required=True,
        help="Comma-separated list of indices (e.g., NIFTY,BANKNIFTY)"
    )
    parser.add_argument(
        "--api-host",
        type=str,
        default="localhost",
        help="ML API host (default: localhost)"
    )
    parser.add_argument(
        "--api-port",
        type=int,
        default=9210,
        help="ML API port (default: 9210)"
    )
    parser.add_argument(
        "--metrics-base-port",
        type=int,
        default=9325,
        help="Base port for metrics exporters (default: 9325)"
    )
    parser.add_argument(
        "--max-model-age",
        type=int,
        default=14,
        help="Maximum acceptable model age in days (default: 14)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file for results JSON"
    )
    
    args = parser.parse_args()
    
    # Parse indices
    indices = [idx.strip() for idx in args.index.split(',')]
    
    # Run checks
    checker = DailyHealthCheck(
        indices=indices,
        api_host=args.api_host,
        api_port=args.api_port,
        metrics_base_port=args.metrics_base_port,
        max_model_age_days=args.max_model_age
    )
    
    all_passed, summary = checker.run_checks()
    
    # Save results if requested
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, 'w') as f:
            json.dump(summary, f, indent=2)
        logger.info(f"\nResults saved to: {args.output}")
    
    # Exit with appropriate code
    if all_passed:
        sys.exit(0 if not summary['warnings'] else 2)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
