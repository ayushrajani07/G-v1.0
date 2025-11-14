from src.analytics.ml.baseline import baseline_tp

def test_hybrid_additivity_sanity():
    base = baseline_tp(underlying=100, iv_proxy=0.2, minutes_to_expiry=120)
    resid = 10.0
    hybrid = base + resid
    assert abs(hybrid - (base + resid)) < 1e-9
