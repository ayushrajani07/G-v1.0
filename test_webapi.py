"""Test Web API /api/live_csv endpoint"""
import requests
import json

BASE_URL = "http://127.0.0.1:9500"

print("\n=== TESTING WEB API ENDPOINTS ===\n")

# Test 1: Health check
print("1. Testing /health...")
try:
    r = requests.get(f"{BASE_URL}/health", timeout=3)
    print(f"   ✅ Status: {r.status_code}")
    print(f"   Response: {r.text[:100]}")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 2: /api/live_csv with minimal parameters
print("\n2. Testing /api/live_csv (minimal)...")
try:
    r = requests.get(f"{BASE_URL}/api/live_csv?index=NIFTY&expiry_tag=this_week", timeout=5)
    print(f"   ✅ Status: {r.status_code}")
    print(f"   Content length: {len(r.content)} bytes")
    if r.status_code == 200:
        data = r.json()
        print(f"   Records: {len(data) if isinstance(data, list) else 'N/A'}")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 3: /api/live_csv with full parameters (like Grafana)
print("\n3. Testing /api/live_csv (full params)...")
params = {
    "index": "BANKNIFTY",
    "expiry_tag": "this_week",
    "offset": "0",
    "include_index": "1",
    "include_vol": "1",
    "include_oi": "1",
    "include_pcr": "1",
    "pct": "1",
    "pct_fields": "index_price,pcr,ce_vol,pe_vol,ce_oi,pe_oi"
}
try:
    r = requests.get(f"{BASE_URL}/api/live_csv", params=params, timeout=5)
    print(f"   ✅ Status: {r.status_code}")
    print(f"   URL: {r.url}")
    print(f"   Content length: {len(r.content)} bytes")
    if r.status_code == 200:
        data = r.json()
        print(f"   Records: {len(data) if isinstance(data, list) else 'N/A'}")
        if isinstance(data, list) and data:
            print(f"   First record keys: {list(data[0].keys())}")
    else:
        print(f"   Error response: {r.text[:200]}")
except Exception as e:
    print(f"   ❌ Error: {e}")

print("\n=== TEST COMPLETE ===\n")
