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
from pathlib import Path
from typing import Optional

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analytics.ml.kalman import Kalman1D  # type: ignore
from src.web.dashboard.core.csv_io import find_live_csv, load_csv_rows_full  # type: ignore
from src.web.dashboard.core.paths import project_root  # type: ignore
from src.error_handling import safe_write_text, safe_append_line  # type: ignore

MODEL_NAME = "kalman_smooth"


def ensure_out_csv(index: str) -> Path:
    base = project_root() / "data" / "ml" / "live_predictions"
    base.mkdir(parents=True, exist_ok=True)
    fp = base / f"{index.upper()}_smooth.csv"
    if not fp.exists():
        # Include shock_score column (may start blank) for downstream dashboards
        safe_write_text(fp, "timestamp,prediction,raw_tp,shock_score,model,index,horizon\n")
    return fp


def main() -> None:
    ap = argparse.ArgumentParser(description="Kalman smoother exporter for TP")
    ap.add_argument("--index", required=True)
    ap.add_argument("--horizon", default="1")
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--expiry-tag", default="this_week")
    ap.add_argument("--offset", default="0")
    ap.add_argument("--q", type=float, default=1.0, help="Process noise variance")
    ap.add_argument("--r", type=float, default=9.0, help="Measurement noise variance")
    ap.add_argument("--port", type=int, default=None, help="Prometheus metrics port")
    ap.add_argument("--shock-window", type=int, default=120, help="Rolling window size (observations) for shock std")
    args = ap.parse_args()

    METRICS_ENABLED = False
    g_smooth = g_raw = g_shock = None
    if args.port is not None:
        try:
            from prometheus_client import Gauge, start_http_server  # type: ignore
            g_smooth = Gauge("g6_ml_smoothed_tp", "Kalman smoothed TP", ["index", "horizon", "model"])  # type: ignore
            g_raw = Gauge("g6_ml_raw_tp", "Raw TP used by Kalman", ["index", "horizon", "model"])  # type: ignore
            g_shock = Gauge("g6_ml_tp_shock_score", "TP shock score (|raw - smooth| / rolling_std)", ["index", "horizon", "model"])  # type: ignore
            start_http_server(int(args.port))
            METRICS_ENABLED = True
            print(f"Prometheus metrics server started on port {args.port}")
        except Exception:
            METRICS_ENABLED = False

    idx = str(args.index).upper()
    horizon = str(args.horizon)
    out_fp = ensure_out_csv(idx)
    print(f"Writing Kalman-smoothed TP to {out_fp}")

    kf = Kalman1D(q=float(args.q), r=float(args.r), x0=None, p0=1.0)
    kf.reset()

    # Rolling buffer for shock score std estimation
    residuals: list[float] = []
    max_window = max(10, int(args.shock_window))

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
            tp = last.get("tp")
            try:
                tp_val = float(tp) if tp is not None else float("nan")
            except Exception:
                tp_val = float("nan")
            if tp_val == tp_val:  # not NaN
                smooth = kf.update(tp_val)
                resid = tp_val - smooth
                residuals.append(resid)
                if len(residuals) > max_window:
                    residuals = residuals[-max_window:]
                # Compute rolling std (population) ignoring extremely small values
                shock_score = float("nan")
                if len(residuals) >= 10:
                    import math
                    mean_r = sum(residuals) / len(residuals)
                    var_r = sum((r - mean_r) ** 2 for r in residuals) / len(residuals)
                    std_r = math.sqrt(var_r)
                    if std_r > 1e-6:
                        shock_score = abs(resid) / std_r
                ts_iso = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
                line = f"{ts_iso},{smooth:.6f},{tp_val:.6f},{(shock_score if shock_score == shock_score else float('nan')):.6f},{MODEL_NAME},{idx},{horizon}\n"
                safe_append_line(out_fp, line.rstrip("\n"))
                if METRICS_ENABLED:
                    try:
                        if g_smooth is not None:
                            g_smooth.labels(index=idx, horizon=horizon, model=MODEL_NAME).set(smooth)
                        if g_raw is not None:
                            g_raw.labels(index=idx, horizon=horizon, model=MODEL_NAME).set(tp_val)
                        if g_shock is not None and shock_score == shock_score:
                            g_shock.labels(index=idx, horizon=horizon, model=MODEL_NAME).set(shock_score)
                    except Exception:
                        pass
        except KeyboardInterrupt:
            break
        except Exception as e:
            sys.stderr.write(f"[warn] kalman smoother loop error: {e}\n")
    _sleep_s(max(1, int(args.interval)))


if __name__ == "__main__":
    main()
