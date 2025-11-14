import builtins
from pathlib import Path
import types

from src.collectors.pipeline.executor import execute_phases
from src.collectors.pipeline.state import ExpiryState
from src.error_handling import get_error_handler, initialize_error_handler, ErrorCategory, ErrorSeverity


def _mk_state():
    return ExpiryState(index='NIFTY', rule='R', settings=types.SimpleNamespace())


def _ok_phase(ctx, state: ExpiryState) -> ExpiryState:
    return state


def _count_errors():
    return len(get_error_handler().get_recent_errors(1000))


def test_trends_write_failure_routed(monkeypatch, tmp_path: Path):
    # Enable panel export and trends; point to tmp dir
    monkeypatch.setenv('G6_PIPELINE_PANEL_EXPORT', '1')
    monkeypatch.setenv('G6_PIPELINE_TRENDS_ENABLED', '1')
    monkeypatch.setenv('G6_PANELS_DIR', str(tmp_path))

    # Ensure handler initialized
    h = initialize_error_handler(max_errors=200)
    h.clear_errors()

    real_open = builtins.open

    def open_fail_on_trend(path, mode='r', *args, **kwargs):
        p = str(path)
        if p.endswith('pipeline_errors_trends.json') and 'w' in mode:
            raise OSError('simulated trends write failure')
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, 'open', open_fail_on_trend)

    before = _count_errors()
    execute_phases({}, _mk_state(), [_ok_phase])
    after = _count_errors()

    assert after == before + 1, 'Expected one FILE_IO low error recorded from trends write failure'
    err = get_error_handler().get_recent_errors(1)[-1]
    assert err.category in (ErrorCategory.FILE_IO, getattr(ErrorCategory, 'FILE_IO'))
    assert err.severity in (ErrorSeverity.LOW, getattr(ErrorSeverity, 'LOW'))
    assert 'trends' in err.message.lower()
