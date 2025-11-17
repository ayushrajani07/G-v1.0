#!/usr/bin/env python3
"""
Model Age Checker - Phase 8 Production Operations

Checks the age of trained models and alerts if they exceed threshold.
Models should be retrained regularly to adapt to changing market conditions.

Usage:
    python scripts/ml/check_model_age.py --index NIFTY --alert-threshold 14
    
Exit codes:
    0 - Model age within threshold
    1 - Model age exceeds threshold (needs retraining)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class ModelAgeChecker:
    """Model age checker."""
    
    def __init__(
        self,
        index: str,
        models_dir: Path,
        alert_threshold_days: int = 14,
        warning_threshold_days: int = 10
    ):
        """
        Initialize model age checker.
        
        Args:
            index: Index name (NIFTY, BANKNIFTY)
            models_dir: Directory containing models
            alert_threshold_days: Alert if model age exceeds this (days)
            warning_threshold_days: Warn if model age exceeds this (days)
        """
        self.index = index
        self.models_dir = models_dir
        self.alert_threshold_days = alert_threshold_days
        self.warning_threshold_days = warning_threshold_days
        
    def check_model_age(self) -> Dict:
        """
        Check model age and return status.
        
        Returns:
            Dictionary with status and details
        """
        model_dir = self.models_dir / f"{self.index.lower()}_gbrt_quantile"
        
        if not model_dir.exists():
            logger.error(f"Model directory not found: {model_dir}")
            return {
                "status": "error",
                "message": f"Model directory not found: {model_dir}",
                "index": self.index
            }
        
        # Check training report for model age
        report_file = model_dir / "training_report.json"
        
        if not report_file.exists():
            logger.warning(f"Training report not found: {report_file}")
            logger.info("Falling back to directory modification time")
            
            # Use directory modification time as fallback
            mtime = datetime.fromtimestamp(model_dir.stat().st_mtime)
            training_date = mtime
            model_age_days = (datetime.now() - training_date).days
            
        else:
            # Read training report
            try:
                with open(report_file, 'r') as f:
                    report = json.load(f)
                
                # Extract training timestamp
                training_timestamp = report.get("training_timestamp")
                if not training_timestamp:
                    logger.warning("No training_timestamp in report, using file mtime")
                    mtime = datetime.fromtimestamp(report_file.stat().st_mtime)
                    training_date = mtime
                else:
                    # Parse timestamp (ISO format)
                    training_date = datetime.fromisoformat(training_timestamp.replace('Z', '+00:00'))
                    if training_date.tzinfo:
                        training_date = training_date.replace(tzinfo=None)
                
                model_age_days = (datetime.now() - training_date).days
                
            except Exception as e:
                logger.error(f"Error reading training report: {e}")
                return {
                    "status": "error",
                    "message": f"Failed to read training report: {e}",
                    "index": self.index
                }
        
        # Determine status
        if model_age_days >= self.alert_threshold_days:
            status = "alert"
            message = f"Model age ({model_age_days} days) exceeds alert threshold ({self.alert_threshold_days} days)"
            logger.error(f"✗ {message}")
        elif model_age_days >= self.warning_threshold_days:
            status = "warning"
            message = f"Model age ({model_age_days} days) exceeds warning threshold ({self.warning_threshold_days} days)"
            logger.warning(f"⚠ {message}")
        else:
            status = "ok"
            message = f"Model age ({model_age_days} days) within threshold"
            logger.info(f"✓ {message}")
        
        result = {
            "status": status,
            "index": self.index,
            "model_age_days": model_age_days,
            "training_date": training_date.isoformat(),
            "alert_threshold_days": self.alert_threshold_days,
            "warning_threshold_days": self.warning_threshold_days,
            "message": message,
            "model_dir": str(model_dir)
        }
        
        return result
    
    def check_all_quantiles(self) -> Dict:
        """
        Check that all required quantile models exist.
        
        Returns:
            Dictionary with status and details
        """
        model_dir = self.models_dir / f"{self.index.lower()}_gbrt_quantile"
        
        if not model_dir.exists():
            return {
                "status": "error",
                "message": f"Model directory not found: {model_dir}"
            }
        
        required_models = ["model_q10.joblib", "model_q50.joblib", "model_q90.joblib"]
        missing_models = []
        
        for model_file in required_models:
            if not (model_dir / model_file).exists():
                missing_models.append(model_file)
        
        if missing_models:
            logger.error(f"✗ Missing model files: {missing_models}")
            return {
                "status": "error",
                "message": f"Missing model files: {missing_models}",
                "missing_files": missing_models
            }
        else:
            logger.info("✓ All quantile models present")
            return {
                "status": "ok",
                "message": "All quantile models present"
            }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Check model age and alert if retraining needed"
    )
    parser.add_argument(
        "--index",
        type=str,
        required=True,
        help="Index name (NIFTY, BANKNIFTY)"
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=Path("models"),
        help="Directory containing models (default: models)"
    )
    parser.add_argument(
        "--alert-threshold",
        type=int,
        default=14,
        help="Alert threshold in days (default: 14)"
    )
    parser.add_argument(
        "--warning-threshold",
        type=int,
        default=10,
        help="Warning threshold in days (default: 10)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file for results JSON"
    )
    
    args = parser.parse_args()
    
    logger.info("=" * 70)
    logger.info(f"Model Age Check - {args.index}")
    logger.info("=" * 70)
    
    # Create checker
    checker = ModelAgeChecker(
        index=args.index,
        models_dir=args.models_dir,
        alert_threshold_days=args.alert_threshold,
        warning_threshold_days=args.warning_threshold
    )
    
    # Check model files exist
    files_result = checker.check_all_quantiles()
    
    # Check model age
    age_result = checker.check_model_age()
    
    # Combine results
    result = {
        "timestamp": datetime.now().isoformat(),
        "index": args.index,
        "files_check": files_result,
        "age_check": age_result
    }
    
    # Save results if requested
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2)
        logger.info(f"\nResults saved to: {args.output}")
    
    # Exit based on status
    if files_result["status"] == "error" or age_result["status"] == "error":
        sys.exit(1)
    elif age_result["status"] == "alert":
        logger.info("\n⚠ RECOMMENDATION: Schedule model retraining")
        sys.exit(1)
    elif age_result["status"] == "warning":
        logger.info("\n⚠ Model is aging, consider retraining soon")
        sys.exit(0)
    else:
        logger.info("\n✓ Model is fresh")
        sys.exit(0)


if __name__ == "__main__":
    main()
