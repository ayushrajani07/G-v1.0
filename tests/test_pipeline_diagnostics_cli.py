from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CLI = Path('scripts/g6.py')


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True)


def test_pipeline_diagnostics_cli_filters_and_summary(tmp_path: Path) -> None:
    store = tmp_path / 'expiry_diagnostics.jsonl'
    # Two records: one NIFTY ok, one BANKNIFTY with error outcomes
    rec_ok = {
        'schema': 1,
        'exported_at': 0,
        'index': 'NIFTY',
        'rule': 'weekly',
        'expiry_date': None,
        'errors': [],
        'error_records': [],
        'meta': {
            'pipeline_summary': {'phases_total': 1, 'phases_ok': 1, 'phases_error': 0, 'phases_with_retries': 0, 'retry_enabled': False, 'error_outcomes': {}, 'aborted_early': False, 'fatal': False, 'recoverable_exhausted': False},
            'phase_runs': [{'phase': 'a', 'final_outcome': 'ok', 'attempts': 1, 'duration_ms': 1.0}],
        },
    }
    rec_err = {
        'schema': 1,
        'exported_at': 0,
        'index': 'BANKNIFTY',
        'rule': 'monthly',
        'expiry_date': None,
        'errors': ['fatal:fetch:oops'],
        'error_records': [],
        'meta': {
            'pipeline_summary': {'phases_total': 1, 'phases_ok': 0, 'phases_error': 1, 'phases_with_retries': 0, 'retry_enabled': False, 'error_outcomes': {'fatal': 1}, 'aborted_early': False, 'fatal': True, 'recoverable_exhausted': False},
            'phase_runs': [{'phase': 'fetch', 'final_outcome': 'fatal', 'attempts': 1, 'duration_ms': 2.0}],
        },
    }
    store.write_text(json.dumps(rec_ok) + '\n' + json.dumps(rec_err) + '\n', encoding='utf-8')

    # Filter by index and ensure one line returned
    r = run_cli('pipeline-diagnostics', '--path', str(store), '--index', 'NIFTY')
    assert r.returncode == 0, r.stderr
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])['index'] == 'NIFTY'

    # Summary for records with errors
    r2 = run_cli('pipeline-diagnostics', '--path', str(store), '--has-errors', '--summary', '--pretty', '--format', 'json')
    assert r2.returncode == 0, r2.stderr
    payload = json.loads(r2.stdout)
    assert payload['count'] == 1
    assert payload['by_index']['BANKNIFTY'] == 1
    assert payload['phase_error_outcomes']['fatal'] == 1
