from __future__ import annotations
"""Auto-calibrate disagreement scaling factor k for effective bands.

Effective radius per bucket:
    radius_eff(b) = max(conformal_radius, k * disagreement(b))

We seek k such that empirical effective coverage ~= target over a window.

Outputs recommended k and summary stats; optional daemon mode updates a Prometheus gauge.

CSV requirements:
  Ensemble file: data/ml/live_predictions/<INDEX>_ensemble.csv
    Columns must include: timestamp,consensus,disagreement,index,horizon
    Optional weighted_consensus column used if present.
  Live TP resolved via find_live_csv (same index/horizon/expiry_tag/offset logic as exporter).

Sidecar written:
  data/ml/live_predictions/<INDEX>_ensemble_k_calibration.json
  {"timestamp": <epoch_ms>, "recommended_k": <float>, "window_minutes": <int>, "effective_cov": <float>, "band_radius": <float>, "target": <float>}

CLI Example:
  python scripts/ml/auto_calibrate_ensemble.py --index NIFTY --horizon 1 --target 0.8 --window-minutes 180 --grid "0.5,0.75,1.0,1.25,1.5" --weighted --port 9325

"""

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.web.dashboard.core.paths import project_root  # type: ignore
from src.web.dashboard.core.csv_io import find_live_csv, load_csv_rows_full  # type: ignore
from src.error_handling import safe_write_json, safe_read_json  # type: ignore
import datetime as _dt

# Standardized sleep helper using centralized backoff if available
try:
    from src.utils.backoff import sleep_ms as _sleep_ms  # type: ignore
except Exception:  # pragma: no cover
    _sleep_ms = None  # type: ignore

def _sleep_s(_sec: float) -> None:
    try:
        ms = int(float(_sec) * 1000)
        if _sleep_ms:
            _sleep_ms(ms)
        else:
            time.sleep(float(_sec))
    except Exception:
        time.sleep(float(_sec))

try:
    from prometheus_client import Gauge, start_http_server  # type: ignore
except Exception:  # pragma: no cover
    Gauge = None  # type: ignore
    start_http_server = None  # type: ignore

@dataclass
class CalibrationResult:
    k: float
    effective_cov: float
    band_radius: float
    target: float
    n: int


def parse_grid(s: str) -> List[float]:
    vals: List[float] = []
    for part in s.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            vals.append(float(part))
        except Exception:
            pass
    return vals


def load_ensemble(index: str, horizon: str, base: Path, tail: int = 50_000, bucket_ms: int = 60_000) -> List[dict]:
    fp = base / f"{index.upper()}_ensemble.csv"
    if not fp.exists():
        return []
    lines = fp.read_text(encoding="utf-8").splitlines()
    if not lines:
        return []
    header = lines[0].split(',')
    rows = lines[1:]
    if tail and len(rows) > tail:
        rows = rows[-tail:]
    # required cols
    try:
        ts_i = header.index('timestamp')
        dis_i = header.index('disagreement')
        idx_i = header.index('index')
        hor_i = header.index('horizon')
    except Exception:
        return []
    # prediction: prefer weighted_consensus
    pred_col = None
    if 'weighted_consensus' in header:
        pred_col = 'weighted_consensus'
    elif 'consensus' in header:
        pred_col = 'consensus'
    if pred_col is None:
        return []
    pred_i = header.index(pred_col)
    out: List[dict] = []
    for r in rows:
        parts = r.split(',')
        if len(parts) <= max(ts_i, dis_i, pred_i, idx_i, hor_i):
            continue
        if parts[idx_i] != index.upper() or parts[hor_i] != horizon:
            continue
        ts_s = parts[ts_i]
        try:
            # parse ISO or epoch
            if ts_s.isdigit():
                ems = int(ts_s[:13]) if len(ts_s) >= 13 else int(ts_s) * 1000
            else:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M:%S"):
                    try:
                        dt = _dt.datetime.strptime(ts_s, fmt)
                        ems = int(dt.timestamp() * 1000)
                        break
                    except Exception:
                        continue
                else:
                    continue
        except Exception:
            continue
        try:
            pred = float(parts[pred_i])
            dis = float(parts[dis_i])
        except Exception:
            continue
        b = (ems // int(bucket_ms)) * int(bucket_ms)
        out.append({'bucket_ms': b, 'pred': pred, 'dis': dis})
    return out


def load_tp(index: str, horizon: str, expiry_tag: str, offset: str, bucket_ms: int, window_minutes: int) -> dict[int, float]:
    from datetime import date
    # Use dynamic root resolution (env or cwd) so pytest cwd override works
    p = find_live_csv(resolve_project_root() / 'data' / 'g6_data', index.upper(), expiry_tag, offset, date.today())
    if not p or not p.exists():
        return {}
    rows = load_csv_rows_full(p)
    now_ms = int(_dt.datetime.now(tz=_dt.timezone.utc).timestamp() * 1000)
    cutoff = now_ms - window_minutes * 60_000
    tp_by_bucket: dict[int, float] = {}

    def _parse_to_epoch_ms(val: object) -> int | None:
        try:
            # Already numeric epoch ms (int/float)
            if isinstance(val, (int, float)):
                v = int(val)
                # Heuristic: treat seconds as ms if 10 digits
                return v if v > 10_000_000_000 else v * 1000
            s = str(val).strip()
            if not s:
                return None
            # If purely digits: ms or s
            if s.isdigit():
                v = int(s)
                return v if len(s) >= 13 else v * 1000
            # Try common ISO formats
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M:%S"):
                try:
                    dt = _dt.datetime.strptime(s, fmt)
                    return int(dt.timestamp() * 1000)
                except Exception:
                    continue
        except Exception:
            return None
        return None

    for row in rows:
        # Support multiple timestamp keys: ts (epoch ms), time (epoch ms), timestamp (ISO or epoch)
        raw_ts = row.get('ts') or row.get('time') or row.get('timestamp')
        ems = _parse_to_epoch_ms(raw_ts)
        if not ems or ems < cutoff:
            continue
        b = (ems // bucket_ms) * bucket_ms
        tp = row.get('tp')
        if isinstance(tp, (int, float)):
            tp_by_bucket[b] = float(tp)
    return tp_by_bucket


def empirical_quantile(values: Sequence[float], q: float) -> float:
    if not values:
        return float('nan')
    s = sorted(values)
    k = (len(s) - 1) * q
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def compute_recommended_k(
    preds: List[dict],
    tp_by_bucket: dict[int, float],
    target: float,
    window_minutes: int,
    bucket_ms: int,
    grid: Iterable[float],
    min_points: int = 30,
) -> CalibrationResult | None:
    # Join on bucket keys
    keys = sorted(set(tp_by_bucket.keys()) & {p['bucket_ms'] for p in preds})
    if len(keys) < min_points:
        return None
    # residual absolute errors
    abs_res: List[float] = []
    dis_vals: List[float] = []
    pred_map = {p['bucket_ms']: p for p in preds}
    for k in keys:
        rec = pred_map.get(k)
        if not rec:
            continue
        tp = tp_by_bucket.get(k)
        if tp is None:
            continue
        abs_res.append(abs(rec['pred'] - tp))
        dis_vals.append(rec['dis'])
    if len(abs_res) < min_points:
        return None
    # conformal radius at target quantile
    band_radius = empirical_quantile(abs_res, target)
    best: Optional[CalibrationResult] = None
    for k in grid:
        eff_inside = 0
        for r, dis in zip(abs_res, dis_vals):
            radius_eff = band_radius if band_radius == band_radius else 0.0
            if dis == dis:  # not NaN
                radius_eff = max(radius_eff, k * dis)
            if r <= radius_eff:
                eff_inside += 1
        eff_cov = eff_inside / len(abs_res)
        cand = CalibrationResult(k=k, effective_cov=eff_cov, band_radius=band_radius, target=target, n=len(abs_res))
        if best is None:
            best = cand
        else:
            # choose minimal absolute coverage error; tie-breaker smaller k
            cur_err = abs(cand.effective_cov - target)
            best_err = abs(best.effective_cov - target)
            if cur_err < best_err - 1e-6:
                best = cand
            elif abs(cur_err - best_err) <= 1e-6:
                # If target is higher than achieved coverage and both candidates tie,
                # prefer larger k to encourage expansion; otherwise prefer smaller k.
                if target > cand.effective_cov + 1e-9:
                    if cand.k > best.k:
                        best = cand
                else:
                    if cand.k < best.k:
                        best = cand
    return best


def write_sidecar(index: str, horizon: str, res: CalibrationResult, base: Path) -> None:
    sidecar = base / f"{index.upper()}_ensemble_k_calibration.json"
    payload = {
    'timestamp': int(_dt.datetime.now(tz=_dt.timezone.utc).timestamp() * 1000),
        'recommended_k': res.k,
        'effective_cov': res.effective_cov,
        'band_radius': res.band_radius,
        'target': res.target,
        'n': res.n,
        'index': index,
        'horizon': horizon,
        # Include latest smoothed k if available (filled by daemon after write via patching logic)
        # For one-shot runs (interval<=0) this may remain absent.
    }
    # Centralized FILE_IO error handling
    safe_write_json(sidecar, payload, function_name='ensemble_k_calibration_write_sidecar')


def resolve_project_root() -> Path:
    """Test-friendly project root resolution.

    Order:
    - G6_PROJECT_ROOT env var if set
    - Current working directory if it contains a 'data' directory (pytest tmp with cwd override)
    - Fallback to imported project_root() provider
    - Repo ROOT
    """
    try:
        env_root = os.environ.get("G6_PROJECT_ROOT", "").strip()  # type: ignore[name-defined]
        if env_root:
            p = Path(env_root)
            if p.exists():
                return p
    except Exception:
        pass
    try:
        cwd = Path.cwd()
        if (cwd / "data").exists():
            return cwd
    except Exception:
        pass
    try:
        return project_root()  # type: ignore[misc]
    except Exception:
        return ROOT

def main() -> None:
    ap = argparse.ArgumentParser(description='Auto-calibrate disagreement scaling k for effective bands')
    ap.add_argument('--index', required=True)
    ap.add_argument('--horizon', default='1')
    ap.add_argument('--target', type=float, default=0.8)
    ap.add_argument('--window-minutes', type=int, default=180)
    ap.add_argument('--bucket-ms', type=int, default=60_000)
    ap.add_argument('--expiry-tag', default='this_week')
    ap.add_argument('--offset', default='0')
    ap.add_argument('--grid', default='0.5,0.75,1.0,1.25,1.5,1.75,2.0')
    ap.add_argument('--weighted', action='store_true', help='Use weighted_consensus if available')
    ap.add_argument('--port', type=int, default=None, help='If set, start Prometheus metrics server & publish gauge')
    ap.add_argument('--interval', type=int, default=300, help='Daemon loop interval seconds; if <=0 run once')
    ap.add_argument('--min-points', type=int, default=30)
    ap.add_argument('--ema-alpha', type=float, default=0.3, help='EMA smoothing factor for k in daemon mode (0<alpha<=1)')
    # Adaptive target knobs (optional, backward-compatible defaults leave disabled)
    ap.add_argument('--adaptive-target', action='store_true', help='Enable adaptive coverage target computation')
    ap.add_argument('--target-min', type=float, default=0.70)
    ap.add_argument('--target-max', type=float, default=0.90)
    ap.add_argument('--target-step', type=float, default=0.01)
    ap.add_argument('--cov-delta-low', type=float, default=0.02, help='Lower tolerance around target for under-coverage detection')
    ap.add_argument('--cov-delta-high', type=float, default=0.02, help='Upper tolerance around target for over-coverage detection')
    ap.add_argument('--fast-window-minutes', type=int, default=15)
    ap.add_argument('--slow-window-minutes', type=int, default=60)
    args = ap.parse_args()

    idx = args.index.upper()
    horizon = str(args.horizon)

    # Prometheus gauge
    g_k = None
    if args.port and Gauge and start_http_server:
        try:
            g_k = Gauge('g6_ml_ensemble_k_recommended', 'Recommended disagreement scaling k', ['index', 'horizon'])
            start_http_server(int(args.port))
            print(f'[auto-calibrate] Prometheus server started on port {args.port}')
        except Exception:
            g_k = None

    base = resolve_project_root() / 'data' / 'ml' / 'live_predictions'
    base.mkdir(parents=True, exist_ok=True)

    grid_vals = parse_grid(args.grid)
    if not grid_vals:
        print('[auto-calibrate] Empty k grid; abort')
        return

    ema_k: Optional[float] = None
    dynamic_target: Optional[float] = None

    def _apply_ema(new_k: float) -> float:
        nonlocal ema_k
        a = float(args.ema_alpha)
        if not (0.0 < a <= 1.0):
            a = 0.3
        ema_k = new_k if ema_k is None else (a * new_k + (1 - a) * ema_k)
        return ema_k

    def _effective_coverage_for_window(
        preds: List[dict],
        tp_by_bucket: dict[int, float],
        window_minutes: int,
        bucket_ms: int,
        k_val: float,
        target_q: float,
    ):
        now_ms = int(_dt.datetime.now(tz=_dt.timezone.utc).timestamp() * 1000)
        cutoff = now_ms - int(window_minutes) * 60_000
        # join filtered by cutoff
        keys = [p['bucket_ms'] for p in preds if p['bucket_ms'] >= cutoff]
        pred_map = {p['bucket_ms']: p for p in preds if p['bucket_ms'] >= cutoff}
        abs_res: List[float] = []
        dis_vals: List[float] = []
        for b in keys:
            tp = tp_by_bucket.get(b)
            rec = pred_map.get(b)
            if tp is None or rec is None:
                continue
            try:
                abs_res.append(abs(rec['pred'] - tp))
                dis_vals.append(float(rec['dis']))
            except Exception:
                continue
        if not abs_res:
            return float('nan'), 0
        band_radius = empirical_quantile(abs_res, target_q)
        eff_inside = 0
        for r, d in zip(abs_res, dis_vals):
            # Adaptive coverage evaluation focuses on disagreement scaling effect;
            # use k*dis only (ignore conformal band component) to detect under/over conditions.
            radius_eff = 0.0
            if d == d:  # not NaN
                radius_eff = float(k_val) * float(d)
            if r <= radius_eff:
                eff_inside += 1
        return eff_inside / len(abs_res), len(abs_res)

    def _calibrate_once() -> None:
        nonlocal dynamic_target
        preds = load_ensemble(idx, horizon, base, bucket_ms=int(args.bucket_ms))
        if not preds:
            # Emit placeholder sidecar so downstream/tests can observe calibration state even with no data
            print('[auto-calibrate] No ensemble rows found')
            sc_fp = base / f"{idx}_ensemble_k_calibration.json"
            try:
                payload = {
                    'timestamp': int(_dt.datetime.now(tz=_dt.timezone.utc).timestamp() * 1000),
                    'recommended_k': float('nan'),
                    'k_smooth': float('nan'),
                    'effective_cov': float('nan'),
                    'band_radius': float('nan'),
                    'target': float(args.target),
                    'n': 0,
                    'index': idx,
                    'horizon': horizon,
                    'adaptive_state': 'no_preds',
                }
                safe_write_json(sc_fp, payload, function_name='ensemble_k_calibration_no_preds_write')
            except Exception:
                pass
            return
        tp_by_bucket = load_tp(idx, horizon, args.expiry_tag, args.offset, args.bucket_ms, args.window_minutes)
        if not tp_by_bucket:
            print('[auto-calibrate] No TP rows found')
            # Emit placeholder sidecar (no_tp) for tests expecting calibration artifact presence
            sc_fp = base / f"{idx}_ensemble_k_calibration.json"
            try:
                payload = {
                    'timestamp': int(_dt.datetime.now(tz=_dt.timezone.utc).timestamp() * 1000),
                    'recommended_k': float('nan'),
                    'k_smooth': float('nan'),
                    'effective_cov': float('nan'),
                    'band_radius': float('nan'),
                    'target': float(args.target),
                    'n': 0,
                    'index': idx,
                    'horizon': horizon,
                    'adaptive_state': 'no_tp',
                }
                safe_write_json(sc_fp, payload, function_name='ensemble_k_calibration_no_tp_write')
            except Exception:
                pass
            return
        # Use dynamic target if enabled and previously computed, else the configured target
        target_q = float(dynamic_target) if (args.adaptive_target and dynamic_target is not None) else float(args.target)
        res = compute_recommended_k(preds, tp_by_bucket, target_q, args.window_minutes, args.bucket_ms, grid_vals, min_points=args.min_points)
        if not res:
            print('[auto-calibrate] Insufficient data points for calibration')
            # Emit sidecar with adaptive_state=insufficient so downstream/tests can introspect state
            cov_fast, n_fast = _effective_coverage_for_window(
                preds, tp_by_bucket, int(args.fast_window_minutes), int(args.bucket_ms), float(1.0), target_q
            )
            cov_slow, n_slow = _effective_coverage_for_window(
                preds, tp_by_bucket, int(args.slow_window_minutes), int(args.bucket_ms), float(1.0), target_q
            )
            sc_fp = base / f"{idx}_ensemble_k_calibration.json"
            obj = {
                'timestamp': int(_dt.datetime.now(tz=_dt.timezone.utc).timestamp() * 1000),
                'recommended_k': float('nan'),
                'effective_cov': float('nan'),
                'band_radius': float('nan'),
                'target': float(target_q),
                'n': 0,
                'index': idx,
                'horizon': horizon,
                'adaptive_state': 'insufficient',
                'coverage_fast': {'value': cov_fast, 'n': n_fast},
                'coverage_slow': {'value': cov_slow, 'n': n_slow},
            }
            safe_write_json(sc_fp, obj, function_name='ensemble_k_calibration_insufficient_write')
            return
        # Smooth k for daemon usage
        smoothed_k = _apply_ema(res.k)
        # Adaptive target update (feedback from effective coverage windows)
        adaptive_state = 'disabled'
        cov_fast = cov_slow = float('nan')
        n_fast = n_slow = 0
        if args.adaptive_target:
            # compute coverage using current smoothed k (or res.k if EMA not ready yet)
            k_eval = float(ema_k if ema_k is not None else res.k)
            cov_fast, n_fast = _effective_coverage_for_window(
                preds, tp_by_bucket, int(args.fast_window_minutes), int(args.bucket_ms), k_eval, target_q
            )
            cov_slow, n_slow = _effective_coverage_for_window(
                preds, tp_by_bucket, int(args.slow_window_minutes), int(args.bucket_ms), k_eval, target_q
            )
            # Decide adjustment only if both windows are valid and agree on direction
            def _nan(x: float) -> bool:
                return not (x == x)  # NaN check
            if not _nan(cov_fast) and not _nan(cov_slow):
                under = (cov_fast < target_q - float(args.cov_delta_low)) and (cov_slow < target_q - float(args.cov_delta_low))
                over = (cov_fast > target_q + float(args.cov_delta_high)) and (cov_slow > target_q + float(args.cov_delta_high))
                if under:
                    new_target = min(float(args.target_max), target_q + float(args.target_step))
                    if dynamic_target is None or abs(new_target - target_q) > 1e-9:
                        dynamic_target = new_target
                        adaptive_state = 'raising'
                elif over:
                    new_target = max(float(args.target_min), target_q - float(args.target_step))
                    if dynamic_target is None or abs(new_target - target_q) > 1e-9:
                        dynamic_target = new_target
                        adaptive_state = 'lowering'
                else:
                    # keep as-is
                    dynamic_target = target_q
                    adaptive_state = 'stable'
            else:
                adaptive_state = 'insufficient'
                dynamic_target = target_q

        # Write sidecar with both raw and smoothed, plus adaptive fields if enabled
        # Write sidecar first (raw recommended_k). Then append k_smooth into JSON for downstream use.
        write_sidecar(idx, horizon, res, base)
        sc_fp = base / f"{idx}_ensemble_k_calibration.json"
        obj = safe_read_json(sc_fp, default={}, function_name='ensemble_k_calibration_load_after_write')
        if not isinstance(obj, dict):
            obj = {}
        obj['k_smooth'] = smoothed_k
        if args.adaptive_target:
            obj['dynamic_target_coverage'] = float(dynamic_target if dynamic_target is not None else target_q)
            obj['adaptive_state'] = adaptive_state
            obj['coverage_fast'] = {'value': cov_fast, 'n': n_fast}
            obj['coverage_slow'] = {'value': cov_slow, 'n': n_slow}
        safe_write_json(sc_fp, obj, function_name='ensemble_k_calibration_update_smooth_write')
        line = (
            f"recommended_k={res.k:.3f} k_smooth={smoothed_k:.3f} effective_cov={res.effective_cov:.3f} "
            f"target={res.target:.3f} band_radius={res.band_radius:.4f} n={res.n}"
        )
        if args.adaptive_target:
            line += f" dyn_target={dynamic_target if dynamic_target is not None else target_q:.3f} cov_fast={cov_fast if cov_fast==cov_fast else float('nan'):.3f} cov_slow={cov_slow if cov_slow==cov_slow else float('nan'):.3f} state={adaptive_state}"
        print('[auto-calibrate] ' + line)
        if g_k is not None:
            try:
                g_k.labels(index=idx, horizon=horizon).set(smoothed_k)
            except Exception:
                pass

    if args.interval <= 0:
        _calibrate_once()
    else:
        while True:
            try:
                _calibrate_once()
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f'[auto-calibrate] loop error: {e}')
            _sleep_s(max(5, int(args.interval)))


if __name__ == '__main__':
    main()
