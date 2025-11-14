"""Unit tests for compute_recommended_k in auto_calibrate_ensemble.

We test pure k search logic on synthetic data, avoiding filesystem.
"""

from importlib import import_module

mod = import_module('scripts.ml.auto_calibrate_ensemble')


def test_recommend_k_zero_when_quantile_hits_target():
    # residuals: [1,2,3,4,5], disagreements small so k=0 should match target 0.6 via band quantile
    # Build preds aligned by key with disagreement ~ 0.0
    keys = [1000, 2000, 3000, 4000, 5000]
    preds = []
    tp_by_bucket = {}
    for i, k in enumerate(keys, start=1):
        # residual = i (1..5)
        tp = 0.0
        pred = float(i)
        preds.append({'bucket_ms': k, 'pred': pred, 'dis': 0.0})
        tp_by_bucket[k] = tp
    res = mod.compute_recommended_k(preds, tp_by_bucket, target=0.6, window_minutes=180, bucket_ms=60_000, grid=[0.0, 0.5, 1.0], min_points=5)
    assert res is not None
    # Expect k=0 as best (exact coverage match under our quantile interpolation)
    assert abs(res.k - 0.0) < 1e-9, res
    assert res.n == 5


def test_recommend_k_positive_for_higher_target():
    # Same residuals but disagreements allow expansion when k>0 to approach higher target
    keys = [1000, 2000, 3000, 4000, 5000]
    preds = []
    tp_by_bucket = {}
    # disagreements chosen so that with k around 1.0, last residual gets covered
    # residuals: 1..5, disagreements: 0,0,1,1,1
    dis_list = [0.0, 0.0, 1.0, 1.0, 1.0]
    for i, (k, dis) in enumerate(zip(keys, dis_list), start=1):
        tp = 0.0
        pred = float(i)
        preds.append({'bucket_ms': k, 'pred': pred, 'dis': dis})
        tp_by_bucket[k] = tp
    # Target 0.9 -> need to include 5th point -> k close to 1.0 (band_radius ~ 4.6; need raise to >=5)
    res = mod.compute_recommended_k(preds, tp_by_bucket, target=0.9, window_minutes=180, bucket_ms=60_000, grid=[0.0, 0.5, 1.0, 1.5, 2.0], min_points=5)
    assert res is not None
    assert res.k >= 0.5, res  # should not pick 0.0
    # effective coverage should be within 0.2 of target on this coarse grid
    assert abs(res.effective_cov - 0.9) <= 0.2
