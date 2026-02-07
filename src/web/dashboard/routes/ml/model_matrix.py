from __future__ import annotations

import asyncio
import datetime as _dt

from fastapi import HTTPException, Query
from fastapi.responses import PlainTextResponse

from ...core.csv_io import (
    load_csv_rows_full as _load_csv_rows_full,
    parse_time_epoch_ms as _parse_time_epoch_ms,
)
from .._index_norm import normalize_index
from ._common import project_root as _project_root, resolve_live_csv_path as _resolve_live_csv_path
from .._tabular_file import read_header_and_rows


async def api_ml_model_matrix(
    window_minutes: int = Query(60, ge=1, le=24 * 60, description="Lookback window in minutes for diagnostics"),
    bucket_ms: int = Query(60_000, ge=1_000, le=3_600_000, description="Bucket size for time alignment in ms"),
) -> PlainTextResponse:
    """Return a CSV matrix summarizing models across indices/horizons.

    Sources:
    - models/champions.json for model selection, config and artifact
    - configs/ml/*.json for features, params, FE options
    - models/*.fe.json sidecars for used_features and normalize stats (if present)
    - Live diagnostics computed like /api/ml/diagnostics over the given window

    Columns:
    model,index,horizon,config,artifact,features_count,used_features_count,fe_horizon,lag_columns,lags,roll_windows,add_time,add_moneyness,normalize_keys,normalize_cols_count,params_summary,champion_metric,champion_score,diag_count,diag_mae,diag_rmse,diag_bias_mean,diag_bias_median,diag_corr,diag_slope_pred,diag_slope_tp,diag_delta_p10,diag_delta_p90,diag_last_pred,diag_last_tp,diag_last_delta,window_minutes
    """
    try:
        import json as _json

        base = _project_root()
        champs_path = base / "models" / "champions.json"
        if not champs_path.exists():
            raise HTTPException(status_code=404, detail="champions.json not found")
        champs = _json.loads(champs_path.read_text(encoding="utf-8"))
        champions = champs.get("champions", {}) or {}

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
            except (ImportError, OverflowError, ZeroDivisionError, TypeError, ValueError):
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
            except (OverflowError, ZeroDivisionError, TypeError, ValueError):
                return float("nan")

        out = [
            "model,index,horizon,config,artifact,features_count,used_features_count,fe_horizon,lag_columns,lags,roll_windows,add_time,add_moneyness,normalize_keys,normalize_cols_count,params_summary,champion_metric,champion_score,diag_count,diag_mae,diag_rmse,diag_bias_mean,diag_bias_median,diag_corr,diag_slope_pred,diag_slope_tp,diag_delta_p10,diag_delta_p90,diag_last_pred,diag_last_tp,diag_last_delta,window_minutes"
        ]

        for _key, meta in sorted(champions.items()):
            try:
                idx = str(meta.get("index", "")).upper()
                horizon = str(meta.get("horizon", ""))
                model = str(meta.get("model_name", meta.get("model") or ""))
                cfg_rel = meta.get("config") or ""
                art_rel = meta.get("artifact") or ""
                metric = meta.get("metric") or ""
                score = meta.get("score")
                cfg_path = (base / cfg_rel) if cfg_rel else None
                art_path = (base / art_rel) if art_rel else None

                features_count = used_features_count = fe_hor = 0
                lag_cols: list[str] = []
                lags: list[int] = []
                roll_windows: list[int] = []
                add_time = add_moneyness = False
                norm_keys: list[str] = []
                norm_cols_count = 0
                params_summary = ""
                if cfg_path and cfg_path.exists():
                    cfg_json = _json.loads(cfg_path.read_text(encoding="utf-8"))
                    feats = list(cfg_json.get("features") or [])
                    features_count = len(feats)
                    fe = cfg_json.get("feature_engineering") or {}
                    fe_hor = int(fe.get("forecast_horizon", 0))
                    lag_cols = list(fe.get("lag_columns") or [])
                    lags = list(fe.get("lags") or [])
                    roll_windows = list(fe.get("roll_windows") or [])
                    add_time = bool(fe.get("add_time", False))
                    add_moneyness = bool(fe.get("add_moneyness", False))
                    nb = fe.get("normalize_by") or {}
                    norm_keys = list(nb.get("keys") or [])
                    norm_cols = list(nb.get("columns") or [])
                    norm_cols_count = len(norm_cols)
                    params = cfg_json.get("params") or {}
                    try:
                        params_summary = ";".join(f"{k}={v}" for k, v in list(params.items())[:8])
                    except (AttributeError, TypeError, ValueError):
                        params_summary = ""

                if art_path and art_path.exists():
                    sidecar = None
                    cand1 = art_path.with_suffix(art_path.suffix + ".fe.json")
                    cand2 = art_path.with_suffix(".fe.json")
                    for c in (cand1, cand2):
                        if c.exists():
                            sidecar = c
                            break
                    if sidecar is None:
                        sc_guess = art_path.parent / (art_path.name + ".fe.json")
                        if sc_guess.exists():
                            sidecar = sc_guess
                    if sidecar and sidecar.exists():
                        try:
                            sc = _json.loads(sidecar.read_text(encoding="utf-8"))
                            used_features = list(sc.get("used_features") or [])
                            used_features_count = len(used_features)
                        except (_json.JSONDecodeError, UnicodeDecodeError, OSError, TypeError, ValueError):
                            used_features_count = 0

                pred_fp = base / "data" / "ml" / "live_predictions" / f"{idx}.csv"
                now_ms = int(_dt.datetime.now(tz=_dt.timezone.utc).timestamp() * 1000)
                cutoff_ms = now_ms - window_minutes * 60_000
                preds_map: dict[int, float] = {}
                diag_count = 0
                mae = rmse = bias_mean = bias_median = float("nan")
                corr = slope_pred = slope_tp = float("nan")
                p10 = p90 = last_pred = last_tp = last_delta = float("nan")
                if pred_fp.exists():
                    header, data_lines = read_header_and_rows(pred_fp)
                    if header:
                        cols = header.split(",")
                        try:
                            ts_idx = cols.index("timestamp")
                            pred_idx = cols.index("prediction")
                            mdl_idx = cols.index("model")
                            hor_idx = cols.index("horizon")
                        except ValueError:
                            ts_idx = pred_idx = mdl_idx = hor_idx = -1
                        for r in data_lines[-5000:]:
                            parts = r.split(",")
                            if ts_idx < 0 or len(parts) <= max(ts_idx, pred_idx, mdl_idx, hor_idx):
                                continue
                            if parts[mdl_idx] != model or parts[hor_idx] != str(horizon):
                                continue
                            ems = _parse_time_epoch_ms(parts[ts_idx])
                            if ems is None or ems < cutoff_ms:
                                continue
                            bucket = (ems // bucket_ms) * bucket_ms
                            try:
                                pv = float(parts[pred_idx])
                            except (TypeError, ValueError, IndexError):
                                continue
                            preds_map[bucket] = pv

                tp_by_bucket: dict[int, float] = {}
                from datetime import date

                p = _resolve_live_csv_path(idx, "this_week", "0", date.today())
                if p and p.exists():
                    live_rows = _load_csv_rows_full(p)
                    for row in live_rows:
                        try:
                            ems = int(row.get("ts") or row.get("time") or 0)
                        except (TypeError, ValueError):
                            continue
                        if not ems or ems < cutoff_ms:
                            continue
                        bucket = (ems // bucket_ms) * bucket_ms
                        tp = row.get("tp")
                        if isinstance(tp, (int, float)):
                            tp_by_bucket[bucket] = float(tp)

                keys = sorted(set(preds_map.keys()) & set(tp_by_bucket.keys()))
                if keys:
                    import math

                    diag_count = len(keys)
                    preds = [preds_map[k] for k in keys]
                    tps = [tp_by_bucket[k] for k in keys]
                    deltas = [a - b for a, b in zip(preds, tps)]
                    mae = sum(abs(d) for d in deltas) / diag_count
                    rmse = math.sqrt(sum((d) ** 2 for d in deltas) / diag_count)
                    bias_mean = sum(deltas) / diag_count
                    sd = sorted(deltas)
                    m = diag_count // 2
                    bias_median = sd[m] if diag_count % 2 == 1 else 0.5 * (sd[m - 1] + sd[m])
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
                    last_pred = preds_map[last_k]
                    last_tp = tp_by_bucket[last_k]
                    last_delta = last_pred - last_tp

                out.append(
                    ",".join(
                        [
                            model,
                            idx,
                            str(horizon),
                            (cfg_rel or ""),
                            (art_rel or ""),
                            str(features_count),
                            str(used_features_count),
                            str(fe_hor),
                            "|".join(map(str, lag_cols)) if lag_cols else "",
                            "|".join(map(str, lags)) if lags else "",
                            "|".join(map(str, roll_windows)) if roll_windows else "",
                            "1" if add_time else "0",
                            "1" if add_moneyness else "0",
                            "|".join(map(str, norm_keys)) if norm_keys else "",
                            str(norm_cols_count),
                            params_summary.replace(",", ";"),
                            str(metric),
                            (f"{float(score):.6f}" if isinstance(score, (int, float)) else str(score or "")),
                            str(diag_count),
                            (f"{mae:.4f}" if diag_count else ""),
                            (f"{rmse:.4f}" if diag_count else ""),
                            (f"{bias_mean:.4f}" if diag_count else ""),
                            (f"{bias_median:.4f}" if diag_count else ""),
                            (f"{corr:.4f}" if diag_count and corr == corr else ""),
                            (f"{slope_pred:.4f}" if diag_count else ""),
                            (f"{slope_tp:.4f}" if diag_count else ""),
                            (f"{p10:.4f}" if diag_count else ""),
                            (f"{p90:.4f}" if diag_count else ""),
                            (f"{last_pred:.4f}" if diag_count else ""),
                            (f"{last_tp:.4f}" if diag_count else ""),
                            (f"{last_delta:.4f}" if diag_count else ""),
                            str(window_minutes),
                        ]
                    )
                )
            except BaseException as e:
                if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
                    raise
                out.append(
                    ",".join(
                        [
                            str(meta.get("model_name", "")),
                            str(meta.get("index", "")),
                            str(meta.get("horizon", "")),
                            str(meta.get("config", "")),
                            str(meta.get("artifact", "")),
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            str(meta.get("metric", "")),
                            str(meta.get("score", "")),
                            "0",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            str(window_minutes),
                        ]
                    )
                )

        return PlainTextResponse("\n".join(out), media_type="text/csv")
    except HTTPException:
        raise
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError)):
            raise
        raise HTTPException(status_code=500, detail=str(e))
