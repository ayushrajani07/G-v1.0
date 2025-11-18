import json, os
from pathlib import Path
from src.web.dashboard.routes import advisor
from fastapi.testclient import TestClient

# Build a miniature FastAPI app for testing these endpoints
from fastapi import FastAPI

app = FastAPI()
app.include_router(advisor.router)
client = TestClient(app)


def test_trend_endpoint_reads_reports(tmp_path, monkeypatch):
    # Create fake reports/drift files
    base = Path('reports') / 'drift'
    if base.exists():
        # ensure clean
        for p in base.glob('daily_*.json'):
            try: p.unlink()
            except Exception: pass
    os.makedirs(base, exist_ok=True)
    def write(day, counts):
        d = {'generated_at': f'2025-11-{day:02d}T00:00:00Z', 'aggregate_counts': counts}
        (base / f'daily_2025-11-{day:02d}.json').write_text(json.dumps(d), encoding='utf-8')
    write(16, {'critical':1})
    write(17, {'critical':3})
    write(18, {'critical':2})
    r = client.get('/api/ml/drift/daily_reports/trend?days=2')
    assert r.status_code == 200
    data = r.json()
    assert data['count'] == 2
    # per-index series present and contains NIFTY
    assert 'per_index_series' in data and 'NIFTY' in data['per_index_series']
    # Latest two days should be 17 and 18
    assert data['series'][0]['generated_at'].startswith('2025-11-17')
    assert data['series'][1]['generated_at'].startswith('2025-11-18')


def test_latest_endpoint_returns_latest(tmp_path):
    base = Path('reports') / 'drift'
    (base / 'daily_2025-11-17.json').write_text(json.dumps({'generated_at':'2025-11-17T00:00:00Z'}), encoding='utf-8')
    (base / 'daily_2025-11-18.json').write_text(json.dumps({'generated_at':'2025-11-18T00:00:00Z'}), encoding='utf-8')
    r = client.get('/api/ml/drift/daily_reports/latest')
    assert r.status_code == 200
    assert r.json()['generated_at'].startswith('2025-11-18')
