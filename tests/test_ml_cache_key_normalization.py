"""Tests cache key normalization (avg_iv bucketing).

Requires server started with env:
  G6_FORECAST_CACHE_NORMALIZE_AVG_IV=1
  G6_FORECAST_CACHE_AVG_IV_BUCKETS=0.2,0.35,0.5

Verifies two forecasts whose avg_iv fall in same bucket produce a cache hit on second request.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error

import pytest

BASE = "http://127.0.0.1:9500"


def _call(index: str, avg_iv: float) -> dict:
    url = (
        f"{BASE}/api/ml/ensemble/forecast?index={index}"
        f"&horizon=60&quantiles=0.1,0.5,0.9&underlying=20000&avg_iv={avg_iv}"  # constant underlying to stabilize key
        f"&minutes_to_expiry=375&recent_window_size=60"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "pytest-cache-norm"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def test_avg_iv_bucket_normalization_cache_hit():
    # If server not running, skip
    try:
        first = _call("NIFTY", 0.34)  # bucket edge 0.35
    except urllib.error.URLError:
        pytest.skip("API not running")

    # Ensure first not marked as hit (fresh compute)
    assert first.get("metadata", {}).get("cache_hit") is False

    second = _call("NIFTY", 0.349)  # same bucket edge 0.35
    # With normalization, second should be served from cache
    assert second.get("metadata", {}).get("cache_hit") is True, "Expected cache hit for same avg_iv bucket"

    # If normalization disabled, the second may miss; expose helpful warning
    if not second.get("metadata", {}).get("cache_hit"):
        pytest.warns(UserWarning, "avg_iv normalization appears disabled or ineffective")
