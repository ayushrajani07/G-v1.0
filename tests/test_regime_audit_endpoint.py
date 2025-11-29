from src.web.api.ml_ensemble import create_app


def test_regime_audit_endpoint_basic():
    app = create_app()
    client = app.test_client()
    # Ensure regime audit returns classification
    r = client.get('/api/ml/ensemble/regime_audit?index=NIFTY&horizon=60')
    assert r.status_code == 200
    data = r.get_json()
    assert 'regime' in data
    assert data['regime']['classification'] in {'stable','transition','volatile'}
    assert 0.0 <= data['regime']['score'] <= 1.0


def test_forecast_includes_regime_block():
    app = create_app()
    client = app.test_client()
    f = client.get('/api/ml/ensemble/forecast?index=NIFTY&horizon=60')
    assert f.status_code == 200
    data = f.get_json()
    assert 'regime' in data
    assert 'classification' in data['regime']
