from pathlib import Path
import builtins

from src.web.dashboard.routes.path_forecast import _save_calibration
from src.error_handling import initialize_error_handler, get_error_handler, ErrorCategory, ErrorSeverity


def test_save_calibration_write_failures_routed(monkeypatch, tmp_path: Path):
    # Redirect calibration dirs under tmp by monkeypatching helper
    from src.web.dashboard.routes import path_forecast as mod

    def fake_dirs():
        cal = tmp_path / 'cal'
        hist = tmp_path / 'hist'
        cal.mkdir(parents=True, exist_ok=True)
        hist.mkdir(parents=True, exist_ok=True)
        return cal, hist

    monkeypatch.setattr(mod, '_calibration_dirs', fake_dirs)

    h = initialize_error_handler(max_errors=100)
    h.clear_errors()

    real_path_open = Path.open
    def path_open_fail_on_hist(self, mode='r', *args, **kwargs):
        p = str(self)
        if p.endswith('.csv') and 'a' in mode:
            raise OSError('simulated hist append failure')
        return real_path_open(self, mode, *args, **kwargs)

    real_write_text = Path.write_text
    def write_text_fail_json(self, *args, **kwargs):
        if str(self).endswith('.json'):
            raise OSError('simulated json write failure')
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'write_text', write_text_fail_json, raising=True)
    monkeypatch.setattr(Path, 'open', path_open_fail_on_hist, raising=True)

    before = len(get_error_handler().get_recent_errors(1000))
    _save_calibration('NIFTY', 1.2, 0.8, 0.9, None, 123)
    after = len(get_error_handler().get_recent_errors(1000))

    # Two errors expected: one for JSON write, one for CSV append
    assert after >= before + 2
    last_errs = get_error_handler().get_recent_errors(2)
    assert all(e.category in (ErrorCategory.FILE_IO, getattr(ErrorCategory, 'FILE_IO')) for e in last_errs)
    assert all(e.severity in (ErrorSeverity.LOW, getattr(ErrorSeverity, 'LOW')) for e in last_errs)
