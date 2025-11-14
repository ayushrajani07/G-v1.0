from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, GradientBoostingClassifier  # type: ignore
from sklearn.metrics import roc_auc_score
import joblib  # type: ignore


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_csv(path: Path) -> List[Dict[str, Any]]:
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
    X = np.asarray(X, dtype=float)
    # simple impute
    col_means = np.nanmean(X, axis=0)
    inds = np.where(np.isnan(X))
    X[inds] = np.take(col_means, inds[1])
    return X


def main() -> None:
    ap = argparse.ArgumentParser(description="Train TP move classifier (significant |Δtp| event)")
    ap.add_argument("--config", required=True, help="Move signal config JSON")
    ap.add_argument("--input", required=True, help="Training CSV containing tp and features")
    ap.add_argument("--artifact", required=True, help="Output artifact base path")
    args = ap.parse_args()

    cfg = load_json(Path(args.config))
    feats: List[str] = list(cfg.get("features") or [])
    lab = cfg.get("labeling", {})
    win = int(lab.get("rolling_window", 60))
    k = float(lab.get("threshold_factor", 1.25))
    p_thresh = float(cfg.get("inference", {}).get("prob_threshold", 0.6))

    rows = read_csv(Path(args.input))
    # Compute abs delta and rolling std on tp
    tp_series: List[float] = [parse_float(r.get("tp")) for r in rows]
    deltas: List[float] = [0.0] + [abs(tp_series[i] - tp_series[i - 1]) for i in range(1, len(tp_series))]
    # rolling std of deltas
    rstd: List[float] = []
    for i in range(len(deltas)):
        s = deltas[max(0, i - win + 1): i + 1]
        m = float(np.mean(s)) if s else 0.0
        v = float(np.mean([(x - m) ** 2 for x in s])) if s else 0.0
        rstd.append(float(np.sqrt(v)))
    thresh = [k * (rs if rs > 1e-6 else 0.0) for rs in rstd]
    y = np.array([1 if deltas[i] > thresh[i] and rstd[i] > 0 else 0 for i in range(len(deltas))], dtype=int)

    X = build_X(rows, feats)
    n = min(len(y), X.shape[0])
    X = X[:n]
    y = y[:n]

    try:
        model = HistGradientBoostingClassifier()
    except Exception:
        model = GradientBoostingClassifier()
    model.fit(X, y)

    try:
        proba = model.predict_proba(X)[:, 1]
        auc = roc_auc_score(y, proba)
        print({"auc": float(auc)})
    except Exception:
        print({"auc": None})

    artifact = {
        "model": model,
        "features": feats,
        "labeling": {"rolling_window": win, "threshold_factor": k},
        "inference": {"prob_threshold": p_thresh},
    }
    out = Path(args.artifact).with_suffix(".joblib")
    joblib.dump(artifact, out)


if __name__ == "__main__":
    main()
