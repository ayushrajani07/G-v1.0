from fastapi.testclient import TestClient
from src.web.dashboard.app import app
import urllib.parse

client = TestClient(app)

params = {
    'index': 'NIFTY',
    'horizon_minutes': 60,
    'mode': 'auto',
    'window': 180,
    'k': 20,
    'bucket_ms': 60000,
    'calibrate': 'true',
    'no_cache': 'true',
    'date_str': '',
    'now_override_ms': 'now',
    'expiry_tag': 'auto',
    'offset': '0',
    'align': 'future',
    'profile': 'optimized'
}

print(f"Requesting with params: {params}")
r = client.get('/api/ml/path_forecast_json', params=params)
print('STATUS', r.status_code)
# print('TEXT', r.text)
import json
try:
    data = r.json()
    print(f"Received {len(data)} points")
    if len(data) > 0:
        print("First point:", data[0])
        print("Last point:", data[-1])
except:
    print("Response is not JSON")
    print(r.text[:200])
