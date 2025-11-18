import os
import time


def test_drift_health_gauges_present():
    """Ensure drift evaluator sets health gauges (last_eval, alert_count)."""
    # Enable drift monitoring with short interval
    os.environ['G6_DRIFT_ENABLE'] = '1'
    os.environ['G6_DRIFT_EVAL_INTERVAL_SEC'] = '1'
    os.environ['G6_DRIFT_INDICES'] = 'NIFTY'

    from src.web.dashboard import drift_metrics

    # Start evaluator thread
    drift_metrics.start_drift_evaluator()
    try:
        # Allow first evaluation to run
        time.sleep(0.25)
        reg = drift_metrics.get_registry()
        assert reg is not None, 'Prometheus registry not initialized'

        last_eval_ms = None
        alert_count = None
        for fam in reg.collect():  # type: ignore[attr-defined]
            name = getattr(fam, 'name', None)
            if name == 'g6_drift_last_eval_ms':
                for s in fam.samples:
                    if s.labels.get('index') == 'NIFTY':
                        last_eval_ms = float(s.value)
                        break
            elif name == 'g6_drift_alert_count':
                for s in fam.samples:
                    if s.labels.get('index') == 'NIFTY':
                        alert_count = float(s.value)
                        break

        assert last_eval_ms is not None, 'g6_drift_last_eval_ms missing for NIFTY'
        assert alert_count is not None, 'g6_drift_alert_count missing for NIFTY'
        # Last eval should be within last 10 seconds
        now_ms = time.time() * 1000.0
        assert now_ms - last_eval_ms < 10_000, 'last eval timestamp too old'
        # Alert count should be >= 0
        assert alert_count >= 0
    finally:
        drift_metrics.stop_drift_evaluator()