"""
Tests for A/B Testing Script (Phase 5)
"""

from __future__ import annotations

import numpy as np
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.ml.ab_test_ensemble import (
    calculate_metrics,
    calculate_improvement
)


def test_calculate_metrics_valid_data():
    """Test metric calculation with valid data."""
    actuals = np.array([100.0, 110.0, 105.0, 115.0, 108.0])
    preds_p50 = np.array([98.0, 112.0, 104.0, 113.0, 110.0])
    preds_p10 = np.array([90.0, 104.0, 96.0, 105.0, 102.0])
    preds_p90 = np.array([106.0, 120.0, 112.0, 121.0, 118.0])
    
    metrics = calculate_metrics(actuals, preds_p50, preds_p10, preds_p90)
    
    assert "mae" in metrics
    assert "rmse" in metrics
    assert "mape" in metrics
    assert "correlation" in metrics
    assert "coverage" in metrics
    assert "avg_band_width" in metrics
    assert "n_samples" in metrics
    
    assert metrics["n_samples"] == 5
    assert metrics["mae"] > 0
    assert metrics["rmse"] > 0
    assert metrics["coverage"] >= 0 and metrics["coverage"] <= 100


def test_calculate_metrics_with_nan():
    """Test metric calculation with NaN values."""
    actuals = np.array([100.0, np.nan, 105.0, 115.0])
    preds_p50 = np.array([98.0, 112.0, np.nan, 113.0])
    preds_p10 = np.array([90.0, 104.0, 96.0, 105.0])
    preds_p90 = np.array([106.0, 120.0, 112.0, 121.0])
    
    metrics = calculate_metrics(actuals, preds_p50, preds_p10, preds_p90)
    
    # Should only have 2 valid samples
    assert metrics["n_samples"] == 2


def test_calculate_metrics_empty_data():
    """Test metric calculation with empty data."""
    actuals = np.array([])
    preds_p50 = np.array([])
    preds_p10 = np.array([])
    preds_p90 = np.array([])
    
    metrics = calculate_metrics(actuals, preds_p50, preds_p10, preds_p90)
    
    assert metrics["n_samples"] == 0
    assert np.isnan(metrics["mae"])


def test_calculate_improvement():
    """Test improvement calculation."""
    metrics_a = {
        "mae": 2.0,
        "rmse": 3.0,
        "mape": 5.0,
        "correlation": 0.9,
        "coverage": 82.0,
        "avg_band_width": 20.0
    }
    
    metrics_b = {
        "mae": 2.5,
        "rmse": 3.5,
        "mape": 6.0,
        "correlation": 0.85,
        "coverage": 80.0,
        "avg_band_width": 22.0
    }
    
    improvements = calculate_improvement(metrics_a, metrics_b)
    
    # A should be better (lower MAE)
    assert improvements["mae_improvement_pct"] > 0
    assert improvements["rmse_improvement_pct"] > 0
    assert improvements["correlation_improvement_abs"] > 0


def test_calculate_coverage():
    """Test coverage calculation."""
    actuals = np.array([100.0, 110.0, 105.0, 115.0, 108.0])
    preds_p50 = np.array([100.0, 110.0, 105.0, 115.0, 108.0])  # Perfect predictions
    preds_p10 = np.array([95.0, 105.0, 100.0, 110.0, 103.0])
    preds_p90 = np.array([105.0, 115.0, 110.0, 120.0, 113.0])
    
    metrics = calculate_metrics(actuals, preds_p50, preds_p10, preds_p90)
    
    # All actuals should be within bands
    assert metrics["coverage"] == 100.0


def test_zero_division_protection():
    """Test MAPE calculation with zero actuals."""
    actuals = np.array([0.0, 100.0, 0.0])
    preds_p50 = np.array([5.0, 95.0, 10.0])
    preds_p10 = np.array([0.0, 90.0, 5.0])
    preds_p90 = np.array([10.0, 100.0, 15.0])
    
    metrics = calculate_metrics(actuals, preds_p50, preds_p10, preds_p90)
    
    # MAPE should be calculated only for non-zero actuals
    assert not np.isnan(metrics["mape"])
