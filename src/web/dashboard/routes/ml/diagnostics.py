from __future__ import annotations

import asyncio
import datetime as _dt
import logging
from typing import Optional

from fastapi import HTTPException, Query
from fastapi.responses import PlainTextResponse

from ...core.csv_io import (
    load_csv_rows_full as _load_csv_rows_full,
    parse_time_epoch_ms as _parse_time_epoch_ms,
)
from .._index_norm import normalize_index
from ._common import project_root as _project_root, resolve_live_csv_path as _resolve_live_csv_path
from .._tabular_file import read_header_and_rows

logger = logging.getLogger(__name__)

# Exception hygiene: avoid `except Exception` in request paths.
# These are intentionally broad-but-specific buckets for I/O, parsing, and math.
_NON_FATAL_HTTP_ERRORS = (OSError, IOError, ValueError, TypeError, KeyError, IndexError, AttributeError, RuntimeError)
_NON_FATAL_PARSE_ERRORS = (ValueError, TypeError, IndexError)
_NON_FATAL_MATH_ERRORS = (ValueError, TypeError, ZeroDivisionError, OverflowError)
async def api_ml_diagnostics(
    index: str = Query("NIFTY", description="Index name e.g., NIFTY, BANKNIFTY, SENSEX, FINNIFTY"),
    horizon: str = Query("1", description="Horizon label to select (string)"),
    model: str = Query("all", description="Model name to select or 'all' for all models found"),
    expiry_tag: str = Query("this_month", description="Expiry tag for live_csv lookup"),
    offset: str = Query("0", description="Offset for live_csv lookup"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000, description="Bucket size for time alignment in ms"),
    window_minutes: int = Query(120, ge=1, le=24 * 60, description="Lookback window in minutes"),
    include_bands: bool = Query(False, description="If true, compute conformal band radius and coverage estimate"),
    coverage: float = Query(0.8, ge=0.5, le=0.99, description="Target coverage for conformal radius"),
    include_move_stats: bool = Query(
        False,
        description="If true, include move probability and conditional magnitude stats from <INDEX>_move.csv",
    ),
    move_prob_threshold: float = Query(
        0.6,
        ge=0.0,
        le=1.0,
        description="Threshold to consider a 'high probability' move for stats",
    ),
    include_effective_bands: bool = Query(
        False,
        description=(
            "If true, compute effective bands = max(conformal_radius, k * disagreement) using ensemble disagreement"
        ),
    ),
    disagreement_k: float = Query(1.0, ge=0.1, le=5.0, description="Scaling factor k for disagreement component"),
    ensemble_models: str = Query(
        "sk_hgb_regressor,xgb_regressor,torch_lstm_regressor,sk_hgb_residual",
        description="Comma-separated models to compute disagreement over",
    ),
) -> PlainTextResponse:
    """Return CSV diagnostics over a recent window, per model.

    Metrics include: count, MAE, RMSE, mean/median bias (prediction - tp),
    Pearson correlation, trend slopes (per hour) for pred and tp, last values.

    Output columns:
    model,index,horizon,count,mae,rmse,bias_mean,bias_median,corr,slope_pred_per_hr,slope_tp_per_hr,delta_p10,delta_p90,last_pred,last_tp,last_delta,window_minutes
    """
    try:
        idx_norm = normalize_index(index)

        base = _project_root() / "data" / "ml" / "live_predictions"
        pred_fp = base / f"{idx_norm}.csv"
        hybrid_fp = base / f"{idx_norm}_hybrid.csv"

        lines: list[str] = []
        rows: list[str] = []
        cols: list[str] = []
        ts_idx = pred_idx = mdl_idx = hor_idx = -1

        if pred_fp.exists():
            header, rows = read_header_and_rows(pred_fp)
            if header:
                cols = header.split(",")
                try:
                    ts_idx = cols.index("timestamp")
                    pred_idx = cols.index("prediction")
                    mdl_idx = cols.index("model")
                    hor_idx = cols.index("horizon")
                except ValueError:
                    rows = []
                    cols = []
                    ts_idx = pred_idx = mdl_idx = hor_idx = -1

        if not pred_fp.exists() and not hybrid_fp.exists():
            raise HTTPException(status_code=404, detail=f"predictions file not found: {pred_fp} or {hybrid_fp}")

        if (not rows) and (not hybrid_fp.exists()):
            return PlainTextResponse(
                "model,index,horizon,count,mae,rmse,bias_mean,bias_median,corr,slope_pred_per_hr,slope_tp_per_hr,delta_p10,delta_p90,last_pred,last_tp,last_delta,window_minutes\n",
                media_type="text/csv",
            )

        include_models: set[str] = set()
        if model and model.lower() != "all":
            include_models.add(model)
        else:
            for r in rows[-500:]:
                parts = r.split(",")
                if mdl_idx >= 0 and len(parts) > mdl_idx:
                    include_models.add(parts[mdl_idx])
            if hybrid_fp.exists():
                try:
                    h_header, h_lines = read_header_and_rows(hybrid_fp)
                except (OSError, UnicodeDecodeError):
                    h_header, h_lines = "", []
                if h_header:
                    h_cols = h_header.split(",")
                    try:
                        h_mdl_idx = h_cols.index("model")
                    except ValueError:
                        h_mdl_idx = -1
                    for r in h_lines[-500:]:
                        parts = r.split(",")
                        if h_mdl_idx >= 0 and len(parts) > h_mdl_idx:
                            include_models.add(parts[h_mdl_idx])

        if model and model == "sk_hgb_residual":
            include_models.add(model)

        now_ms = int(_dt.datetime.now(tz=_dt.timezone.utc).timestamp() * 1000)
        cutoff_ms = now_ms - window_minutes * 60_000
        preds_map: dict[str, dict[int, float]] = {m: {} for m in include_models}

        for r in rows[-max(5000, window_minutes * 4) :]:  # heuristic slice
            if ts_idx < 0:
                break
            parts = r.split(",")
            if len(parts) <= max(ts_idx, pred_idx, mdl_idx, hor_idx):
                continue
            mname = parts[mdl_idx]
            if mname not in include_models:
                continue
            if parts[hor_idx] != str(horizon):
                continue
            ems = _parse_time_epoch_ms(parts[ts_idx])
            if ems is None or ems < cutoff_ms:
                continue
            bucket = (ems // bucket_ms) * bucket_ms
            try:
                pv = float(parts[pred_idx])
            except (TypeError, ValueError, IndexError):
                continue
            preds_map[mname][bucket] = pv

        hybrid_baseline_by_bucket: dict[int, float] = {}
        hybrid_residual_by_bucket: dict[int, float] = {}
        if hybrid_fp.exists() and ("sk_hgb_residual" in include_models or (model and model.lower() == "all")):
            try:
                h_header, h_lines = read_header_and_rows(hybrid_fp)
            except (OSError, UnicodeDecodeError):
                h_header, h_lines = "", []
            if h_header:
                h_cols = h_header.split(",")
                try:
                    h_ts_idx = h_cols.index("timestamp")
                    h_pred_idx = h_cols.index("prediction")
                    h_mdl_idx = h_cols.index("model")
                    h_hor_idx = h_cols.index("horizon")
                except ValueError:
                    h_ts_idx = h_pred_idx = h_mdl_idx = h_hor_idx = -1
                h_base_idx = h_cols.index("baseline") if "baseline" in h_cols else -1
                h_resid_idx = h_cols.index("residual") if "residual" in h_cols else -1
                for r in h_lines[-max(5000, window_minutes * 4) :]:
                    parts = r.split(",")
                    if h_ts_idx < 0 or len(parts) <= max(h_ts_idx, h_pred_idx, h_mdl_idx, h_hor_idx):
                        continue
                    if parts[h_hor_idx] != str(horizon):
                        continue
                    mname = parts[h_mdl_idx]
                    if mname not in include_models:
                        include_models.add(mname)
                        preds_map.setdefault(mname, {})
                    ems = _parse_time_epoch_ms(parts[h_ts_idx])
                    if ems is None or ems < cutoff_ms:
                        continue
                    bucket = (ems // bucket_ms) * bucket_ms
                    try:
                        pv = float(parts[h_pred_idx])
                    except (TypeError, ValueError, IndexError):
                        continue
                    preds_map[mname][bucket] = pv
                    if h_base_idx >= 0 and len(parts) > h_base_idx:
                        try:
                            hybrid_baseline_by_bucket[bucket] = float(parts[h_base_idx])
                        except (TypeError, ValueError):
                            pass
                    if h_resid_idx >= 0 and len(parts) > h_resid_idx:
                        try:
                            hybrid_residual_by_bucket[bucket] = float(parts[h_resid_idx])
                        except (TypeError, ValueError):
                            pass

        from datetime import date

        p = _resolve_live_csv_path(idx_norm, expiry_tag, offset, date.today())
        if not p or not p.exists():
            raise HTTPException(status_code=404, detail="live_csv file not found")
        live_rows = _load_csv_rows_full(p)
        tp_by_bucket: dict[int, float] = {}
        for row in live_rows:
            try:
                ems = int(row.get("ts") or row.get("time") or 0)
            except (TypeError, ValueError):
                continue
            if not ems or ems < cutoff_ms:
                continue
            bucket = (ems // bucket_ms) * bucket_ms
            tp_raw = row.get("tp")
            try:
                tp_val = float(tp_raw) if tp_raw is not None else None
            except (TypeError, ValueError):
                tp_val = None
            if isinstance(tp_val, (int, float)):
                tp_by_bucket[bucket] = float(tp_val)

        joined_any = any(set(pmap.keys()) & set(tp_by_bucket.keys()) for pmap in preds_map.values())
        seq_pred_by_model: dict[str, list[float]] = {}
        seq_hybrid_baseline: list[float] = []
        seq_hybrid_residual: list[float] = []
        seq_tp: list[float] = []
        if not joined_any:
            preds_map = {m: {} for m in include_models}
            for r in rows:
                if ts_idx < 0:
                    break
                parts = r.split(",")
                if len(parts) <= max(ts_idx, pred_idx, mdl_idx, hor_idx):
                    continue
                mname = parts[mdl_idx]
                if mname not in include_models:
                    continue
                if parts[hor_idx] != str(horizon):
                    continue
                ems = _parse_time_epoch_ms(parts[ts_idx])
                if ems is None:
                    continue
                b = (ems // bucket_ms) * bucket_ms
                try:
                    pv = float(parts[pred_idx])
                except (TypeError, ValueError, IndexError):
                    continue
                preds_map[mname][b] = pv

            if hybrid_fp.exists() and ("sk_hgb_residual" in include_models or (model and model.lower() == "all")):
                try:
                    h_header, h_lines = read_header_and_rows(hybrid_fp)
                    if h_header:
                        h_cols = h_header.split(",")
                        try:
                            h_ts_idx = h_cols.index("timestamp")
                            h_pred_idx = h_cols.index("prediction")
                            h_mdl_idx = h_cols.index("model")
                            h_hor_idx = h_cols.index("horizon")
                            h_base_idx = h_cols.index("baseline") if "baseline" in h_cols else -1
                            h_resid_idx = h_cols.index("residual") if "residual" in h_cols else -1
                        except ValueError:
                            h_ts_idx = h_pred_idx = h_mdl_idx = h_hor_idx = -1
                            h_base_idx = h_resid_idx = -1
                        hybrid_baseline_by_bucket.clear()
                        hybrid_residual_by_bucket.clear()
                        for r in h_lines:
                            parts = r.split(",")
                            if h_ts_idx < 0 or len(parts) <= max(h_ts_idx, h_pred_idx, h_mdl_idx, h_hor_idx):
                                continue
                            if parts[h_hor_idx] != str(horizon):
                                continue
                            mname = parts[h_mdl_idx]
                            if mname not in include_models:
                                include_models.add(mname)
                                preds_map.setdefault(mname, {})
                            ems = _parse_time_epoch_ms(parts[h_ts_idx])
                            if ems is None:
                                continue
                            b = (ems // bucket_ms) * bucket_ms
                            try:
                                pv = float(parts[h_pred_idx])
                            except (TypeError, ValueError, IndexError):
                                continue
                            preds_map[mname][b] = pv
                            if h_base_idx >= 0 and len(parts) > h_base_idx:
                                try:
                                    hybrid_baseline_by_bucket[b] = float(parts[h_base_idx])
                                except (TypeError, ValueError):
                                    pass
                            if h_resid_idx >= 0 and len(parts) > h_resid_idx:
                                try:
                                    hybrid_residual_by_bucket[b] = float(parts[h_resid_idx])
                                except (TypeError, ValueError):
                                    pass
                except (OSError, UnicodeDecodeError):
                    pass

            tp_by_bucket = {}
            for row in live_rows:
                try:
                    ems = int(row.get("ts") or row.get("time") or 0)
                except (TypeError, ValueError):
                    continue
                if not ems:
                    continue
                b = (ems // bucket_ms) * bucket_ms
                tp_raw = row.get("tp")
                try:
                    tp_val = float(tp_raw) if tp_raw is not None else None
                except (TypeError, ValueError):
                    tp_val = None
                if isinstance(tp_val, (int, float)):
                    tp_by_bucket[b] = float(tp_val)
                    seq_tp.append(float(tp_val))

            for r in rows:
                if ts_idx < 0:
                    break
                parts = r.split(",")
                if len(parts) <= max(ts_idx, pred_idx, mdl_idx, hor_idx):
                    continue
                if parts[hor_idx] != str(horizon):
                    continue
                mname = parts[mdl_idx]
                if mname not in include_models:
                    continue
                try:
                    pv = float(parts[pred_idx])
                except (TypeError, ValueError, IndexError):
                    continue
                seq_pred_by_model.setdefault(mname, []).append(pv)

            if hybrid_fp.exists():
                try:
                    h_header, h_lines = read_header_and_rows(hybrid_fp)
                    if h_header:
                        h_cols = h_header.split(",")
                        try:
                            h_pred_idx = h_cols.index("prediction")
                            h_mdl_idx = h_cols.index("model")
                            h_hor_idx = h_cols.index("horizon")
                            h_base_idx = h_cols.index("baseline") if "baseline" in h_cols else -1
                            h_resid_idx = h_cols.index("residual") if "residual" in h_cols else -1
                        except ValueError:
                            h_pred_idx = h_mdl_idx = h_hor_idx = -1
                            h_base_idx = h_resid_idx = -1
                        for r in h_lines:
                            parts = r.split(",")
                            if h_hor_idx < 0 or len(parts) <= max(h_pred_idx, h_mdl_idx, h_hor_idx):
                                continue
                            if parts[h_hor_idx] != str(horizon):
                                continue
                            mname = parts[h_mdl_idx]
                            if mname not in include_models:
                                continue
                            try:
                                pv = float(parts[h_pred_idx])
                            except (TypeError, ValueError, IndexError):
                                pv = None
                            if pv is not None:
                                seq_pred_by_model.setdefault(mname, []).append(pv)
                            if h_base_idx >= 0 and len(parts) > h_base_idx:
                                try:
                                    seq_hybrid_baseline.append(float(parts[h_base_idx]))
                                except (TypeError, ValueError):
                                    pass
                            if h_resid_idx >= 0 and len(parts) > h_resid_idx:
                                try:
                                    seq_hybrid_residual.append(float(parts[h_resid_idx]))
                                except (TypeError, ValueError):
                                    pass
                except (OSError, UnicodeDecodeError):
                    pass

        base_header = "model,index,horizon,count,mae,rmse,bias_mean,bias_median,corr,slope_pred_per_hr,slope_tp_per_hr,delta_p10,delta_p90,last_pred,last_tp,last_delta,window_minutes"
        hybrid_extras = (
            ",baseline_rmse,hybrid_rmse,improvement_ratio,last_baseline,last_residual" if ("sk_hgb_residual" in include_models) else ""
        )
        band_header = ",band_radius,coverage_estimate" if include_bands else ""
        eff_header = (
            ",effective_cov_estimate,effective_radius_avg,effective_radius_last"
            if (include_bands and include_effective_bands)
            else ""
        )
        move_header = (
            ",avg_move_probability,move_high_prob_share,move_mag_p10,move_mag_p50,move_mag_p90,move_last_prob,move_last_mag"
            if include_move_stats
            else ""
        )
        out = [base_header + hybrid_extras + band_header + eff_header + move_header]
        expected_len = len(out[0].split(","))

        dis_by_bucket: dict[int, float] = {}
        if include_bands and include_effective_bands:
            try:
                ens_models = [m.strip() for m in (ensemble_models or "").split(",") if m.strip()]
                vals_by_bucket: dict[int, list[float]] = {}
                for r in rows[-max(5000, window_minutes * 4) :]:
                    if ts_idx < 0:
                        break
                    parts = r.split(",")
                    if len(parts) <= max(ts_idx, pred_idx, mdl_idx, hor_idx):
                        continue
                    if parts[hor_idx] != str(horizon):
                        continue
                    if ens_models and parts[mdl_idx] not in ens_models:
                        continue
                    ems = _parse_time_epoch_ms(parts[ts_idx])
                    if ems is None or ems < cutoff_ms:
                        continue
                    b = (ems // bucket_ms) * bucket_ms
                    try:
                        pv = float(parts[pred_idx])
                    except (TypeError, ValueError, IndexError):
                        continue
                    vals_by_bucket.setdefault(b, []).append(pv)
                try:
                    import math
                except ImportError:
                    math = None  # type: ignore
                for b, vs in vals_by_bucket.items():
                    if len(vs) >= 2:
                        if math is not None:
                            mean = sum(vs) / len(vs)
                            var = sum((x - mean) ** 2 for x in vs) / (len(vs) - 1)
                            dis_by_bucket[b] = (var**0.5)
                        else:
                            dis_by_bucket[b] = 0.0
            except BaseException as e:
                if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
                    raise
                dis_by_bucket = {}

        move_stats_row: list[str] | None = None
        if include_move_stats:
            try:
                mv_fp = (_project_root() / "data" / "ml" / "live_predictions") / f"{idx_norm}_move.csv"
                if mv_fp.exists():
                    mv_header, lines_mv = read_header_and_rows(mv_fp)
                    if mv_header:
                        cols_mv = mv_header.split(",")
                        try:
                            mv_ts = cols_mv.index("timestamp")
                            mv_prob = cols_mv.index("move_prob")
                            mv_lbl = cols_mv.index("move_label_pred")
                            mv_mag = cols_mv.index("conditional_magnitude")
                            mv_hor = cols_mv.index("horizon")
                        except ValueError:
                            mv_ts = mv_prob = mv_lbl = mv_mag = mv_hor = -1
                        now_ms_mv = int(_dt.datetime.now(tz=_dt.timezone.utc).timestamp() * 1000)
                        cutoff_mv = now_ms_mv - window_minutes * 60_000
                        probs: list[float] = []
                        mags_on_pred: list[float] = []
                        last_prob: Optional[float] = None
                        last_mag: Optional[float] = None
                        hi_count = 0
                        total = 0
                        for r in lines_mv[-max(5000, window_minutes * 4) :]:
                            parts = r.split(",")
                            if mv_ts < 0 or len(parts) <= max(mv_ts, mv_prob, mv_lbl, mv_mag, mv_hor):
                                continue
                            if parts[mv_hor] != str(horizon):
                                continue
                            ems = _parse_time_epoch_ms(parts[mv_ts])
                            if ems is None or ems < cutoff_mv:
                                continue
                            try:
                                p = float(parts[mv_prob])
                            except (TypeError, ValueError, IndexError):
                                p = None  # type: ignore
                            try:
                                lbl = int(parts[mv_lbl])
                            except (TypeError, ValueError, IndexError):
                                lbl = 0
                            try:
                                mag = float(parts[mv_mag])
                            except (TypeError, ValueError, IndexError):
                                mag = None  # type: ignore
                            total += 1
                            if isinstance(p, (int, float)):
                                probs.append(float(p))
                                if p >= move_prob_threshold:
                                    hi_count += 1
                                last_prob = float(p)
                            if lbl == 1 and isinstance(mag, (int, float)):
                                mags_on_pred.append(float(mag))
                                last_mag = float(mag)

                        def _pct_mv(vals: list[float], q: float) -> float:
                            if not vals:
                                return float("nan")
                            s = sorted(vals)
                            k = (len(s) - 1) * q
                            f = int(k)
                            c = min(f + 1, len(s) - 1)
                            if f == c:
                                return s[f]
                            return s[f] + (s[c] - s[f]) * (k - f)

                        count = len(probs)
                        avg_prob = (sum(probs) / count) if count else float("nan")
                        hi_share = (hi_count / total) if total else float("nan")
                        p10 = _pct_mv(mags_on_pred, 0.10)
                        p50 = _pct_mv(mags_on_pred, 0.50)
                        p90 = _pct_mv(mags_on_pred, 0.90)
                        move_stats_row = [
                            (f"{avg_prob:.4f}" if count else ""),
                            (f"{hi_share:.4f}" if total else ""),
                            (f"{p10:.4f}" if mags_on_pred else ""),
                            (f"{p50:.4f}" if mags_on_pred else ""),
                            (f"{p90:.4f}" if mags_on_pred else ""),
                            (f"{last_prob:.4f}" if isinstance(last_prob, (int, float)) else ""),
                            (f"{last_mag:.4f}" if isinstance(last_mag, (int, float)) else ""),
                        ]
            except _NON_FATAL_HTTP_ERRORS:
                move_stats_row = None

        def _corr(xs: list[float], ys: list[float]) -> float:
            try:
                import math

                n = len(xs)
                if n < 3:
                    return float("nan")
                mean_x = sum(xs) / n
                mean_y = sum(ys) / n
                cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / (n - 1)
                var_x = sum((x - mean_x) ** 2 for x in xs) / (n - 1)
                var_y = sum((y - mean_y) ** 2 for y in ys) / (n - 1)
                if var_x <= 0 or var_y <= 0:
                    return float("nan")
                return cov / math.sqrt(var_x * var_y)
            except (ImportError, *_NON_FATAL_MATH_ERRORS):
                return float("nan")

        def _slope_per_hr(ts_ms: list[int], vals: list[float]) -> float:
            try:
                n = len(ts_ms)
                if n < 2:
                    return float("nan")
                xs = [t / 3_600_000.0 for t in ts_ms]
                mean_x = sum(xs) / n
                mean_y = sum(vals) / n
                denom = sum((x - mean_x) ** 2 for x in xs)
                if denom == 0:
                    return float(0.0)
                numer = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, vals))
                return numer / denom
            except _NON_FATAL_MATH_ERRORS:
                return float("nan")

        for mname, pmap in preds_map.items():
            keys = sorted(set(pmap.keys()) & set(tp_by_bucket.keys()))
            if not keys:
                if seq_tp and (mname in seq_pred_by_model):
                    try:
                        import math

                        xs = list(seq_pred_by_model.get(mname, []))
                        ys = list(seq_tp)
                        n = min(len(xs), len(ys))
                        xs = xs[:n]
                        ys = ys[:n]
                        if n >= 3:
                            deltas = [a - b for a, b in zip(xs, ys)]
                            mae = sum(abs(d) for d in deltas) / n
                            rmse = math.sqrt(sum((d) ** 2 for d in deltas) / n)
                            bias_mean = sum(deltas) / n
                            sd = sorted(deltas)
                            mpos = n // 2
                            bias_median = sd[mpos] if n % 2 == 1 else 0.5 * (sd[mpos - 1] + sd[mpos])
                            p10 = sd[int((n - 1) * 0.10)]
                            p90 = sd[int((n - 1) * 0.90)]
                            last_pred = xs[-1]
                            last_tp_v = ys[-1]
                            last_delta = last_pred - last_tp_v
                            row_parts = [
                                mname,
                                idx_norm,
                                str(horizon),
                                str(n),
                                f"{mae:.4f}",
                                f"{rmse:.4f}",
                                f"{bias_mean:.4f}",
                                f"{bias_median:.4f}",
                                "",
                                "",
                                "",
                                f"{p10:.4f}",
                                f"{p90:.4f}",
                                f"{last_pred:.4f}",
                                f"{last_tp_v:.4f}",
                                f"{last_delta:.4f}",
                                str(window_minutes),
                            ]
                            if "sk_hgb_residual" in include_models:
                                if mname == "sk_hgb_residual":
                                    bxs = list(seq_hybrid_baseline)
                                    nb = min(len(bxs), len(ys))
                                    bxs = bxs[:nb]
                                    ys_b = ys[:nb]
                                    b_rmse = None
                                    if nb >= 3:
                                        bd = [a - b for a, b in zip(bxs, ys_b)]
                                        b_rmse = math.sqrt(sum((d) ** 2 for d in bd) / nb)
                                    h_rmse = rmse
                                    ratio = None
                                    try:
                                        if b_rmse and h_rmse and h_rmse > 0:
                                            ratio = b_rmse / h_rmse
                                    except _NON_FATAL_MATH_ERRORS:
                                        ratio = None
                                    try:
                                        logger.debug(
                                            "DBG_HYBRID_FALLBACK %s",
                                            {
                                                "nb": nb,
                                                "len_seq_base": len(seq_hybrid_baseline),
                                                "len_seq_resid": len(seq_hybrid_residual),
                                                "len_seq_tp": len(seq_tp),
                                                "b_rmse": b_rmse,
                                                "h_rmse": h_rmse,
                                                "ratio": ratio,
                                            },
                                        )
                                    except (TypeError, ValueError):
                                        pass
                                    row_parts.extend(
                                        [
                                            (
                                                f"{b_rmse:.4f}"
                                                if isinstance(b_rmse, (int, float)) and b_rmse == b_rmse
                                                else ""
                                            ),
                                            (
                                                f"{h_rmse:.4f}"
                                                if isinstance(h_rmse, (int, float)) and h_rmse == h_rmse
                                                else ""
                                            ),
                                            (
                                                f"{ratio:.4f}"
                                                if isinstance(ratio, (int, float)) and ratio == ratio
                                                else ""
                                            ),
                                            (f"{(bxs[-1] if bxs else float('nan')):.4f}" if bxs else ""),
                                            (
                                                f"{(seq_hybrid_residual[-1] if seq_hybrid_residual else float('nan')):.4f}"
                                                if seq_hybrid_residual
                                                else ""
                                            ),
                                        ]
                                    )
                                else:
                                    row_parts.extend(["", "", "", "", ""])
                            if include_bands:
                                row_parts.extend(["", ""])
                                if include_effective_bands:
                                    row_parts.extend(["", "", ""])
                            if include_move_stats:
                                row_parts.extend(["", "", "", "", "", "", ""])
                            if len(row_parts) < expected_len:
                                row_parts.extend([""] * (expected_len - len(row_parts)))
                            try:
                                if mname == "sk_hgb_residual":
                                    logger.debug("DEBUG_DIAG_FALLBACK_ROW %s", row_parts)
                            except (TypeError, ValueError):
                                pass
                            out.append(",".join(row_parts))
                            continue
                    except _NON_FATAL_HTTP_ERRORS:
                        pass

                seq_mae = seq_rmse = None
                seq_bias_mean = seq_bias_median = None
                seq_p10 = seq_p90 = None
                seq_last_pred = seq_last_tp = seq_last_delta = None
                if seq_tp and (mname in seq_pred_by_model):
                    try:
                        import math

                        xs = list(seq_pred_by_model.get(mname, []))
                        ys = list(seq_tp)
                        n2 = min(len(xs), len(ys))
                        xs = xs[:n2]
                        ys = ys[:n2]
                        if n2 >= 3:
                            dd = [a - b for a, b in zip(xs, ys)]
                            seq_mae = sum(abs(d) for d in dd) / n2
                            seq_rmse = math.sqrt(sum(d * d for d in dd) / n2)
                            seq_bias_mean = sum(dd) / n2
                            sdd = sorted(dd)
                            mid2 = n2 // 2
                            seq_bias_median = (
                                sdd[mid2]
                                if n2 % 2 == 1
                                else 0.5 * (sdd[mid2 - 1] + sdd[mid2])
                            )

                            def _pct_last(vals: list[float], q: float) -> float:
                                if not vals:
                                    return float("nan")
                                s = sorted(vals)
                                k = (len(s) - 1) * q
                                f = int(k)
                                c = min(f + 1, len(s) - 1)
                                return s[f] if f == c else (s[f] + (s[c] - s[f]) * (k - f))

                            seq_p10 = _pct_last(dd, 0.10)
                            seq_p90 = _pct_last(dd, 0.90)
                            seq_last_pred = xs[-1]
                            seq_last_tp = ys[-1]
                            seq_last_delta = seq_last_pred - seq_last_tp
                    except _NON_FATAL_HTTP_ERRORS:
                        pass

                base_parts = [
                    mname,
                    idx_norm,
                    str(horizon),
                    "0",
                    (f"{seq_mae:.4f}" if isinstance(seq_mae, (int, float)) and seq_mae == seq_mae else ""),
                    (f"{seq_rmse:.4f}" if isinstance(seq_rmse, (int, float)) and seq_rmse == seq_rmse else ""),
                    (
                        f"{seq_bias_mean:.4f}"
                        if isinstance(seq_bias_mean, (int, float)) and seq_bias_mean == seq_bias_mean
                        else ""
                    ),
                    (
                        f"{seq_bias_median:.4f}"
                        if isinstance(seq_bias_median, (int, float)) and seq_bias_median == seq_bias_median
                        else ""
                    ),
                    "",
                    "",
                    "",
                    (f"{seq_p10:.4f}" if isinstance(seq_p10, (int, float)) and seq_p10 == seq_p10 else ""),
                    (f"{seq_p90:.4f}" if isinstance(seq_p90, (int, float)) and seq_p90 == seq_p90 else ""),
                    (
                        f"{seq_last_pred:.4f}"
                        if isinstance(seq_last_pred, (int, float)) and seq_last_pred == seq_last_pred
                        else ""
                    ),
                    (
                        f"{seq_last_tp:.4f}"
                        if isinstance(seq_last_tp, (int, float)) and seq_last_tp == seq_last_tp
                        else ""
                    ),
                    (
                        f"{seq_last_delta:.4f}"
                        if isinstance(seq_last_delta, (int, float)) and seq_last_delta == seq_last_delta
                        else ""
                    ),
                    str(window_minutes),
                ]

                if "sk_hgb_residual" in include_models:
                    if mname == "sk_hgb_residual":
                        b_rmse_v = h_rmse_v = ratio_v = None
                        last_base_v = last_resid_v = None
                        try:
                            import math

                            ys = list(seq_tp)
                            bxs = list(seq_hybrid_baseline)
                            xs = list(seq_pred_by_model.get(mname, []))
                            n3 = min(len(bxs), len(ys))
                            if n3 >= 3:
                                bd = [bxs[i] - ys[i] for i in range(n3)]
                                b_rmse_v = math.sqrt(sum(d * d for d in bd) / n3)
                            n4 = min(len(xs), len(ys))
                            if n4 >= 3:
                                dd2 = [xs[i] - ys[i] for i in range(n4)]
                                h_rmse_v = math.sqrt(sum(d * d for d in dd2) / n4)
                            if (
                                isinstance(b_rmse_v, (int, float))
                                and isinstance(h_rmse_v, (int, float))
                                and h_rmse_v > 0
                            ):
                                ratio_v = b_rmse_v / h_rmse_v
                            if seq_hybrid_baseline:
                                last_base_v = seq_hybrid_baseline[-1]
                            if seq_hybrid_residual:
                                last_resid_v = seq_hybrid_residual[-1]
                        except _NON_FATAL_HTTP_ERRORS:
                            pass

                        if (
                            (not isinstance(b_rmse_v, (int, float)) or b_rmse_v == 0 or not (b_rmse_v == b_rmse_v))
                            and hybrid_fp.exists()
                        ):
                            try:
                                h_header3, h_lines3 = read_header_and_rows(hybrid_fp)
                                if h_header3:
                                    hc = h_header3.split(",")
                                    _p = hc.index("prediction") if "prediction" in hc else -1
                                    _b = hc.index("baseline") if "baseline" in hc else -1
                                    preds_arr: list[float] = []
                                    bases_arr: list[float] = []
                                    for _r in h_lines3:
                                        _parts = _r.split(",")
                                        try:
                                            if _p >= 0 and len(_parts) > _p:
                                                preds_arr.append(float(_parts[_p]))
                                            if _b >= 0 and len(_parts) > _b:
                                                bases_arr.append(float(_parts[_b]))
                                        except _NON_FATAL_PARSE_ERRORS:
                                            continue

                                    tp_arr: list[float] = []
                                    for row in live_rows:
                                        try:
                                            tp_raw = row.get("tp")
                                            tp_val = float(tp_raw) if tp_raw is not None else None
                                        except (TypeError, ValueError):
                                            tp_val = None
                                        if isinstance(tp_val, (int, float)):
                                            tp_arr.append(float(tp_val))

                                    import math as _m

                                    n_b = min(len(bases_arr), len(tp_arr))
                                    if n_b >= 3:
                                        bd = [bases_arr[i] - tp_arr[i] for i in range(n_b)]
                                        b_rmse_v = _m.sqrt(sum(d * d for d in bd) / n_b)
                                    n_h = min(len(preds_arr), len(tp_arr))
                                    if n_h >= 3:
                                        dd = [preds_arr[i] - tp_arr[i] for i in range(n_h)]
                                        h_rmse_v = _m.sqrt(sum(d * d for d in dd) / n_h)
                                    if (
                                        isinstance(b_rmse_v, (int, float))
                                        and isinstance(h_rmse_v, (int, float))
                                        and h_rmse_v > 0
                                    ):
                                        ratio_v = b_rmse_v / h_rmse_v
                            except _NON_FATAL_HTTP_ERRORS:
                                pass

                        base_parts.extend(
                            [
                                (
                                    f"{b_rmse_v:.4f}"
                                    if isinstance(b_rmse_v, (int, float)) and b_rmse_v == b_rmse_v
                                    else ""
                                ),
                                (
                                    f"{h_rmse_v:.4f}"
                                    if isinstance(h_rmse_v, (int, float)) and h_rmse_v == h_rmse_v
                                    else ""
                                ),
                                (
                                    f"{ratio_v:.4f}"
                                    if isinstance(ratio_v, (int, float)) and ratio_v == ratio_v
                                    else ""
                                ),
                                (
                                    f"{last_base_v:.4f}"
                                    if isinstance(last_base_v, (int, float)) and last_base_v == last_base_v
                                    else ""
                                ),
                                (
                                    f"{last_resid_v:.4f}"
                                    if isinstance(last_resid_v, (int, float)) and last_resid_v == last_resid_v
                                    else ""
                                ),
                            ]
                        )
                    else:
                        base_parts.extend(["", "", "", "", ""])

                if include_bands:
                    base_parts.extend(["", ""])
                    if include_effective_bands:
                        base_parts.extend(["", "", ""])

                if include_move_stats:
                    base_parts.extend(["", "", "", "", "", "", ""])

                if len(base_parts) < expected_len:
                    base_parts.extend([""] * (expected_len - len(base_parts)))
                out.append(",".join(base_parts))
                continue

            preds = [pmap[k] for k in keys]
            tps = [tp_by_bucket[k] for k in keys]
            deltas = [a - b for a, b in zip(preds, tps)]

            import math

            n = len(keys)
            mae = sum(abs(d) for d in deltas) / n
            rmse = math.sqrt(sum((d) ** 2 for d in deltas) / n)
            bias_mean = sum(deltas) / n
            sorted_d = sorted(deltas)
            mid = n // 2
            bias_median = sorted_d[mid] if n % 2 == 1 else 0.5 * (sorted_d[mid - 1] + sorted_d[mid])
            corr = _corr(preds, tps)
            slope_pred = _slope_per_hr(keys, preds)
            slope_tp = _slope_per_hr(keys, tps)

            def _pct(vals: list[float], p: float) -> float:
                if not vals:
                    return float("nan")
                s = sorted(vals)
                k = (len(s) - 1) * p
                f = int(k)
                c = min(f + 1, len(s) - 1)
                if f == c:
                    return s[f]
                return s[f] + (s[c] - s[f]) * (k - f)

            p10 = _pct(deltas, 0.10)
            p90 = _pct(deltas, 0.90)
            last_k = keys[-1]
            last_pred = pmap[last_k]
            last_tp = tp_by_bucket[last_k]
            last_delta = last_pred - last_tp

            baseline_rmse = hybrid_rmse = improv_ratio = None
            last_base = last_resid = None
            if mname == "sk_hgb_residual":
                b_keys = [k for k in keys if k in hybrid_baseline_by_bucket]
                if b_keys:
                    b_deltas = [hybrid_baseline_by_bucket[k] - tp_by_bucket[k] for k in b_keys]
                    if b_deltas:
                        baseline_rmse = math.sqrt(sum((d) ** 2 for d in b_deltas) / len(b_deltas))
                    hybrid_rmse = rmse
                    try:
                        if hybrid_rmse and hybrid_rmse > 0:
                            improv_ratio = baseline_rmse / hybrid_rmse
                    except _NON_FATAL_MATH_ERRORS:
                        improv_ratio = None
                    if last_k in hybrid_baseline_by_bucket:
                        try:
                            last_base = float(hybrid_baseline_by_bucket[last_k])
                        except (TypeError, ValueError):
                            last_base = None
                    if last_k in hybrid_residual_by_bucket:
                        try:
                            last_resid = float(hybrid_residual_by_bucket[last_k])
                        except (TypeError, ValueError):
                            last_resid = None

                def _seq_rmse(xs: list[float], ys: list[float]) -> float | None:
                    try:
                        n = min(len(xs), len(ys))
                        if n < 3:
                            return None
                        xs2 = xs[:n]
                        ys2 = ys[:n]
                        dd = [(a - b) for a, b in zip(xs2, ys2)]
                        return math.sqrt(sum((d) ** 2 for d in dd) / n)
                    except _NON_FATAL_MATH_ERRORS:
                        return None

                try:
                    if (not isinstance(baseline_rmse, (int, float)) or not (baseline_rmse == baseline_rmse)):
                        b_rmse_seq = _seq_rmse(list(seq_hybrid_baseline), list(seq_tp))
                        if isinstance(b_rmse_seq, (int, float)) and b_rmse_seq == b_rmse_seq:
                            baseline_rmse = b_rmse_seq
                    if (not isinstance(hybrid_rmse, (int, float)) or not (hybrid_rmse == hybrid_rmse)):
                        h_rmse_seq = _seq_rmse(list(seq_pred_by_model.get(mname, [])), list(seq_tp))
                        if isinstance(h_rmse_seq, (int, float)) and h_rmse_seq == h_rmse_seq:
                            hybrid_rmse = h_rmse_seq

                    if (
                        mname == "sk_hgb_residual"
                        and (not isinstance(baseline_rmse, (int, float)) or baseline_rmse == 0.0)
                        and hybrid_fp.exists()
                    ):
                        try:
                            h_header2, h_lines2 = read_header_and_rows(hybrid_fp)
                            if h_header2:
                                h_cols2 = h_header2.split(",")
                                try:
                                    _h_pred = h_cols2.index("prediction")
                                    _h_base = h_cols2.index("baseline") if "baseline" in h_cols2 else -1
                                    _h_resid = h_cols2.index("residual") if "residual" in h_cols2 else -1
                                except ValueError:
                                    _h_pred = _h_base = _h_resid = -1
                                bases_seq: list[float] = []
                                hybrid_seq: list[float] = []
                                for _r in h_lines2:
                                    _parts = _r.split(",")
                                    if _h_pred < 0 or len(_parts) <= _h_pred:
                                        continue
                                    try:
                                        hybrid_seq.append(float(_parts[_h_pred]))
                                    except _NON_FATAL_PARSE_ERRORS:
                                        continue
                                    if _h_base >= 0 and len(_parts) > _h_base:
                                        try:
                                            bases_seq.append(float(_parts[_h_base]))
                                        except _NON_FATAL_PARSE_ERRORS:
                                            pass

                                if not seq_tp:
                                    for row in live_rows:
                                        try:
                                            tp_raw = row.get("tp")
                                            tp_val = float(tp_raw) if tp_raw is not None else None
                                        except (TypeError, ValueError):
                                            tp_val = None
                                        if isinstance(tp_val, (int, float)):
                                            seq_tp.append(float(tp_val))

                                pos_n = min(len(bases_seq), len(seq_tp))
                                if pos_n >= 3 and (
                                    not isinstance(baseline_rmse, (int, float)) or baseline_rmse == 0.0
                                ):
                                    pos_dd = [(bases_seq[i] - seq_tp[i]) for i in range(pos_n)]
                                    try:
                                        baseline_rmse = math.sqrt(sum(d * d for d in pos_dd) / pos_n)
                                    except _NON_FATAL_MATH_ERRORS:
                                        pass

                                b_rmse_seq2 = _seq_rmse(bases_seq, list(seq_tp))
                                h_rmse_seq2 = _seq_rmse(hybrid_seq, list(seq_tp))
                                if isinstance(b_rmse_seq2, (int, float)) and b_rmse_seq2 == b_rmse_seq2:
                                    baseline_rmse = b_rmse_seq2
                                if (
                                    isinstance(h_rmse_seq2, (int, float))
                                    and h_rmse_seq2 == h_rmse_seq2
                                    and (not isinstance(hybrid_rmse, (int, float)) or hybrid_rmse == hybrid_rmse)
                                ):
                                    hybrid_rmse = h_rmse_seq2 or hybrid_rmse
                                if (
                                    isinstance(baseline_rmse, (int, float))
                                    and isinstance(hybrid_rmse, (int, float))
                                    and hybrid_rmse > 0
                                ):
                                    improv_ratio = baseline_rmse / hybrid_rmse
                                if last_base is None and bases_seq:
                                    try:
                                        last_base = float(bases_seq[-1])
                                    except (TypeError, ValueError, IndexError):
                                        pass
                                if last_resid is None and _h_resid >= 0 and len(h_lines2) > 1:
                                    try:
                                        last_resid = float(h_lines2[-1].split(",")[_h_resid])
                                    except (TypeError, ValueError, IndexError):
                                        pass
                        except _NON_FATAL_HTTP_ERRORS:
                            pass

                    if (
                        isinstance(baseline_rmse, (int, float))
                        and baseline_rmse == baseline_rmse
                        and isinstance(hybrid_rmse, (int, float))
                        and hybrid_rmse == hybrid_rmse
                        and hybrid_rmse > 0
                    ):
                        improv_ratio = baseline_rmse / hybrid_rmse

                    if last_base is None and seq_hybrid_baseline:
                        try:
                            last_base = float(seq_hybrid_baseline[-1])
                        except (TypeError, ValueError, IndexError):
                            last_base = None
                    if last_resid is None and seq_hybrid_residual:
                        try:
                            last_resid = float(seq_hybrid_residual[-1])
                        except (TypeError, ValueError, IndexError):
                            last_resid = None
                except _NON_FATAL_HTTP_ERRORS:
                    pass

            band_radius = None
            cov_est = None
            if include_bands:
                abs_res = [abs(d) for d in deltas]
                if abs_res:
                    s = sorted(abs_res)
                    q = min(max(coverage, 0.5), 0.99)
                    kf = (len(s) - 1) * q
                    fi = int(kf)
                    ci = min(fi + 1, len(s) - 1)
                    band_radius = s[fi] if fi == ci else (s[fi] + (s[ci] - s[fi]) * (kf - fi))
                    inside = sum(1 for r in abs_res if r <= band_radius)
                    cov_est = inside / len(abs_res)
                    if include_effective_bands:
                        kfac = float(disagreement_k)
                        eff_inside = 0
                        eff_radii: list[float] = []
                        for i, k_b in enumerate(keys):
                            r = abs_res[i]
                            dis_b = float(dis_by_bucket.get(k_b, 0.0))
                            rad_b = band_radius if band_radius is not None else 0.0
                            eff_r = max(float(rad_b), kfac * dis_b)
                            eff_radii.append(eff_r)
                            if r <= eff_r:
                                eff_inside += 1
                        eff_cov = eff_inside / len(abs_res) if abs_res else float("nan")
                        eff_avg = (sum(eff_radii) / len(eff_radii)) if eff_radii else float("nan")
                        eff_last = (eff_radii[-1] if eff_radii else float("nan"))

            row_parts = [
                mname,
                idx_norm,
                str(horizon),
                str(n),
                f"{mae:.4f}",
                f"{rmse:.4f}",
                f"{bias_mean:.4f}",
                f"{bias_median:.4f}",
                f"{corr:.4f}" if corr == corr else "",
                f"{slope_pred:.4f}",
                f"{slope_tp:.4f}",
                f"{p10:.4f}",
                f"{p90:.4f}",
                f"{last_pred:.4f}",
                f"{last_tp:.4f}",
                f"{last_delta:.4f}",
                str(window_minutes),
            ]

            if "sk_hgb_residual" in include_models:
                if mname == "sk_hgb_residual":
                    row_parts.extend(
                        [
                            (
                                f"{baseline_rmse:.4f}"
                                if isinstance(baseline_rmse, (int, float)) and baseline_rmse == baseline_rmse
                                else ""
                            ),
                            (
                                f"{hybrid_rmse:.4f}"
                                if isinstance(hybrid_rmse, (int, float)) and hybrid_rmse == hybrid_rmse
                                else f"{rmse:.4f}"
                            ),
                            (
                                f"{improv_ratio:.4f}"
                                if isinstance(improv_ratio, (int, float)) and improv_ratio == improv_ratio
                                else ""
                            ),
                            (f"{last_base:.4f}" if isinstance(last_base, (int, float)) else ""),
                            (f"{last_resid:.4f}" if isinstance(last_resid, (int, float)) else ""),
                        ]
                    )
                else:
                    row_parts.extend(["", "", "", "", ""])

            if include_bands:
                row_parts.append(f"{(band_radius if band_radius is not None else float('nan')):.4f}")
                row_parts.append(f"{(cov_est if cov_est is not None else float('nan')):.4f}")
                if include_effective_bands:
                    try:
                        row_parts.append(f"{eff_cov:.4f}")
                        row_parts.append(f"{eff_avg:.4f}")
                        row_parts.append(f"{eff_last:.4f}")
                    except (NameError, TypeError, ValueError):
                        row_parts.extend(["", "", ""])

            if include_move_stats:
                if move_stats_row is not None:
                    row_parts.extend(move_stats_row)
                else:
                    row_parts.extend(["", "", "", "", "", "", ""])

            if len(row_parts) < expected_len:
                row_parts.extend([""] * (expected_len - len(row_parts)))
            out.append(",".join(row_parts))

        return PlainTextResponse("\n".join(out), media_type="text/csv")

    except asyncio.CancelledError:
        raise
    except HTTPException:
        raise
    except _NON_FATAL_HTTP_ERRORS as e:
        raise HTTPException(status_code=500, detail=str(e))
