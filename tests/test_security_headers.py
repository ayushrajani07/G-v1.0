from src.web.api.ml_ensemble import create_app


def test_security_headers_present():
    app = create_app()
    app.config['TESTING'] = True
    client = app.test_client()
    resp = client.get('/health')
    assert resp.status_code == 200
    headers = resp.headers
    for h in [
        'Strict-Transport-Security',
        'X-Content-Type-Options',
        'X-Frame-Options',
        'Referrer-Policy',
        'Content-Security-Policy'
    ]:
        assert h in headers, f"Missing header {h}"
    assert headers['X-Content-Type-Options'] == 'nosniff'
    assert headers['X-Frame-Options'] == 'DENY'
