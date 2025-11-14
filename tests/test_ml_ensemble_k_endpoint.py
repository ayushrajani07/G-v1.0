from pathlib import Path
from fastapi.testclient import TestClient
import json

from src.web.dashboard.app import app
from src.web.dashboard.core import paths as real_paths

client = TestClient(app)


def _write_sidecar(tmp_path: Path, index: str, horizon: str, include_smooth: bool = True):
    base = tmp_path / 'data' / 'ml' / 'live_predictions'
    base.mkdir(parents=True, exist_ok=True)
    payload = {
        'timestamp': 1731230000000,
        'recommended_k': 1.25,
        'effective_cov': 0.79,
        'band_radius': 4.5678,
        'target': 0.8,
        'n': 321,
        'index': index,
        'horizon': horizon,
    }
    if include_smooth:
        payload['k_smooth'] = 1.10
    (base / f'{index}_ensemble_k_calibration.json').write_text(json.dumps(payload), encoding='utf-8')


def test_k_calibration_endpoint_happy_path(tmp_path, monkeypatch):  # type: ignore
    index, horizon = 'NIFTY', '1'

    def fake_project_root():
        return tmp_path

    monkeypatch.setattr(real_paths, 'project_root', fake_project_root, raising=True)
    _write_sidecar(tmp_path, index, horizon, include_smooth=True)

    r = client.get(f'/api/ml/ensemble/k_calibration?index={index}&horizon={horizon}')
    assert r.status_code == 200, r.text
    lines = r.text.strip().splitlines()
    assert lines[0] == 'timestamp,recommended_k,k_smooth,effective_cov,band_radius,target,index,horizon,n'
    # Row should contain both raw and smooth k
    assert lines[1].startswith('1731230000000,1.25,1.10,0.79,4.5678,0.8,NIFTY,1,321')


def test_k_calibration_endpoint_missing_file(tmp_path, monkeypatch):  # type: ignore
    index = 'NIFTY'

    def fake_project_root():
        return tmp_path

    monkeypatch.setattr(real_paths, 'project_root', fake_project_root, raising=True)
    r = client.get(f'/api/ml/ensemble/k_calibration?index={index}')
    assert r.status_code == 404
    assert 'not found' in r.text.lower()
