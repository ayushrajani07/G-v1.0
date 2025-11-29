import os
from src.web.api.ml_ensemble import create_app, _forecast_semaphore


def test_backpressure_rejection():
    os.environ['FORECAST_MAX_CONCURRENCY'] = '1'
    app = create_app()
    client = app.test_client()
    # Acquire the only permit to force rejection
    if _forecast_semaphore:
        _forecast_semaphore.acquire(blocking=False)
    resp = client.get('/api/ml/ensemble/forecast?index=NIFTY&horizon=60')
    assert resp.status_code == 429
    data = resp.get_json()
    assert data.get('backpressure') is True
    assert 'rejections' in data
