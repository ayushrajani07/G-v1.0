import builtins
import os
import types
from pathlib import Path

import pytest

from src.orchestrator.panel_diffs import emit_panel_artifacts
from src.error_handling import (
    get_error_handler,
    initialize_error_handler,
    ErrorCategory,
    ErrorSeverity,
)


@pytest.fixture(autouse=True)
def _enable_diffs_and_reset_state(monkeypatch):
    # Enable panel diffs and ensure egress not frozen
    monkeypatch.setenv('G6_PANEL_DIFFS', '1')
    monkeypatch.delenv('G6_EGRESS_FROZEN', raising=False)
    # Reset internal state across tests
    import src.orchestrator.panel_diffs as pd
    pd._state = None
    pd._BUS = None
    # Fresh error handler per test
    handler = initialize_error_handler(max_errors=100)
    handler.clear_errors()
    yield
    handler.clear_errors()


def _count_errors():
    h = get_error_handler()
    return len(h.get_recent_errors(1000))


def test_bootstrap_full_snapshot_file_error_is_routed(monkeypatch, tmp_path: Path):
    status_path = tmp_path / 'runtime_status.json'

    real_open = builtins.open

    def open_fail_on_full(path, mode='r', *args, **kwargs):
        p = str(path)
        if p.endswith('.full.json') and 'w' in mode:
            raise PermissionError('simulated permission error for full.json')
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, 'open', open_fail_on_full)

    before = _count_errors()
    emit_panel_artifacts({"a": 1}, status_path=str(status_path))
    after = _count_errors()
    assert after == before + 1, 'Expected one error recorded via handler'

    err = get_error_handler().get_recent_errors(1)[-1]
    assert err.category in (ErrorCategory.FILE_IO, getattr(ErrorCategory, 'FILE_IO'))
    assert err.severity in (ErrorSeverity.LOW, getattr(ErrorSeverity, 'LOW'))
    assert 'initial full' in err.message.lower()


def test_diff_snapshot_file_error_is_routed(monkeypatch, tmp_path: Path):
    status_path = tmp_path / 'runtime_status.json'

    # First successful call to set state
    emit_panel_artifacts({"a": 1}, status_path=str(status_path))

    real_open = builtins.open

    def open_fail_on_diff(path, mode='r', *args, **kwargs):
        p = str(path)
        if p.endswith('.diff.json') and 'w' in mode:
            raise OSError('simulated write error for diff.json')
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, 'open', open_fail_on_diff)

    before = _count_errors()
    emit_panel_artifacts({"a": 2}, status_path=str(status_path))
    after = _count_errors()
    assert after == before + 1, 'Expected one error recorded for diff write failure'

    err = get_error_handler().get_recent_errors(1)[-1]
    assert err.category in (ErrorCategory.FILE_IO, getattr(ErrorCategory, 'FILE_IO'))
    assert err.severity in (ErrorSeverity.LOW, getattr(ErrorSeverity, 'LOW'))
    assert 'panel diff' in err.message.lower()


def test_event_bus_publish_failure_is_routed(monkeypatch, tmp_path: Path):
    status_path = tmp_path / 'runtime_status.json'

    class _BadBus:
        def publish(self, *a, **k):
            raise RuntimeError('publish failed')
        def enforce_snapshot_guard(self):
            return None

    import src.orchestrator.panel_diffs as pd
    monkeypatch.setattr(pd, 'get_event_bus', lambda: _BadBus())

    before = _count_errors()
    emit_panel_artifacts({"a": 1}, status_path=str(status_path))
    after = _count_errors()
    # On bootstrap we publish a 'panel_full' event, expect one publish failure
    assert after >= before + 1
    err = get_error_handler().get_recent_errors(1)[-1]
    # Accept PANEL_DISPLAY or CONFIGURATION depending on failure branch
    assert err.category in (
        getattr(ErrorCategory, 'PANEL_DISPLAY', None) or ErrorCategory.UNKNOWN,
        getattr(ErrorCategory, 'CONFIGURATION', None) or ErrorCategory.UNKNOWN,
    )
    assert err.severity in (ErrorSeverity.LOW, getattr(ErrorSeverity, 'LOW'))
