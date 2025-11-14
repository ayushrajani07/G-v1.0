from __future__ import annotations

r"""
Train a simple quantile regressor (sklearn GradientBoostingRegressor with quantile loss)
for TP forecasting using a prepared features CSV. Saves three artifacts (q10,q50,q90)
and a minimal sidecar with used_features.

Usage (example) on Windows (escape backslashes shown):
    %CD%\.venv\Scripts\python.exe scripts\ml\train_tp_quantile_skgbr.py \
            --config configs\ml\nifty_tp_forecast_skgbr_quantile.json \
            --input data\ml\training\nifty_tp_train.csv \
            --artifact models\nifty_tp_forecast_skgbr_quantile

Note: This trainer expects a tabular CSV with the columns listed in the config's
"features" plus the target column name (e.g., "tp"). Feature engineering beyond
simple lags/rolls should be done offline for now.
"""

import argparse
import json
from pathlib import Path
from typing import List, Dict, Any

import numpy as np
import pandas as pd

from src.analytics.ml.quantile import QuantileRegressor


def load_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def make_dataset(df: pd.DataFrame, features: List[str], target: str) -> tuple[np.ndarray, np.ndarray, List[str]]:
    used = []
    X_cols: List[str] = []
    for c in features:
        if c in df.columns:
            X_cols.append(c)
            used.append(c)
    if target not in df.columns:
        raise ValueError(f"target '{target}' not found in input CSV")
    X: np.ndarray = df[X_cols].astype(float).to_numpy()
    y: np.ndarray = df[target].astype(float).to_numpy()
    return X, y, used


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--input", required=True, help="Training CSV path")
    ap.add_argument("--artifact", required=True, help="Artifact base path (without _qXX suffix)")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    features = list(cfg.get("features") or [])
    target = str(cfg.get("target") or "tp")
    quantiles = list(cfg.get("quantiles") or [0.1, 0.5, 0.9])
    params = dict(cfg.get("params") or {})

    df = pd.read_csv(args.input)
    X, y, used = make_dataset(df, features, target)

    model = QuantileRegressor(
        quantiles=quantiles,
        n_estimators=int(params.get("n_estimators", 300)),
        max_depth=int(params.get("max_depth", 3)),
        learning_rate=float(params.get("learning_rate", 0.05)),
        subsample=float(params.get("subsample", 1.0)),
        params={k: v for k, v in params.items() if k not in {"n_estimators","max_depth","learning_rate","subsample"}},
    )
    model.fit(X, y)

    # Save one payload with all quantiles
    out_base = Path(args.artifact)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    model.save(str(out_base) + ".joblib")

    # FE sidecar to match existing tooling
    sidecar = {
        "used_features": used,
        "quantiles": quantiles,
        "params": params,
    }
    with (out_base.with_suffix(".fe.json")).open("w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=2)

    print(f"Saved artifact to {str(out_base)+'.joblib'} and sidecar {out_base.with_suffix('.fe.json')}")


if __name__ == "__main__":
    main()
