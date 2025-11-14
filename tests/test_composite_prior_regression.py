import math
from typing import Dict, Sequence, Tuple

import pytest


def test_composite_prior_blend(monkeypatch, tmp_path):
    from src.path_forecast.composite import CompositePathForecaster, CompositeConfig
    from src.path_forecast import retrieval as retrieval_mod

    # --- Arrange: config and subject ---
    cfg = CompositeConfig(root=tmp_path, window=60, k=10, min_days=3)
    comp = CompositePathForecaster(cfg)

    H = 3
    prior_val = 100.0
    retr_med_val = 110.0
    retr_q10_val = 105.0
    retr_q90_val = 115.0

    # Provide deterministic prior median regardless of inputs
    monkeypatch.setattr(
        CompositePathForecaster,
        "_prior_median",
        lambda self, index, now_pos, horizon: [prior_val] * int(horizon),
        raising=True,
    )

    # Stub retrieval.forecast_path to return fixed quantiles and meta
    def fake_retrieval(
        self,
        recent_window: Sequence[Sequence[float]],
        *,
        context: Dict,
        quantiles: Sequence[float],
        horizon_minutes: int,
        bucket_ms: int,
    ) -> Tuple[Sequence[int], Dict[float, Sequence[float]]]:
        self.last_meta = {
            "candidates_total": 10,
            "threshold_needed": 5,
            "k_used": 10,
            "window_used": 60,
        }
        times = list(range(int(horizon_minutes)))
        rq: Dict[float, Sequence[float]] = {
            0.1: [retr_q10_val for _ in range(int(horizon_minutes))],
            0.5: [retr_med_val for _ in range(int(horizon_minutes))],
            0.9: [retr_q90_val for _ in range(int(horizon_minutes))],
        }
        return times, rq

    monkeypatch.setattr(retrieval_mod.RetrievalPathForecaster, "forecast_path", fake_retrieval, raising=True)

    # --- Act ---
    times, out = comp.forecast_path(
        [],
        context={"index": "NIFTY", "now_ms": 0, "live_rows": []},
        quantiles=(0.1, 0.5, 0.9),
        horizon_minutes=H,
        bucket_ms=60_000,
    )

    # --- Assert: alpha and blended median ---
    # alpha = cands / (cands + thresh) clipped to [0.3, 0.9]
    cands = 10
    thresh = 5
    alpha_raw = cands / float(cands + thresh)
    alpha = max(0.3, min(0.9, alpha_raw))

    expected_blended = alpha * retr_med_val + (1.0 - alpha) * prior_val
    shift = expected_blended - retr_med_val

    # q50 replaced by blended median
    assert list(out[0.5]) == [pytest.approx(expected_blended)] * H

    # q10/q90 shifted by the same delta
    assert list(out[0.1]) == [pytest.approx(retr_q10_val + shift)] * H
    assert list(out[0.9]) == [pytest.approx(retr_q90_val + shift)] * H

    # meta
    meta = comp.last_meta
    assert meta.get("alpha") == pytest.approx(alpha)
    assert int(meta.get("candidates_total") or 0) == 10
    assert int(meta.get("threshold_needed") or 0) == 5
    assert int(meta.get("k_used") or 0) == 10
    assert int(meta.get("window_used") or 0) == 60
