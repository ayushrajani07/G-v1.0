import math

from src.path_forecast.retrieval import _weighted_quantile


def test_weighted_quantile_basic():
    vals = [1.0, 2.0, 3.0, 4.0]
    w = [1.0, 1.0, 1.0, 1.0]
    assert _weighted_quantile(vals, w, 0.5) == 2.5


def test_weighted_quantile_skewed_weights():
    vals = [1.0, 2.0, 3.0, 4.0]
    w = [0.0, 0.0, 1.0, 0.0]
    # Entire weight on 3.0 -> all quantiles should be ~3.0
    assert math.isclose(_weighted_quantile(vals, w, 0.1), 3.0, rel_tol=1e-9)
    assert math.isclose(_weighted_quantile(vals, w, 0.5), 3.0, rel_tol=1e-9)
    assert math.isclose(_weighted_quantile(vals, w, 0.9), 3.0, rel_tol=1e-9)


def test_weighted_quantile_empty_and_zero():
    assert math.isnan(_weighted_quantile([], [], 0.5))
    vals = [10.0]
    assert _weighted_quantile(vals, [], 0.5) == 10.0
