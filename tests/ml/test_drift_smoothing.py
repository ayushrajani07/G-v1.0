import math
import os
import time
from src.ml.drift_monitor import DriftMonitor


def test_smoothing_reduces_initial_spike(monkeypatch):
    monkeypatch.setenv('G6_DRIFT_ENABLE_SMOOTHING','1')
    monkeypatch.setenv('G6_DRIFT_SMOOTHING_HALF_LIFE','4')
    m = DriftMonitor(baseline_days=1, recent_rows=50)
    # Baseline: centered at 0
    baseline = {
        'features': {
            'feat': {
                'values': [0.0]*200,
                'mean': 0.0,
                'std': 0.001,
                'min': 0.0,
                'max': 0.0,
                'quantiles': [0.0 for _ in range(m.num_bins+1)]
            }
        }
    }
    # First recent: large shift
    recent1 = {
        'features': {
            'feat': {
                'values': [5.0]*200,
                'mean': 5.0,
                'std': 0.001,
                'min': 5.0,
                'max': 5.0,
                'quantiles': [0.0 for _ in range(m.num_bins+1)]
            }
        }
    }
    metrics1 = m.calculate_drift_metrics(baseline, recent1)
    psi_raw_1 = metrics1['feat']['psi_raw']
    psi_smoothed_1 = metrics1['feat']['psi']
    assert psi_smoothed_1 <= psi_raw_1, 'smoothed PSI should not exceed raw on first spike'
    # Second recent: same shift, smoothing should move closer to raw
    metrics2 = m.calculate_drift_metrics(baseline, recent1)
    psi_smoothed_2 = metrics2['feat']['psi']
    assert psi_smoothed_2 >= psi_smoothed_1 - 1e-9, 'second smoothed PSI should not decrease'
    # Raw remains identical
    assert metrics2['feat']['psi_raw'] == psi_raw_1


def test_quantile_cache_reuse(monkeypatch):
    monkeypatch.setenv('G6_DRIFT_ENABLE_SMOOTHING','0')
    m = DriftMonitor(baseline_days=1, recent_rows=50)
    # Build baseline via compute_feature_distributions (populates cache)
    baseline = m.compute_feature_distributions('NIFTY', m.baseline_days, features=['tp'])
    assert 'tp' in m._quantile_cache and m._quantile_cache['tp'], 'quantile cache not populated'
    # Recent distribution should not recompute quantiles; quantiles may be None or reused
    recent = m.compute_feature_distributions('NIFTY', 0, features=['tp'])
    # If quantiles reused present else None - ensure no recompute by verifying baseline edges unchanged
    assert m._quantile_cache['tp'] == baseline['features']['tp']['quantiles']
    # When calling calculate_drift_metrics quantile edges retrieved from baseline feature
    metrics = m.calculate_drift_metrics(baseline, recent)
    assert 'tp' in metrics
