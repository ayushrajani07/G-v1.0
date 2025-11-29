from src.web.api.ml_ensemble import create_app


def test_weight_volatility_accumulates():
    app = create_app()
    client = app.test_client()
    # Invoke multiple forecasts to accumulate history
    for i in range(8):
        # Manipulate residuals to shift weights slightly
        client.post('/api/ml/ensemble/residuals', json={
            'index': 'NIFTY', 'horizon': 60, 'forecast_p50': 100.0, 'actual': 100.0 + i*0.2
        })
        f = client.get('/api/ml/ensemble/forecast?index=NIFTY&horizon=60')
        assert f.status_code == 200
    # Regime audit should reflect non-zero volatility (after multiple samples)
    r = client.get('/api/ml/ensemble/regime_audit?index=NIFTY&horizon=60')
    data = r.get_json()
    gv = data['regime']['weight_volatility_gbrt']
    rv = data['regime']['weight_volatility_retrieval']
    assert gv >= 0.0 and rv >= 0.0
    # At least one should be >0 (weights shifted due to residual trend changes)
    assert (gv > 0.0) or (rv > 0.0)
