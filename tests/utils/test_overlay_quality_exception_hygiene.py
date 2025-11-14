from datetime import date
from pathlib import Path

from src.utils.overlay_quality import write_quality_report
from src.error_handling import initialize_error_handler, get_error_handler, ErrorCategory, ErrorSeverity


def test_overlay_quality_write_failure_routed(monkeypatch, tmp_path: Path):
    # Force write failure by pointing to a path that will fail on write
    def write_text_fail(self, *args, **kwargs):
        raise OSError('simulated overlay write failure')

    monkeypatch.setattr(Path, 'write_text', write_text_fail, raising=True)

    h = initialize_error_handler(max_errors=100)
    h.clear_errors()

    before = len(get_error_handler().get_recent_errors(1000))
    out = write_quality_report(tmp_path, date(2025, 11, 13), 'Thursday', {'issues': []})
    after = len(get_error_handler().get_recent_errors(1000))

    assert isinstance(out, Path)
    assert after == before + 1
    err = get_error_handler().get_recent_errors(1)[-1]
    assert err.category in (ErrorCategory.FILE_IO, getattr(ErrorCategory, 'FILE_IO'))
    assert err.severity in (ErrorSeverity.LOW, getattr(ErrorSeverity, 'LOW'))
