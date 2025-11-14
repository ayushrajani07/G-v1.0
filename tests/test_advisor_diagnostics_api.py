from __future__ import annotations

import math
import pytest

try:
    from fastapi.testclient import TestClient  # type: ignore
except Exception:  # pragma: no cover
    TestClient = None  # type: ignore

FASTAPI_AVAILABLE = TestClient is not None


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="fastapi test client not available")
def test_advisor_integrity_endpoint_structure_and_presence():
    from src.web.dashboard.app import app  # type: ignore

    assert TestClient is not None
    client = TestClient(app)  # type: ignore[call-arg]

    resp = client.get("/api/diag/advisor_integrity")
    assert resp.status_code == 200
    data = resp.json()

    # Basic structure
    for key in ("pid", "generated_at_iso", "present", "routes", "expected_count", "found_count", "openapi_present"):
        assert key in data

    # Presence expectations
    assert data["present"] is True
    assert isinstance(data["routes"], list)
    # Expect the three universal advisor endpoints to be registered
    expected = {
        "/api/ml/universal_advisor",
        "/api/ml/universal_advisor/health",
        "/api/ml/universal_advisor/generated_at_age_minutes",
    }
    assert expected.issubset(set(data["routes"]))

    # Should report in OpenAPI as well
    assert data["openapi_present"] is True

    # Snapshot, when available
    snap = data.get("latest_snapshot")
    if snap:
        for k in ("pid", "ts_iso", "route_count", "openapi_has_advisor"):
            assert k in snap
        assert snap.get("openapi_has_advisor") in (True, False)


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="fastapi test client not available")
def test_universal_advisor_age_endpoint_is_fresh_and_structured():
    from src.web.dashboard.app import app  # type: ignore

    assert TestClient is not None
    client = TestClient(app)  # type: ignore[call-arg]

    resp = client.get("/api/ml/universal_advisor/generated_at_age_minutes")
    assert resp.status_code == 200
    payload = resp.json()

    assert "age_minutes" in payload
    age = payload["age_minutes"]
    assert isinstance(age, (int, float)) and not math.isnan(float(age))
    assert age >= 0

    # Optional fields
    if "generated_at" in payload:
        assert isinstance(payload["generated_at"], str)
    if "indices" in payload:
        assert isinstance(payload["indices"], list)
