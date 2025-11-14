from __future__ import annotations
from typing import Optional, Sequence, Tuple, Dict, Any

# Phase A refactor: leverage shared path-forecast utilities to remove duplicated
# TP/time/window logic and fallback extraction heuristics.
from ....path_forecast.common import (
    extract_tp as _extract_tp,
    row_time_ms as _row_time_ms,
    effective_window_since_open as _effective_window_since_open_util,
)

# Lightweight service that encapsulates path-forecast computation logic
# (hybrid -> retrieval -> fallback) with an optional trend drift in fallback.

# Import forecasting backends from path_forecast package (repo-local)
from ....path_forecast.composite import CompositePathForecaster, CompositeConfig
from ....path_forecast.retrieval import RetrievalPathForecaster, RetrievalConfig
from ....path_forecast.hybrid import HybridPathForecaster


def _clamp_non_negative(qmap: Dict[float, Sequence[float]] | Dict) -> Dict[float, Sequence[float]]:
    out: Dict[float, list[float]] = {}
    for q in (0.1, 0.5, 0.9):
        seq = list(qmap.get(q) or [])  # type: ignore[index]
        clamped: list[float] = []
        for v in seq:
            if isinstance(v, (int, float)):
                clamped.append(v if v >= 0 else 0.0)
            else:
                clamped.append(v)  # type: ignore[arg-type]
        out[q] = clamped
    # Widen to Sequence for callers
    return {k: list(v) for k, v in out.items()}


def _effective_window_since_open(now_ms: Optional[int], window: int) -> int:
    # Delegate to shared utility (window=0 => since open logic encapsulated)
    return _effective_window_since_open_util(now_ms, int(window))


def load_profiles(config_path: Optional[str]) -> Dict[str, Dict[str, float]]:
    import json, os
    profiles: Dict[str, Dict[str, float]] = {
        "optimized": {"window": 180, "k": 20, "fallback_band_pct": 0.05},
        "base": {"window": 120, "k": 15, "fallback_band_pct": 0.08},
    }
    if not config_path:
        return profiles
    try:
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # Merge/override values safely
                for name, cfg in data.items():
                    if isinstance(cfg, dict):
                        profiles[name] = {**profiles.get(name, {}), **cfg}
    except Exception:
        pass
    return profiles


def forecast_path_core(
    *,
    index: str,
    expiry_tag: str,
    offset: str,
    window: int,
    k: int,
    horizon_minutes: int,
    bucket_ms: int,
    mode: str,
    ref_now_ms: int,
    rows: Sequence[dict],
    last_tp: float,
    profile: Optional[str] = None,
    profiles_path: Optional[str] = None,
) -> Tuple[Sequence[int], Dict[float, Sequence[float]], str, Dict[str, Any]]:
    """Compute forecast times and quantiles using selected profile.

    Returns: (times, qmap, mode_used, diag)
    """
    # Apply profile overrides
    profiles = load_profiles(profiles_path)
    p = profiles.get((profile or "").lower()) if profile else None
    window_eff = _effective_window_since_open(ref_now_ms, int(p.get("window", window)) if p else window)
    k_eff = int(p.get("k", k)) if p else k
    fb_band_pct = float(p.get("fallback_band_pct", 0.05)) if p else 0.05

    qs = [0.1, 0.5, 0.9]
    recent_tp: list[list[float]] = []
    for r in rows[-120:]:
        tpv = _extract_tp(r)
        if isinstance(tpv, (int, float)):
            recent_tp.append([float(tpv)])

    times: Sequence[int] = []
    qmap: Dict[float, Sequence[float]] = {}
    mode_used = ""
    diag: Dict[str, Any] = {}

    try:
        if str(mode).lower() in ("auto", "hybrid"):
            # Expect upstream caller to provide proper data root via rows context; fallback to None not allowed
            from pathlib import Path
            ccfg = CompositeConfig(root=Path("data/g6_data"), expiry_tag=expiry_tag, offset=offset, window=window_eff, k=k_eff)
            comp = CompositePathForecaster(ccfg)
            times, qmap = comp.forecast_path(
                recent_tp,
                context={"index": index, "now_ms": ref_now_ms, "live_rows": rows},
                quantiles=qs,
                horizon_minutes=int(horizon_minutes),
                bucket_ms=int(bucket_ms),
            )
            mode_used = "hybrid"
            try:
                diag = dict(comp.last_meta or {})
            except Exception:
                diag = {}
        else:
            from pathlib import Path
            rcfg = RetrievalConfig(root=Path("data/g6_data"), expiry_tag=expiry_tag, offset=offset, window=window_eff, k=k_eff)
            retr = RetrievalPathForecaster(rcfg)
            times, qmap = retr.forecast_path(
                recent_tp,
                context={"index": index, "now_ms": ref_now_ms, "live_rows": rows},
                quantiles=qs,
                horizon_minutes=int(horizon_minutes),
                bucket_ms=int(bucket_ms),
            )
            mode_used = "retrieval"
            try:
                diag = dict(retr.last_meta or {})
            except Exception:
                diag = {}
    except Exception:
        # Keep a functional fallback
        forecaster = HybridPathForecaster(band_pct=fb_band_pct)
        times, qmap = forecaster.forecast_path(
            [],
            context={"last_tp": last_tp, "now_ms": ref_now_ms, "index": index},
            quantiles=qs,
            horizon_minutes=int(horizon_minutes),
            bucket_ms=int(bucket_ms),
        )
        mode_used = "fallback"
        diag = {}
        # Inject simple drift to avoid perfectly flat forecasts
        try:
            tps: list[tuple[int, float]] = []
            for r in rows[-60:]:
                ems = _row_time_ms(r)
                if not isinstance(ems, int) or ems <= 0:
                    continue
                tpv = _extract_tp(r)
                if isinstance(tpv, (int, float)):
                    tps.append((ems, float(tpv)))
            if len(tps) >= 5 and times:
                tps_recent = tps[-15:]
                t0, v0 = tps_recent[0]
                t1, v1 = tps_recent[-1]
                dt_min = max(1.0, (t1 - t0) / 60000.0)
                slope = (v1 - v0) / dt_min
                for i, tgt_ms in enumerate(times):
                    delta_min = (tgt_ms - ref_now_ms) / 60000.0 if ref_now_ms else 0.0
                    for q in (0.5, 0.1, 0.9):
                        arr = list(qmap.get(q) or [])
                        if i < len(arr) and isinstance(arr[i], (int, float)):
                            base = float(arr[i])
                            arr[i] = base + slope * delta_min
                        qmap[q] = arr
                try:
                    qmap = _clamp_non_negative(qmap)
                except Exception:
                    pass
                diag["fallback_trend_slope"] = slope
                diag["fallback_trend_points"] = len(tps_recent)
        except Exception:
            pass

    return times, qmap, mode_used, diag
