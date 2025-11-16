#!/usr/bin/env python3
"""
Feature Importance Tracking Script (Phase 5)

Track and analyze feature importance from GBRT models over time.
Helps identify feature stability and importance drift.

Based on ML_ARM_IMPLEMENTATION_ROADMAP.md Phase 5 specifications.

Usage:
    python scripts/ml/track_feature_importance.py \
        --model models/nifty_gbrt_quantile/ \
        --output reports/feature_importance_weekly.html \
        --history reports/feature_importance_history.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime

import numpy as np
import pandas as pd

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.analytics.ml.quantile import QuantileRegressor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_model(model_path: Path, quantile: float = 0.5) -> Optional[QuantileRegressor]:
    """Load trained GBRT model.
    
    Args:
        model_path: Path to model directory
        quantile: Quantile to load (default: 0.5)
        
    Returns:
        Loaded QuantileRegressor or None if failed
    """
    logger.info(f"Loading model from {model_path} for quantile {quantile}")
    
    try:
        model = QuantileRegressor(quantile=quantile)
        
        # Try to load model file
        quantile_str = f"q{int(quantile*100):02d}"
        model_file = model_path / f"model_{quantile_str}.joblib"
        
        if not model_file.exists():
            logger.error(f"Model file not found: {model_file}")
            return None
        
        model.load(str(model_file))
        logger.info(f"Model loaded successfully")
        return model
        
    except Exception as e:
        logger.error(f"Failed to load model: {e}", exc_info=True)
        return None


def extract_feature_importance(
    model: QuantileRegressor,
    feature_names: List[str],
    top_k: int = 15
) -> Dict[str, float]:
    """Extract feature importance from GBRT model.
    
    Args:
        model: Trained QuantileRegressor
        feature_names: List of feature names
        top_k: Number of top features to return
        
    Returns:
        Dictionary mapping feature names to importance scores
    """
    logger.info("Extracting feature importance")
    
    try:
        # Get feature importance from underlying model
        if hasattr(model.model, "feature_importances_"):
            importances = model.model.feature_importances_
        else:
            logger.warning("Model does not have feature_importances_ attribute")
            return {}
        
        if len(importances) != len(feature_names):
            logger.warning(
                f"Importance length ({len(importances)}) != feature names length ({len(feature_names)})"
            )
            min_len = min(len(importances), len(feature_names))
            importances = importances[:min_len]
            feature_names = feature_names[:min_len]
        
        # Create feature importance dictionary
        feature_importance = dict(zip(feature_names, importances))
        
        # Sort by importance and take top k
        sorted_features = sorted(
            feature_importance.items(),
            key=lambda x: x[1],
            reverse=True
        )[:top_k]
        
        top_features = dict(sorted_features)
        
        logger.info(f"Extracted top {len(top_features)} features")
        for feat, imp in list(top_features.items())[:5]:
            logger.info(f"  {feat}: {imp:.4f}")
        
        return top_features
        
    except Exception as e:
        logger.error(f"Failed to extract feature importance: {e}", exc_info=True)
        return {}


def load_feature_names(model_path: Path) -> List[str]:
    """Load feature names from model directory.
    
    Args:
        model_path: Path to model directory
        
    Returns:
        List of feature names
    """
    feature_config_file = model_path / "feature_engineering.json"
    
    if not feature_config_file.exists():
        logger.warning(f"Feature config not found: {feature_config_file}")
        # Return default feature names
        from src.analytics.ml.feature_engineering import FeatureEngineer
        fe = FeatureEngineer()
        return fe.get_feature_names()
    
    try:
        with open(feature_config_file, "r") as f:
            config = json.load(f)
        
        feature_names = config.get("feature_names", [])
        logger.info(f"Loaded {len(feature_names)} feature names from config")
        return feature_names
        
    except Exception as e:
        logger.error(f"Failed to load feature names: {e}", exc_info=True)
        from src.analytics.ml.feature_engineering import FeatureEngineer
        fe = FeatureEngineer()
        return fe.get_feature_names()


def update_importance_history(
    current_importance: Dict[str, float],
    history_file: Path
) -> List[Dict[str, Any]]:
    """Update feature importance history.
    
    Args:
        current_importance: Current feature importance scores
        history_file: Path to history JSON file
        
    Returns:
        Updated history list
    """
    logger.info(f"Updating importance history in {history_file}")
    
    # Load existing history
    history = []
    if history_file.exists():
        try:
            with open(history_file, "r") as f:
                history = json.load(f)
            logger.info(f"Loaded {len(history)} historical records")
        except Exception as e:
            logger.warning(f"Failed to load history: {e}")
    
    # Add current record
    record = {
        "timestamp": datetime.now().isoformat(),
        "importance": current_importance
    }
    history.append(record)
    
    # Keep only last 52 weeks (1 year of weekly data)
    if len(history) > 52:
        history = history[-52:]
    
    # Save updated history
    history_file.parent.mkdir(parents=True, exist_ok=True)
    with open(history_file, "w") as f:
        json.dump(history, f, indent=2)
    
    logger.info(f"Updated history with {len(history)} records")
    return history


def analyze_importance_stability(
    history: List[Dict[str, Any]],
    min_records: int = 4
) -> Dict[str, Any]:
    """Analyze feature importance stability over time.
    
    Args:
        history: List of historical importance records
        min_records: Minimum records needed for analysis
        
    Returns:
        Stability analysis results
    """
    logger.info("Analyzing feature importance stability")
    
    if len(history) < min_records:
        logger.warning(f"Insufficient history ({len(history)} < {min_records}) for stability analysis")
        return {
            "n_records": len(history),
            "sufficient_data": False,
            "feature_stability": {}
        }
    
    # Extract all features seen in history
    all_features = set()
    for record in history:
        all_features.update(record["importance"].keys())
    
    # Calculate stability metrics for each feature
    feature_stability = {}
    
    for feature in all_features:
        # Get importance values for this feature across history
        values = []
        for record in history:
            imp = record["importance"].get(feature, 0.0)
            values.append(imp)
        
        values = np.array(values)
        
        # Calculate stability metrics
        mean_importance = float(np.mean(values))
        std_importance = float(np.std(values))
        cv = std_importance / mean_importance if mean_importance > 0 else np.inf
        
        # Count how often feature appears in top 15
        appearances = sum(1 for v in values if v > 0)
        appearance_rate = appearances / len(values)
        
        feature_stability[feature] = {
            "mean_importance": mean_importance,
            "std_importance": std_importance,
            "coefficient_of_variation": cv,
            "appearance_rate": appearance_rate,
            "stable": cv < 0.5 and appearance_rate > 0.75
        }
    
    # Identify most stable features
    stable_features = [
        feat for feat, metrics in feature_stability.items()
        if metrics["stable"]
    ]
    
    logger.info(f"Found {len(stable_features)} stable features out of {len(all_features)} total")
    
    return {
        "n_records": len(history),
        "sufficient_data": True,
        "n_features": len(all_features),
        "n_stable_features": len(stable_features),
        "stable_features": stable_features,
        "feature_stability": feature_stability
    }


def generate_html_report(
    current_importance: Dict[str, float],
    stability_analysis: Dict[str, Any],
    output_path: Path
) -> None:
    """Generate HTML report for feature importance.
    
    Args:
        current_importance: Current feature importance scores
        stability_analysis: Stability analysis results
        output_path: Output path for HTML report
    """
    logger.info(f"Generating HTML report: {output_path}")
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Feature Importance Report</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background-color: white;
            padding: 20px;
            box-shadow: 0 0 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
            border-bottom: 2px solid #4CAF50;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #555;
            margin-top: 30px;
        }}
        .timestamp {{
            color: #777;
            font-size: 14px;
            margin-bottom: 20px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }}
        th, td {{
            padding: 10px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background-color: #4CAF50;
            color: white;
        }}
        tr:hover {{
            background-color: #f5f5f5;
        }}
        .bar {{
            background-color: #4CAF50;
            height: 20px;
            display: inline-block;
        }}
        .stable {{
            color: green;
            font-weight: bold;
        }}
        .unstable {{
            color: orange;
        }}
        .metric {{
            display: inline-block;
            margin: 10px 20px;
            padding: 10px;
            background-color: #f9f9f9;
            border-radius: 5px;
        }}
        .metric-label {{
            color: #777;
            font-size: 12px;
        }}
        .metric-value {{
            font-size: 24px;
            font-weight: bold;
            color: #333;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Feature Importance Report</h1>
        <div class="timestamp">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
        
        <h2>Current Top Features</h2>
        <table>
            <tr>
                <th>Rank</th>
                <th>Feature</th>
                <th>Importance</th>
                <th>Visualization</th>
            </tr>
"""
    
    # Add current importance table
    sorted_features = sorted(
        current_importance.items(),
        key=lambda x: x[1],
        reverse=True
    )
    
    max_importance = max(current_importance.values()) if current_importance else 1.0
    
    for rank, (feature, importance) in enumerate(sorted_features, 1):
        bar_width = int((importance / max_importance) * 300)
        html += f"""
            <tr>
                <td>{rank}</td>
                <td>{feature}</td>
                <td>{importance:.4f}</td>
                <td><div class="bar" style="width: {bar_width}px;"></div></td>
            </tr>
"""
    
    html += """
        </table>
        
        <h2>Stability Analysis</h2>
"""
    
    # Add stability metrics
    if stability_analysis.get("sufficient_data", False):
        html += f"""
        <div>
            <div class="metric">
                <div class="metric-label">Historical Records</div>
                <div class="metric-value">{stability_analysis['n_records']}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Total Features</div>
                <div class="metric-value">{stability_analysis['n_features']}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Stable Features</div>
                <div class="metric-value">{stability_analysis['n_stable_features']}</div>
            </div>
        </div>
        
        <table>
            <tr>
                <th>Feature</th>
                <th>Mean Importance</th>
                <th>Std Dev</th>
                <th>CV</th>
                <th>Appearance Rate</th>
                <th>Status</th>
            </tr>
"""
        
        # Sort by mean importance
        feature_stability = stability_analysis.get("feature_stability", {})
        sorted_stability = sorted(
            feature_stability.items(),
            key=lambda x: x[1]["mean_importance"],
            reverse=True
        )
        
        for feature, metrics in sorted_stability[:20]:  # Top 20
            status = "stable" if metrics["stable"] else "unstable"
            status_class = "stable" if metrics["stable"] else "unstable"
            
            html += f"""
            <tr>
                <td>{feature}</td>
                <td>{metrics['mean_importance']:.4f}</td>
                <td>{metrics['std_importance']:.4f}</td>
                <td>{metrics['coefficient_of_variation']:.2f}</td>
                <td>{metrics['appearance_rate']:.2%}</td>
                <td class="{status_class}">{status.upper()}</td>
            </tr>
"""
        
        html += """
        </table>
"""
    else:
        html += f"""
        <p>Insufficient historical data for stability analysis. 
        Need at least 4 records, currently have {stability_analysis['n_records']}.</p>
"""
    
    html += """
    </div>
</body>
</html>
"""
    
    # Save report
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html)
    
    logger.info(f"HTML report saved to {output_path}")


def main() -> int:
    """Main entry point for feature importance tracking."""
    parser = argparse.ArgumentParser(
        description="Track and analyze feature importance from GBRT models"
    )
    parser.add_argument(
        "--model",
        type=Path,
        required=True,
        help="Path to model directory"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/feature_importance_report.html"),
        help="Output path for HTML report"
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=Path("reports/feature_importance_history.json"),
        help="Path to importance history JSON file"
    )
    parser.add_argument(
        "--quantile",
        type=float,
        default=0.5,
        help="Quantile model to analyze (default: 0.5)"
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=15,
        help="Number of top features to track (default: 15)"
    )
    
    args = parser.parse_args()
    
    try:
        # Load feature names
        feature_names = load_feature_names(args.model)
        
        # Load model
        model = load_model(args.model, args.quantile)
        if model is None:
            logger.error("Failed to load model")
            return 1
        
        # Extract feature importance
        current_importance = extract_feature_importance(model, feature_names, args.top_k)
        if not current_importance:
            logger.error("Failed to extract feature importance")
            return 1
        
        # Update history
        history = update_importance_history(current_importance, args.history)
        
        # Analyze stability
        stability_analysis = analyze_importance_stability(history)
        
        # Generate report
        generate_html_report(current_importance, stability_analysis, args.output)
        
        logger.info("Feature importance tracking completed successfully")
        return 0
        
    except Exception as e:
        logger.error(f"Feature importance tracking failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
