#!/usr/bin/env python3
"""
Data Freshness Validator - Phase 8 Production Operations

Validates that data pipeline is working and producing fresh data.
Critical for ensuring ML models have up-to-date inputs.

Usage:
    python scripts/ml/validate_data_freshness.py --max-age-hours 24
    
Exit codes:
    0 - Data is fresh
    1 - Data is stale or pipeline issues detected
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class DataFreshnessValidator:
    """Data freshness validator."""
    
    def __init__(
        self,
        data_root: Path,
        max_age_hours: int = 24,
        indices: List[str] = None
    ):
        """
        Initialize validator.
        
        Args:
            data_root: Root directory for g6 data
            max_age_hours: Maximum acceptable data age in hours
            indices: List of indices to check (default: NIFTY, BANKNIFTY)
        """
        self.data_root = data_root
        self.max_age_hours = max_age_hours
        self.indices = indices or ["NIFTY", "BANKNIFTY"]
        
    def check_index_freshness(self, index: str) -> Dict:
        """
        Check data freshness for specific index.
        
        Args:
            index: Index name
            
        Returns:
            Dictionary with freshness results
        """
        logger.info(f"Checking data freshness for {index}...")
        
        index_lower = index.lower()
        possible_paths = [
            self.data_root / "g6_data" / index_lower,
            self.data_root / index_lower,
        ]
        
        index_data_dir = None
        for path in possible_paths:
            if path.exists():
                index_data_dir = path
                break
        
        if index_data_dir is None:
            logger.error(f"✗ Data directory not found for {index}")
            return {
                "status": "error",
                "message": f"Data directory not found",
                "index": index
            }
        
        # Find all CSV files
        csv_files = list(index_data_dir.rglob("*.csv"))
        
        if not csv_files:
            logger.error(f"✗ No CSV files found for {index}")
            return {
                "status": "error",
                "message": "No CSV files found",
                "index": index
            }
        
        # Get most recent file
        most_recent_file = max(csv_files, key=lambda p: p.stat().st_mtime)
        mtime = datetime.fromtimestamp(most_recent_file.stat().st_mtime)
        age_hours = (datetime.now() - mtime).total_seconds() / 3600
        
        # Determine status based on age and current time
        now = datetime.now()
        is_weekend = now.weekday() >= 5  # Saturday or Sunday
        is_market_hours = 9 <= now.hour < 16  # Rough market hours
        
        # Adjust threshold based on context
        if is_weekend:
            # On weekends, allow up to 72 hours (Friday evening to Monday morning)
            threshold = 72
        elif not is_market_hours:
            # Outside market hours, be more lenient
            threshold = self.max_age_hours * 2
        else:
            # During market hours, strict threshold
            threshold = self.max_age_hours
        
        status = "ok" if age_hours <= threshold else "stale"
        
        if status == "stale":
            logger.warning(f"⚠ Data for {index} is {age_hours:.1f} hours old (threshold: {threshold}h)")
        else:
            logger.info(f"✓ Data for {index} is fresh ({age_hours:.1f} hours old)")
        
        return {
            "status": status,
            "index": index,
            "most_recent_file": str(most_recent_file.relative_to(index_data_dir)),
            "last_modified": mtime.isoformat(),
            "age_hours": round(age_hours, 2),
            "threshold_hours": threshold,
            "total_files": len(csv_files),
            "data_dir": str(index_data_dir)
        }
    
    def check_collector_status(self) -> Dict:
        """
        Check if data collectors are running (basic check).
        
        Returns:
            Dictionary with collector status
        """
        logger.info("Checking collector status...")
        
        # Look for recent collector logs or status files
        log_dir = Path("logs")
        
        if not log_dir.exists():
            return {
                "status": "unknown",
                "message": "Log directory not found"
            }
        
        # Look for recent collector logs
        collector_logs = list(log_dir.glob("*collector*.log"))
        
        if not collector_logs:
            return {
                "status": "unknown",
                "message": "No collector logs found"
            }
        
        # Check most recent log
        most_recent_log = max(collector_logs, key=lambda p: p.stat().st_mtime)
        mtime = datetime.fromtimestamp(most_recent_log.stat().st_mtime)
        age_hours = (datetime.now() - mtime).total_seconds() / 3600
        
        status = "ok" if age_hours < 24 else "inactive"
        
        if status == "inactive":
            logger.warning(f"⚠ Collector logs are {age_hours:.1f} hours old")
        else:
            logger.info(f"✓ Collector logs are recent ({age_hours:.1f} hours old)")
        
        return {
            "status": status,
            "most_recent_log": str(most_recent_log.name),
            "last_modified": mtime.isoformat(),
            "age_hours": round(age_hours, 2)
        }
    
    def validate_all(self) -> Dict:
        """
        Run all freshness validations.
        
        Returns:
            Dictionary with all results
        """
        results = {
            "timestamp": datetime.now().isoformat(),
            "max_age_hours": self.max_age_hours,
            "indices": {}
        }
        
        # Check each index
        all_ok = True
        for index in self.indices:
            result = self.check_index_freshness(index)
            results["indices"][index] = result
            if result["status"] != "ok":
                all_ok = False
        
        # Check collector status
        collector_result = self.check_collector_status()
        results["collector"] = collector_result
        
        # Overall status
        results["overall_status"] = "ok" if all_ok else "issues_detected"
        
        return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Validate data pipeline freshness"
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("data"),
        help="Root directory for data (default: data)"
    )
    parser.add_argument(
        "--max-age-hours",
        type=int,
        default=24,
        help="Maximum acceptable data age in hours (default: 24)"
    )
    parser.add_argument(
        "--indices",
        type=str,
        default="NIFTY,BANKNIFTY",
        help="Comma-separated list of indices (default: NIFTY,BANKNIFTY)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file for results JSON"
    )
    
    args = parser.parse_args()
    
    # Parse indices
    indices = [idx.strip() for idx in args.indices.split(',')]
    
    logger.info("=" * 70)
    logger.info("Data Freshness Validation")
    logger.info("=" * 70)
    
    # Create validator
    validator = DataFreshnessValidator(
        data_root=args.data_root,
        max_age_hours=args.max_age_hours,
        indices=indices
    )
    
    # Run validation
    results = validator.validate_all()
    
    # Save results if requested
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        logger.info(f"\nResults saved to: {args.output}")
    
    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("Validation Summary")
    logger.info("=" * 70)
    
    if results["overall_status"] == "ok":
        logger.info("✓ All data freshness checks passed")
        sys.exit(0)
    else:
        logger.error("✗ Data freshness issues detected")
        for index, result in results["indices"].items():
            if result["status"] != "ok":
                logger.error(f"  - {index}: {result['status']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
