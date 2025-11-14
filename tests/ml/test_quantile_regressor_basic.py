from __future__ import annotations

import numpy as np

from src.analytics.ml.quantile import QuantileRegressor


def test_quantile_regressor_basic_fit_predict():
    # Synthetic linear data with noise
    rng = np.random.default_rng(42)
    X = rng.uniform(0, 10, size=200).reshape(-1, 1)
    y = 2.0 * X.reshape(-1) + rng.normal(0, 1, size=200)

    qr = QuantileRegressor(quantiles=(0.1, 0.5, 0.9), n_estimators=50, max_depth=2, learning_rate=0.1)
    qr.fit(X, y)
    preds = qr.predict(X[:5])
    assert "q0.10" in preds and "q0.90" in preds and "p50" in preds
    assert preds["p50"].shape[0] == 5
    # Basic ordering check: lower quantile <= median <= upper quantile for first sample
    assert preds["q0.10"][0] <= preds["p50"][0] <= preds["q0.90"][0]
