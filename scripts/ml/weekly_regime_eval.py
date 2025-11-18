#!/usr/bin/env python3
"""Weekly Regime Evaluation Script (Phase 10)

Aggregates weekly average embedding, detects shift vs prior week centroid,
and writes artifact reports.

Usage:
    python scripts/ml/weekly_regime_eval.py --indices NIFTY,BANKNIFTY
    python scripts/ml/weekly_regime_eval.py --indices NIFTY --output custom_report.json

Environment Variables:
    G6_REGIME_WEEKLY_ENABLED (default 1) - Enable/disable weekly evaluation
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
_project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_project_root))

from src.ml import regime_detector

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
_LOG = logging.getLogger(__name__)


def get_weekly_average_embedding(index: str) -> Optional[Dict[str, float]]:
    """Compute weekly average embedding from recent history.
    
    Args:
        index: Index name
    
    Returns:
        Average embedding dict, or None if insufficient data
    """
    history = regime_detector._safe_read_history(index)
    
    if not history:
        _LOG.warning(f"No history found for {index}")
        return None
    
    # Get last 7 entries (roughly last week if updated daily)
    recent = history[-7:]
    
    if not recent:
        return None
    
    # Compute average for each feature
    features = regime_detector._get_regime_features()
    avg_embedding: Dict[str, float] = {}
    
    for feature in features:
        values = []
        for entry in recent:
            embedding = entry.get("embedding", {})
            if feature in embedding:
                values.append(embedding[feature])
        
        if values:
            avg_embedding[feature] = sum(values) / len(values)
        else:
            avg_embedding[feature] = 0.0
    
    return avg_embedding


def get_prior_week_centroid(index: str) -> Optional[Dict[str, float]]:
    """Get centroid from prior week (entries 8-14 days ago).
    
    Args:
        index: Index name
    
    Returns:
        Prior week centroid, or None if insufficient data
    """
    history = regime_detector._safe_read_history(index)
    
    if len(history) < 14:
        _LOG.warning(f"Insufficient history for prior week centroid: {len(history)} entries")
        return None
    
    # Get entries from 8-14 days ago (assuming daily updates)
    prior_week = history[-14:-7]
    
    if not prior_week:
        return None
    
    # Compute average
    features = regime_detector._get_regime_features()
    centroid: Dict[str, float] = {}
    
    for feature in features:
        values = []
        for entry in prior_week:
            embedding = entry.get("embedding", {})
            if feature in embedding:
                values.append(embedding[feature])
        
        if values:
            centroid[feature] = sum(values) / len(values)
        else:
            centroid[feature] = 0.0
    
    return centroid


def evaluate_weekly_regime(index: str) -> Dict[str, Any]:
    """Evaluate weekly regime shift for given index.
    
    Args:
        index: Index name
    
    Returns:
        Dictionary with evaluation results
    """
    _LOG.info(f"Evaluating weekly regime for {index}")
    
    # Get current week's average embedding
    current_avg = get_weekly_average_embedding(index)
    
    if not current_avg:
        return {
            "index": index,
            "status": "insufficient_data",
            "message": "No recent history available",
        }
    
    # Get prior week's centroid
    prior_centroid = get_prior_week_centroid(index)
    
    if not prior_centroid:
        return {
            "index": index,
            "status": "insufficient_data",
            "message": "Not enough historical data for prior week comparison",
            "current_week_avg": current_avg,
        }
    
    # Compute distance between current avg and prior centroid
    metric = regime_detector._get_env_str(
        "G6_REGIME_DISTANCE_METRIC",
        regime_detector._DEFAULT_DISTANCE_METRIC
    )
    
    current_vec = regime_detector._embedding_to_vector(current_avg)
    prior_vec = regime_detector._embedding_to_vector(prior_centroid)
    distance = regime_detector._compute_distance(current_vec, prior_vec, metric)
    
    # Determine status based on thresholds
    warn_threshold = regime_detector._get_env_float(
        "G6_REGIME_SHIFT_DISTANCE_WARN",
        regime_detector._DEFAULT_DISTANCE_WARN
    )
    crit_threshold = regime_detector._get_env_float(
        "G6_REGIME_SHIFT_DISTANCE_CRIT",
        regime_detector._DEFAULT_DISTANCE_CRIT
    )
    
    if distance >= crit_threshold:
        status = regime_detector.REGIME_STATUS_CRITICAL
    elif distance >= warn_threshold:
        status = regime_detector.REGIME_STATUS_WARN
    else:
        status = regime_detector.REGIME_STATUS_STABLE
    
    return {
        "index": index,
        "status": status,
        "distance": round(distance, 4),
        "current_week_avg": current_avg,
        "prior_week_centroid": prior_centroid,
        "thresholds": {
            "warn": warn_threshold,
            "critical": crit_threshold,
        },
        "metric": metric,
    }


def main():
    """Main entry point for weekly regime evaluation."""
    parser = argparse.ArgumentParser(
        description="Weekly Regime Evaluation - Aggregates and reports regime shifts"
    )
    parser.add_argument(
        "--indices",
        type=str,
        default="NIFTY,BANKNIFTY",
        help="Comma-separated list of indices to evaluate (default: NIFTY,BANKNIFTY)"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Custom output path (default: reports/regime/weekly_<date>.json)"
    )
    
    args = parser.parse_args()
    
    # Check if weekly evaluation is enabled
    enabled = regime_detector._get_env_int("G6_REGIME_WEEKLY_ENABLED", 1)
    if not enabled:
        _LOG.info("Weekly regime evaluation is disabled (G6_REGIME_WEEKLY_ENABLED=0)")
        print("Weekly evaluation disabled")
        return 0
    
    # Parse indices
    indices = [idx.strip() for idx in args.indices.split(",") if idx.strip()]
    
    if not indices:
        _LOG.error("No indices specified")
        return 1
    
    _LOG.info(f"Evaluating regime for indices: {', '.join(indices)}")
    
    # Evaluate each index
    results: List[Dict[str, Any]] = []
    for index in indices:
        try:
            result = evaluate_weekly_regime(index)
            results.append(result)
            
            # Print one-line summary for CI
            status = result.get("status", "unknown")
            distance = result.get("distance", 0.0)
            print(f"{index}: {status} (distance={distance})")
            
        except Exception as e:
            _LOG.error(f"Failed to evaluate {index}: {e}")
            results.append({
                "index": index,
                "status": "error",
                "message": str(e),
            })
    
    # Generate output path
    if args.output:
        output_path = Path(args.output)
    else:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        output_dir = _project_root / "reports" / "regime"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"weekly_{today}.json"
    
    # Write report
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "evaluation_type": "weekly",
        "results": results,
        "summary": {
            "total_indices": len(indices),
            "stable": sum(1 for r in results if r.get("status") == "stable"),
            "warn": sum(1 for r in results if r.get("status") == "warn"),
            "critical": sum(1 for r in results if r.get("status") == "critical"),
            "errors": sum(1 for r in results if r.get("status") == "error"),
        }
    }
    
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        _LOG.info(f"Weekly regime report written to: {output_path}")
        print(f"\nReport written to: {output_path}")
    except Exception as e:
        _LOG.error(f"Failed to write report: {e}")
        return 1
    
    # Return non-zero if any critical status detected
    if report["summary"]["critical"] > 0:
        _LOG.warning(f"Critical regime shifts detected: {report['summary']['critical']}")
        return 0  # Don't fail CI, just warn
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
