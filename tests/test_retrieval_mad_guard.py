import os
from pathlib import Path
from typing import List

import pytest

from src.path_forecast.retrieval import RetrievalPathForecaster, RetrievalConfig


def _make_series(base: List[float], future_len: int, offset: float = 0.0, noise: float = 0.0) -> List[float]:
    out = [float(b) + float(offset) for b in base]
    # simple future: continue linear trend
    last = out[-1] if out else 0.0
    fut = [last + (i + 1) * 1.0 for i in range(future_len)]
    return out + fut


def test_ann_mad_guard_filters_outlier(monkeypatch):
    # Control environment flags
    monkeypatch.setenv("ENABLE_PATH_FORECAST_PROFILING", "1")
    monkeypatch.setenv("ANN_MAD_GUARD_THRESHOLD", "0.5")  # reasonably tight
    monkeypatch.delenv("PATH_FORECAST_DISABLE_WEIGHTED", raising=False)

    # Recent window: simple ramp
    n_today = 20
    W = 10
    H = 5
    recent = [float(i) for i in range(n_today)]

    # Build synthetic day files list
    fake_days = [
        Path(f"/fake/2025-11-0{i+1}.csv") for i in range(6)
    ]

    # Monkeypatch list_day_files to return our fake paths
    monkeypatch.setattr(RetrievalPathForecaster, "_list_day_files", lambda self, index: fake_days)

    # Synthetic historical series: 5 near to query, 1 far outlier
    # near windows ~ recent[-W:]
    base_window = recent[-W:]
    day_to_series = {}
    for i, p in enumerate(fake_days):
        if i < 5:
            # similar pattern, small offset
            series = _make_series(recent, H, offset=float(i) * 0.1)
        else:
            # outlier: large offset making cosine/l2 distance large
            series = _make_series([v + 100.0 for v in recent], H, offset=0.0)
        day_to_series[p.stem] = series

    # Patch cache loader to return our synthetic series
    import src.path_forecast.retrieval as retrieval_mod

    def _fake_get_day_tp(root: Path, index: str, expiry: str, offset: str, dstr: str):
        return list(day_to_series.get(dstr, []))

    monkeypatch.setattr(retrieval_mod, "_cache_get_day_tp", _fake_get_day_tp)

    # Build config with ANN enabled
    cfg = RetrievalConfig(root=Path("/fake_root"), window=W, k=3, use_ann=True, ann_space="cosine", ann_max_candidates=6)
    forecaster = RetrievalPathForecaster(cfg)

    # forecast_path expects a Sequence[Sequence[float]] for recent_window; wrap scalar list
    recent_wrapped = [[v] for v in recent]
    times, qmap = forecaster.forecast_path(recent_wrapped, context={"index": "TEST", "now_ms": 0}, horizon_minutes=H, bucket_ms=60_000)

    meta = forecaster.last_meta
    # MAD guard diagnostics should be present
    assert "ann_mad_median" in meta
    assert "ann_mad_mad" in meta
    assert "ann_mad_cutoff" in meta
    assert "ann_mad_filtered" in meta
    # Should filter at least the outlier
    assert isinstance(meta.get("ann_mad_filtered"), int)
    assert meta.get("ann_mad_filtered", 0) >= 1
    # Ensure we still have candidates and quantiles
    assert len(qmap) > 0
    assert len(times) == H
