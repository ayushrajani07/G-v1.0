from __future__ import annotations

from src.analytics.ml.conformal import ConformalBand


def test_conformal_band_radius_and_coverage():
    cb = ConformalBand(target_coverage=0.8, window=10)
    # residuals: 0..9
    cb.extend_from_residuals(range(10))
    r = cb.radius()  # 80th percentile of 0..9 is approx element at index 7.2 -> between 7 and 8
    assert 7.0 <= r <= 8.5
    cov = cb.coverage_estimate(r)
    assert 0.7 <= cov <= 0.9
