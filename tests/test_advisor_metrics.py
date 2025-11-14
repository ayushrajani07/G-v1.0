from __future__ import annotations

import math
import pytest

try:
    from fastapi.testclient import TestClient  # type: ignore
except Exception:  # pragma: no cover
    TestClient = None  # type: ignore

FASTAPI_AVAILABLE = TestClient is not None


@pytest.mark.skipif(not FASTAPI_AVAILABLE, reason="fastapi test client not available")
def test_advisor_metrics_gauges_populate_and_update():
    """Ensure advisor integrity and age gauges are created and updated after endpoint calls."""
    from src.web.dashboard.app import app  # type: ignore
    from src.metrics import get_metrics_singleton  # type: ignore

    assert TestClient is not None
    client = TestClient(app)  # type: ignore[call-arg]

    # Trigger integrity and age endpoints
    r1 = client.get("/api/diag/advisor_integrity")
    assert r1.status_code in (200, 503)  # integrity may fail in extreme fallback scenarios
    r2 = client.get("/api/ml/universal_advisor/generated_at_age_minutes")
    assert r2.status_code == 200

    reg = get_metrics_singleton()
    assert reg is not None

    # Integrity gauge
    assert hasattr(reg, 'advisor_integrity_ok')
    integrity_val = None
    try:
        fams = list(reg.advisor_integrity_ok.collect())  # type: ignore[attr-defined]
        if fams and fams[0].samples:
            integrity_val = fams[0].samples[0].value
    except Exception:
        pass
    assert integrity_val in (0, 1)

    # Age gauge
    assert hasattr(reg, 'advisor_age_minutes')
    age_val = None
    try:
        fams2 = list(reg.advisor_age_minutes.collect())  # type: ignore[attr-defined]
        if fams2 and fams2[0].samples:
            age_val = fams2[0].samples[0].value
    except Exception:
        pass
    assert age_val is not None and isinstance(age_val, (int, float)) and not math.isnan(float(age_val)) and age_val >= 0
