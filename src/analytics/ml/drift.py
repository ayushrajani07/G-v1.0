"""
Drift Monitoring Module.

Provides functionality to detect:
1. Data Drift: Changes in feature distributions (using PSI).
2. Concept Drift: Changes in model performance (using MAE/RMSE).

Stores drift records in a JSONL file for long-term tracking.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class DriftMonitor:
    """Monitor for data and concept drift."""

    def __init__(self, storage_path: Union[str, Path] = "data/ml/drift/drift_history.jsonl"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def compute_psi(self, expected: np.ndarray, actual: np.ndarray, buckets: int = 10) -> float:
        """Compute Population Stability Index (PSI) for a single feature.
        
        Args:
            expected: Reference distribution (training data).
            actual: Current distribution (production data).
            buckets: Number of buckets for histogram.
            
        Returns:
            PSI value.
        """
        try:
            # Define breakpoints based on expected distribution
            breakpoints = np.linspace(0, 100, buckets + 1)
            breakpoints = np.percentile(expected, breakpoints)
            
            # Handle duplicate breakpoints (e.g., for sparse data)
            breakpoints = np.unique(breakpoints)
            if len(breakpoints) < 2:
                return 0.0
            
            # Calculate frequencies
            expected_percents = np.histogram(expected, breakpoints)[0] / len(expected)
            actual_percents = np.histogram(actual, breakpoints)[0] / len(actual)
            
            # Avoid division by zero
            expected_percents = np.where(expected_percents == 0, 0.0001, expected_percents)
            actual_percents = np.where(actual_percents == 0, 0.0001, actual_percents)
            
            # Calculate PSI
            psi = np.sum((actual_percents - expected_percents) * np.log(actual_percents / expected_percents))
            return float(psi)
        except Exception as e:
            logger.warning(f"Failed to compute PSI: {e}")
            return 0.0

    def check_data_drift(
        self, 
        reference_df: pd.DataFrame, 
        current_df: pd.DataFrame, 
        features: List[str]
    ) -> Dict[str, float]:
        """Check data drift for multiple features using PSI.
        
        Args:
            reference_df: Training data.
            current_df: Production data.
            features: List of features to check.
            
        Returns:
            Dictionary of {feature: psi_value}.
        """
        drift_metrics = {}
        for feature in features:
            if feature in reference_df.columns and feature in current_df.columns:
                psi = self.compute_psi(
                    reference_df[feature].dropna().values,
                    current_df[feature].dropna().values
                )
                drift_metrics[feature] = psi
            else:
                logger.warning(f"Feature {feature} not found in both datasets")
        
        return drift_metrics

    def check_concept_drift(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray
    ) -> Dict[str, float]:
        """Check concept drift by calculating error metrics.
        
        Args:
            y_true: Actual values.
            y_pred: Predicted values.
            
        Returns:
            Dictionary of error metrics (MAE, RMSE, MAPE).
        """
        try:
            mae = np.mean(np.abs(y_true - y_pred))
            rmse = np.sqrt(np.mean((y_true - y_pred) ** 2))
            
            # MAPE (handle division by zero)
            mask = y_true != 0
            mape = np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100 if np.any(mask) else 0.0
            
            return {
                "mae": float(mae),
                "rmse": float(rmse),
                "mape": float(mape)
            }
        except Exception as e:
            logger.error(f"Failed to compute concept drift: {e}")
            return {}

    def analyze_residuals(self, residuals: np.ndarray) -> Dict[str, float]:
        """Analyze forecast residuals for bias and variance shifts.
        
        Args:
            residuals: Array of forecast residuals (y_true - y_pred).
            
        Returns:
            Dictionary of residual metrics.
        """
        try:
            if len(residuals) == 0:
                return {}
                
            mean_residual = np.mean(residuals)
            std_residual = np.std(residuals)
            
            # Skewness (simple approximation)
            skewness = 0.0
            if std_residual > 0:
                skewness = np.mean(((residuals - mean_residual) / std_residual) ** 3)
            
            return {
                "residual_mean": float(mean_residual),
                "residual_std": float(std_residual),
                "residual_skew": float(skewness)
            }
        except Exception as e:
            logger.error(f"Failed to analyze residuals: {e}")
            return {}

    def check_alerts(
        self, 
        metrics: Dict[str, Any], 
        thresholds: Optional[Dict[str, float]] = None
    ) -> List[str]:
        """Check metrics against thresholds and generate alerts.
        
        Args:
            metrics: Dictionary of metrics (from check_concept_drift or analyze_residuals).
            thresholds: Dictionary of {metric_name: threshold_value}.
            
        Returns:
            List of alert messages.
        """
        alerts = []
        if not thresholds:
            # Default thresholds
            thresholds = {
                "mae": 50.0,
                "mape": 5.0,
                "residual_mean": 20.0, # Absolute bias threshold
                "psi": 0.2
            }
            
        for metric, value in metrics.items():
            if metric in thresholds:
                threshold = thresholds[metric]
                
                # Handle absolute checks for signed metrics like residual_mean
                check_value = abs(value) if metric in ["residual_mean", "residual_skew"] else value
                
                if check_value > threshold:
                    alerts.append(f"Alert: {metric} ({value:.4f}) exceeded threshold ({threshold})")
                    
        return alerts

    def save_drift_record(
        self,
        index: str,
        timestamp: float,
        data_drift: Dict[str, float],
        concept_drift: Dict[str, float],
        metadata: Optional[Dict[str, Any]] = None,
        alerts: Optional[List[str]] = None
    ) -> None:
        """Save drift metrics to long-term storage.
        
        Args:
            index: Index name (e.g., NIFTY).
            timestamp: Timestamp of the check.
            data_drift: Data drift metrics (PSI).
            concept_drift: Concept drift metrics (Error rates).
            metadata: Additional metadata.
            alerts: List of triggered alerts.
        """
        record = {
            "timestamp": timestamp,
            "iso_timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp)),
            "index": index,
            "data_drift": data_drift,
            "concept_drift": concept_drift,
            "metadata": metadata or {},
            "alerts": alerts or []
        }
        
        try:
            with open(self.storage_path, "a") as f:
                f.write(json.dumps(record) + "\n")
            logger.info(f"Saved drift record for {index}")
        except Exception as e:
            logger.error(f"Failed to save drift record: {e}")

    def load_history(self, index: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Load recent drift history.
        
        Args:
            index: Filter by index name.
            limit: Max records to return.
            
        Returns:
            List of drift records.
        """
        records = []
        if not self.storage_path.exists():
            return records
            
        try:
            with open(self.storage_path, "r") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                        if index and rec.get("index") != index:
                            continue
                        records.append(rec)
                    except json.JSONDecodeError:
                        continue
            
            # Return last N records
            return records[-limit:]
        except Exception as e:
            logger.error(f"Failed to load history: {e}")
            return []

    def get_long_term_accuracy(self, index: str, window: int = 30) -> Dict[str, float]:
        """Calculate long-term accuracy metrics from history.
        
        Args:
            index: Index name.
            window: Number of recent records to consider.
            
        Returns:
            Dictionary with average metrics and trends.
        """
        history = self.load_history(index=index, limit=window)
        if not history:
            return {}
            
        maes = []
        mapes = []
        
        for record in history:
            cd = record.get("concept_drift", {})
            if "mae" in cd and cd["mae"] is not None and not np.isnan(cd["mae"]):
                maes.append(cd["mae"])
            if "mape" in cd and cd["mape"] is not None and not np.isnan(cd["mape"]):
                mapes.append(cd["mape"])
                
        if not maes:
            return {}
            
        avg_mae = np.mean(maes)
        avg_mape = np.mean(mapes) if mapes else 0.0
        
        # Calculate trend (slope of linear fit)
        mae_trend = 0.0
        if len(maes) > 1:
            x = np.arange(len(maes))
            slope, _ = np.polyfit(x, maes, 1)
            mae_trend = slope
            
        return {
            "avg_mae": float(avg_mae),
            "avg_mape": float(avg_mape),
            "mae_trend": float(mae_trend),
            "samples_count": len(maes)
        }
