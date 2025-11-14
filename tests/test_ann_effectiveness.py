import math

from src.path_forecast.metrics import compute_ann_effectiveness


def test_effectiveness_happy_path():
    # speedup=4, prune_ratio=0.25 -> prune_gain=0.75, mad=2, tol=8 -> quality=1-(2/8)=0.75
    # expected = 4 * 0.75 * 0.75 = 2.25
    eff = compute_ann_effectiveness(4.0, 0.25, 2.0, 8.0)
    assert eff is not None
    assert abs(eff - 2.25) < 1e-9


def test_effectiveness_no_mad():
    # If ann_q50_mad is None quality defaults to 1
    eff = compute_ann_effectiveness(3.0, 0.4, None, 5.0)
    # prune_gain=0.6 -> expected 1.8 (allow tiny floating error)
    assert eff is not None
    assert abs(eff - 1.8) < 1e-12


def test_effectiveness_clamps_prune_ratio():
    # prune_ratio >1 should clamp to 1 => prune_gain 0 => eff 0
    eff = compute_ann_effectiveness(10.0, 5.0, 0.0, 1.0)
    assert eff == 0.0


def test_effectiveness_quality_floor():
    # mad larger than tolerance -> quality=0
    eff = compute_ann_effectiveness(5.0, 0.0, 10.0, 5.0)
    assert eff == 0.0


def test_effectiveness_missing_inputs():
    assert compute_ann_effectiveness(None, 0.2, 1.0, 5.0) is None
    assert compute_ann_effectiveness(2.0, None, 1.0, 5.0) is None
    assert compute_ann_effectiveness(2.0, 0.2, 1.0, None) is None
    assert compute_ann_effectiveness(2.0, 0.2, 1.0, 0.0) is None
