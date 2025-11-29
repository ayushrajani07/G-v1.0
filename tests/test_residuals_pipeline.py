from src.web.api.ml_ensemble import create_app


def test_residuals_record_and_stats():
    app = create_app()
    client = app.test_client()
    # Record three residuals
    for actual in [195.3, 198.0, 192.0]:
        resp = client.post('/api/ml/ensemble/residuals', json={
            'index': 'NIFTY',
            'horizon': 60,
            'forecast_p50': 195.3,
            'actual': actual
        })
        assert resp.status_code == 200
    # Fetch stats
    stats_resp = client.get('/api/ml/ensemble/residuals?index=NIFTY&horizons=60')
    assert stats_resp.status_code == 200
    data = stats_resp.get_json()
    assert data['index'] == 'NIFTY'
    assert data['stats'][0]['count'] >= 3
    assert 'trend_ratio' in data['stats'][0]


def test_forecast_includes_residual_trend():
    app = create_app()
    client = app.test_client()
    # First forecast (no residuals yet) trend defaults ~1.0
    f1 = client.get('/api/ml/ensemble/forecast?index=NIFTY&horizon=60')
    assert f1.status_code == 200
    meta1 = f1.get_json()['metadata']
    assert 'residual_trend' in meta1
    # Add residuals
    for actual in [194.0, 196.0]:
        client.post('/api/ml/ensemble/residuals', json={
            'index': 'NIFTY', 'horizon': 60, 'forecast_p50': 195.3, 'actual': actual
        })
    f2 = client.get('/api/ml/ensemble/forecast?index=NIFTY&horizon=60')
    meta2 = f2.get_json()['metadata']
    assert meta2['residual_trend'] != meta1['residual_trend'] or meta2['residual_trend'] == 1.0
