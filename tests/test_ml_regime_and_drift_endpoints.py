"""Tests for regime breaches and drift-inclusive metrics compare endpoint.

Run with:
    pytest tests/test_ml_regime_and_drift_endpoints.py -v

These tests are lenient: if API not running they skip.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error

import pytest


API_BASE = "http://127.0.0.1:9500"


def _get(url: str, timeout: int = 10):
    req = urllib.request.Request(url, headers={"User-Agent": "pytest-ml-regime"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode()
        try:
            return json.loads(body), resp.code
        except json.JSONDecodeError:
            return {}, resp.code


class TestRegimeEndpoints:
    def test_regime_breaches_flat(self):
        url = f"{API_BASE}/api/ml/ensemble/regime/breaches?index=NIFTY"
        try:
            data, code = _get(url, timeout=15)
        except urllib.error.URLError:
            pytest.skip("API not running")

        assert code == 200
        assert isinstance(data, list)
        # If breaches exist, validate expected keys
        if data:
            sample = data[0]
            for key in ["horizon", "coverage_window_pct", "norm_error_p90", "triggered"]:
                assert key in sample

    def test_regime_status_single(self):
        url = f"{API_BASE}/api/ml/ensemble/regime/status?index=NIFTY"
        try:
            data, code = _get(url, timeout=15)
        except urllib.error.URLError:
            pytest.skip("API not running")

        if code == 404:
            pytest.skip("Regime status not yet computed")
        assert code == 200
        assert isinstance(data, dict)
        for key in ["index", "breaches", "alerts"]:
            assert key in data
        assert isinstance(data.get("breaches", []), list)


class TestDriftInCompare:
    def test_metrics_compare_with_drift(self):
        url = f"{API_BASE}/api/ml/ensemble/metrics/compare?index=NIFTY&horizon=60&include_drift=1"
        try:
            data, code = _get(url, timeout=20)
        except urllib.error.URLError:
            pytest.skip("API not running")

        assert code == 200
        assert isinstance(data, dict)
        
        # Support both flat (legacy) and nested (consolidated) formats
        if "entries" in data:
            # Nested format
            entries = data["entries"]
            assert isinstance(entries, list)
            if entries:
                entry = entries[0]
                assert entry["index"] == "NIFTY"
                assert int(entry["horizon"]) == 60
        else:
            # Flat format
            for key in ["index", "horizon"]:
                assert key in data

        # If available, validate drift summary contents
        drift = data.get("drift_summary")
        if drift:
            assert isinstance(drift, dict)
            # Check for performance drift keys (rolling_mae style)
            if "mae_ratio" in drift:
                for k in ["index", "alert_count", "mae_ratio", "norm_ratio"]:
                    assert k in drift
                # Ratios non-negative
                assert drift.get("mae_ratio", 0) >= 0
                assert drift.get("norm_ratio", 0) >= 0
