from __future__ import annotations

import argparse
import sys
import time
try:
    from src.utils.backoff import sleep_ms as _sleep_ms  # type: ignore
except Exception:
    _sleep_ms = None  # type: ignore

def _sleep_s(_sec: float) -> None:
    try:
        if _sleep_ms:
            _sleep_ms(float(_sec) * 1000.0)
            return
    except Exception:
        pass
    time.sleep(_sec)
from datetime import datetime, date, timezone
import datetime as _dt
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import joblib  # type: ignore
try:
    import cloudpickle  # type: ignore
except Exception:  # pragma: no cover
    cloudpickle = None  # type: ignore

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.web.dashboard.core.csv_io import find_live_csv, load_csv_rows_full  # type: ignore
from src.web.dashboard.core.paths import project_root  # type: ignore
from src.error_handling import safe_write_text, safe_append_line  # type: ignore

CLASSIFIER_NAME = "tp_move_classifier"
REGRESSOR_NAME = "tp_move_conditional"


def parse_float(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return float("nan")


def ensure_out_csv(index: str) -> Path:
    base = project_root() / "data" / "ml" / "live_predictions"
    base.mkdir(parents=True, exist_ok=True)
    fp = base / f"{index.upper()}_move.csv"
    if not fp.exists():
        safe_write_text(fp, "timestamp,move_prob,move_label_pred,conditional_magnitude,model,index,horizon\n")
    return fp


def build_feature_vector(row: Dict[str, Any], features: List[str]) -> np.ndarray:
    vals: List[float] = []
    for f in features:
        v = row.get(f)
        try:
            vals.append(float(v) if v is not None else float("nan"))
        except Exception:
            vals.append(float("nan"))
    arr = np.asarray(vals, dtype=float).reshape(1, -1)
    arr = np.nan_to_num(arr, nan=0.0)
    return arr


def main() -> None:
    ap = argparse.ArgumentParser(description="Live TP move probability + conditional magnitude exporter")
    ap.add_argument("--config", required=True, help="Move signal config JSON path")
    ap.add_argument("--classifier-artifact", required=True, help="Classifier artifact .joblib path")
    ap.add_argument("--regressor-artifact", required=True, help="Conditional regressor artifact .joblib path")
    ap.add_argument("--index", required=True)
    ap.add_argument("--horizon", default="1")
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--expiry-tag", default="this_week")
    ap.add_argument("--offset", default="0")
    ap.add_argument("--port", type=int, default=None, help="Prometheus metrics port")
    ap.add_argument("--once", action="store_true", help="Run a single iteration and exit (test helper)")
    args = ap.parse_args()

    import json
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    feats = list(cfg.get("features") or [])
    prob_threshold = float(cfg.get("inference", {}).get("prob_threshold", 0.6))

    # Safe load with cloudpickle fallback (subprocess may not have sitecustomize patches)
    def _safe_load(p: Path):
        try:
            return joblib.load(p)
        except Exception:
            if cloudpickle is not None:
                try:
                    with open(p, "rb") as f:
                        return cloudpickle.load(f)
                except Exception:
                    pass
            raise

    clf_art = _safe_load(Path(args.classifier_artifact))
    classifier = clf_art.get("model")
    clf_feats = clf_art.get("features", feats)
    reg_art = _safe_load(Path(args.regressor_artifact))
    reg_model = reg_art.get("model")
    reg_feats = reg_art.get("features", feats)
    mean_magnitude = reg_art.get("mean_magnitude")

    METRICS_ENABLED = False
    g_prob = g_mag = None
    if args.port is not None:
        try:
            from prometheus_client import Gauge, start_http_server  # type: ignore
            g_prob = Gauge("g6_ml_move_probability", "Probability of significant TP move", ["index", "horizon", "model"])  # type: ignore
            g_mag = Gauge("g6_ml_move_conditional_magnitude", "Conditional predicted move magnitude", ["index", "horizon", "model"])  # type: ignore
            start_http_server(int(args.port))
            METRICS_ENABLED = True
            print(f"Prometheus metrics server started on port {args.port}")
        except Exception:
            METRICS_ENABLED = False

    idx = str(args.index).upper()
    horizon = str(args.horizon)
    out_fp = ensure_out_csv(idx)
    snap_dir = out_fp.parent / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    print(f"Writing move predictions to {out_fp}")

    # Prepare flat fallback path if nested structure not present (tests may write directly)
    flat_name = f"{idx}_{args.expiry_tag}_{args.offset}.csv"
    candidate = project_root() / "data" / "g6_data" / flat_name
    iteration_count = 0
    while True:
        try:
            live_fp = find_live_csv(project_root() / "data" / "g6_data", idx, args.expiry_tag, args.offset, date.today())
            # Flat fallback used in tests
            if (not live_fp or not live_fp.exists()) and candidate.exists():
                live_fp = candidate
            if not live_fp or not live_fp.exists():
                _sleep_s(args.interval)
                continue
            rows = load_csv_rows_full(live_fp)
            if len(rows) < 2:
                _sleep_s(args.interval)
                continue
            last = rows[-1]
            prev = rows[-2]
            tp_last = parse_float(last.get("tp"))
            tp_prev = parse_float(prev.get("tp"))
            if not np.isfinite(tp_last) or not np.isfinite(tp_prev):
                _sleep_s(args.interval)
                continue

            X_clf = build_feature_vector(last, clf_feats)
            move_prob = 0.0
            try:
                move_prob = float(classifier.predict_proba(X_clf)[0, 1]) if classifier is not None else 0.0
            except Exception:
                pass
            move_label_pred = 1 if move_prob >= prob_threshold else 0

            conditional_mag = float(mean_magnitude or 0.0)
            if move_label_pred:
                try:
                    X_reg = build_feature_vector(last, reg_feats)
                    if reg_model is not None:
                        conditional_mag = float(reg_model.predict(X_reg)[0])
                except Exception:
                    pass

            ts_iso = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
            line = f"{ts_iso},{move_prob:.6f},{move_label_pred},{conditional_mag:.6f},{CLASSIFIER_NAME}+{REGRESSOR_NAME},{idx},{horizon}"
            safe_append_line(out_fp, line)
            # Daily snapshot persistence for historical trend analysis
            try:
                day_str = _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y-%m-%d")
                snap_fp = snap_dir / f"{idx}_move_{day_str}.csv"
                if not snap_fp.exists():
                    safe_write_text(
                        snap_fp,
                        "timestamp,move_prob,move_label_pred,conditional_magnitude,model,index,horizon\n",
                    )
                safe_append_line(snap_fp, line)
            except Exception:
                pass
            # Apply flat fallback path after main write loop logic (if nested path missing)
            if live_fp is None:
                live_fp = candidate if candidate.exists() else None
            if METRICS_ENABLED:
                try:
                    if g_prob is not None:
                        g_prob.labels(index=idx, horizon=horizon, model=CLASSIFIER_NAME).set(move_prob)
                    if g_mag is not None and move_label_pred:
                        g_mag.labels(index=idx, horizon=horizon, model=REGRESSOR_NAME).set(conditional_mag)
                except Exception:
                    pass
            iteration_count += 1
            if args.once:
                break
        except KeyboardInterrupt:
            break
        except Exception as e:
            sys.stderr.write(f"[warn] move exporter loop error: {e}\n")
    _sleep_s(max(1, int(args.interval)))


if __name__ == "__main__":
    main()
