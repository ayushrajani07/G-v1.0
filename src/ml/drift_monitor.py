"""
Drift Monitoring Module for ML Ensemble - Phase 10

Implements production-ready drift detection for feature distributions:
- PSI (Population Stability Index) computation with quantile binning
- KS (Kolmogorov-Smirnov) test for distribution shifts
- Mean/variance delta tracking with Z-score normalization
- Baseline persistence for long-term comparison

Part of Phase 10 continuous improvement objectives.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
try:  # Graceful fallback if SciPy not installed in minimal env
    from scipy import stats  # type: ignore
    _SCIPY_AVAILABLE = True
except Exception:  # pragma: no cover
    _SCIPY_AVAILABLE = False
    class _StatsFallback:
        @staticmethod
        def ks_2samp(a, b):  # type: ignore
            # Neutral values: no detected drift
            return 0.0, 1.0
    stats = _StatsFallback()  # type: ignore

_LOG = logging.getLogger(__name__)


class DriftMonitor:
    """Monitor feature distribution drift for ML models.
    
    Tracks drift metrics:
    - PSI (Population Stability Index): Measures distribution shift
    - KS test: Statistical test for distribution differences
    - Mean delta: Change in feature mean (Z-score normalized)
    - Variance delta: Change in feature variance
    - Alert flag: Combined threshold-based alert
    
    Environment Variables:
    - G6_DRIFT_BASELINE_DAYS: Number of days for baseline window (default 30)
    - G6_DRIFT_RECENT_ROWS: Number of recent rows for comparison (default 300)
    - G6_DRIFT_PSI_THRESHOLD: PSI threshold for alert (default 0.25)
    - G6_DRIFT_KS_PVALUE_THRESHOLD: KS p-value threshold (default 0.01)
    - G6_DRIFT_MEAN_ZSCORE_THRESHOLD: Mean delta Z-score threshold (default 3.0)
    """
    
    def __init__(
        self,
        baseline_days: int = 30,
        recent_rows: int = 300,
        psi_threshold: float = 0.25,
        ks_pvalue_threshold: float = 0.01,
        mean_zscore_threshold: float = 3.0,
        num_bins: int = 10,
    ):
        """Initialize drift monitor.
        
        Args:
            baseline_days: Number of days for baseline window
            recent_rows: Number of recent rows for comparison
            psi_threshold: PSI threshold for alert
            ks_pvalue_threshold: KS test p-value threshold (alert if below)
            mean_zscore_threshold: Mean delta Z-score threshold
            num_bins: Number of quantile bins for PSI calculation
        """
        self.baseline_days = baseline_days
        self.recent_rows = recent_rows
        self.psi_threshold = psi_threshold
        self.ks_pvalue_threshold = ks_pvalue_threshold
        self.mean_zscore_threshold = mean_zscore_threshold
        self.num_bins = num_bins
        
        # Get project root for baseline storage
        self.project_root = self._find_project_root()
        self.baseline_dir = self.project_root / "metrics" / "drift_baselines"
        self.baseline_dir.mkdir(parents=True, exist_ok=True)
        
        _LOG.info(
            f"DriftMonitor initialized: baseline={baseline_days}d, recent={recent_rows} rows, "
            f"psi_thresh={psi_threshold} scipy={'yes' if _SCIPY_AVAILABLE else 'no'}"
        )
    
    def _find_project_root(self) -> Path:
        """Find project root directory."""
        # Start from this file and walk up
        current = Path(__file__).resolve()
        for parent in [current.parent] + list(current.parents):
            if (parent / "src").exists() and (parent / "metrics").exists():
                return parent
        # Fallback
        return Path(__file__).resolve().parents[2]
    
    def compute_feature_distributions(
        self,
        index: str,
        lookback_days: int,
        features: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Compute feature distributions from historical data.
        
        This is a placeholder that should be integrated with actual data loading.
        In production, this would load from CSV files or database.
        
        Args:
            index: Index name (e.g., "NIFTY", "BANKNIFTY")
            lookback_days: Number of days to look back
            features: List of feature names to compute (None = all)
        
        Returns:
            Dictionary with feature distributions:
            {
                "index": str,
                "lookback_days": int,
                "window_start": str (ISO timestamp),
                "window_end": str (ISO timestamp),
                "features": {
                    "feature_name": {
                        "values": List[float],
                        "mean": float,
                        "std": float,
                        "min": float,
                        "max": float,
                        "quantiles": List[float],  # For binning
                    }
                }
            }
        """
        # Placeholder implementation
        # In production, replace with actual data loading from CSV/database
        _LOG.warning(
            f"compute_feature_distributions called with index={index}, "
            f"lookback_days={lookback_days}. Using placeholder data."
        )
        
        now = datetime.now(timezone.utc)
        window_end = now
        window_start = now - timedelta(days=lookback_days)
        
        # Default feature list (Phase 1 + Phase 7 features)
        if features is None:
            features = [
                "tp_residual_lag1", "tp_residual_lag2", "tp_residual_lag5",
                "index_return_1min", "index_return_5min", "avg_iv_level",
                "iv_percentile", "index_vol_percentile", "volume_ratio",
            ]
        
        feature_data = {}
        for feature_name in features:
            # Generate placeholder normal distribution
            # In production, load from actual data
            values = list(np.random.randn(1000) * 10 + 100)
            
            feature_data[feature_name] = {
                "values": values,
                "mean": float(np.mean(values)),
                "std": float(np.std(values)),
                "min": float(np.min(values)),
                "max": float(np.max(values)),
                "quantiles": [float(q) for q in np.quantile(values, np.linspace(0, 1, self.num_bins + 1))],
            }
        
        return {
            "index": index,
            "lookback_days": lookback_days,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "features": feature_data,
        }
    
    def calculate_drift_metrics(
        self,
        baseline_window: Dict[str, Any],
        recent_window: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        """Calculate drift metrics comparing baseline to recent window.
        
        Args:
            baseline_window: Baseline feature distributions (from compute_feature_distributions)
            recent_window: Recent feature distributions
        
        Returns:
            Dictionary mapping feature names to drift metrics:
            {
                "feature_name": {
                    "psi": float,
                    "ks_statistic": float,
                    "ks_pvalue": float,
                    "mean_delta": float,
                    "mean_delta_zscore": float,
                    "var_delta": float,
                    "alert_flag": bool,
                    "alert_reasons": List[str],
                    "bins": List[Dict],  # Bin-level PSI breakdown
                }
            }
        """
        baseline_features = baseline_window.get("features", {})
        recent_features = recent_window.get("features", {})
        
        # Find common features
        common_features = set(baseline_features.keys()) & set(recent_features.keys())
        
        if not common_features:
            _LOG.warning("No common features between baseline and recent windows")
            return {}
        
        drift_metrics = {}
        for feature_name in common_features:
            baseline_data = baseline_features[feature_name]
            recent_data = recent_features[feature_name]
            
            # Calculate PSI
            psi, bins = self._calculate_psi(
                baseline_data["values"],
                recent_data["values"],
                baseline_data.get("quantiles"),
            )
            
            # KS test (graceful fallback if SciPy missing)
            try:
                ks_stat, ks_pvalue = stats.ks_2samp(
                    baseline_data["values"],
                    recent_data["values"],
                )
            except Exception:  # pragma: no cover
                ks_stat, ks_pvalue = 0.0, 1.0
            
            # Mean delta
            baseline_mean = baseline_data["mean"]
            recent_mean = recent_data["mean"]
            mean_delta = recent_mean - baseline_mean
            
            # Z-score normalize mean delta
            baseline_std = baseline_data["std"]
            mean_delta_zscore = mean_delta / baseline_std if baseline_std > 0 else 0.0
            
            # Variance delta (ratio)
            baseline_var = baseline_std ** 2
            recent_var = recent_data["std"] ** 2
            var_delta = (recent_var - baseline_var) / baseline_var if baseline_var > 0 else 0.0
            
            # Determine alert status
            alert_flag, alert_reasons = self._check_alert_conditions(
                psi, ks_pvalue, mean_delta_zscore
            )
            
            drift_metrics[feature_name] = {
                "psi": float(psi),
                "ks_statistic": float(ks_stat),
                "ks_pvalue": float(ks_pvalue),
                "mean_delta": float(mean_delta),
                "mean_delta_zscore": float(mean_delta_zscore),
                "var_delta": float(var_delta),
                "alert_flag": alert_flag,
                "alert_reasons": alert_reasons,
                "bins": bins,
            }
        
        return drift_metrics
    
    def _calculate_psi(
        self,
        baseline_values: List[float],
        recent_values: List[float],
        quantile_edges: Optional[List[float]] = None,
    ) -> Tuple[float, List[Dict[str, Any]]]:
        """Calculate Population Stability Index (PSI).
        
        Args:
            baseline_values: Baseline distribution values
            recent_values: Recent distribution values
            quantile_edges: Pre-computed quantile bin edges (optional)
        
        Returns:
            Tuple of (psi_value, bins_detail)
            bins_detail is a list of dicts with bin-level PSI info
        """
        baseline_arr = np.array(baseline_values)
        recent_arr = np.array(recent_values)
        
        # Create bins using baseline quantiles
        if quantile_edges is None:
            quantile_edges = np.quantile(
                baseline_arr,
                np.linspace(0, 1, self.num_bins + 1)
            )
        
        # Handle edge case: ensure unique bin edges
        quantile_edges = np.unique(quantile_edges)
        if len(quantile_edges) < 2:
            # Not enough unique values for binning
            return 0.0, []
        
        # Digitize values into bins
        baseline_bins = np.digitize(baseline_arr, quantile_edges[1:-1])
        recent_bins = np.digitize(recent_arr, quantile_edges[1:-1])
        
        # Count proportions in each bin
        num_bins_actual = len(quantile_edges) - 1
        baseline_counts = np.bincount(baseline_bins, minlength=num_bins_actual)
        recent_counts = np.bincount(recent_bins, minlength=num_bins_actual)
        
        baseline_props = baseline_counts / len(baseline_arr)
        recent_props = recent_counts / len(recent_arr)
        
        # Calculate PSI per bin
        psi_total = 0.0
        bins_detail = []
        
        for i in range(num_bins_actual):
            baseline_prop = baseline_props[i]
            recent_prop = recent_props[i]
            
            # Avoid log(0) by adding small epsilon
            epsilon = 1e-10
            baseline_prop = max(baseline_prop, epsilon)
            recent_prop = max(recent_prop, epsilon)
            
            psi_bin = (recent_prop - baseline_prop) * np.log(recent_prop / baseline_prop)
            psi_total += psi_bin
            
            bins_detail.append({
                "bin": i,
                "baseline": float(baseline_prop),
                "recent": float(recent_prop),
                "psi": float(psi_bin),
            })
        
        return float(psi_total), bins_detail
    
    def _check_alert_conditions(
        self,
        psi: float,
        ks_pvalue: float,
        mean_delta_zscore: float,
    ) -> Tuple[bool, List[str]]:
        """Check if any alert conditions are triggered.
        
        Returns:
            Tuple of (alert_flag, reasons)
        """
        alert_flag = False
        alert_reasons = []
        
        if psi > self.psi_threshold:
            alert_flag = True
            alert_reasons.append(f"PSI {psi:.3f} > {self.psi_threshold}")
        
        if ks_pvalue < self.ks_pvalue_threshold:
            alert_flag = True
            alert_reasons.append(f"KS p-value {ks_pvalue:.4f} < {self.ks_pvalue_threshold}")
        
        if abs(mean_delta_zscore) > self.mean_zscore_threshold:
            alert_flag = True
            alert_reasons.append(
                f"Mean delta Z-score {abs(mean_delta_zscore):.2f} > {self.mean_zscore_threshold}"
            )
        
        return alert_flag, alert_reasons
    
    def load_baseline(self, index: str) -> Optional[Dict[str, Any]]:
        """Load baseline feature distributions from disk.
        
        Args:
            index: Index name (e.g., "NIFTY")
        
        Returns:
            Baseline distribution dict or None if not found
        """
        baseline_path = self.baseline_dir / f"{index}.json"
        
        if not baseline_path.exists():
            _LOG.info(f"No baseline found for {index} at {baseline_path}")
            return None
        
        try:
            with open(baseline_path, "r") as f:
                baseline = json.load(f)
            _LOG.info(f"Loaded baseline for {index} from {baseline_path}")
            return baseline
        except Exception as e:
            _LOG.error(f"Failed to load baseline for {index}: {e}")
            return None
    
    def save_baseline(self, index: str, baseline: Dict[str, Any]) -> bool:
        """Save baseline feature distributions to disk.
        
        Args:
            index: Index name (e.g., "NIFTY")
            baseline: Baseline distribution dict (from compute_feature_distributions)
        
        Returns:
            True if saved successfully, False otherwise
        """
        baseline_path = self.baseline_dir / f"{index}.json"
        
        try:
            # Add metadata
            baseline["saved_at"] = datetime.now(timezone.utc).isoformat()
            baseline["version"] = "1.0"
            
            with open(baseline_path, "w") as f:
                json.dump(baseline, f, indent=2)
            
            _LOG.info(f"Saved baseline for {index} to {baseline_path}")
            return True
        except Exception as e:
            _LOG.error(f"Failed to save baseline for {index}: {e}")
            return False
    
    def get_or_create_baseline(
        self,
        index: str,
        features: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Get existing baseline or create a new one.
        
        Args:
            index: Index name
            features: List of features to compute (None = all)
        
        Returns:
            Baseline distribution dict
        """
        # Try to load existing baseline
        baseline = self.load_baseline(index)
        
        if baseline is not None:
            return baseline
        
        # Create new baseline
        _LOG.info(f"Creating new baseline for {index} (last {self.baseline_days} days)")
        baseline = self.compute_feature_distributions(
            index=index,
            lookback_days=self.baseline_days,
            features=features,
        )
        
        # Save for future use
        self.save_baseline(index, baseline)
        
        return baseline


def create_drift_monitor_from_env() -> DriftMonitor:
    """Create DriftMonitor instance from environment variables.
    
    Environment Variables:
    - G6_DRIFT_BASELINE_DAYS: Baseline window in days (default 30)
    - G6_DRIFT_RECENT_ROWS: Recent window size (default 300)
    - G6_DRIFT_PSI_THRESHOLD: PSI alert threshold (default 0.25)
    - G6_DRIFT_KS_PVALUE_THRESHOLD: KS p-value threshold (default 0.01)
    - G6_DRIFT_MEAN_ZSCORE_THRESHOLD: Mean delta Z-score threshold (default 3.0)
    """
    baseline_days = int(os.environ.get("G6_DRIFT_BASELINE_DAYS", "30"))
    recent_rows = int(os.environ.get("G6_DRIFT_RECENT_ROWS", "300"))
    psi_threshold = float(os.environ.get("G6_DRIFT_PSI_THRESHOLD", "0.25"))
    ks_pvalue_threshold = float(os.environ.get("G6_DRIFT_KS_PVALUE_THRESHOLD", "0.01"))
    mean_zscore_threshold = float(os.environ.get("G6_DRIFT_MEAN_ZSCORE_THRESHOLD", "3.0"))
    
    return DriftMonitor(
        baseline_days=baseline_days,
        recent_rows=recent_rows,
        psi_threshold=psi_threshold,
        ks_pvalue_threshold=ks_pvalue_threshold,
        mean_zscore_threshold=mean_zscore_threshold,
    )
