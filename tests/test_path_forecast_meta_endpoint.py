import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import src.web.dashboard.routes.path_forecast as path_mod
from src.web.dashboard.app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_meta_endpoint_basic(monkeypatch, client):
    # Monkeypatch live rows loader to provide deterministic single-day context
    def fake_load(request, idx_norm, expiry_tag, offset, date_str, now_override_ms):
        # rows as minimal list with tp/time fields
        rows = [{"time": 1234567890000, "tp": 100.0}]
        last_tp = 100.0
        ref_now_ms = 1234567890000
        eff_tag = "this_week"
        return rows, last_tp, ref_now_ms, eff_tag, datetime.date(2025, 11, 7)

    def fake_run(idx_norm, rows, ref_now_ms, horizon_minutes, bucket_ms,
                 mode_eff, fb_band_pct, window_eff, k_eff,
                 dist_eff, weight_eff, recent_gamma_eff, regime_tol_eff, regime_penalty_eff, qs,
                 use_ann=None, ann_space=None, ann_max_candidates=None):
        times = [ref_now_ms + 60_000, ref_now_ms + 120_000]
        qmap = {0.5: [100.0, 101.0]}
        diag = {
            "regime_penalized": 2,
            "candidates_total": 2,
            "retained_days": 2,
            "k_used": k_eff,
            "window_used": window_eff,
            "distance_metric": dist_eff or "l2",
            "weight_mode": weight_eff,
            "cache_entries": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "cache_evictions": 0,
        }
        return times, qmap, "hybrid", diag

    monkeypatch.setattr(path_mod, "_load_live_rows_and_context", fake_load)
    # Patch forecast pipeline with signature matching production including ANN kwargs for robustness
    monkeypatch.setattr(path_mod, "_run_forecast_pipeline", fake_run, raising=False)

    resp = client.get("/api/ml/path_forecast_meta?index=NIFTY&profile=optimized")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "hybrid"
    assert data["index"] == "NIFTY"
    assert data["profile"] == "optimized"
    # Profile overrides should apply (window from profile not default 60)
    profs = path_mod._load_profiles()
    assert data["window"] == profs["optimized"]["window"]
    # retrieval diagnostics embedded
    assert "retrieval" in data
    assert isinstance(data["retrieval"].get("regime_penalized"), int)
    # profile fields surfaced
    assert "profile_fallback_band_pct" in data
    assert "profile_force_mode" in data


def test_meta_endpoint_fallback(monkeypatch, client):
    # Monkeypatch loader to simulate missing rows (fallback response)
    def fake_load(request, idx_norm, expiry_tag, offset, date_str, now_override_ms):
        return [], None, None, "this_week", datetime.date(2025, 11, 7)

    def fake_run(*a, **kw):  # should not be used
        raise AssertionError("_run_forecast_pipeline should not be invoked in fallback scenario")

    monkeypatch.setattr(path_mod, "_load_live_rows_and_context", fake_load)
    monkeypatch.setattr(path_mod, "_run_forecast_pipeline", fake_run, raising=False)

    resp = client.get("/api/ml/path_forecast_meta?index=NIFTY")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("mode") == "fallback"
    assert "reason" in data


def test_meta_endpoint_profile_knobs(monkeypatch, client):
    """Ensure Phase C profile knobs appear in meta payload when provided."""
    def fake_load(request, idx_norm, expiry_tag, offset, date_str, now_override_ms):
        rows = [{"time": 1234567890000, "tp": 250.0}]
        return rows, 250.0, 1234567890000, "this_week", datetime.date(2025, 11, 7)

    def fake_run(idx_norm, rows, ref_now_ms, horizon_minutes, bucket_ms,
                 mode_eff, fb_band_pct, window_eff, k_eff,
                 dist_eff, weight_eff, recent_gamma_eff, regime_tol_eff, regime_penalty_eff, qs,
                 use_ann=None, ann_space=None, ann_max_candidates=None):
        # Only diagnostics matter for this test
        times = [ref_now_ms + 60_000]
        qmap = {0.5: [250.0]}
        diag = {
            "regime_penalized": 0,
            "candidates_total": 1,
            "retained_days": 1,
            "k_used": k_eff,
            "window_used": window_eff,
            "distance_metric": dist_eff or "l2",
            "weight_mode": weight_eff,
        }
        return times, qmap, "hybrid", diag

    monkeypatch.setattr(path_mod, "_load_live_rows_and_context", fake_load)
    monkeypatch.setattr(path_mod, "_run_forecast_pipeline", fake_run)

    resp = client.get("/api/ml/path_forecast_meta?index=NIFTY&profile=optimized")
    assert resp.status_code == 200
    data = resp.json()
    # Check presence of Phase C related profile fields
    for key in [
        "profile_fallback_band_pct",
        "profile_force_mode",
        "profile_recent_gamma",
        "profile_regime_tolerance",
        "profile_regime_penalty",
        "profile_distance_metric",
        "profile_weight_mode",
    ]:
        assert key in data or key in (data.get("retrieval") or {}), f"Missing {key} in meta payload"
    # retrieval meta contains regime_penalized
    assert "retrieval" in data and "regime_penalized" in data["retrieval"]


def test_meta_endpoint_404_when_live_missing(monkeypatch, client):
    # rows=None indicates missing live_csv path in helper contract
    def fake_load(request, idx_norm, expiry_tag, offset, date_str, now_override_ms):
        return None, None, None, "this_week", datetime.date(2025, 11, 7)

    def fake_run(*a, **kw):
        raise AssertionError("_run_forecast_pipeline should not be called when live file is missing")

    monkeypatch.setattr(path_mod, "_load_live_rows_and_context", fake_load)
    monkeypatch.setattr(path_mod, "_run_forecast_pipeline", fake_run)

    resp = client.get("/api/ml/path_forecast_meta?index=NIFTY")
    assert resp.status_code == 404
    data = resp.json()
    assert data.get("error")
