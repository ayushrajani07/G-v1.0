"""Enhanced cache stats endpoint test.

Validates new fields: eviction_rate_per_min, ttl_remaining_* and ttl_distribution buckets.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error

import pytest

BASE = "http://127.0.0.1:9500"


def _fetch(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "pytest-cache-stats"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode()), resp.code


def test_cache_stats_enhanced_fields():
    url = f"{BASE}/api/ml/ensemble/cache/stats"
    try:
        data, code = _fetch(url)
    except urllib.error.URLError:
        pytest.skip("API not running")

    assert code == 200
    assert "forecast_cache" in data
    fc = data["forecast_cache"]

    for field in [
        "eviction_rate_per_min",
        "ttl_remaining_min_sec",
        "ttl_remaining_max_sec",
        "ttl_remaining_avg_sec",
        "ttl_distribution",
    ]:
        assert field in fc, f"Missing field {field}"

    dist = fc["ttl_distribution"]
    assert isinstance(dist, dict)
    for bucket in ["le_15", "le_30", "le_45", "le_60", "gt_60"]:
        assert bucket in dist
        assert isinstance(dist[bucket], int)

    # Basic sanity: averages within min/max range
    if fc["ttl_remaining_max_sec"] >= fc["ttl_remaining_min_sec"]:
        assert fc["ttl_remaining_min_sec"] <= fc["ttl_remaining_avg_sec"] <= fc["ttl_remaining_max_sec"]
