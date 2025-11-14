from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from scripts.ml.train_tp_move_classifier import build_X


def test_move_classifier_roc_sanity(tmp_path: Path) -> None:
    # Create a tiny synthetic dataset with a separable feature for move events
    # tp zig-zags; feature is scaled delta so classifier has signal
    n = 200
    tp = np.zeros(n)
    tp[1:] = np.cumsum(np.random.randn(n - 1))
    delta = np.abs(np.diff(tp, prepend=tp[0]))
    feat = delta * 2.0  # separable-ish

    # rolling window params
    win = 20
    k = 0.5

    # build CSV rows
    rows = [{"tp": float(tp[i]), "f1": float(feat[i])} for i in range(n)]
    # write CSV
    data_csv = tmp_path / "train.csv"
    data_csv.write_text("tp,f1\n" + "\n".join(f"{r['tp']},{r['f1']}" for r in rows), encoding="utf-8")

    # config JSON
    cfg = {
        "features": ["f1"],
        "labeling": {"rolling_window": win, "threshold_factor": k},
        "inference": {"prob_threshold": 0.6},
    }
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    # Train
    from scripts.ml.train_tp_move_classifier import main as train_main
    import sys

    argv = sys.argv
    try:
        sys.argv = [
            "train_tp_move_classifier.py",
            "--config",
            str(cfg_path),
            "--input",
            str(data_csv),
            "--artifact",
            str(tmp_path / "clf_artifact"),
        ]
        train_main()
    finally:
        sys.argv = argv

    # Load artifact and score AUC on training data as a sanity check
    import joblib

    art = joblib.load(str((tmp_path / "clf_artifact.joblib")))
    model = art["model"]
    feats = art["features"]

    X = build_X(rows, feats)
    proba = model.predict_proba(X)[:, 1]

    # Compute labels the same way as trainer for reproducibility
    deltas = [0.0] + [abs(rows[i]["tp"] - rows[i - 1]["tp"]) for i in range(1, n)]
    rstd = []
    for i in range(len(deltas)):
        s = deltas[max(0, i - win + 1) : i + 1]
        m = float(np.mean(s)) if s else 0.0
        v = float(np.mean([(x - m) ** 2 for x in s])) if s else 0.0
        rstd.append(float(np.sqrt(v)))
    thresh = [k * (rs if rs > 1e-6 else 0.0) for rs in rstd]
    y = np.array([1 if deltas[i] > thresh[i] and rstd[i] > 0 else 0 for i in range(len(deltas))], dtype=int)

    from sklearn.metrics import roc_auc_score

    auc = roc_auc_score(y, proba)

    # Sanity check: AUC should beat random (>0.6) on this synthetic data
    assert auc > 0.6, f"AUC too low: {auc}"
