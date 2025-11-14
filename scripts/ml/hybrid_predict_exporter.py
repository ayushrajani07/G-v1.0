from __future__ import annotations

import argparse
import json
import sys
import time
import logging
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import joblib  # type: ignore

try:
    from src.utils.backoff import sleep_ms as _sleep_ms  # type: ignore
except Exception:  # pragma: no cover - optional dependency path
    _sleep_ms = None  # type: ignore

logger = logging.getLogger(__name__)

def _sleep_s(_sec: float) -> None:
    """Sleep helper that prefers backoff.sleep_ms when available."""
    try:
        if _sleep_ms:
            _sleep_ms(float(_sec) * 1000.0)
            return
    except Exception:  # pragma: no cover - defensive fallback
        pass
    time.sleep(_sec)

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analytics.ml.baseline import baseline_tp  # type: ignore
from src.web.dashboard.core.csv_io import find_live_csv, load_csv_rows_full  # type: ignore
from src.web.dashboard.core.paths import project_root  # type: ignore

MODEL_NAME = "sk_hgb_residual"


def load_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_float(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return float("nan")


def get_latest_features(row: Dict[str, Any], features: List[str]) -> np.ndarray:
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


def ensure_pred_csv(index: str) -> Path:
    base = project_root() / "data" / "ml" / "live_predictions"
    base.mkdir(parents=True, exist_ok=True)
    fp = base / f"{index.upper()}_hybrid.csv"
    if not fp.exists():
        fp.write_text("timestamp,prediction,baseline,residual,model,index,horizon\n", encoding="utf-8")
    return fp


def append_prediction(fp: Path, ts_iso: str, pred: float, baseline: float, residual: float, index: str, horizon: str) -> None:
    """Append one hybrid prediction row via CSVIO facade with safe fallback.

    Debug-log fallback outcomes; never raise to keep loop resilient.
    """
    header = ["timestamp","prediction","baseline","residual","model","index","horizon"]
    row: List[Any] = [ts_iso, pred, baseline, residual, MODEL_NAME, index, horizon]
    try:
        from src.storage.csvio import api as _csvio_api  # type: ignore
        _csvio_api.append_one(str(fp), row, header)
    except Exception as e:  # pragma: no cover - facade failure path
        try:
            line = f"{ts_iso},{pred},{baseline},{residual},{MODEL_NAME},{index},{horizon}\n"
            with fp.open("a", encoding="utf-8") as f:
                f.write(line)
        except Exception as fe:  # pragma: no cover - rare file append failure
            logger.debug("hybrid prediction append fallback failed", extra={"error": str(fe), "path": str(fp)})
        else:
            logger.debug("hybrid prediction append via fallback", extra={"error": str(e), "path": str(fp)})


def main() -> None:
    ap = argparse.ArgumentParser(description="Hybrid baseline + residual prediction exporter")
    ap.add_argument("--config", required=True, help="Hybrid residual config JSON path")
    ap.add_argument("--artifact", required=True, help="Hybrid residual model artifact (.joblib) path")
    ap.add_argument("--index", required=True)
    ap.add_argument("--horizon", default="1")
    ap.add_argument("--interval", type=int, default=30, help="Polling interval seconds")
    ap.add_argument("--port", type=int, default=None, help="Prometheus metrics port")
    ap.add_argument("--expiry-tag", default="this_week")
    ap.add_argument("--offset", default="0")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    feat_list = list(cfg.get("features") or [])
    base_cfg = cfg.get("baseline", {"k": 1.0, "min_iv": 1e-4, "min_T_minutes": 1.0})
    target_col = str(cfg.get("target") or "tp")

    artifact = joblib.load(Path(args.artifact))  # {'model': model, 'features': [...], 'baseline': {...}}
    model = artifact.get("model")
    model_features = artifact.get("features", feat_list)

    METRICS_ENABLED = False
    g_pred = g_baseline = g_residual = None
    g_loop_errors = g_metrics_errors = None
    if args.port is not None:
        try:
            from prometheus_client import Gauge, Counter, start_http_server  # type: ignore
            g_pred = Gauge("g6_ml_hybrid_prediction", "Hybrid prediction (baseline + residual)", ["index", "horizon", "model"])  # type: ignore
            g_baseline = Gauge("g6_ml_hybrid_baseline", "Hybrid structural baseline component", ["index", "horizon", "model"])  # type: ignore
            g_residual = Gauge("g6_ml_hybrid_residual", "Hybrid residual component", ["index", "horizon", "model"])  # type: ignore
            g_loop_errors = Counter("g6_ml_hybrid_exporter_loop_errors_total", "Total loop iteration errors", ["index", "horizon", "model"])  # type: ignore
            g_metrics_errors = Counter("g6_ml_hybrid_exporter_metrics_errors_total", "Metrics export failures", ["index", "horizon", "model"])  # type: ignore
            start_http_server(int(args.port))
            METRICS_ENABLED = True
            logger.info("metrics server started", extra={"port": int(args.port)})
        except Exception as e:
            METRICS_ENABLED = False
            logger.debug("metrics init failed", extra={"error": str(e), "port": args.port})

    idx = str(args.index).upper()
    horizon = str(args.horizon)
    out_fp = ensure_pred_csv(idx)
    logger.info("writing hybrid predictions", extra={"path": str(out_fp), "index": idx, "horizon": horizon})

    while True:
        try:
            live_fp = find_live_csv(project_root() / "data" / "g6_data", idx, args.expiry_tag, args.offset, date.today())
            if not live_fp or not live_fp.exists():
                _sleep_s(args.interval)
                continue
            rows = load_csv_rows_full(live_fp)
            if not rows:
                _sleep_s(args.interval)
                continue
            last = rows[-1]
            # Baseline inputs
            tp_val = parse_float(last.get("tp"))
            spot = parse_float(last.get("index_price"))
            ce_iv = parse_float(last.get("ce_iv"))
            pe_iv = parse_float(last.get("pe_iv"))
            m2e = parse_float(last.get("minutes_to_expiry"))
            base_val = baseline_tp(underlying=spot, ce_iv=ce_iv, pe_iv=pe_iv, minutes_to_expiry=m2e,
                                   k=float(base_cfg.get("k", 1.0)),
                                   min_iv=float(base_cfg.get("min_iv", 1e-4)),
                                   min_T_minutes=float(base_cfg.get("min_T_minutes", 1.0)))
            # Residual prediction
            X = get_latest_features(last, model_features)
            resid_pred = float(model.predict(X)[0]) if model is not None else 0.0
            hybrid_pred = base_val + resid_pred
            ts_iso = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
            append_prediction(out_fp, ts_iso, hybrid_pred, base_val, resid_pred, idx, horizon)
            # Export gauges
            if METRICS_ENABLED:
                try:
                    if g_pred is not None:
                        g_pred.labels(index=idx, horizon=horizon, model=MODEL_NAME).set(hybrid_pred)
                    if g_baseline is not None:
                        g_baseline.labels(index=idx, horizon=horizon, model=MODEL_NAME).set(base_val)
                    if g_residual is not None:
                        g_residual.labels(index=idx, horizon=horizon, model=MODEL_NAME).set(resid_pred)
                except Exception as me:  # pragma: no cover - metrics failure path
                    try:
                        if g_metrics_errors is not None:
                            g_metrics_errors.labels(index=idx, horizon=horizon, model=MODEL_NAME).inc()
                    except Exception:
                        pass
                    logger.debug("metrics export failed", extra={"error": str(me), "index": idx, "horizon": horizon})
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.warning("hybrid exporter loop error", extra={"error": str(e), "index": idx, "horizon": horizon})
            try:
                if METRICS_ENABLED and g_loop_errors is not None:
                    g_loop_errors.labels(index=idx, horizon=horizon, model=MODEL_NAME).inc()
            except Exception:
                pass
        _sleep_s(max(1, int(args.interval)))


if __name__ == "__main__":
    main()
