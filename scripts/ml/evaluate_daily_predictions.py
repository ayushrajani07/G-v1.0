#!/usr/bin/env python3
"""
Evaluate Daily Predictions - Phase 8 Production Operations

Compare forecasted values against actual outcomes for the day.
Tracks prediction accuracy and identifies systematic errors.

Usage:
    python scripts/ml/evaluate_daily_predictions.py --date today
    
Outputs:
- Prediction accuracy metrics (MAE, RMSE)
- Coverage analysis
- Systematic bias detection
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class DailyPredictionEvaluator:
    """Daily prediction evaluator."""
    
    def __init__(
        self,
        date: datetime,
        indices: List[str],
        data_root: Path
    ):
        """
        Initialize evaluator.
        
        Args:
            date: Date to evaluate
            indices: List of indices to evaluate
            data_root: Root directory for data
        """
        self.date = date
        self.indices = indices
        self.data_root = data_root
        
    def load_predictions(self, index: str) -> List[Dict]:
        """
        Load predictions made for the date.
        
        Args:
            index: Index name
            
        Returns:
            List of prediction dictionaries
        """
        logger.info(f"Loading predictions for {index}...")
        
        # Placeholder - in production, would load from prediction storage
        predictions = []
        
        # Example structure:
        # {
        #   "timestamp": "2025-11-17T09:30:00",
        #   "horizon": 60,
        #   "p10": 18500.0,
        #   "p50": 18550.0,
        #   "p90": 18600.0,
        #   "confidence": 0.85
        # }
        
        logger.info(f"Loaded {len(predictions)} predictions for {index}")
        return predictions
    
    def load_actuals(self, index: str) -> List[Dict]:
        """
        Load actual values for the date.
        
        Args:
            index: Index name
            
        Returns:
            List of actual value dictionaries
        """
        logger.info(f"Loading actual values for {index}...")
        
        # Placeholder - in production, would load from market data
        actuals = []
        
        # Example structure:
        # {
        #   "timestamp": "2025-11-17T10:30:00",  # 60 min after 09:30
        #   "value": 18555.0
        # }
        
        logger.info(f"Loaded {len(actuals)} actual values for {index}")
        return actuals
    
    def match_predictions_to_actuals(
        self,
        predictions: List[Dict],
        actuals: List[Dict]
    ) -> List[Tuple[Dict, float]]:
        """
        Match predictions to their corresponding actual values.
        
        Args:
            predictions: List of predictions
            actuals: List of actual values
            
        Returns:
            List of (prediction, actual_value) tuples
        """
        matched = []
        
        # Placeholder matching logic
        # In production, would match by timestamp + horizon
        
        logger.info(f"Matched {len(matched)} prediction-actual pairs")
        return matched
    
    def calculate_accuracy_metrics(
        self,
        matches: List[Tuple[Dict, float]]
    ) -> Dict:
        """
        Calculate accuracy metrics from matched pairs.
        
        Args:
            matches: List of (prediction, actual) tuples
            
        Returns:
            Dictionary with accuracy metrics
        """
        if not matches:
            logger.warning("No matches available for metric calculation")
            return {
                "mae": None,
                "rmse": None,
                "mape": None,
                "bias": None,
                "n_samples": 0
            }
        
        # Extract predictions and actuals
        p50_values = np.array([m[0]["p50"] for m in matches])
        actual_values = np.array([m[1] for m in matches])
        
        # Calculate metrics
        errors = actual_values - p50_values
        mae = float(np.mean(np.abs(errors)))
        rmse = float(np.sqrt(np.mean(errors ** 2)))
        
        # MAPE (avoid division by zero)
        non_zero_mask = actual_values != 0
        if np.sum(non_zero_mask) > 0:
            mape = float(np.mean(np.abs(errors[non_zero_mask] / actual_values[non_zero_mask])) * 100)
        else:
            mape = None
        
        # Bias (systematic over/under prediction)
        bias = float(np.mean(errors))
        
        metrics = {
            "mae": mae,
            "rmse": rmse,
            "mape": mape,
            "bias": bias,
            "n_samples": len(matches)
        }
        
        return metrics
    
    def calculate_coverage_metrics(
        self,
        matches: List[Tuple[Dict, float]]
    ) -> Dict:
        """
        Calculate coverage metrics from matched pairs.
        
        Args:
            matches: List of (prediction, actual) tuples
            
        Returns:
            Dictionary with coverage metrics
        """
        if not matches:
            return {
                "coverage_rate": None,
                "avg_band_width": None,
                "n_samples": 0
            }
        
        within_band = 0
        band_widths = []
        
        for pred, actual in matches:
            p10 = pred["p10"]
            p90 = pred["p90"]
            
            # Check if actual is within band
            if p10 <= actual <= p90:
                within_band += 1
            
            # Calculate band width
            band_width = p90 - p10
            band_widths.append(band_width)
        
        coverage_rate = within_band / len(matches)
        avg_band_width = np.mean(band_widths)
        
        metrics = {
            "coverage_rate": float(coverage_rate),
            "avg_band_width": float(avg_band_width),
            "within_band_count": within_band,
            "outside_band_count": len(matches) - within_band,
            "n_samples": len(matches)
        }
        
        return metrics
    
    def detect_systematic_errors(
        self,
        matches: List[Tuple[Dict, float]]
    ) -> Dict:
        """
        Detect systematic errors in predictions.
        
        Args:
            matches: List of (prediction, actual) tuples
            
        Returns:
            Dictionary with error analysis
        """
        if not matches:
            return {
                "systematic_bias": None,
                "error_trend": None
            }
        
        # Extract errors
        errors = [m[1] - m[0]["p50"] for m in matches]
        
        # Detect bias
        mean_error = np.mean(errors)
        std_error = np.std(errors)
        
        # Check if bias is statistically significant
        # (simple test: |mean| > std/sqrt(n))
        n = len(errors)
        significance_threshold = std_error / np.sqrt(n) if n > 0 else 0
        
        has_bias = abs(mean_error) > significance_threshold
        
        # Detect trend
        # Simple linear regression on errors over time
        if len(errors) > 2:
            x = np.arange(len(errors))
            y = np.array(errors)
            slope = np.polyfit(x, y, 1)[0]
            
            # Check if trend is significant
            has_trend = abs(slope) > 0.1  # Arbitrary threshold
        else:
            slope = 0
            has_trend = False
        
        analysis = {
            "systematic_bias": {
                "detected": has_bias,
                "mean_error": float(mean_error),
                "std_error": float(std_error)
            },
            "error_trend": {
                "detected": has_trend,
                "slope": float(slope)
            }
        }
        
        return analysis
    
    def evaluate_index(self, index: str) -> Dict:
        """
        Evaluate predictions for a single index.
        
        Args:
            index: Index name
            
        Returns:
            Dictionary with evaluation results
        """
        logger.info(f"\n--- Evaluating {index} ---")
        
        # Load data
        predictions = self.load_predictions(index)
        actuals = self.load_actuals(index)
        
        # Match predictions to actuals
        matches = self.match_predictions_to_actuals(predictions, actuals)
        
        if not matches:
            logger.warning(f"No matched predictions for {index}")
            return {
                "index": index,
                "status": "no_data",
                "message": "No matched predictions available"
            }
        
        # Calculate metrics
        accuracy = self.calculate_accuracy_metrics(matches)
        coverage = self.calculate_coverage_metrics(matches)
        errors = self.detect_systematic_errors(matches)
        
        # Log results
        logger.info(f"Accuracy - MAE: {accuracy['mae']:.2f}, RMSE: {accuracy['rmse']:.2f}")
        logger.info(f"Coverage - Rate: {coverage['coverage_rate']:.1%}, Band Width: {coverage['avg_band_width']:.2f}")
        
        if errors["systematic_bias"]["detected"]:
            logger.warning(f"⚠ Systematic bias detected: {errors['systematic_bias']['mean_error']:.2f}")
        
        if errors["error_trend"]["detected"]:
            logger.warning(f"⚠ Error trend detected: slope={errors['error_trend']['slope']:.4f}")
        
        evaluation = {
            "index": index,
            "date": self.date.strftime("%Y-%m-%d"),
            "accuracy": accuracy,
            "coverage": coverage,
            "error_analysis": errors,
            "status": "ok"
        }
        
        return evaluation
    
    def evaluate_all(self) -> Dict:
        """
        Evaluate predictions for all indices.
        
        Returns:
            Dictionary with all evaluation results
        """
        logger.info("=" * 70)
        logger.info(f"Daily Prediction Evaluation - {self.date.strftime('%Y-%m-%d')}")
        logger.info("=" * 70)
        
        results = {
            "evaluation_type": "daily_predictions",
            "date": self.date.strftime("%Y-%m-%d"),
            "generated_at": datetime.now().isoformat(),
            "indices": {}
        }
        
        for index in self.indices:
            evaluation = self.evaluate_index(index)
            results["indices"][index] = evaluation
        
        # Generate summary
        results["summary"] = self.generate_summary(results)
        
        logger.info("\n" + "=" * 70)
        logger.info("Evaluation Complete")
        logger.info("=" * 70)
        
        return results
    
    def generate_summary(self, results: Dict) -> Dict:
        """
        Generate summary across all indices.
        
        Args:
            results: Results dictionary
            
        Returns:
            Summary dictionary
        """
        summary = {
            "overall_status": "ok",
            "issues": [],
            "highlights": []
        }
        
        # Check for issues across indices
        for index, evaluation in results["indices"].items():
            if evaluation.get("status") != "ok":
                summary["issues"].append(f"{index}: {evaluation.get('message', 'unknown issue')}")
                summary["overall_status"] = "issues_detected"
                continue
            
            # Check for systematic bias
            if evaluation.get("error_analysis", {}).get("systematic_bias", {}).get("detected"):
                summary["issues"].append(f"{index}: Systematic bias detected")
                summary["overall_status"] = "issues_detected"
            
            # Check for poor coverage
            coverage_rate = evaluation.get("coverage", {}).get("coverage_rate")
            if coverage_rate is not None and (coverage_rate < 0.75 or coverage_rate > 0.90):
                summary["issues"].append(f"{index}: Coverage rate out of range ({coverage_rate:.1%})")
                summary["overall_status"] = "issues_detected"
        
        return summary


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Evaluate daily predictions against actuals"
    )
    parser.add_argument(
        "--date",
        type=str,
        default="today",
        help="Date to evaluate (YYYY-MM-DD or 'today')"
    )
    parser.add_argument(
        "--indices",
        type=str,
        default="NIFTY,BANKNIFTY",
        help="Comma-separated list of indices (default: NIFTY,BANKNIFTY)"
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
    
    # Parse date
    if args.date.lower() == "today":
        date = datetime.now()
    else:
        try:
            date = datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            logger.error(f"Invalid date format: {args.date}. Use YYYY-MM-DD")
            sys.exit(1)
    
    # Parse indices
    indices = [idx.strip() for idx in args.indices.split(',')]
    
    # Evaluate predictions
    evaluator = DailyPredictionEvaluator(
        date=date,
        indices=indices,
        data_root=args.data_root
    )
    
    results = evaluator.evaluate_all()
    
    # Save results if requested
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        logger.info(f"\nResults saved to: {args.output}")
    
    # Print summary
    summary = results.get("summary", {})
    logger.info(f"\n=== Summary ===")
    logger.info(f"Status: {summary.get('overall_status', 'N/A')}")
    
    if summary.get("issues"):
        logger.warning("\nIssues detected:")
        for issue in summary["issues"]:
            logger.warning(f"  ⚠ {issue}")
        sys.exit(1)
    else:
        logger.info("\n✓ All evaluations passed")
        sys.exit(0)


if __name__ == "__main__":
    main()
