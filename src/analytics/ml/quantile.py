from __future__ import annotations

"""
Lightweight quantile regressor wrapper using scikit-learn's GradientBoostingRegressor
with quantile loss. Trains one model per requested quantile and provides a
uniform interface for predict/save/load.

This module is intentionally dependency-light and avoids adding third-party
libraries beyond scikit-learn and joblib, both commonly available.
"""

from dataclasses import dataclass, field
from typing import Iterable, Sequence, Dict, Any

import numpy as np

try:  # typed import guard
    from sklearn.ensemble import GradientBoostingRegressor  # type: ignore
except Exception as _e:  # pragma: no cover - imported only when used
    GradientBoostingRegressor = None  # type: ignore

try:
    import joblib  # type: ignore
except Exception as _e:  # pragma: no cover
    joblib = None  # type: ignore


@dataclass
class QuantileRegressor:
    """Train separate GBRT models for each quantile.

    Parameters mirror common GBRT knobs; additional params can be supplied via
    the `params` dict and forwarded to scikit-learn's constructor.
    """

    quantiles: Sequence[float] = (0.1, 0.5, 0.9)
    n_estimators: int = 300
    max_depth: int = 3
    learning_rate: float = 0.05
    subsample: float = 1.0
    random_state: int | None = 42
    params: Dict[str, Any] = field(default_factory=dict)

    _models: Dict[float, Any] = field(default_factory=dict, init=False)

    def fit(self, X: np.ndarray, y: np.ndarray) -> "QuantileRegressor":
        if GradientBoostingRegressor is None:
            raise RuntimeError("scikit-learn is required for QuantileRegressor")
        X = _as_2d(X)
        y = _as_1d(y)
        self._models = {}
        for q in self.quantiles:
            model = GradientBoostingRegressor(
                loss="quantile",
                alpha=float(q),
                n_estimators=self.n_estimators,
                max_depth=self.max_depth,
                learning_rate=self.learning_rate,
                subsample=self.subsample,
                random_state=self.random_state,
                **(self.params or {}),
            )
            model.fit(X, y)
            self._models[float(q)] = model
        return self

    def predict(self, X: np.ndarray) -> Dict[str, np.ndarray]:
        if not self._models:
            raise RuntimeError("QuantileRegressor is not fitted")
        X = _as_2d(X)
        out: Dict[str, np.ndarray] = {}
        for q, m in self._models.items():
            pred = m.predict(X)
            key = _qkey(q)
            out[key] = _as_1d(pred)
        # Convenience aliases
        if "q0.50" in out and "p50" not in out:
            out["p50"] = out["q0.50"]
        if "q0.10" in out and "p10" not in out:
            out["p10"] = out["q0.10"]
        if "q0.90" in out and "p90" not in out:
            out["p90"] = out["q0.90"]
        return out

    def save(self, path: str) -> None:
        if joblib is None:
            raise RuntimeError("joblib is required to save QuantileRegressor")
        payload = {
            "meta": {
                "quantiles": list(map(float, self.quantiles)),
                "n_estimators": self.n_estimators,
                "max_depth": self.max_depth,
                "learning_rate": self.learning_rate,
                "subsample": self.subsample,
                "random_state": self.random_state,
                "params": self.params,
            },
            "models": self._models,
        }
        joblib.dump(payload, path)

    @classmethod
    def load(cls, path: str) -> "QuantileRegressor":
        if joblib is None:
            raise RuntimeError("joblib is required to load QuantileRegressor")
        payload = joblib.load(path)
        meta = payload.get("meta", {})
        inst = cls(
            quantiles=tuple(meta.get("quantiles", (0.1, 0.5, 0.9))),
            n_estimators=int(meta.get("n_estimators", 300)),
            max_depth=int(meta.get("max_depth", 3)),
            learning_rate=float(meta.get("learning_rate", 0.05)),
            subsample=float(meta.get("subsample", 1.0)),
            random_state=meta.get("random_state", 42),
            params=meta.get("params", {}),
        )
        inst._models = payload.get("models", {})
        return inst


def _qkey(q: float) -> str:
    return f"q{float(q):.2f}".replace("-0", "0")


def _as_2d(x: np.ndarray | Iterable[Iterable[float]] | Iterable[float]) -> np.ndarray:
    a = np.asarray(list(x))
    if a.ndim == 1:
        a = a.reshape(-1, 1)
    return a


def _as_1d(x: np.ndarray | Iterable[float]) -> np.ndarray:
    a = np.asarray(x).reshape(-1)
    return a
