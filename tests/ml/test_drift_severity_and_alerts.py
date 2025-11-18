import re
import json
from pathlib import Path

from src.ml.drift_monitor import DriftMonitor

# Synthetic helper to build baseline/recent windows

def _make_window(values, monitor: DriftMonitor):
    import numpy as np
    arr = np.array(values)
    return {
        'features': {
            'feat': {
                'values': list(map(float, arr)),
                'mean': float(arr.mean()),
                'std': float(arr.std(ddof=0)),
                'min': float(arr.min()),
                'max': float(arr.max()),
                'quantiles': list(map(float, np.quantile(arr, np.linspace(0,1,monitor.num_bins+1))))
            }
        }
    }

def test_severity_classification_stable():
    m = DriftMonitor(baseline_days=1, recent_rows=100)
    baseline_vals = [0.0]*50 + [0.1]*50  # low variance
    recent_vals = list(baseline_vals)  # identical
    baseline = _make_window(baseline_vals, m)
    recent = _make_window(recent_vals, m)
    metrics = m.calculate_drift_metrics(baseline, recent)
    assert metrics['feat']['severity'] == 'stable'


def test_severity_classification_critical_mean_shift():
    m = DriftMonitor(baseline_days=1, recent_rows=100)
    import random
    random.seed(0)
    baseline_vals = [random.gauss(0,1) for _ in range(500)]
    recent_vals = [v + 5 for v in baseline_vals]  # large mean shift
    baseline = _make_window(baseline_vals, m)
    recent = _make_window(recent_vals, m)
    metrics = m.calculate_drift_metrics(baseline, recent)
    assert metrics['feat']['severity'] == 'critical'
    assert any('mean_z_crit' in r for r in metrics['feat']['reasons'])


def test_severity_classification_actionable():
    m = DriftMonitor(baseline_days=1, recent_rows=100)
    import random
    random.seed(1)
    baseline_vals = [random.gauss(0,1) for _ in range(500)]
    # moderate mean shift ~2.5 std dev (actionable)
    recent_vals = [v + 2.5 for v in baseline_vals]
    baseline = _make_window(baseline_vals, m)
    recent = _make_window(recent_vals, m)
    metrics = m.calculate_drift_metrics(baseline, recent)
    sev = metrics['feat']['severity']
    assert sev in ('actionable','critical'), f"expected actionable or critical, got {sev}"  # allow critical if PSI escalates


def test_alert_rules_file_contains_severity_gauge():
    path = Path('prometheus_alerts_drift.yml')
    assert path.exists(), 'prometheus_alerts_drift.yml missing'
    text = path.read_text(encoding='utf-8')
    assert 'g6_feature_drift_severity' in text, 'severity gauge not referenced in alert rules'
    # Basic check for critical alert name
    assert re.search(r'alert:\s+MLFeatureDriftCritical', text), 'Critical drift alert missing'

