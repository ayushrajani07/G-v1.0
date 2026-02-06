from __future__ import annotations

import datetime as _dt
import logging
from typing import Optional

from src.config.env_config import EnvConfig
from src.path_forecast.common import extract_tp as _extract_tp, row_time_ms as _row_time_ms

logger = logging.getLogger(__name__)


def _build_output_rows_and_headers(
    idx_norm: str,
    rows: list[dict],
    times: list[int],
    qmap: dict,
    diag: dict,
    last_tp: float,
    ref_now_ms: int,
    bucket_ms: int,
    align: str,
    mode_used: str,
    profile: Optional[str],
    distance_metric_eff: Optional[str],
    weight_mode_eff: Optional[str],
    recent_gamma_eff: Optional[float],
    regime_tolerance_eff: Optional[float],
    regime_penalty_eff: Optional[float],
):
    # Build realized TP overlay
    tp_ts: list[int] = []
    tp_vals: list[float | None] = []
    try:
        for r in rows:
            tms = _row_time_ms(r)
            if not isinstance(tms, int) or tms <= 0:
                continue
            v = _extract_tp(r)
            vv = None
            if isinstance(v, (int, float)):
                vv = float(v)
                if vv < 0:
                    vv = 0.0
            tp_ts.append(int(tms))
            tp_vals.append(vv)
    except (AttributeError, KeyError, TypeError, ValueError):
        tp_ts, tp_vals = [], []
    q10_list = list(qmap.get(0.1) or qmap.get("0.1") or [])
    q50_list = list(qmap.get(0.5) or qmap.get("0.5") or [])
    q90_list = list(qmap.get(0.9) or qmap.get("0.9") or [])
    # Capture width sample before any widening for diagnostics
    widths_pre_sample: list[float] = []
    try:
        total_pre = min(len(q10_list), len(q50_list), len(q90_list))
        for i in range(min(5, total_pre)):
            v10 = q10_list[i] if i < len(q10_list) else None
            v50 = q50_list[i] if i < len(q50_list) else None
            v90 = q90_list[i] if i < len(q90_list) else None
            if all(isinstance(v, (int, float)) for v in (v10, v50, v90)):
                widths_pre_sample.append(float(v90) - float(v10))
    except (TypeError, ValueError, IndexError):
        widths_pre_sample = []
    # Final safety: if bands are still completely flat at this stage, widen minimally for output only
    try:
        total_ = min(len(q10_list), len(q50_list), len(q90_list))
        # Detect exact identity across arrays (strong signal of degeneracy)
        identical_seq = (
            len(q10_list) == len(q50_list) == len(q90_list)
            and q10_list == q50_list == q90_list
            and total_ >= 3
        )
        should_widen = False
        if identical_seq:
            should_widen = True
        elif total_ >= 10:
            flat_cnt_ = 0
            for i in range(total_):
                v10 = q10_list[i] if i < len(q10_list) else None
                v50v = q50_list[i] if i < len(q50_list) else None
                v90 = q90_list[i] if i < len(q90_list) else None
                if all(isinstance(v, (int, float)) for v in (v10, v50v, v90)) and v10 == v50v == v90:
                    flat_cnt_ += 1
            if flat_cnt_ / float(total_) >= 0.8:
                should_widen = True
        # Also widen when upstream flagged fallback_stub (degenerate retrieval)
        try:
            if bool(diag.get("fallback_stub")):
                should_widen = True
        except (AttributeError, TypeError):
            pass
        if should_widen:
            base_pct_ = 0.01
            try:
                if isinstance(diag.get("ribbon_dispersion_pct"), (int, float)):
                    base_pct_ = float(diag["ribbon_dispersion_pct"])
            except (TypeError, ValueError, KeyError):
                pass
            # Cap between 0.05% and 2% to avoid extremes
            base_pct_ = max(0.0005, min(0.02, base_pct_))
            for i in range(total_):
                v50v = q50_list[i] if i < len(q50_list) else None
                if isinstance(v50v, (int, float)):
                    # Ensure a visible absolute floor so even low-priced indices show spread
                    # Environment override for minimum absolute ribbon half-width.
                    # G6_RIBBON_ABS_FLOOR specifies the minimum enforced spread (half-width)
                    # applied when widening an otherwise too-thin ribbon. Defaults to 1.0.
                    # Allow profile-level override to take precedence over environment flag
                    profile_override = diag.get("ribbon_abs_floor_override")
                    if isinstance(profile_override, (int, float)) and profile_override >= 0:
                        ribbon_abs_floor = float(profile_override)
                    else:
                        ribbon_abs_floor = EnvConfig.get_float("G6_RIBBON_ABS_FLOOR", 1.0)
                    abs_floor = max(ribbon_abs_floor, base_pct_ * float(v50v))
                    spread_ = max(0.0001, abs_floor)
                    if i < len(q10_list) and isinstance(q10_list[i], (int, float)):
                        q10_list[i] = max(0.0, float(v50v) - spread_)
                    if i < len(q90_list) and isinstance(q90_list[i], (int, float)):
                        q90_list[i] = float(v50v) + spread_
            try:
                diag["ribbon_output_fix"] = 1
                diag["ribbon_output_pct"] = base_pct_
                try:
                    profile_override = diag.get("ribbon_abs_floor_override")
                    if isinstance(profile_override, (int, float)) and profile_override >= 0:
                        diag["ribbon_abs_floor"] = float(profile_override)
                    else:
                        diag["ribbon_abs_floor"] = EnvConfig.get_float("G6_RIBBON_ABS_FLOOR", 1.0)
                except (AttributeError, TypeError, ValueError):
                    diag["ribbon_abs_floor"] = 1.0
            except (AttributeError, TypeError, ValueError):
                pass
    except (AttributeError, KeyError, TypeError, ValueError):
        pass
    # Capture width sample after widening for diagnostics
    widths_post_sample: list[float] = []
    try:
        total_post = min(len(q10_list), len(q50_list), len(q90_list))
        for i in range(min(5, total_post)):
            v10 = q10_list[i] if i < len(q10_list) else None
            v50 = q50_list[i] if i < len(q50_list) else None
            v90 = q90_list[i] if i < len(q90_list) else None
            if all(isinstance(v, (int, float)) for v in (v10, v50, v90)):
                widths_post_sample.append(float(v90) - float(v10))
    except (TypeError, ValueError, IndexError):
        widths_post_sample = []
    # Log concise width diagnostics
    try:
        if widths_pre_sample or widths_post_sample:
            logger.info(
                "ribbon-widths %s mode=%s pre=%s post=%s",
                idx_norm,
                (mode_used or ""),
                widths_pre_sample,
                widths_post_sample,
            )
    except (TypeError, ValueError):
        pass
    out: list[dict] = []
    H = len(times)
    use_trailing = str(align).lower() == "trailing"
    trailing_base = (ref_now_ms - (H - 1) * int(bucket_ms)) if (use_trailing and H > 0) else None
    import bisect

    def _tp_at(ts_ms: int) -> float | None:
        try:
            if not tp_ts:
                return None
            j = bisect.bisect_right(tp_ts, int(ts_ms)) - 1
            if j < 0:
                for vv in tp_vals:
                    if isinstance(vv, (int, float)):
                        return float(vv)
                return None
            while j >= 0:
                vv = tp_vals[j] if (j < len(tp_vals)) else None
                if isinstance(vv, (int, float)):
                    return float(vv)
                j -= 1
            return None
        except (TypeError, ValueError, IndexError):
            return None

    seed_tp = float(last_tp) if isinstance(last_tp, (int, float)) else None
    for i, t in enumerate(times):
        row = {
            "time": _dt.datetime.fromtimestamp(t / 1000).replace(microsecond=0).isoformat(),
            "q10": (max(0.0, float(q10_list[i])) if i < len(q10_list) and q10_list[i] is not None else None),
            "q50": (max(0.0, float(q50_list[i])) if i < len(q50_list) and q50_list[i] is not None else None),
            "q90": (max(0.0, float(q90_list[i])) if i < len(q90_list) and q90_list[i] is not None else None),
        }
        if trailing_base is not None:
            plot_ts = trailing_base + i * int(bucket_ms)
            row["plot_ms"] = int(plot_ts)
            row["plot_time"] = _dt.datetime.utcfromtimestamp(plot_ts / 1000).replace(microsecond=0).isoformat() + "Z"
            tv = _tp_at(plot_ts) or seed_tp
            row["tp"] = tv
        else:
            row["plot_ms"] = int(t)
            row["plot_time"] = _dt.datetime.utcfromtimestamp(t / 1000).replace(microsecond=0).isoformat() + "Z"
            tv = _tp_at(t) or seed_tp
            row["tp"] = tv
        # Per-row safeguard: if bands are degenerate or near-zero width, force a small visible spread
        try:
            q10v = row.get("q10")
            q50v = row.get("q50")
            q90v = row.get("q90")
            if isinstance(q50v, (int, float)):
                # If width is zero or below tiny epsilon, apply absolute floor
                width_ok = (isinstance(q10v, (int, float)) and isinstance(q90v, (int, float)))
                current_w = (float(q90v) - float(q10v)) if width_ok else 0.0
                if (not width_ok) or (current_w <= 1e-6):
                    # Apply unified environment-controlled absolute floor for fallback widening.
                    profile_override = diag.get("ribbon_abs_floor_override")
                    if isinstance(profile_override, (int, float)) and profile_override >= 0:
                        ribbon_abs_floor = float(profile_override)
                    else:
                        ribbon_abs_floor = EnvConfig.get_float("G6_RIBBON_ABS_FLOOR", 1.0)
                    abs_floor = max(ribbon_abs_floor, 0.005 * float(q50v))
                    row["q10"] = max(0.0, float(q50v) - abs_floor)
                    row["q90"] = float(q50v) + abs_floor
                    try:
                        diag.setdefault("ribbon_output_fix_rows", 0)
                        diag["ribbon_output_fix_rows"] = int(diag.get("ribbon_output_fix_rows", 0)) + 1
                    except (TypeError, ValueError):
                        pass
        except (AttributeError, KeyError, TypeError, ValueError):
            pass
        out.append(row)

    # Headers
    headers = {
        "X-PathForecast-Mode": mode_used or "",
        "X-Retrieval-Candidates": str(diag.get("candidates_total", "")),
        "X-Retrieval-KUsed": str(diag.get("k_used", "")),
        "X-Retrieval-Window": str(diag.get("window_used", "")),
        "X-Retrieval-Pruned": str(diag.get("pruned_days", "")),
        "X-Retrieval-Retained": str(diag.get("retained_days", "")),
        "X-Retrieval-RegimePenalized": str(diag.get("regime_penalized", "")),
        "X-Retrieval-AnnEnabled": str(diag.get("ann_enabled", "")),
        "X-Retrieval-AnnTotalWindows": str(diag.get("ann_total_windows", "")),
        "X-Retrieval-AnnShortlisted": str(diag.get("ann_shortlisted", "")),
        "X-Cache-Entries": str(diag.get("cache_entries", "")),
        "X-Cache-Hits": str(diag.get("cache_hits", "")),
        "X-Cache-Misses": str(diag.get("cache_misses", "")),
        "X-Cache-Evictions": str(diag.get("cache_evictions", "")),
        "X-Retrieval-Distance": str(diag.get("distance_metric", distance_metric_eff or "")),
        "X-Retrieval-WeightMode": str(diag.get("weight_mode", weight_mode_eff or "")),
        "X-PathForecast-RequestedMode": str(mode_used),
        "X-Gen-Ms": str(ref_now_ms),
        "X-Gen-Iso": _dt.datetime.fromtimestamp(ref_now_ms / 1000).replace(microsecond=0).isoformat() if ref_now_ms else "",
        "X-Time-Align": str(align),
        "X-Route-Version": "json-v3",
    }
    # Width sample headers (best-effort, compact)
    try:
        if widths_pre_sample:
            headers["X-Ribbon-Width-Pre"] = ",".join(f"{w:.3f}" for w in widths_pre_sample)
        if widths_post_sample:
            headers["X-Ribbon-Width-Post"] = ",".join(f"{w:.3f}" for w in widths_post_sample)
    except (TypeError, ValueError):
        pass
    if isinstance(diag.get("ribbon_output_fix"), int) and diag.get("ribbon_output_fix") == 1:
        try:
            headers["X-Ribbon-Output-Fix"] = "1"
            if isinstance(diag.get("ribbon_output_pct"), (int, float)):
                headers["X-Ribbon-Output-Pct"] = str(diag.get("ribbon_output_pct"))
            # Surface absolute floor used for visibility (constant min of 3.0)
            headers["X-Ribbon-Output-AbsFloorMin"] = "3.0"
        except (AttributeError, TypeError, ValueError, KeyError):
            pass
    # Indicate pre-cache dispersion attempt
    if isinstance(diag.get("ribbon_pre_disp"), int) and diag.get("ribbon_pre_disp") == 1:
        try:
            headers["X-Ribbon-PreDispersion"] = "1"
        except (TypeError, ValueError):
            pass
    # Always surface profile echo headers for parity, use empty string when not set
    headers["X-Profile"] = (str(profile).lower() if profile else "")
    headers["X-Profile-Distance"] = (str(distance_metric_eff).lower() if distance_metric_eff else "")
    headers["X-Profile-WeightMode"] = (str(weight_mode_eff).lower() if weight_mode_eff else "")
    if recent_gamma_eff is not None:
        headers["X-Profile-RecentGamma"] = str(recent_gamma_eff)
    if regime_tolerance_eff is not None:
        headers["X-Profile-RegimeTolerance"] = str(regime_tolerance_eff)
    if regime_penalty_eff is not None:
        headers["X-Profile-RegimePenalty"] = str(regime_penalty_eff)
    if "post_shift" in diag:
        headers["X-PostShift"] = str(diag.get("post_shift"))
    return out, headers
