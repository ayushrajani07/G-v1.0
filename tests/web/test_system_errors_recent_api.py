from fastapi.testclient import TestClient

from src.web.dashboard.app import app
from src.error_handling import initialize_error_handler, get_error_handler, ErrorCategory, ErrorSeverity


def test_errors_recent_filters_by_category_and_severity():
    h = initialize_error_handler(max_errors=200)
    h.clear_errors()
    # Seed some errors
    try:
        raise OSError("file write failed A")
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.FILE_IO,
            severity=ErrorSeverity.LOW,
            component="seed",
            function_name="seedA",
            message="A",
        )
    try:
        raise RuntimeError("other error")
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.UNKNOWN,
            severity=ErrorSeverity.MEDIUM if hasattr(ErrorSeverity, 'MEDIUM') else ErrorSeverity.LOW,
            component="seed",
            function_name="seedB",
            message="B",
        )
    try:
        raise OSError("file write failed C")
    except Exception as e:
        get_error_handler().handle_error(
            e,
            category=ErrorCategory.FILE_IO,
            severity=ErrorSeverity.LOW,
            component="seed",
            function_name="seedC",
            message="C",
        )

    client = TestClient(app)
    # Filter for file_io + low; expect at least two entries seeded above
    r = client.get("/api/errors/recent", params={"count": 10, "category": "FILE_IO", "severity": "LOW"})
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, dict) and isinstance(data.get("errors"), list)
    arr = data["errors"]
    # Should contain the two FILE_IO LOW entries we seeded
    cats = [d.get("category") for d in arr]
    sevs = [d.get("severity") for d in arr]
    assert cats.count("FILE_IO") >= 2 or cats.count("file_io") >= 2
    assert sevs.count("LOW") >= 2 or sevs.count("low") >= 2


def test_errors_recent_count_cap_and_default():
    h = initialize_error_handler(max_errors=10_000)
    h.clear_errors()
    # Seed more than cap to ensure server-side cap won't break shape
    for i in range(250):
        try:
            raise OSError(f"E{i}")
        except Exception as e:
            get_error_handler().handle_error(
                e,
                category=ErrorCategory.FILE_IO,
                severity=ErrorSeverity.LOW,
                component="seed",
                function_name="seedLoop",
                message=f"E{i}",
            )
    client = TestClient(app)
    # Request beyond cap (500) should still return at most 200
    r = client.get("/api/errors/recent", params={"count": 500})
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, dict) and isinstance(data.get("errors"), list)
    assert len(data["errors"]) <= 200
