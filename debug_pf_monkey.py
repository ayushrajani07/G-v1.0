from fastapi.testclient import TestClient
from src.web.dashboard.routes import path_forecast as pf
from src.web.dashboard.app import app

now_ms = 1731043200000
rows = [{"ts": now_ms - 60000 * (30 - i), "tp": 100.0 + i * 0.5} for i in range(30)]

def fake(request, index, expiry_tag, offset, date_str, now_override_ms):
    last_tp = rows[-1]["tp"]
    return rows, last_tp, now_ms, (expiry_tag or "this_week"), pf._dt.date(2025,11,8)

pf._load_live_rows_and_context = fake
client = TestClient(app)
r = client.get('/api/ml/path_forecast_json', params={'index':'NIFTY','horizon_minutes':30,'window':10,'k':5,'mode':'retrieval','profile':'base','calibrate':False,'no_cache':True})
print('STATUS', r.status_code)
print('TEXT', r.text)
