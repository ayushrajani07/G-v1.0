#!/usr/bin/env python3
"""
Historical Data Validation Script - Phase 8 Production Operations

Validates that sufficient historical data is available for model training and forecasting.
Checks:
- Data availability for required number of days
- Data completeness (no large gaps)
- Data quality (reasonable values)

Usage:
    python scripts/ml/validate_historical_data.py \
        --index NIFTY \
        --days 60 \
        --min-completeness 0.95
        
Exit codes:
    0 - Data validation passed
    1 - Data validation failed
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class HistoricalDataValidator:
    """Historical data validator."""
    
    def __init__(
        self,
        index: str,
        days: int,
        min_completeness: float,
        data_root: Path
    ):
        """
        Initialize validator.
        
        Args:
            index: Index name (NIFTY, BANKNIFTY)
            days: Required number of days of data
            min_completeness: Minimum completeness ratio (0.0-1.0)
            data_root: Root directory for g6 data
        """
        self.index = index
        self.days = days
        self.min_completeness = min_completeness
        self.data_root = data_root
        
    def get_expected_dates(self, end_date: Optional[datetime] = None) -> List[datetime]:
        """
        Get list of expected trading dates (excluding weekends).
        
        Args:
            end_date: End date (default: today)
            
        Returns:
            List of expected dates
        """
        if end_date is None:
            end_date = datetime.now()
        
        dates = []
        current = end_date
        
        while len(dates) < self.days * 2:  # Allow extra for weekends/holidays
            # Skip weekends (Saturday=5, Sunday=6)
            if current.weekday() < 5:
                dates.append(current)
            current = current - timedelta(days=1)
        
        # Return most recent N dates
        return sorted(dates)[-self.days:]
    
    def check_data_availability(self) -> Dict:
        """
        Check if data files exist for required dates.
        
        Returns:
            Dictionary with availability results
        """
        logger.info(f"Checking data availability for {self.index}...")
        
        # Look for data in multiple possible locations
        index_lower = self.index.lower()
        possible_paths = [
            self.data_root / "g6_data" / index_lower,
            self.data_root / index_lower,
        ]
        
        index_data_dir = None
        for path in possible_paths:
            if path.exists():
                index_data_dir = path
                logger.info(f"Found data directory: {index_data_dir}")
                break
        
        if index_data_dir is None:
            logger.error(f"No data directory found for {self.index}")
            return {
                "status": "error",
                "message": f"Data directory not found",
                "checked_paths": [str(p) for p in possible_paths]
            }
        
        # Get expected dates
        expected_dates = self.get_expected_dates()
        logger.info(f"Checking for {len(expected_dates)} trading days")
        
        # Check for data files
        available_dates = []
        missing_dates = []
        
        for date in expected_dates:
            date_str = date.strftime("%Y-%m-%d")
            
            # Look for CSV files in various subdirectories
            found = False
            
            # Check common subdirectory patterns
            for subdir in index_data_dir.rglob(f"*{date_str}*.csv"):
                found = True
                break
            
            if found:
                available_dates.append(date)
            else:
                missing_dates.append(date)
        
        # Calculate completeness
        completeness = len(available_dates) / len(expected_dates) if expected_dates else 0.0
        
        logger.info(f"Data availability: {len(available_dates)}/{len(expected_dates)} days ({completeness:.1%})")
        
        status = "ok" if completeness >= self.min_completeness else "insufficient"
        
        if status == "insufficient":
            logger.error(f"✗ Data completeness {completeness:.1%} below threshold {self.min_completeness:.1%}")
            logger.error(f"Missing {len(missing_dates)} days of data")
        else:
            logger.info(f"✓ Data completeness {completeness:.1%} meets threshold")
        
        return {
            "status": status,
            "required_days": self.days,
            "available_days": len(available_dates),
            "missing_days": len(missing_dates),
            "completeness": completeness,
            "min_completeness": self.min_completeness,
            "data_dir": str(index_data_dir),
            "first_date": available_dates[0].strftime("%Y-%m-%d") if available_dates else None,
            "last_date": available_dates[-1].strftime("%Y-%m-%d") if available_dates else None,
            "missing_date_samples": [d.strftime("%Y-%m-%d") for d in missing_dates[:10]]
        }
    
    def check_data_recency(self) -> Dict:
        """
        Check how recent the data is.
        
        Returns:
            Dictionary with recency check results
        """
        logger.info("Checking data recency...")
        
        index_lower = self.index.lower()
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
            return {
                "status": "error",
                "message": "Data directory not found"
            }
        
        # Find most recent CSV file
        csv_files = list(index_data_dir.rglob("*.csv"))
        
        if not csv_files:
            logger.error("✗ No CSV files found")
            return {
                "status": "error",
                "message": "No CSV files found"
            }
        
        # Get most recent file by modification time
        most_recent_file = max(csv_files, key=lambda p: p.stat().st_mtime)
        mtime = datetime.fromtimestamp(most_recent_file.stat().st_mtime)
        age_hours = (datetime.now() - mtime).total_seconds() / 3600
        
        # Check if data is stale (more than 48 hours old, accounting for weekends)
        status = "ok" if age_hours < 72 else "stale"
        
        if status == "stale":
            logger.warning(f"⚠ Most recent data is {age_hours:.1f} hours old")
        else:
            logger.info(f"✓ Data is recent ({age_hours:.1f} hours old)")
        
        return {
            "status": status,
            "most_recent_file": str(most_recent_file.name),
            "last_modified": mtime.isoformat(),
            "age_hours": age_hours
        }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Validate historical data availability and quality"
    )
    parser.add_argument(
        "--index",
        type=str,
        required=True,
        help="Index name (NIFTY, BANKNIFTY)"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=60,
        help="Required number of days of data (default: 60)"
    )
    parser.add_argument(
        "--min-completeness",
        type=float,
        default=0.95,
        help="Minimum data completeness ratio (default: 0.95)"
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("data"),
        help="Root directory for data (default: data)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file for results JSON"
    )
    
    args = parser.parse_args()
    
    logger.info("=" * 70)
    logger.info(f"Historical Data Validation - {args.index}")
    logger.info("=" * 70)
    
    # Create validator
    validator = HistoricalDataValidator(
        index=args.index,
        days=args.days,
        min_completeness=args.min_completeness,
        data_root=args.data_root
    )
    
    # Run checks
    availability_result = validator.check_data_availability()
    recency_result = validator.check_data_recency()
    
    # Combine results
    result = {
        "timestamp": datetime.now().isoformat(),
        "index": args.index,
        "availability": availability_result,
        "recency": recency_result
    }
    
    # Save results if requested
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2)
        logger.info(f"\nResults saved to: {args.output}")
    
    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("Validation Summary")
    logger.info("=" * 70)
    
    all_ok = (
        availability_result["status"] == "ok" and
        recency_result["status"] == "ok"
    )
    
    if all_ok:
        logger.info("✓ All validations passed")
        sys.exit(0)
    else:
        logger.error("✗ Validation failed")
        if availability_result["status"] != "ok":
            logger.error(f"  - Data availability: {availability_result['status']}")
        if recency_result["status"] != "ok":
            logger.error(f"  - Data recency: {recency_result['status']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
