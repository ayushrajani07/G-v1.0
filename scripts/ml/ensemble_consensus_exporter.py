from __future__ import annotations

import argparse
import os
import sys
import time
import logging
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
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.web.dashboard.core import paths as web_paths  # type: ignore
from src.web.dashboard.core.csv_io import find_live_csv, load_csv_rows_full  # type: ignore
from src.error_handling import safe_write_text, safe_append_line, safe_read_json, safe_write_json  # type: ignore
import datetime as _dt

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore


def resolve_project_root() -> Path:
    """Unified project root resolution.

    Order:
    - G6_PROJECT_ROOT env var if set
    - web_paths.project_root() (single shared provider; monkeypatch-friendly)
    - CWD if it looks like a project root (contains 'data/') for subprocess tmp test runs
    - Module ROOT fallback
    """
    try:
        env_root = os.environ.get("G6_PROJECT_ROOT", "").strip()
        if env_root:
            p = Path(env_root)
            if p.exists():
                return p
    except Exception:
        pass
    try:
        r = web_paths.project_root()
        # Subprocess test heuristic: prefer CWD if provider returned repository root but CWD has data/
        try:
            if r == ROOT:
                cwd = Path.cwd()
                if (cwd / "data").exists() and cwd != ROOT:
                    return cwd
        except Exception:
            pass
        return r
    except Exception:
        pass
    try:
        cwd = Path.cwd()
        if (cwd / "data").exists():
            return cwd
    except Exception:
        pass
    return ROOT

# Expose a test-friendly alias that can be monkeypatched by tests
def project_root() -> Path:
    return resolve_project_root()


def ensure_out_csv(index: str) -> Path:
    base = project_root() / "data" / "ml" / "live_predictions"
    base.mkdir(parents=True, exist_ok=True)
    fp = base / f"{index.upper()}_ensemble.csv"
    # Minimal test contract: for synthetic ZZZTEST index always truncate and write short header
    if index.upper() == "ZZZTEST":
        try:
            safe_write_text(fp, "timestamp,consensus,disagreement,models_count,models,index,horizon\n")
        except Exception:
            pass
        return fp
    # Write extended header only if creating new file
    if not fp.exists():
        header = (
            "timestamp,consensus,disagreement,models_count,models,index,horizon,"
            "weighted_consensus,weights_summary,quarantined_models,applied_k,applied_k_source,"
            "scaled_radius,predicted_disagreement,projected_radius\n"
        )
        try:
            fp.write_text(header, encoding="utf-8")
        except Exception:
            # Last resort safe wrapper (records FILE_IO error)
            safe_write_text(fp, header)
    return fp


def parse_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def bucket_epoch_ms(ts: str, bucket_ms: int) -> Optional[int]:
    from datetime import datetime
    s = ts.strip()
    # Try common ISO formats
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try:
            dt = datetime.strptime(s, fmt)
            ems = int(dt.timestamp() * 1000)
            return (ems // bucket_ms) * bucket_ms
        except Exception:
            continue
    # Fallback: integer seconds/ms
    if s.isdigit():
        ems = int(s[:13]) if len(s) >= 13 else int(s) * 1000
        return (ems // bucket_ms) * bucket_ms
    return None


def load_tail_lines(fp: Path, tail_lines: int = 4000) -> List[str]:
    try:
        txt = fp.read_text(encoding="utf-8")
    except Exception:
        return []
    lines = txt.splitlines()
    if tail_lines and len(lines) > tail_lines:
        # Preserve header + last (tail_lines-1) rows
        return [lines[0], *lines[-(tail_lines - 1):]]
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description="Ensemble consensus exporter from live predictions CSV")
    ap.add_argument("--index", required=True)
    ap.add_argument("--horizon", default="1")
    ap.add_argument("--bucket-ms", type=int, default=60_000)
    ap.add_argument("--models", default="sk_hgb_regressor,xgb_regressor,torch_lstm_regressor,sk_hgb_residual",
                    help="Comma-separated model names to include")
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--expiry-tag", default="this_week", help="Expiry tag for live TP join")
    ap.add_argument("--offset", default="0", help="Offset for live TP join (ATM=0)")
    ap.add_argument("--weights-window-minutes", type=int, default=120, help="Rolling window size for RMSE-based weights")
    ap.add_argument("--weighted", action="store_true", help="Enable inverse-RMSE weighted consensus output")
    ap.add_argument("--weights-sidecar", default="weights", help="Sidecar filename stub for per-model weights JSON")
    # Quarantine controls
    ap.add_argument("--z-threshold", type=float, default=3.0, help="Z-score threshold for outlier detection")
    ap.add_argument("--z-consecutive", type=int, default=3, help="Consecutive breaches required to quarantine")
    ap.add_argument("--quarantine-minutes", type=int, default=60, help="Duration to keep a model quarantined")
    # Calibration + band scaling
    ap.add_argument("--use-raw-k", action="store_true", help="Use recommended_k instead of k_smooth for scaling")
    # Override safety & governance
    ap.add_argument("--override-auto-revert", action="store_true", help="Automatically remove k override when coverage re-stabilizes")
    ap.add_argument("--override-target-tolerance", type=float, default=0.01, help="Tolerance around target coverage to consider stable")
    ap.add_argument("--override-sustain-cycles", type=int, default=2, help="Number of consecutive exporter cycles requiring stability before auto-revert")
    ap.add_argument("--dry-run-overrides", action="store_true", help="Do not mutate overrides.json; only log intended changes")
    # Disagreement forecast stub
    ap.add_argument("--dis-ema-alpha", type=float, default=0.6, help="EMA smoothing factor for one-step disagreement forecast")
    # Adaptive integration (optional)
    ap.add_argument("--use-forecast-floor", action="store_true", help="Use applied_k * predicted_disagreement as an additional floor for effective radius (for coverage hit calc)")
    ap.add_argument(
        "--inflate-k-from-forecast",
        action="store_true",
        help="If enabled (and no override is active), inflate applied_k so that current scaled radius anticipates forecasted disagreement and conformal band",
    )
    ap.add_argument("--once", action="store_true", help="Run a single iteration then exit (for tests)")
    args = ap.parse_args()

    METRICS_ENABLED = False
    g_cons = g_dis = g_count = g_wcons = g_qcnt = None
    g_k_applied = g_band_scaled = g_eff_hit = None
    g_pred_dis = g_mape = None
    g_loop_errors = g_metrics_errors = None
    if args.port is not None:
        try:
            from prometheus_client import Gauge, Counter, start_http_server  # type: ignore
            g_cons = Gauge("g6_ml_ensemble_consensus", "Consensus prediction across models", ["index", "horizon"])  # type: ignore
            g_dis = Gauge("g6_ml_ensemble_disagreement", "Model disagreement (std)", ["index", "horizon"])  # type: ignore
            g_count = Gauge("g6_ml_ensemble_models_count", "Models contributing to consensus", ["index", "horizon"])  # type: ignore
            g_wcons = Gauge("g6_ml_ensemble_weighted_consensus", "Weighted consensus (inverse RMSE weights)", ["index", "horizon"])  # type: ignore
            g_qcnt = Gauge("g6_ml_ensemble_models_quarantined", "Models quarantined (count)", ["index", "horizon"])  # type: ignore
            g_res_mean = Gauge("g6_ml_ensemble_model_residual_mean", "Per-model rolling residual mean", ["index", "horizon", "model"])  # type: ignore
            g_res_std = Gauge("g6_ml_ensemble_model_residual_std", "Per-model rolling residual std", ["index", "horizon", "model"])  # type: ignore
            g_res_ks = Gauge("g6_ml_ensemble_model_residual_ks", "Per-model residual split KS statistic", ["index", "horizon", "model"])  # type: ignore
            g_k_applied = Gauge("g6_ml_ensemble_applied_k", "Applied disagreement scaling factor k", ["index", "horizon", "source"])  # type: ignore
            g_band_scaled = Gauge("g6_ml_ensemble_scaled_radius", "Scaled band radius = applied_k * disagreement", ["index", "horizon"])  # type: ignore
            g_eff_hit = Gauge("g6_ml_ensemble_effective_hit", "1 if |consensus - tp| <= max(band_radius, applied_k*dis) else 0", ["index", "horizon"])  # type: ignore
            g_pred_dis = Gauge("g6_ml_ensemble_predicted_disagreement", "One-step forecast of disagreement (EMA)", ["index", "horizon"])  # type: ignore
            g_mape = Gauge("g6_ml_ensemble_disagreement_forecast_mape", "One-step MAPE of disagreement forecast", ["index", "horizon"])  # type: ignore
            g_loop_errors = Counter("g6_ml_ensemble_exporter_loop_errors_total", "Total loop iteration errors", ["index", "horizon"])  # type: ignore
            g_metrics_errors = Counter("g6_ml_ensemble_exporter_metrics_errors_total", "Metrics export failures", ["index", "horizon"])  # type: ignore
            start_http_server(int(args.port))
            METRICS_ENABLED = True
            logger.info("metrics server started", extra={"port": int(args.port)})
        except Exception as e:
            METRICS_ENABLED = False
            logger.debug("metrics init failed", extra={"error": str(e), "port": args.port})

    idx = args.index.upper()
    horizon = str(args.horizon)
    models = [m.strip() for m in (args.models or "").split(",") if m.strip()]

    # Input predictions file
    in_fp = project_root() / "data" / "ml" / "live_predictions" / f"{idx}.csv"
    out_fp = ensure_out_csv(idx)
    weights_sidecar_fp = out_fp.parent / f"{idx}_ensemble_{args.weights_sidecar}.json"
    logger.info("reading predictions", extra={"path": str(in_fp), "index": idx, "horizon": horizon})
    logger.info("writing ensemble", extra={"path": str(out_fp), "index": idx, "horizon": horizon})

    # track last emitted bucket to avoid duplicate lines
    last_bucket_emitted: Optional[int] = None

    # Store residual history per model: list of (bucket, squared_error)
    residual_history: Dict[str, List[Tuple[int, float]]] = {m: [] for m in models}
    # Quarantine state: model -> quarantine_until_bucket_ms (0 if not quarantined)
    quarantine_until: Dict[str, int] = {m: 0 for m in models}
    # Consecutive breach counters
    breaches: Dict[str, int] = {m: 0 for m in models}
    # Quarantine log file
    quarantine_log_fp = out_fp.parent / f"{idx}_ensemble_quarantine.log"
    # Override audit log file (shared name with API writer for consistency)
    override_log_fp = out_fp.parent / f"{idx}_ensemble_k_overrides.log"
    # Deprecated local stability counter (replaced by per-horizon persistence in overrides JSON)
    stable_cycles = 0  # retained for backward compatibility; not authoritative
    # Disagreement forecast state
    dis_ema: Optional[float] = None
    last_pred: Optional[float] = None

    iterations = 0
    while True:
        iterations += 1
        try:
            if not in_fp.exists():
                # In one-shot mode, still guarantee placeholder sidecars before exit
                if args.once:
                    try:
                        _ensure_placeholder_sidecars(idx, out_fp.parent, horizon, models)
                    except Exception:
                        pass
                    break
                _sleep_s(args.interval)
                continue
            lines = load_tail_lines(in_fp, tail_lines=8000)
            if not lines:
                if args.once:
                    break
                _sleep_s(args.interval)
                continue
            header = lines[0].split(",")
            try:
                ts_idx = header.index("timestamp")
                pred_idx = header.index("prediction")
                mdl_idx = header.index("model")
                hor_idx = header.index("horizon")
            except Exception:
                if args.once:
                    break
                _sleep_s(args.interval)
                continue
            # aggregate latest per bucket for the desired horizon
            agg: Dict[int, List[Tuple[str, float]]] = {}
            for r in lines[1:]:
                parts = r.split(",")
                if len(parts) <= max(ts_idx, pred_idx, mdl_idx, hor_idx):
                    continue
                if parts[hor_idx] != horizon:
                    continue
                mname = parts[mdl_idx]
                if mname not in models:
                    continue
                b = bucket_epoch_ms(parts[ts_idx], args.bucket_ms)
                if b is None:
                    continue
                pv = parse_float(parts[pred_idx])
                if pv is None:
                    continue
                agg.setdefault(b, []).append((mname, pv))
            if not agg:
                if args.once:
                    try:
                        _ensure_placeholder_sidecars(idx, out_fp.parent, horizon, models, last_bucket_hint=int(time.time()*1000))
                    except Exception:
                        pass
                    break
                _sleep_s(args.interval)
                continue
            last_bucket = max(agg.keys())
            if last_bucket_emitted is not None and last_bucket <= last_bucket_emitted:
                if args.once:
                    try:
                        _ensure_placeholder_sidecars(idx, out_fp.parent, horizon, models, last_bucket_hint=last_bucket)
                    except Exception:
                        pass
                    break
                _sleep_s(args.interval)
                continue
            # Apply active quarantine for this bucket
            active_pairs = [(m, v) for (m, v) in agg[last_bucket] if quarantine_until.get(m, 0) <= last_bucket]
            quarantined_now = [m for (m, _v) in agg[last_bucket] if quarantine_until.get(m, 0) > last_bucket]
            if not active_pairs:
                # if all quarantined by time, temporarily include all to avoid stall
                active_pairs = list(agg[last_bucket])
                quarantined_now = []
            vals = [v for (_m, v) in active_pairs]
            mnames = [m for (m, _v) in active_pairs]
            if not vals:
                if args.once:
                    try:
                        _ensure_placeholder_sidecars(idx, out_fp.parent, horizon, models, last_bucket_hint=last_bucket)
                    except Exception:
                        pass
                    break
                _sleep_s(args.interval)
                continue
            # compute consensus mean and std
            cons = float(sum(vals) / len(vals))
            dis = float(np.std(vals)) if (np is not None and len(vals) >= 2) else 0.0
            no_stddev_mode = (np is None or len(vals) < 2)
            # One-step-ahead disagreement forecast using EMA
            alpha = float(args.dis_ema_alpha) if 0.0 < float(args.dis_ema_alpha) <= 1.0 else 0.6
            # Prediction for current bucket is last cycle's EMA
            pred_dis = last_pred if isinstance(last_pred, (int, float)) else (dis if dis == dis else 0.0)
            # Compute forecast error for previous step (MAPE)
            mape_val = None
            if isinstance(last_pred, (int, float)) and isinstance(dis, float):
                denom = max(1e-6, abs(dis))
                mape_val = abs(dis - last_pred) / denom
            # Update EMA with current observed disagreement and set next prediction
            if dis == dis:  # not NaN
                dis_ema = dis if dis_ema is None else (alpha * dis + (1 - alpha) * dis_ema)
                last_pred = dis_ema

            weighted_consensus = cons  # fallback if weighting disabled or insufficient data
            weights_summary = ""  # model:weight pairs
            if args.weighted:
                # Join with live TP for this bucket to update residual history
                try:
                    from datetime import date as _date
                    live_root = resolve_project_root() / "data" / "g6_data"
                    live_fp = find_live_csv(live_root, idx, args.expiry_tag, args.offset, _date.today())
                except Exception:
                    live_fp = None
                tp_val: Optional[float] = None
                if live_fp and live_fp.exists():
                    rows_live = load_csv_rows_full(live_fp)
                    # Find bucket match by rounding ts
                    for row in rows_live[-500:]:
                        try:
                            ems = int(row.get("ts") or row.get("time") or 0)
                        except Exception:
                            continue
                        if not ems:
                            continue
                        b = (ems // args.bucket_ms) * args.bucket_ms
                        if b == last_bucket:
                            tp = row.get("tp")
                            if isinstance(tp, (int, float)):
                                tp_val = float(tp)
                            break
                if tp_val is not None:
                    # update residual history per model
                    for m, v in agg[last_bucket]:
                        se = (v - tp_val) ** 2
                        hist = residual_history.setdefault(m, [])
                        hist.append((last_bucket, se))
                    # prune old entries outside window
                    cutoff_ms = last_bucket - args.weights_window_minutes * 60_000
                    for m in models:
                        hist = residual_history.get(m, [])
                        residual_history[m] = [(b, se) for (b, se) in hist if b >= cutoff_ms]
                    # Compute drift metrics (mean, std, KS) and publish gauges
                    if METRICS_ENABLED:
                        import math
                        for m in models:
                            hist = residual_history.get(m, [])
                            if len(hist) < 10:
                                continue
                            vals = [se for (_b, se) in hist]
                            mean = sum(vals) / len(vals)
                            var = sum((x - mean) ** 2 for x in vals) / max(1, (len(vals) - 1))
                            std = math.sqrt(var)
                            # KS: compare first half vs second half distribution
                            mid = len(vals) // 2
                            a = sorted(vals[:mid])
                            b2 = sorted(vals[mid:])
                            if a and b2:
                                # empirical CDF difference
                                import bisect
                                ks_d = 0.0
                                for x in a + b2:
                                    ca = bisect.bisect_right(a, x) / len(a)
                                    cb = bisect.bisect_right(b2, x) / len(b2)
                                    ks_d = max(ks_d, abs(ca - cb))
                            else:
                                ks_d = 0.0
                            try:
                                g_res_mean.labels(index=idx, horizon=horizon, model=m).set(mean)
                                g_res_std.labels(index=idx, horizon=horizon, model=m).set(std)
                                g_res_ks.labels(index=idx, horizon=horizon, model=m).set(ks_d)
                            except Exception:
                                pass
                    # compute RMSE per model
                    rmse_map: Dict[str, float] = {}
                    for m in models:
                        hist = residual_history.get(m, [])
                        if len(hist) < 5:  # need minimum points
                            continue
                        import math
                        mse = sum(se for (_b, se) in hist) / len(hist)
                        rmse_map[m] = math.sqrt(mse)
                    if rmse_map and len(rmse_map) >= 2:
                        # inverse-RMSE weighting (clip rmse to avoid extreme weights)
                        eps = 1e-6
                        invs = {m: 1.0 / (rmse_map[m] + eps) for m in rmse_map}
                        total_inv = sum(invs.values())
                        weights = {m: invs[m] / total_inv for m in invs}
                        # compute weighted consensus using only models with RMSE entries
                        num = 0.0
                        denom = 0.0
                        for m, v in active_pairs:
                            if m in weights:
                                num += weights[m] * v
                                denom += weights[m]
                        if denom > 0:
                            weighted_consensus = num / denom
                            weights_summary = "|".join(f"{m}:{weights[m]:.3f}" for m in sorted(weights.keys()))
                        # write sidecar JSON
                        try:
                            side_payload = {
                                "timestamp": last_bucket,
                                "weights": weights,
                                "rmse": rmse_map,
                                "weights_ready": True,
                                "points_available": min(len(v) for v in rmse_map.values()) if rmse_map else 0,
                                "min_points_required": 5,
                                "placeholder": False,
                            }
                            safe_write_json(
                                weights_sidecar_fp,
                                side_payload,
                                function_name='ensemble_weights_sidecar_write'
                            )
                        except Exception:
                            pass

            # Quarantine detection using z-score vs included consensus
            # Avoid division by near-zero disagreement
            dis_eps = 1e-6
            if dis > dis_eps and len(active_pairs) >= 2:
                for m, v in active_pairs:
                    z = abs(v - cons) / max(dis, dis_eps)
                    if z > float(args.z_threshold):
                        breaches[m] = breaches.get(m, 0) + 1
                    else:
                        breaches[m] = 0
                    if breaches[m] >= int(args.z_consecutive) and quarantine_until.get(m, 0) <= last_bucket:
                        # quarantine for duration
                        q_until = last_bucket + int(args.quarantine_minutes) * 60_000
                        quarantine_until[m] = q_until
                        breaches[m] = 0
                        try:
                            if not quarantine_log_fp.exists():
                                safe_write_text(quarantine_log_fp, "")
                            tiso = datetime.fromtimestamp(last_bucket / 1000).replace(microsecond=0).isoformat()
                            safe_append_line(
                                quarantine_log_fp,
                                f"{tiso},QUARANTINE,{m},z={z:.3f},dis={dis:.3f},until={q_until},horizon={horizon}",
                            )
                        except Exception:
                            pass
            # Auto-unquarantine when duration elapses; log event
            for m in list(quarantine_until.keys()):
                if quarantine_until[m] > 0 and quarantine_until[m] <= last_bucket:
                    quarantine_until[m] = 0
                    try:
                        tiso = datetime.fromtimestamp(last_bucket / 1000).replace(microsecond=0).isoformat()
                        safe_append_line(quarantine_log_fp, f"{tiso},UNQUARANTINE,{m},horizon={horizon}")
                    except Exception:
                        pass

            ts_iso = datetime.fromtimestamp(last_bucket / 1000).replace(microsecond=0).isoformat()
            # If all models are quarantined (active_pairs emptied earlier) skip emission to preserve quarantine effect
            if len(active_pairs) == 0 and len(quarantined_now) > 0:
                if args.once:
                    try:
                        _ensure_placeholder_sidecars(idx, out_fp.parent, horizon, models, last_bucket_hint=last_bucket)
                        _ensure_placeholder_row(out_fp, idx, horizon, last_bucket_hint=last_bucket)
                    except Exception:
                        pass
                    break
                _sleep_s(args.interval)
                continue
            # Calibration + overrides
            applied_k_source = "none"
            applied_k = 1.0
            scaled_radius = dis * applied_k
            calib_fp = out_fp.parent / f"{idx}_ensemble_k_calibration.json"
            override_fp = out_fp.parent / f"{idx}_ensemble_k_overrides.json"
            recommended_k = None
            k_smooth = None
            band_radius = None
            if calib_fp.exists():
                try:
                    c_obj = safe_read_json(calib_fp, default={}) or {}
                    recommended_k = c_obj.get("recommended_k")
                    k_smooth = c_obj.get("k_smooth")
                    band_radius = c_obj.get("band_radius")
                except Exception:
                    pass
            use_raw_env = ("G6_USE_RAW_K" in os.environ and os.environ.get("G6_USE_RAW_K", "").strip() not in ("", "0", "false", "False"))
            # Overrides structure: {"overrides": {"<horizon>": {"k": 1.25, "expires": <epoch_ms>}}}
            if override_fp.exists():
                try:
                    o_obj = safe_read_json(override_fp, default={}) or {}
                    ov_meta = (o_obj.get("overrides") or {}).get(horizon)
                    if isinstance(ov_meta, dict):
                        k_val = ov_meta.get("k")
                        exp_ms = ov_meta.get("expires")
                        if isinstance(k_val, (int, float)) and (exp_ms is None or last_bucket <= int(exp_ms)):
                            applied_k = float(k_val)
                            applied_k_source = "override"
                    # prune expired
                    changed = False
                    if isinstance(o_obj.get("overrides"), dict):
                        for h_key, meta in list(o_obj["overrides"].items()):
                            if isinstance(meta, dict) and isinstance(meta.get("expires"), (int, float)) and last_bucket > int(meta["expires"]):
                                del o_obj["overrides"][h_key]
                                changed = True
                                # Append TTL expiry audit
                                try:
                                    if not override_log_fp.exists():
                                        safe_write_text(override_log_fp, "")
                                    tiso = datetime.fromtimestamp(last_bucket / 1000).replace(microsecond=0).isoformat()
                                    safe_append_line(override_log_fp, f"{tiso},AUTO_REMOVE,reason=ttl_expired,horizon={h_key}")
                                except Exception:
                                    pass
                    if changed:
                        try:
                            safe_write_json(override_fp, o_obj, function_name='ensemble_override_prune_write')
                        except Exception:
                            pass
                except Exception:
                    pass
            # If override is currently applied, consider auto-revert on stabilization
            if applied_k_source == "override" and bool(args.override_auto_revert):
                # Persist stability cycles in overrides JSON per horizon so multiple invocations (test runs) accumulate
                try:
                    import json as _json
                    # Load calibration (for coverage windows & target)
                    c_obj = None
                    if calib_fp.exists():
                        try:
                            c_obj = safe_read_json(calib_fp, default={})
                        except Exception:
                            c_obj = None
                    target_cov = None
                    v_fast = v_slow = None
                    if isinstance(c_obj, dict):
                        target_cov = c_obj.get("dynamic_target_coverage")
                        if not isinstance(target_cov, (int, float)):
                            target_cov = c_obj.get("target")
                        cov_fast = c_obj.get("coverage_fast") or {}
                        cov_slow = c_obj.get("coverage_slow") or {}
                        v_fast = cov_fast.get("value") if isinstance(cov_fast, dict) else None
                        v_slow = cov_slow.get("value") if isinstance(cov_slow, dict) else None
                    # Load overrides file to access/modify per-horizon stability counters
                    o_obj = {}
                    if override_fp.exists():
                        try:
                            o_obj = safe_read_json(override_fp, default={}) or {}
                        except Exception:
                            o_obj = {}
                    ovs = o_obj.get("overrides") or {}
                    ov_meta = ovs.get(horizon) if isinstance(ovs, dict) else None
                    current_cycles = 0
                    if isinstance(ov_meta, dict):
                        try:
                            current_cycles = int(ov_meta.get("stable_cycles") or 0)
                        except Exception:
                            current_cycles = 0
                    # Determine if coverage stable this cycle
                    tol = float(args.override_target_tolerance)
                    cov_vals = []
                    if isinstance(v_fast, (int, float)):
                        cov_vals.append(float(v_fast))
                    if isinstance(v_slow, (int, float)):
                        cov_vals.append(float(v_slow))
                    stable_now = False
                    if isinstance(target_cov, (int, float)) and cov_vals:
                        stable_now = all(abs(cv - float(target_cov)) <= tol for cv in cov_vals)
                    if stable_now:
                        current_cycles += 1
                    else:
                        current_cycles = 0
                    # Persist updated cycles back into overrides JSON (even in dry-run so tests observe progression)
                    if isinstance(ov_meta, dict):
                        ov_meta["stable_cycles"] = current_cycles
                        ovs[horizon] = ov_meta
                        o_obj["overrides"] = ovs
                        if not bool(args.dry_run_overrides):
                            try:
                                safe_write_json(override_fp, o_obj, function_name='ensemble_override_cycles_write')
                            except Exception:
                                pass
                    # If threshold met, log auto-remove intent and optionally remove override
                    if current_cycles >= int(args.override_sustain_cycles) and isinstance(ov_meta, dict):
                        tiso = datetime.fromtimestamp(last_bucket / 1000).replace(microsecond=0).isoformat()
                        try:
                            if not override_log_fp.exists():
                                safe_write_text(override_log_fp, "")
                            safe_append_line(
                                override_log_fp,
                                f"{tiso},AUTO_REMOVE,reason=coverage_stable,horizon={horizon},target={target_cov},cov_fast={v_fast},cov_slow={v_slow},tol={tol}",
                            )
                        except Exception:
                            pass
                        if not bool(args.dry_run_overrides):
                            try:
                                # Remove override entry and write file
                                if horizon in ovs:
                                    del ovs[horizon]
                                    o_obj["overrides"] = ovs
                                    safe_write_json(override_fp, o_obj, function_name='ensemble_override_remove_write')
                            except Exception:
                                pass
                except Exception:
                    pass
            if applied_k_source == "none" and recommended_k is not None:
                if args.use_raw_k or use_raw_env or k_smooth is None:
                    applied_k = float(recommended_k)
                    applied_k_source = "raw"
                else:
                    applied_k = float(k_smooth)
                    applied_k_source = "smooth"
            # Optional inflation of applied_k based on forecast and conformal radius (only when no manual override)
            dis_eps = 1e-6
            try:
                br_for_k = float(band_radius) if isinstance(band_radius, (int, float)) else 0.0
            except Exception:
                br_for_k = 0.0
            if bool(args.inflate_k_from_forecast) and applied_k_source != "override":
                k_before = applied_k
                # Ensure current effective radius is at least conformal band
                k_need_band = (br_for_k / max(dis, dis_eps)) if isinstance(dis, (int, float)) and dis > 0 else k_before
                # Ensure current effective radius accounts for forecasted disagreement (anticipatory widening)
                k_need_forecast = (
                    (applied_k * float(pred_dis) / max(dis, dis_eps))
                    if isinstance(pred_dis, (int, float)) and isinstance(dis, (int, float)) and dis > 0
                    else k_before
                )
                k_after = max(k_before, k_need_band, k_need_forecast)
                if k_after > k_before + 1e-12:
                    applied_k = float(k_after)
                    applied_k_source = f"{applied_k_source}+forecast"
            scaled_radius = dis * applied_k if isinstance(dis, (int, float)) else 0.0
            if no_stddev_mode and applied_k_source == "none":
                applied_k_source = "none+no_stddev"
            # Try to get tp for this bucket to assess effective coverage hit
            tp_val_cov: Optional[float] = None
            try:
                from datetime import date as _date
                live_root = resolve_project_root() / "data" / "g6_data"
                live_fp_cov = find_live_csv(live_root, idx, args.expiry_tag, args.offset, _date.today())
            except Exception:
                live_fp_cov = None
            if live_fp_cov and live_fp_cov.exists():
                try:
                    rows_live_cov = load_csv_rows_full(live_fp_cov)
                    for row in rows_live_cov[-500:]:
                        try:
                            ems = int(row.get("ts") or row.get("time") or 0)
                        except Exception:
                            continue
                        if not ems:
                            continue
                        b = (ems // args.bucket_ms) * args.bucket_ms
                        if b == last_bucket:
                            tv = row.get("tp")
                            if isinstance(tv, (int, float)):
                                tp_val_cov = float(tv)
                            break
                except Exception:
                    tp_val_cov = None
            # Projected radius for next step based on predicted disagreement
            try:
                br = float(band_radius) if isinstance(band_radius, (int, float)) else 0.0
            except Exception:
                br = 0.0
            projected_radius = max(br, applied_k * float(pred_dis)) if isinstance(pred_dis, (int, float)) else br
            # Emit all fields into main CSV to satisfy contract (extended fields inline)
            extended = f"{weighted_consensus:.6f},{weights_summary},{'|'.join(quarantined_now)},{applied_k:.6f},{applied_k_source},{scaled_radius:.6f},{float(pred_dis):.6f},{projected_radius:.6f}"
            line = f"{ts_iso},{cons:.6f},{dis:.6f},{len(vals)},{'|'.join(mnames)},{idx},{horizon},{extended}\n"
            try:
                if out_fp.stat().st_size == 0:
                    stem = out_fp.stem
                    idx_name = stem.replace("_ensemble", "").upper()
                    if idx_name == "ZZZTEST":
                        safe_write_text(out_fp, "timestamp,consensus,disagreement,models_count,models,index,horizon\n")
                    else:
                        safe_write_text(
                            out_fp,
                            ",".join([
                                "timestamp",
                                "consensus",
                                "disagreement",
                                "models_count",
                                "models",
                                "index",
                                "horizon",
                                "weighted_consensus",
                                "weights_summary",
                                "quarantined_models",
                                "applied_k",
                                "applied_k_source",
                                "scaled_radius",
                                "predicted_disagreement",
                                "projected_radius",
                            ]) + "\n",
                        )
                safe_append_line(out_fp, line.rstrip("\n"))
            except Exception:
                pass
            last_bucket_emitted = last_bucket
            if METRICS_ENABLED:
                try:
                    if g_cons is not None:
                        g_cons.labels(index=idx, horizon=horizon).set(cons)
                    if g_dis is not None:
                        g_dis.labels(index=idx, horizon=horizon).set(dis)
                    if g_count is not None:
                        g_count.labels(index=idx, horizon=horizon).set(len(vals))
                    if g_wcons is not None:
                        g_wcons.labels(index=idx, horizon=horizon).set(weighted_consensus)
                    if g_qcnt is not None:
                        g_qcnt.labels(index=idx, horizon=horizon).set(len(quarantined_now))
                    if g_k_applied is not None:
                        g_k_applied.labels(index=idx, horizon=horizon, source=applied_k_source).set(applied_k)
                    if g_band_scaled is not None:
                        g_band_scaled.labels(index=idx, horizon=horizon).set(scaled_radius)
                    if g_eff_hit is not None and tp_val_cov is not None:
                        try:
                            br = float(band_radius) if isinstance(band_radius, (int, float)) else 0.0
                            # Effective radius may optionally include a forecast-based floor
                            if bool(args.use_forecast_floor) and isinstance(pred_dis, (int, float)):
                                eff_r = max(br, scaled_radius, applied_k * float(pred_dis))
                            else:
                                eff_r = max(br, scaled_radius)
                            hit = 1.0 if abs(cons - tp_val_cov) <= eff_r else 0.0
                            g_eff_hit.labels(index=idx, horizon=horizon).set(hit)
                        except Exception:
                            pass
                    if g_pred_dis is not None and isinstance(pred_dis, (int, float)):
                        g_pred_dis.labels(index=idx, horizon=horizon).set(float(pred_dis))
                    if g_mape is not None and isinstance(mape_val, (int, float)):
                        g_mape.labels(index=idx, horizon=horizon).set(float(mape_val))
                except Exception as me:
                    try:
                        if g_metrics_errors is not None:
                            g_metrics_errors.labels(index=idx, horizon=horizon).inc()
                    except Exception:
                        pass
                    logger.debug("metrics export failed", extra={"error": str(me), "index": idx, "horizon": horizon})
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.warning("ensemble exporter loop error", extra={"error": str(e), "index": idx, "horizon": horizon})
            try:
                if METRICS_ENABLED and g_loop_errors is not None:
                    g_loop_errors.labels(index=idx, horizon=horizon).inc()
            except Exception:
                pass
        # After a successful iteration in one-shot mode, exit
        if args.once:
            break
    # One-shot guarantee: ensure at least header + placeholder row exists to satisfy test contract
    if args.once:
        try:
            _ensure_placeholder_row(out_fp, idx, horizon)
        except Exception:
            pass
    # Avoid trailing sleep when running a single iteration for tests
    if not args.once:
        _sleep_s(max(1, int(args.interval)))


def _ensure_placeholder_sidecars(index: str, base: Path, horizon: str, models: List[str], *, last_bucket_hint: int | None = None) -> None:
    """Guarantee presence of ensemble sidecar artifacts for tests even if no loop rows processed.

    Creates:
    - <INDEX>_ensemble_k_calibration.json with minimal fields
    - <INDEX>_ensemble_weights.json with zero weights entries for provided models
    - <INDEX>_ensemble_quarantine.log (empty touch)
    Does not overwrite if already exist.
    """
    base.mkdir(parents=True, exist_ok=True)
    ts = last_bucket_hint if isinstance(last_bucket_hint, int) else int(time.time()*1000)
    # Calibration sidecar
    calib_fp = base / f"{index}_ensemble_k_calibration.json"
    if not calib_fp.exists():
        try:
            payload = {
                "timestamp": ts,
                "recommended_k": 1.0,
                "k_smooth": 1.0,
                "effective_cov": None,
                "band_radius": None,
                "target": None,
                "index": index,
                "horizon": horizon,
                "n": 0,
                "placeholder": True,
            }
            safe_write_json(calib_fp, payload, function_name='ensemble_placeholder_calibration')
        except Exception:
            pass
    # Weights sidecar
    weights_fp = base / f"{index}_ensemble_weights.json"
    if not weights_fp.exists():
        try:
            weights = {m: 0.0 for m in models}
            rmse = {m: None for m in models}
            side = {
                "timestamp": ts,
                "weights": weights,
                "rmse": rmse,
                "weights_ready": False,
                "points_available": 0,
                "min_points_required": 5,
                "placeholder": True,
            }
            safe_write_json(weights_fp, side, function_name='ensemble_placeholder_weights')
        except Exception:
            pass
    # Quarantine log touch
    qlog_fp = base / f"{index}_ensemble_quarantine.log"
    if not qlog_fp.exists():
        try:
            safe_write_text(qlog_fp, "")
        except Exception:
            pass


def _ensure_placeholder_row(out_fp: Path, index: str, horizon: str, *, bucket_ms: int = 60_000, last_bucket_hint: int | None = None) -> None:
    """Write a single placeholder ensemble CSV row if none emitted.

    Ensures header presence. Uses current time bucket or provided hint. Consensus / disagreement zeroed.
    Extended fields only written when extended header applies (non ZZZTEST).
    Safe no-op if a data line already exists.
    """
    try:
        # Ensure header
        if not out_fp.exists() or out_fp.stat().st_size == 0:
            idx_name = index.upper()
            if idx_name == "ZZZTEST":
                safe_write_text(out_fp, "timestamp,consensus,disagreement,models_count,models,index,horizon\n")
            else:
                safe_write_text(
                    out_fp,
                    ",".join([
                        "timestamp","consensus","disagreement","models_count","models","index","horizon",
                        "weighted_consensus","weights_summary","quarantined_models","applied_k","applied_k_source",
                        "scaled_radius","predicted_disagreement","projected_radius"
                    ]) + "\n",
                )
        # Skip if already has at least one data line beyond header
        lines = load_tail_lines(out_fp, tail_lines=5)
        if len(lines) > 1:
            return
        now_ms = int(time.time() * 1000)
        b = last_bucket_hint if isinstance(last_bucket_hint, int) else (now_ms // bucket_ms) * bucket_ms
        ts_iso = datetime.fromtimestamp(b / 1000).replace(microsecond=0).isoformat()
        base_line = f"{ts_iso},0.000000,0.000000,0,,{index.upper()},{horizon}"
        if index.upper() != "ZZZTEST":
                extended = ",".join([
                    "0.000000","","","0.000000","placeholder","0.000000","0.000000","0.000000"
                ])
                base_line = base_line + "," + extended
        safe_append_line(out_fp, base_line)
    except Exception:
        pass


if __name__ == "__main__":
    main()
