from __future__ import annotations

import argparse
import json
from src.error_handling import safe_write_json  # type: ignore
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor, GradientBoostingRegressor  # type: ignore
from sklearn.metrics import mean_absolute_error, mean_squared_error
import joblib  # type: ignore

from src.analytics.ml.baseline import baseline_tp


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_csv(path: Path) -> List[Dict[str, Any]]:
    # Minimal CSV reader to avoid new deps
    import csv
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def parse_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return float("nan")


def build_X(rows: List[Dict[str, Any]], features: List[str]) -> np.ndarray:
    X = []
    for r in rows:
        vals = []
        for f in features:
            vals.append(parse_float(r.get(f)))
        X.append(vals)
    X = np.array(X, dtype=float)
    # Replace NaNs with column means (simple impute)
    col_means = np.nanmean(X, axis=0)
    inds = np.where(np.isnan(X))
    X[inds] = np.take(col_means, inds[1])
    return X


def main() -> None:
    ap = argparse.ArgumentParser(description="Train hybrid residual model for TP (baseline + residual ML)")
    ap.add_argument("--config", required=True, help="Hybrid residual config JSON")
    ap.add_argument("--input", required=True, help="Training CSV with columns incl. tp, index_price, ce_iv, pe_iv, minutes_to_expiry")
    ap.add_argument("--artifact", required=True, help="Artifact base path (without extension)")
    args = ap.parse_args()

    cfg = load_json(Path(args.config))
    features: List[str] = cfg.get("features", [])
    base_cfg = cfg.get("baseline", {"k": 1.0, "min_iv": 1e-4, "min_T_minutes": 1.0})

    rows = read_csv(Path(args.input))
    # Compute baseline and residuals
    y_true: List[float] = []
    y_resid: List[float] = []
    for r in rows:
        tp = parse_float(r.get("tp"))
        idx = parse_float(r.get("index_price"))
        ce_iv = parse_float(r.get("ce_iv"))
        pe_iv = parse_float(r.get("pe_iv"))
        m2e = parse_float(r.get("minutes_to_expiry"))
        base = baseline_tp(underlying=idx, ce_iv=ce_iv, pe_iv=pe_iv, minutes_to_expiry=m2e,
                           k=float(base_cfg.get("k", 1.0)),
                           min_iv=float(base_cfg.get("min_iv", 1e-4)),
                           min_T_minutes=float(base_cfg.get("min_T_minutes", 1.0)))
        if not np.isfinite(tp):
            continue
        y_true.append(tp)
        y_resid.append(tp - base)

    # Features matrix
    X = build_X(rows, features)
    # Align X to y_resid length by simple trim if mismatch
    n = min(len(y_resid), X.shape[0])
    X = X[:n]
    y_res = np.array(y_resid[:n], dtype=float)

    # Model
    try:
        model = HistGradientBoostingRegressor(loss="squared_error", learning_rate=cfg["params"].get("learning_rate", 0.05))
    except Exception:
        model = GradientBoostingRegressor(**cfg.get("params", {}))
    model.fit(X, y_res)

    # Metrics
    y_hat = model.predict(X)
    mae = mean_absolute_error(y_res, y_hat)
    rmse = mean_squared_error(y_res, y_hat, squared=False)
    print({"mae": mae, "rmse": rmse})

    # Save artifact
    artifact = {
        "model": model,
        "features": features,
        "baseline": base_cfg,
        "config": cfg,
    }
    out_path = Path(args.artifact).with_suffix(".joblib")
    joblib.dump(artifact, out_path)
    # Feature sidecar
    fe_out = Path(args.artifact).with_suffix(".fe.json")
    safe_write_json(fe_out, {"features": features, "baseline": base_cfg}, function_name='train_hybrid_residual_feature_sidecar_write')


if __name__ == "__main__":
    main()
