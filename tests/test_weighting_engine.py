from src.ml.weighting_engine import AdaptiveWeightingEngine


def test_weighting_confidence_high():
    eng = AdaptiveWeightingEngine()
    w = eng.compute(confidence=0.9, residual_trend=1.0, regime_stability=0.9)
    assert w['gbrt'] > w['retrieval']
    assert 0.75 <= w['gbrt'] <= 0.85


def test_weighting_residual_trend_shift():
    eng = AdaptiveWeightingEngine()
    # baseline first call
    w1 = eng.compute(confidence=0.75, residual_trend=1.0, regime_stability=0.8)
    # elevated residual trend should reduce gbrt weight
    w2 = eng.compute(confidence=0.75, residual_trend=1.2, regime_stability=0.8)
    assert w2['gbrt'] < w1['gbrt']
    assert w2['retrieval'] > w1['retrieval']


def test_weighting_regime_unstable():
    eng = AdaptiveWeightingEngine()
    stable = eng.compute(confidence=0.75, residual_trend=1.0, regime_stability=0.9)
    unstable = eng.compute(confidence=0.75, residual_trend=1.0, regime_stability=0.3)
    assert unstable['gbrt'] < stable['gbrt']
    assert unstable['retrieval'] > stable['retrieval']
