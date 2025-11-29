import os
from src.web.api.ml_ensemble import create_app


def test_ml_quality_metrics_export(monkeypatch):
    os.environ['ENABLE_ML_QUALITY_METRICS'] = '1'
    app = create_app()
    client = app.test_client()
    # Record residual to have non-zero stats
    client.post('/api/ml/ensemble/residuals', json={'index': 'NIFTY', 'horizon': 60, 'forecast_p50': 100.0, 'actual': 102.0})
    resp = client.get('/api/ml/ensemble/forecast?index=NIFTY&horizon=60')
    assert resp.status_code == 200
    try:
        from prometheus_client import REGISTRY
    except ImportError:  # metrics optional
        return
    # Verify at least one weight sample exists
    gbrt = REGISTRY.get_sample_value('g6_ml_ensemble_weight', labels={'component': 'gbrt', 'index': 'NIFTY', 'horizon': '60'})
    retrieval = REGISTRY.get_sample_value('g6_ml_ensemble_weight', labels={'component': 'retrieval', 'index': 'NIFTY', 'horizon': '60'})
    trend = REGISTRY.get_sample_value('g6_ml_residual_trend_ratio', labels={'index': 'NIFTY', 'horizon': '60'})
    assert gbrt is not None and retrieval is not None and trend is not None
