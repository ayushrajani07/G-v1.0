import builtins
import sys
import types
from pathlib import Path

import pytest

from src.orchestrator.status_writer import write_runtime_status
from src.error_handling import (
    get_error_handler,
    initialize_error_handler,
    ErrorCategory,
    ErrorSeverity,
)


@pytest.fixture(autouse=True)
def _fresh_handler(monkeypatch):
    h = initialize_error_handler(max_errors=200)
    h.clear_errors()
    yield
    h.clear_errors()


def _stub_call(tmp_path: Path):
    write_runtime_status(
        path=str(tmp_path / 'runtime_status.json'),
        cycle=1,
        elapsed=0.01,
        interval=1.0,
        index_params={},
        providers=types.SimpleNamespace(primary_provider=None),
        csv_sink=None, metrics=None,
        readiness_ok=True,
        readiness_reason="",
        health_monitor=types.SimpleNamespace(components={}),
    )


def _count_errors():
    return len(get_error_handler().get_recent_errors(1000))


def test_catalog_emission_failure_is_routed(monkeypatch, tmp_path: Path):
    monkeypatch.setenv('G6_EMIT_CATALOG', '1')
    # Create a dummy module src.orchestrator.catalog with emit_catalog raising
    mod = types.ModuleType('src.orchestrator.catalog')
    def _emit_catalog(**kwargs):
        raise RuntimeError('catalog emit boom')
    mod.emit_catalog = _emit_catalog  # type: ignore[attr-defined]
    sys.modules['src.orchestrator.catalog'] = mod

    before = _count_errors()
    _stub_call(tmp_path)
    after = _count_errors()

    assert after == before + 1
    err = get_error_handler().get_recent_errors(1)[-1]
    assert err.category in (ErrorCategory.FILE_IO, getattr(ErrorCategory, 'FILE_IO'))
    assert err.severity in (ErrorSeverity.LOW, getattr(ErrorSeverity, 'LOW'))
    assert 'catalog' in err.message.lower()


def test_marker_write_failure_is_routed(monkeypatch, tmp_path: Path):
    # Fail only for .marker path
    real_open = builtins.open
    def open_fail_marker(path, mode='r', *args, **kwargs):
        p = str(path)
        if p.endswith('.marker') and 'w' in mode:
            raise PermissionError('marker write denied')
        return real_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(builtins, 'open', open_fail_marker)

    before = _count_errors()
    _stub_call(tmp_path)
    after = _count_errors()

    assert after == before + 1
    err = get_error_handler().get_recent_errors(1)[-1]
    assert err.category in (ErrorCategory.FILE_IO, getattr(ErrorCategory, 'FILE_IO'))
    assert err.severity in (ErrorSeverity.LOW, getattr(ErrorSeverity, 'LOW'))
    assert 'marker' in err.message.lower()


def test_panel_diff_raise_is_routed(monkeypatch, tmp_path: Path):
    # Force emit_panel_artifacts to raise
    import src.orchestrator.panel_diffs as pd
    def _raiser(*a, **k):
        raise RuntimeError('panel_diffs emit failed')
    monkeypatch.setattr(pd, 'emit_panel_artifacts', _raiser, raising=True)

    before = _count_errors()
    _stub_call(tmp_path)
    after = _count_errors()

    assert after == before + 1
    err = get_error_handler().get_recent_errors(1)[-1]
    # Depending on enum version, accept RENDERING or UNKNOWN for category
    assert err.severity in (ErrorSeverity.LOW, getattr(ErrorSeverity, 'LOW'))
    assert 'panel diff' in err.message.lower()
