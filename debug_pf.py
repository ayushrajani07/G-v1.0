from fastapi.testclient import TestClient
from src.web.dashboard.app import app

client = TestClient(app)
r = client.get('/api/ml/path_forecast_json', params={'index':'NIFTY','horizon_minutes':30,'window':10,'k':5,'mode':'retrieval','profile':'base'})
print('STATUS', r.status_code)
print('TEXT', r.text)
