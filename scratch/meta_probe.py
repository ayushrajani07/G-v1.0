from src.web.dashboard.routes import path_forecast as path_mod
from src.web.dashboard.app import app
from fastapi.testclient import TestClient
import datetime

orig_load = path_mod._load_live_rows_and_context
orig_run = path_mod._run_forecast_pipeline

def fake_load(request, idx_norm, expiry_tag, offset, date_str, now_override_ms):
    rows = [{"time": 1234567890000, "tp": 100.0}]
    return rows, 100.0, 1234567890000, "this_week", datetime.date(2025, 11, 7)

def fake_run(idx_norm, rows, ref_now_ms, horizon_minutes, bucket_ms,
             mode_eff, fb_band_pct, window_eff, k_eff,
             dist_eff, weight_eff, recent_gamma_eff, regime_tol_eff, regime_penalty_eff, qs,
             use_ann=None, ann_space=None, ann_max_candidates=None):
    return [ref_now_ms+60_000], {0.5:[100.0]}, "hybrid", {"k_used":k_eff,"window_used":window_eff}

path_mod._load_live_rows_and_context = fake_load
path_mod._run_forecast_pipeline = fake_run

client = TestClient(app)
resp = client.get("/api/ml/path_forecast_meta?index=NIFTY&profile=optimized")
print("status:", resp.status_code)
print("text:", resp.text)

# Show detail field if 500
try:
    print("json:", resp.json())
except Exception as e:
    print("json decode failed:", e)

path_mod._load_live_rows_and_context = orig_load
path_mod._run_forecast_pipeline = orig_run
