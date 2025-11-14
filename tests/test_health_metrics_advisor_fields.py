from fastapi.testclient import TestClient
from src.web.dashboard.app import app

client = TestClient(app)


def test_health_metrics_includes_advisor_fields_no_data():
    # With no metrics snapshot cache in TestClient app state, endpoint should still include advisor fields
    r = client.get('/health/metrics')
    # Either 503 no_data or 200 with data depending on test environment; both must include keys
    assert r.status_code in (200, 503)
    data = r.json()
    assert 'advisor_integrity_ok' in data
    assert 'advisor_age_minutes' in data
    # Values can be None when no advisor probe has run yet
    # Only assert type if present
    if data['advisor_integrity_ok'] is not None:
        assert isinstance(data['advisor_integrity_ok'], (int, float))
    if data['advisor_age_minutes'] is not None:
        assert isinstance(data['advisor_age_minutes'], (int, float))
