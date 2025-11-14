import os
import importlib

import pytest
from prometheus_client import REGISTRY, generate_latest


def _reset_registry():
    # Use internal helper to clear default registry if available
    try:
        from src.metrics import server as _ms
        _ms._clear_default_registry()  # type: ignore[attr-defined]
    except Exception:
        # Fallback: best-effort purge via internal attribute (prometheus_client internals)
        try:
            collectors = list(REGISTRY._names_to_collectors.values())  # type: ignore[attr-defined]
            for c in collectors:
                try:
                    REGISTRY.unregister(c)  # type: ignore[arg-type]
                except Exception:
                    pass
        except Exception:
            pass


def _reload_pf_metrics():
    import src.path_forecast.metrics as pfm
    return importlib.reload(pfm)


@pytest.mark.parametrize("enable_pf, enable_meta", [
    (False, False),
])
def test_metrics_absent_without_flags(monkeypatch, enable_pf, enable_meta):
    monkeypatch.delenv("ENABLE_PATH_FORECAST_PROM_METRICS", raising=False)
    monkeypatch.delenv("PATH_FORECAST_META_METRICS", raising=False)
    if enable_pf:
        monkeypatch.setenv("ENABLE_PATH_FORECAST_PROM_METRICS", "1")
    if enable_meta:
        monkeypatch.setenv("PATH_FORECAST_META_METRICS", "1")
    _reset_registry()
    pfm = _reload_pf_metrics()
    # Push with empty meta – should be no-op when flags not set
    pfm.push_retrieval_metrics({})
    pfm.push_composite_metrics({})
    exposition = generate_latest().decode("utf-8", errors="ignore")
    # Our metric names should be absent without enable flag
    for name in (
        "pf_window_sanitized",
        "pf_horizon_sanitized",
        "pf_alpha_hist",
        "pf_candidate_richness",
        "pf_retrieval_latency_ms",
        "pf_composite_latency_ms",
    ):
        assert name not in exposition


def test_metrics_present_with_flags(monkeypatch):
    monkeypatch.setenv("ENABLE_PATH_FORECAST_PROM_METRICS", "1")
    monkeypatch.setenv("PATH_FORECAST_META_METRICS", "1")
    _reset_registry()
    pfm = _reload_pf_metrics()
    # Push with minimally sufficient meta
    pfm.push_retrieval_metrics({
        "window_sanitized": 60,
        "horizon_sanitized": 30,
        "candidates_total": 6,
        "threshold_needed": 3,
        "total_ms": 12.0,
    })
    pfm.push_composite_metrics({
        "alpha": 0.5,
        "total_ms": 5.0,
    })
    exposition = generate_latest().decode("utf-8", errors="ignore")
    for name in (
        "pf_window_sanitized",
        "pf_horizon_sanitized",
        "pf_alpha_hist",
        "pf_candidate_richness",
        "pf_retrieval_latency_ms",
        "pf_composite_latency_ms",
    ):
        assert name in exposition
