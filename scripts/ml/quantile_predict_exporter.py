from __future__ import annotations

import argparse
import json
import os
import sys
import time
import logging
try:
    from src.utils.backoff import sleep_ms as _sleep_ms  # type: ignore
except Exception:  # pragma: no cover - optional backoff helper
    _sleep_ms = None  # type: ignore

logger = logging.getLogger(__name__)

def _sleep_s(_sec: float) -> None:
    """Sleep helper with optional millisecond backoff utility.

    Falls back to time.sleep if the backoff helper is unavailable or raises.
    """
    try:
        if _sleep_ms:
            _sleep_ms(float(_sec) * 1000.0)
            return
    except Exception:  # pragma: no cover - defensive, we ignore and fallback
        pass
    time.sleep(_sec)
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

import numpy as np

# Make 'src' importable when running as a script
THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analytics.ml.quantile import QuantileRegressor  # type: ignore
from src.analytics.ml.conformal import ConformalBand  # type: ignore
from src.web.dashboard.core.csv_io import find_live_csv, load_csv_rows_full  # type: ignore
from src.web.dashboard.core.paths import project_root  # type: ignore
from src.error_handling import safe_write_text, safe_append_line  # type: ignore


MODEL_NAME = "sk_gbr_quantile"


def load_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_latest_features(row: Dict[str, Any], features: List[str]) -> np.ndarray:
    vals: List[float] = []
    for c in features:
        v = row.get(c)
        if v is None:
            vals.append(float("nan"))
            continue
        try:
            vals.append(float(v))
        except Exception:
            vals.append(float("nan"))
    arr = np.asarray(vals, dtype=float).reshape(1, -1)
    # Replace NaNs with last observation carried forward doesn't exist here; use zeros as a safe fallback
    arr = np.nan_to_num(arr, nan=0.0)
    return arr


def ensure_pred_csv(index: str) -> Path:
    base = project_root() / "data" / "ml" / "live_predictions"
    base.mkdir(parents=True, exist_ok=True)
    fp = base / f"{index.upper()}.csv"
    if not fp.exists():
        safe_write_text(fp, "timestamp,prediction,model,index,horizon,p10,p50,p90\n")
    return fp


def ensure_residual_store(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        safe_write_text(path, "timestamp,index,horizon,model,prediction,actual,residual\n")
    return path


def preload_residuals(path: Path, limit: int) -> List[float]:
    """Load up to 'limit' most recent residuals from a CSV store (if present)."""
    if not path.exists():
        return []
    vals: List[float] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            # Read all and take last 'limit' lines (skip header)
            lines = f.read().splitlines()
        for line in lines[1:][-int(max(0, limit)):]:
            parts = line.split(",")
            if not parts:
                continue
            try:
                r = float(parts[-1])
                vals.append(r)
            except Exception:
                continue
    except Exception:
        return []
    return vals


def append_residual(path: Path, ts_iso: str, index: str, horizon: str, model: str, pred: float, actual: float, resid: float) -> None:
    """Append one residual row using CSVIO facade with a safe fallback.

    Errors are logged (debug) and swallowed; exporter loop must remain resilient.
    """
    header = ["timestamp","index","horizon","model","prediction","actual","residual"]
    row: List[Any] = [ts_iso, index, horizon, model, pred, actual, resid]
    try:
        from src.storage.csvio import api as _csvio_api  # type: ignore
        _csvio_api.append_one(str(path), row, header)
    except Exception as e:  # pragma: no cover - facade failure path
        # Fallback to direct append if facade unavailable
        try:
            safe_append_line(path, f"{ts_iso},{index},{horizon},{model},{pred},{actual},{resid}")
        except Exception as fe:  # pragma: no cover - rare file append failure
            logger.debug("residual append fallback failed", extra={"error": str(fe), "path": str(path)})
        else:
            logger.debug("residual append via fallback", extra={"error": str(e), "path": str(path)})


def append_prediction(fp: Path, ts_iso: str, pred: float, index: str, horizon: str, p10: float, p50: float, p90: float) -> None:
    """Append one prediction row using CSVIO facade with a safe fallback.

    Structured debug logging on fallback paths only to avoid noise.
    """
    header = ["timestamp","prediction","model","index","horizon","p10","p50","p90"]
    row: List[Any] = [ts_iso, pred, MODEL_NAME, index, horizon, p10, p50, p90]
    try:
        from src.storage.csvio import api as _csvio_api  # type: ignore
        _csvio_api.append_one(str(fp), row, header)
    except Exception as e:  # pragma: no cover - facade failure path
        try:
            line = f"{ts_iso},{pred},{MODEL_NAME},{index},{horizon},{p10},{p50},{p90}"
            safe_append_line(fp, line)
        except Exception as fe:  # pragma: no cover - rare file append failure
            logger.debug("prediction append fallback failed", extra={"error": str(fe), "path": str(fp)})
        else:
            logger.debug("prediction append via fallback", extra={"error": str(e), "path": str(fp)})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="Quantile config JSON path")
    ap.add_argument("--artifact", required=True, help="Quantile model artifact path (.joblib)")
    ap.add_argument("--index", required=True, help="Index name (e.g., NIFTY)")
    ap.add_argument("--horizon", default="1", help="Horizon label to write")
    ap.add_argument("--interval", type=int, default=30, help="Polling interval seconds")
    ap.add_argument("--port", type=int, default=None, help="Optional Prometheus metrics HTTP port (starts server if prometheus_client available)")
    ap.add_argument("--expiry-tag", default="this_week")
    ap.add_argument("--offset", default="0")
    ap.add_argument("--coverage", type=float, default=0.8, help="Target coverage for conformal radius (0.5..0.99)")
    ap.add_argument("--band-window", type=int, default=600, help="Rolling residual window size (samples) for conformal radius")
    ap.add_argument("--residual-store", default=None, help="Optional CSV path to persist residual history (preloaded at startup)")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    feat_list = list(cfg.get("features") or [])
    target_col = str(cfg.get("target") or "tp")

    # Load model
    model = QuantileRegressor.load(args.artifact)

    # Optional Prometheus wiring (best-effort)
    METRICS_ENABLED = False
    g_p10 = g_p90 = g_p50 = g_radius = g_cov = None
    g_loop_errors = g_residual_errors = g_metrics_errors = None
    if args.port is not None:
        try:
            from prometheus_client import Gauge, Counter, start_http_server  # type: ignore

            g_p10 = Gauge("g6_ml_prediction_p10", "ML prediction lower quantile (p10)", ["index", "horizon", "model"])  # type: ignore
            g_p90 = Gauge("g6_ml_prediction_p90", "ML prediction upper quantile (p90)", ["index", "horizon", "model"])  # type: ignore
            g_p50 = Gauge("g6_ml_prediction_p50", "ML prediction median (p50)", ["index", "horizon", "model"])  # type: ignore
            g_radius = Gauge("g6_ml_conformal_radius", "Conformal band radius (abs error quantile) for target coverage", ["index", "horizon", "model"])  # type: ignore
            g_cov = Gauge("g6_ml_conformal_coverage_estimate", "Empirical coverage estimate for current conformal radius", ["index", "horizon", "model"])  # type: ignore
            g_loop_errors = Counter("g6_ml_quantile_exporter_loop_errors_total", "Total loop iteration errors", ["index", "horizon", "model"])  # type: ignore
            g_residual_errors = Counter("g6_ml_quantile_exporter_residual_errors_total", "Residual append failures", ["index", "horizon", "model"])  # type: ignore
            g_metrics_errors = Counter("g6_ml_quantile_exporter_metrics_errors_total", "Metrics export failures", ["index", "horizon", "model"])  # type: ignore
            start_http_server(int(args.port))
            METRICS_ENABLED = True
            logger.info("metrics server started", extra={"port": int(args.port)})
        except Exception as e:
            # prometheus_client missing or failed to bind — continue without metrics
            METRICS_ENABLED = False
            logger.debug("metrics init failed", extra={"error": str(e), "port": args.port})

    # Conformal residual window (rolling)
    conf = ConformalBand(target_coverage=float(max(0.5, min(0.99, args.coverage))), window=int(max(10, args.band_window)))

    # Optional residual store (preload history)
    residual_store: Optional[Path] = None
    if args.residual_store:
        residual_store = ensure_residual_store(Path(args.residual_store))
        # Preload up to band-window residuals
        prev = preload_residuals(residual_store, int(max(10, args.band_window)))
        if prev:
            conf.extend_from_residuals(prev)

    idx = str(args.index).upper()
    horizon = str(args.horizon)

    out_fp = ensure_pred_csv(idx)
    
    # Metrics CSV setup
    metrics_dir = project_root() / "data" / "ml" / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    metrics_fp = metrics_dir / f"{idx}_conformal.csv"
    if not metrics_fp.exists():
        with open(metrics_fp, "w", encoding="utf-8") as f:
            f.write("timestamp,index,horizon,model,radius,coverage_estimate,target_coverage\n")

    logger.info("writing predictions", extra={"path": str(out_fp), "index": idx, "horizon": horizon})

    while True:
        try:
            # Locate and load live CSV
            from datetime import date
            live_fp = find_live_csv(project_root() / "data" / "g6_data", idx, args.expiry_tag, args.offset, date.today())
            if not live_fp or not live_fp.exists():
                _sleep_s(args.interval)
                continue
            rows = load_csv_rows_full(live_fp)
            if not rows:
                _sleep_s(args.interval)
                continue
            last = rows[-1]
            X = get_latest_features(last, feat_list)
            preds = model.predict(X)
            def _extract_scalar(val):
                if isinstance(val, (list, np.ndarray)):
                    if len(val) > 0:
                        return float(val[0])
                    return float("nan")
                return float(val) if val is not None else float("nan")

            p50 = _extract_scalar(preds.get("p50", preds.get("q0.50")))
            p10 = _extract_scalar(preds.get("p10", preds.get("q0.10")))
            p90 = _extract_scalar(preds.get("p90", preds.get("q0.90")))
            pred = p50
            ts_iso = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            append_prediction(out_fp, ts_iso, pred, idx, horizon, p10, p50, p90)
            # Update conformal residuals using latest actual if present
            try:
                actual_val = last.get(target_col) if isinstance(last, dict) else None
                if actual_val is None:
                    actual_val = last.get("tp") if isinstance(last, dict) else None
                if actual_val is not None:
                    av = float(actual_val)
                    conf.update(pred=float(p50), actual=av)
                    # Persist residual if store enabled
                    if residual_store is not None:
                        try:
                            resid = abs(float(p50) - av)
                            append_residual(residual_store, ts_iso, idx, horizon, MODEL_NAME, float(p50), av, resid)
                        except Exception:
                            pass
            except Exception:
                pass
            # Export gauges if available
            try:
                rad = conf.radius(coverage=float(args.coverage))
                cov_est = 0.0
                try:
                    cov_est = float(conf.coverage_estimate(rad))
                except Exception:
                    pass
                
                # Write to metrics CSV
                with open(metrics_fp, "a", encoding="utf-8") as f:
                    f.write(f"{ts_iso},{idx},{horizon},{MODEL_NAME},{rad},{cov_est},{args.coverage}\n")

                if METRICS_ENABLED:
                    # set with labels
                    if g_p10 is not None:
                        g_p10.labels(index=idx, horizon=horizon, model=MODEL_NAME).set(float(p10))
                    if g_p90 is not None:
                        g_p90.labels(index=idx, horizon=horizon, model=MODEL_NAME).set(float(p90))
                    if g_p50 is not None:
                        g_p50.labels(index=idx, horizon=horizon, model=MODEL_NAME).set(float(p50))
                    if g_radius is not None:
                        g_radius.labels(index=idx, horizon=horizon, model=MODEL_NAME).set(float(rad))
                    if g_cov is not None:
                        g_cov.labels(index=idx, horizon=horizon, model=MODEL_NAME).set(cov_est)
            except Exception:
                # Don't let metrics failures stop the exporter
                pass
        except KeyboardInterrupt:
            break
        except Exception as e:
            # Log and continue; record metric counter if enabled
            print(f"Exporter Loop Error: {e}")
            import traceback
            traceback.print_exc()
            logger.warning("exporter loop error", extra={"error": str(e), "index": idx, "horizon": horizon})
            try:
                if METRICS_ENABLED and g_loop_errors is not None:  # type: ignore
                    g_loop_errors.labels(index=idx, horizon=horizon, model=MODEL_NAME).inc()  # type: ignore
            except Exception:  # pragma: no cover - metrics failure should never stop loop
                pass
        
        # Sleep inside the loop!
        _sleep_s(max(1, int(args.interval)))


if __name__ == "__main__":
    main()
