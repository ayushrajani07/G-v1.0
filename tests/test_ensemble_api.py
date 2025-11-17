from fastapi.testclient import TestClient
from src.web.dashboard.app import app

client = TestClient(app)

def test_forecast_route_present_in_openapi():
    spec = app.openapi()
    assert "/api/ml/ensemble/forecast" in spec.get("paths", {}), "Forecast path missing in OpenAPI"

def test_forecast_endpoint_returns_expected_structure():
    r = client.get("/api/ml/ensemble/forecast", params={"index": "NIFTY"})
    assert r.status_code == 200
    data = r.json()
    assert data["index"] == "NIFTY"
    assert "forecast" in data
    assert "p50" in data["forecast"]
    assert "metadata" in data
    assert isinstance(data["metadata"].get("components_used"), list)

def test_diag_routes_lists_forecast():
    r = client.get("/__diag/routes")
    assert r.status_code == 200
    paths = r.json().get("paths", [])
    assert "/api/ml/ensemble/forecast" in paths

def test_forecast_horizon_validation():
    r_bad = client.get("/api/ml/ensemble/forecast", params={"index": "NIFTY", "horizon": 0})
    assert r_bad.status_code == 422  # horizon must be >=1
    r_ok = client.get("/api/ml/ensemble/forecast", params={"index": "NIFTY", "horizon": 120})
    assert r_ok.status_code == 200

def test_forecast_missing_index_param():
    r = client.get("/api/ml/ensemble/forecast")
    assert r.status_code == 422  # missing required 'index' parameter
