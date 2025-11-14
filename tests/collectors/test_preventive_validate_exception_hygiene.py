import builtins
import types
from pathlib import Path

import pytest

from src.collectors.modules.preventive_validate import run_preventive_validation
from src.error_handling import initialize_error_handler, get_error_handler, ErrorCategory, ErrorSeverity


def _mk_inputs():
    return {
        'index_symbol': 'NIFTY',
        'rule': 'R',
        'expiry_date': '2025-11-27',
        'instruments': [{'a': 1}],
        'enriched': {'x': 'y'},
        'index_price': 100.0,
    }


def test_preventive_snapshot_write_failure_routed(monkeypatch, tmp_path: Path):
    # Enable debug snapshotting and redirect data dir under tmp
    monkeypatch.setenv('G6_PREVENTIVE_DEBUG', '1')
    # Preventive uses data/debug_preventive/... under CWD; chdir to tmp to keep isolated
    monkeypatch.chdir(tmp_path)

    h = initialize_error_handler(max_errors=100)
    h.clear_errors()

    real_open = builtins.open

    def open_fail_on_debug(path, mode='r', *args, **kwargs):
        p = str(path)
        if 'debug_preventive' in p and 'w' in mode and (p.endswith('_01_instruments.json') or p.endswith('_02_enriched_head.json')):
            raise OSError('simulated preventive snapshot write failure')
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, 'open', open_fail_on_debug)

    before = len(get_error_handler().get_recent_errors(1000))
    inputs = _mk_inputs()
    cleaned, report = run_preventive_validation(**inputs)
    after = len(get_error_handler().get_recent_errors(1000))

    assert isinstance(cleaned, dict) and isinstance(report, dict)
    assert after == before + 1, 'Expected one FILE_IO LOW error recorded for preventive snapshot write failure'
    err = get_error_handler().get_recent_errors(1)[-1]
    assert err.category in (ErrorCategory.FILE_IO, getattr(ErrorCategory, 'FILE_IO'))
    assert err.severity in (ErrorSeverity.LOW, getattr(ErrorSeverity, 'LOW'))
    assert 'snapshot' in err.message.lower() or 'preventive' in err.message.lower()
