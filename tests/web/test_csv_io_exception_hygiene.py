from pathlib import Path
import builtins

from src.web.dashboard.core.csv_io import load_csv_rows_full
from src.error_handling import get_error_handler


def test_load_csv_rows_full_failure_records_error(monkeypatch, tmp_path):
    # Arrange: path that will trigger our fake open failure
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("header1,header2\n", encoding="utf-8")

    # Simulate failure only for this path by patching Path.open (reliable across layers)
    real_path_open = Path.open

    def fake_path_open(self, *args, **kwargs):  # type: ignore[override]
        p = str(self)
        if p.endswith("bad.csv"):
            raise OSError("simulated read failure for bad.csv")
        return real_path_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fake_path_open)

    # Clear recent errors for deterministic assertion
    eh = get_error_handler()
    try:
        eh.clear_errors()
    except Exception:
        pass

    # Act
    rows = load_csv_rows_full(csv_path)

    # Assert: behavior preserved (empty list) and error recorded
    assert rows == []

    recent = eh.get_recent_errors(5)
    assert recent, "expected a recorded error for failed CSV read"
    last = recent[-1]
    assert getattr(last, "function_name", None) == "load_csv_rows_full"
    assert str(getattr(last, "category", "")).lower().find("file") >= 0
    ctx = getattr(last, "context", {}) or {}
    # Normalize separators for Windows
    assert str(ctx.get("path", "")).replace("\\", "/").endswith("bad.csv")
