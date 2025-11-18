import time
from pathlib import Path

from src.web.dashboard import drift_metrics
from src.ml.drift_monitor import DriftMonitor

def test_monitor_reuse_and_duration_gauge(monkeypatch):
    # Enable drift evaluator via env
    monkeypatch.setenv('G6_DRIFT_ENABLE','1')
    monkeypatch.setenv('G6_DRIFT_INDICES','NIFTY')
    monkeypatch.setenv('G6_DRIFT_EVAL_INTERVAL_SEC','2')

    # Start evaluator
    drift_metrics.start_drift_evaluator()
    # Allow a couple of cycles
    time.sleep(4.5)
    reg = drift_metrics.get_registry()
    assert reg is not None
    # Check duration gauge presence
    duration_samples = [fam for fam in reg.collect() if getattr(fam,'name',None)=='g6_drift_eval_duration_ms']
    assert duration_samples, 'g6_drift_eval_duration_ms gauge missing'
    # Ensure at least one sample value > 0
    vals = []
    for fam in duration_samples:
        for s in fam.samples:
            vals.append(s.value)
    assert any(v > 0 for v in vals), 'evaluation duration not recorded'
    drift_metrics.stop_drift_evaluator()


def test_alert_rules_generalization():
    path = Path('prometheus_alerts_drift.yml')
    assert path.exists(), 'prometheus_alerts_drift.yml missing'
    text = path.read_text(encoding='utf-8')
    assert 'sum by (index) (g6_feature_drift_severity==3) > 5' in text, 'Broad critical drift rule not generalized'
    assert 'increase(sum by (index) (g6_feature_drift_severity==3)' in text, 'Severity spike rule not generalized'
