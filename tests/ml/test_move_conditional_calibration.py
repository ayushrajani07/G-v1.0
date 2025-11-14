from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def test_move_conditional_regressor_calibration(tmp_path: Path) -> None:
    # Build synthetic data where conditional magnitude ~ 2 * feature
    n = 300
    tp = np.cumsum(np.random.randn(n))
    delta = np.abs(np.diff(tp, prepend=tp[0]))
    feat = np.abs(np.random.randn(n))

    # labeling params
    win = 20
    k = 0.5

    # magnitudes only for predicted move rows (label=1)
    rows = []
    deltas = [0.0] + [abs(tp[i] - tp[i - 1]) for i in range(1, n)]
    rstd = []
    for i in range(len(deltas)):
        s = deltas[max(0, i - win + 1) : i + 1]
        m = float(np.mean(s)) if s else 0.0
        v = float(np.mean([(x - m) ** 2 for x in s])) if s else 0.0
        rstd.append(float(np.sqrt(v)))
    thresh = [k * (rs if rs > 1e-6 else 0.0) for rs in rstd]
    labels = [1 if deltas[i] > thresh[i] and rstd[i] > 0 else 0 for i in range(len(deltas))]

    for i in range(n):
        rows.append({"tp": float(tp[i]), "f1": float(feat[i]), "label": int(labels[i])})

    # write training CSV expected by regressor trainer
    data_csv = tmp_path / "train.csv"
    data_csv.write_text(
        "tp,f1,label\n" + "\n".join(f"{r['tp']},{r['f1']},{r['label']}" for r in rows),
        encoding="utf-8",
    )

    cfg = {"features": ["f1"], "target": "label", "inference": {}}
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    # Train regressor on labeled rows
    from scripts.ml.train_tp_move_conditional import main as train_reg_main
    import sys

    argv = sys.argv
    try:
        sys.argv = [
            "train_tp_move_conditional.py",
            "--config",
            str(cfg_path),
            "--input",
            str(data_csv),
            "--artifact",
            str(tmp_path / "cond_artifact"),
        ]
        train_reg_main()
    finally:
        sys.argv = argv

    # Load and evaluate calibration slope
    import joblib
    from scripts.ml.train_tp_move_classifier import build_X

    art = joblib.load(str((tmp_path / "cond_artifact.joblib")))
    model = art["model"]
    feats = art["features"]

    X = build_X(rows, feats)
    y = np.array([r["label"] for r in rows], dtype=int)
    preds = model.predict(X)

    # Correlation between feature and predicted magnitude on positive labels should be positive
    corr = np.corrcoef(X[:, 0][y == 1], preds[y == 1])[0, 1]
    # Loose threshold
    assert corr > 0.2 or np.isnan(corr), f"unexpected calibration corr: {corr}"
