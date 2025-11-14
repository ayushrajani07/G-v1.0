import builtins
from fastapi.testclient import TestClient

from src.web.dashboard.app import app


def test_alerts_file_write_failure_records_error_and_500(monkeypatch, tmp_path):
    client = TestClient(app)

    # Ensure logs directory exists to avoid testing mkdir path here
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Change CWD so the route writes to our temp logs directory
    monkeypatch.chdir(tmp_path)

    real_open = builtins.open

    def fake_open(path, *args, **kwargs):  # type: ignore[override]
        try:
            p = str(path)
        except Exception:
            p = str(path)
        if p.endswith("alerts.log"):
            raise OSError("simulated open failure for alerts.log")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)

    payload = {
        "status": "firing",
        "alerts": [
            {
                "labels": {"alertname": "TestAlert", "severity": "critical"},
                "annotations": {"summary": "S", "description": "D"},
                "values": {"v": 1}
            }
        ],
    }

    resp = client.post("/api/alerts/file", json=payload)
    assert resp.status_code == 500

    # Verify recent errors contains our FILE_IO entry from this route
    resp2 = client.get("/api/errors/recent", params={"count": 10})
    assert resp2.status_code == 200
    data = resp2.json()
    errs = data.get("errors", [])
    assert isinstance(errs, list)
    # Find an error from our function with expected category and context
    match = []
    for e in errs:
        if e.get("function") != "alert_webhook_file":
            continue
        if str(e.get("category", "")).lower().find("file") < 0:
            continue
        fpath = str(e.get("context", {}).get("file", ""))
        fpath_norm = fpath.replace("\\", "/")
        if fpath_norm.endswith("logs/alerts.log"):
            match.append(e)
    assert match, f"expected FILE_IO error from alert_webhook_file; got: {errs}"
