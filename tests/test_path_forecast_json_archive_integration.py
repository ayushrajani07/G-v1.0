import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.web.dashboard.app import app
import src.web.dashboard.routes.path_forecast._router as path_mod


@pytest.fixture
def client():
    return TestClient(app)


def _write_live_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        f.write('timestamp,tp\n')
        for t, v in rows:
            ts = datetime.datetime.fromtimestamp(int(t)/1000).strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"{ts},{v}\n")


def test_path_forecast_json_archives_bands_and_q50(tmp_path: Path, monkeypatch, client):
    """End-to-end JSON route invocation that validates archival side-effects (q50 + bands files).

    1. Seeds project_root with live and historical CSVs.
    2. Seeds calibration snapshot to ensure band_scale != 1.
    3. Invokes JSON route and asserts output payload structure and presence of archive files with expected columns.
    """
    # Patch project_root
    monkeypatch.setattr(path_mod, 'project_root', lambda: tmp_path, raising=False)
    monkeypatch.setattr(path_mod, '_project_root', lambda: tmp_path, raising=False)

    idx = 'ARCHIDX'
    expiry = 'this_week'
    offset = '0'
    data_root = tmp_path / 'data' / 'g6_data' / idx / expiry / offset

    # Historical days (ensure retrieval has candidates)
    day_dates = [datetime.date(2025, 11, 3), datetime.date(2025, 11, 4)]
    for d in day_dates:
        base_ms = int(datetime.datetime(d.year, d.month, d.day, 9, 30).timestamp() * 1000)
        rows_hist = [(base_ms + i*60000, 100 + (i % 3)) for i in range(90)]
        _write_live_csv(data_root / f'{d.isoformat()}.csv', rows_hist)

    # Live file for today
    today = datetime.date(2025, 11, 7)
    base_ms_today = int(datetime.datetime(today.year, today.month, today.day, 11, 0).timestamp() * 1000)
    live_rows = [(base_ms_today + i*60000, 200 + (i % 5)) for i in range(120)]
    _write_live_csv(data_root / f'{today.isoformat()}.csv', live_rows)

    # Calibration snapshot seed
    calib_dir = tmp_path / 'data' / 'ml' / 'path_forecasts' / '_calibration'
    calib_dir.mkdir(parents=True, exist_ok=True)
    (calib_dir / f'{idx}.json').write_text('{"band_scale":1.3,"updated_at":"2025-11-07T10:00:00","target":0.8,"actual":0.76,"samples":120}', encoding='utf-8')

    client_resp = client.get(
        f"/api/ml/path_forecast_json?index={idx}&expiry_tag={expiry}&offset={offset}&profile=optimized&window=60&k=10&horizon_minutes=30&date_str={today.isoformat()}"
    )
    assert client_resp.status_code == 200, client_resp.text
    data = client_resp.json()
    # Basic payload checks
    assert isinstance(data, list)
    if data:
        for k in ['plot_time','q10','q50','q90','tp']:
            assert k in data[0]

    # Verify archive files exist (q50 primary + bands companion)
    arch_base = tmp_path / 'data' / 'ml' / 'path_forecasts' / idx
    day_str = today.isoformat()
    q50_file = arch_base / f'{day_str}.csv'
    bands_file = arch_base / f'{day_str}_bands.csv'
    assert q50_file.exists(), 'q50 archive file missing'
    assert bands_file.exists(), 'bands archive file missing'

    # Inspect first lines for expected headers
    q50_head = q50_file.read_text(encoding='utf-8').splitlines()[0]
    assert 'gen_time_iso' in q50_head and 'q50' in q50_head
    bands_head = bands_file.read_text(encoding='utf-8').splitlines()[0]
    assert 'gen_time_iso' in bands_head and 'q50' in bands_head and 'mode' in bands_head

    # Ensure non-trivial band_scale applied (q10/q90 distance not collapsed to median everywhere)
    # We check at least one row where q10 < q50 < q90 strictly.
    found_spread = False
    for row in data[:10]:
        q10 = row.get('q10')
        q50 = row.get('q50')
        q90 = row.get('q90')
        if all(isinstance(x, (int,float)) for x in (q10,q50,q90)) and q10 < q50 < q90:
            found_spread = True
            break
    assert found_spread, 'Expected at least one row with q10 < q50 < q90 after band scaling'

