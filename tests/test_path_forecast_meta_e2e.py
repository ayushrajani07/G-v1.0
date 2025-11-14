import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.web.dashboard.app import app
from src.web.dashboard.routes import path_forecast as path_mod


@pytest.fixture
def client():
    return TestClient(app)


def _write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        # Use 'timestamp' column to match loader expectations
        f.write('timestamp,tp\n')
        for t, v in rows:
            if isinstance(t, (int, float)):
                ts = datetime.datetime.fromtimestamp(int(t)/1000).strftime('%Y-%m-%d %H:%M:%S')
            else:
                ts = str(t)
            f.write(f"{ts},{v}\n")


def test_meta_endpoint_end_to_end(tmp_path: Path, monkeypatch, client):
    """Strict full pipeline: creates temp data root with sufficient historical + live file + calibration snapshot.

    Ensures non-fallback retrieval/hybrid mode, validates diagnostics, profile override, and calibration fields.
    Falls back to explicit failure (no xfail) if mode becomes 'fallback'.
    """
    # Build a fake project root structure
    data_root = tmp_path / 'data' / 'g6_data'
    idx = 'TESTIDX'
    expiry = 'this_week'
    offset = '0'
    base_idx = data_root / idx / expiry / offset

    # Historical days (3 days) with variance differences to guarantee candidate set >= threshold
    day_dates = [
        datetime.date(2025, 11, 3),
        datetime.date(2025, 11, 4),
        datetime.date(2025, 11, 6),  # skip a day to exercise scanning order
    ]
    base_ms_list = [int(datetime.datetime(d.year, d.month, d.day, 9, 30).timestamp() * 1000) for d in day_dates]
    variances = [1, 2, 3]
    for d, base_ms, var in zip(day_dates, base_ms_list, variances):
        rows_hist = [(base_ms + i*60000, 100 + (i % (var+1)) * var) for i in range(90)]  # ensure >= window + horizon
        _write_csv(base_idx / f'{d.isoformat()}.csv', rows_hist)

    # Live file for today (ensure sufficient rows for recent window and retrieval)
    today = datetime.date(2025, 11, 7)
    base_ms_today = int(datetime.datetime(today.year, today.month, today.day, 11, 0).timestamp() * 1000)
    live_rows = [(base_ms_today + i*60000, 210 + (i % 4)) for i in range(120)]  # >= window (60) and horizon (30)
    _write_csv(base_idx / f'{today.isoformat()}.csv', live_rows)

    # Seed a calibration snapshot (non-default band_scale to assert propagation)
    calib_dir = tmp_path / 'data' / 'ml' / 'path_forecasts' / '_calibration'
    calib_dir.mkdir(parents=True, exist_ok=True)
    calib_file = calib_dir / f'{idx}.json'
    calib_file.write_text('{"band_scale":1.25,"updated_at":"2025-11-07T11:05:00","target":0.8,"actual":0.78,"samples":150}', encoding='utf-8')

    # Patch project_root() to point to tmp_path
    def fake_project_root():
        return tmp_path

    monkeypatch.setattr(path_mod, 'project_root', fake_project_root, raising=False)
    # Also patch module-level alias _project_root if present
    monkeypatch.setattr(path_mod, '_project_root', fake_project_root, raising=False)

    # Call endpoint with profile to exercise profile overrides
    resp = client.get(
        f'/api/ml/path_forecast_meta?index={idx}&expiry_tag={expiry}&offset={offset}&profile=optimized&window=60&k=10&date_str={today.isoformat()}'
    )
    assert resp.status_code == 200, f"Unexpected status {resp.status_code}: {resp.text}"
    data = resp.json()

    # Disallow fallback in strict test now
    assert data.get('mode') != 'fallback', f"Fallback mode encountered: {data}"
    for key in ['mode','index','expiry_tag','window','k','last_tp','gen_ms','retrieval']:
        assert key in data, f'Missing key {key} in response'

    # Retrieval diagnostics present
    meta = data['retrieval']
    assert 'candidates_total' in meta and meta['candidates_total'] >= 1
    assert 'regime_penalized' in meta and isinstance(meta.get('regime_penalized'), int)
    assert meta.get('retained_days', 0) >= 3, "Expected at least 3 retained historical days"

    # Profile mapping applied (window from profile overrides query window if different)
    profiles = path_mod._load_profiles()
    prof_win = profiles['optimized']['window']
    assert data['profile'] == 'optimized'
    assert data['window'] == prof_win

    # last_tp should be resolved from live rows
    assert isinstance(data['last_tp'], (int, float)) and data['last_tp'] >= 0

    # Ensure distance metric and weight mode surfaced somewhere (retrieval or profile fields)
    assert 'distance_metric' in meta or 'profile_distance_metric' in data
    assert 'weight_mode' in meta or 'profile_weight_mode' in data

    # Horizon default behaviors (presence)
    assert 'horizon_minutes' in data

    # Calibration snapshot keys (assert seeded values):
    assert data['band_scale'] == pytest.approx(1.25)
    assert data['cal_target'] == pytest.approx(0.8)
    assert data['cal_actual'] == pytest.approx(0.78)
    assert data['cal_samples'] == 150

    # Sanity on mode (hybrid or retrieval expected)
    assert data['mode'] in ('hybrid','retrieval','fallback')

    # Non-empty gen timestamps
    assert isinstance(data['gen_ms'], int) and data['gen_ms'] > 0
