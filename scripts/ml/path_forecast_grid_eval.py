#!/usr/bin/env python
"""
Grid-evaluate path forecast configs over historical days.

Purpose:
- Sweep window, k, mode, and horizon over a date range and score each config.
- Metrics per config/day: coverage (q10<=tp<=q90), band_width mean, MAE(q50, tp), bias(q50-tp), samples.
- Outputs CSV with per-day results and a summary CSV aggregated by config.

Usage:
  python scripts/ml/path_forecast_grid_eval.py \
    --index NIFTY \
    --expiry-tag this_week \
    --offset 0 \
    --start 2025-10-15 --end 2025-11-05 \
    --horizons 30,60 \
    --windows 0,60,120,180 \
    --k 10,15,20 \
    --modes auto,hybrid,retrieval \
    --bucket-ms 60000 \
    --at end \
    --out results/path_grid_eval.csv \
    --summary results/path_grid_summary.csv

Notes:
- windows=0 uses Open→Now (since 09:15 IST) on each day.
- 'at' can be 'end' (use last timestamp of the day) or 'mid' (12:30 IST).
- Requires live_csvs under data/g6_data/<INDEX>/<expiry>/<offset>/<YYYY-MM-DD>.csv

    Discovery mode:
        python scripts/ml/path_forecast_grid_eval.py --discover \
            --indices NIFTY,BANKNIFTY (optional) \
            --tags this_week,next_week,this_month,next_month (optional) \
            --offsets 0,+50,-50 (optional) \
            --horizons 30,60 --windows 0,60,120,180 --k 10,15,20 --modes auto,hybrid,retrieval \
            --bucket-ms 60000 --at end \
            --out results/grid/all_eval.csv --summary results/grid/all_summary.csv

"""
from __future__ import annotations

import argparse
import csv
import itertools
import os
from dataclasses import dataclass
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Sequence, Tuple, Mapping, Any, cast
import time

# Local imports
from src.path_forecast.retrieval import RetrievalPathForecaster, RetrievalConfig
from src.path_forecast.composite import CompositePathForecaster, CompositeConfig
from src.web.dashboard.core.csv_io import load_csv_rows_full
from src.path_forecast.common import (
    extract_tp as _extract_tp,
    row_time_ms as _row_time_ms,
    effective_window_since_open as _effective_window_since_open,
    build_recent_window as _build_recent_window,
    build_bucketed_realized as _build_bucketed_realized,
)
from src.path_forecast.metrics import compute_ann_effectiveness

IST = timezone(timedelta(hours=5, minutes=30))

@dataclass
class EvalConfig:
    index: str
    expiry_tag: str
    offset: str
    start: date
    end: date
    horizons: List[int]
    windows: List[int]
    ks: List[int]
    modes: List[str]
    bucket_ms: int
    at: str  # 'end' or 'mid'
    out: Path
    summary: Path
    # discovery options
    discover: bool = False
    indices_filter: List[str] | None = None
    tags_filter: List[str] | None = None
    offsets_filter: List[str] | None = None
    # optional discovery bound
    last_days: int | None = None
    # optional band scaling factors (1.0 = no change)
    scales: List[float] | None = None
    # Phase C knobs (optional per run; defaults None -> no change)
    distance_metric: str | None = None
    weight_mode: str | None = None
    recent_gamma: float | None = None
    regime_tolerance: float | None = None
    regime_penalty: float | None = None
    # Phase D: ANN shortlist controls (optional)
    use_ann: bool = False
    ann_space: str | None = None
    ann_max_candidates: int | None = None
    # Optional: compare ANN vs exact for latency & q50 diff metrics
    ann_compare: bool = False
    # Optional: effectiveness tolerance for q50 MAD penalty term
    ann_effect_tolerance: float | None = None
    # Optional: compute only q50-based metrics (skip coverage/band width)
    metrics_minimal: bool = False
    # Per-mode candidate overrides (mode -> candidates)
    ann_max_candidates_per_mode: Dict[str, int] | None = None
    # Guard: if ann_q50_mad exceeds threshold, fall back to exact path
    ann_mad_guard: float | None = None


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _live_csv_path(root: Path, index: str, expiry_tag: str, offset: str, d: date) -> Path:
    return root / "data" / "g6_data" / index / expiry_tag / str(offset) / f"{d.isoformat()}.csv"


def _row_tp(r: dict) -> float | None:
    # Backward-compat shim: use shared extractor
    return _extract_tp(r)


def _since_open_minutes(ts_ms: int) -> int:
    # Delegate to shared logic by passing configured_window=0
    return _effective_window_since_open(ts_ms, 0)


# Use _row_time_ms from shared common module directly


def _choose_now_ms(rows: List[dict], at: str) -> int | None:
    tss: List[int] = []
    for r in rows:
        t = _row_time_ms(r)
        if isinstance(t, int) and t > 0:
            tss.append(t)
    if not tss:
        return None
    tss.sort()
    if at == "end":
        return tss[-1]
    # mid-day target (12:30 IST)
    dt = datetime.fromtimestamp(tss[-1]/1000.0, tz=IST)
    mid = datetime(dt.year, dt.month, dt.day, 12, 30, tzinfo=IST).timestamp() * 1000
    mid = int(mid)
    # choose nearest <= mid
    cand = [t for t in tss if t <= mid]
    if cand:
        return cand[-1]
    return tss[0]


def _prepare_recent(rows: List[dict], now_ms: int, window_min: int) -> List[List[float]]:
    # Delegate to shared builder
    return _build_recent_window(rows, now_ms, window_min)


def _apply_band_scale(qmap: Dict[float, Sequence[float]], scale: float) -> Dict[float, List[float]]:
    """Scale the distance of q10/q90 from q50 by a factor.

    new_lo = mid - s * (mid - lo)
    new_hi = mid + s * (hi - mid)
    """
    if scale is None or abs(scale - 1.0) < 1e-9:
        # Return a shallow copy in list form (avoid extra math)
        return {
            0.1: list(qmap.get(0.1) or []),
            0.5: list(qmap.get(0.5) or []),
            0.9: list(qmap.get(0.9) or []),
        }
    lo = list(qmap.get(0.1) or [])
    mid = list(qmap.get(0.5) or [])
    hi = list(qmap.get(0.9) or [])
    n = min(len(lo), len(mid), len(hi))
    # Compute scaled bands with list comprehensions (fewer Python-level ops)
    out_mid = [float(mid[i]) for i in range(n)]
    out_lo = [out_mid[i] - scale * (out_mid[i] - float(lo[i])) for i in range(n)]
    out_hi = [out_mid[i] + scale * (float(hi[i]) - out_mid[i]) for i in range(n)]
    return {0.1: out_lo, 0.5: out_mid, 0.9: out_hi}


def _metrics(qmap: Mapping[float, Sequence[float]], times: Sequence[int], rows: List[dict], bucket_ms: int, *, minimal: bool = False) -> Dict[str, float]:
    # Build realized map using shared bucketing (single call)
    bucket_ms_int = int(bucket_ms)
    ts_sorted, realized = _build_bucketed_realized(rows, bucket_ms_int)
    if not realized:
        return {"samples": 0, "coverage": float("nan"), "band_width": float("nan"), "mae": float("nan"), "bias": float("nan")}

    q50 = list(qmap.get(0.5) or [])
    if minimal:
        # In minimal mode we compute only MAE/bias using q50; coverage/band_width are NaN
        tol = max(1, bucket_ms_int // 2)
        total = 0
        abs_err_sum = 0.0
        bias_sum = 0.0
        # Prepare aligned realized values to avoid dict lookups
        r_ts = ts_sorted
        r_vals = [realized[t] for t in r_ts]
        n_r = len(r_ts)
        if n_r == 0:
            return {"samples": 0, "coverage": float("nan"), "band_width": float("nan"), "mae": float("nan"), "bias": float("nan")}
        last_ts = r_ts[-1]
        p = 0
        n_use = min(len(times), len(q50))
        for i in range(n_use):
            jt = int(times[i])
            # early stop if targets go beyond realized horizon
            if jt > last_ts + tol:
                break
            # advance pointer
            while p < n_r and r_ts[p] < jt:
                p += 1
            # choose best between p and p-1
            best_idx = None
            best_d = None
            if p < n_r:
                d0 = abs(r_ts[p] - jt)
                best_idx = p
                best_d = d0
            if p > 0:
                d1 = abs(r_ts[p-1] - jt)
                if best_d is None or d1 < best_d:
                    best_idx = p-1
                    best_d = d1
            if best_idx is None or best_d is None or best_d > tol:
                continue
            rv = float(r_vals[best_idx])
            try:
                mid = float(q50[i])
            except Exception:
                continue
            total += 1
            abs_err_sum += abs(mid - rv)
            bias_sum += (mid - rv)
        if total <= 0:
            return {"samples": 0, "coverage": float("nan"), "band_width": float("nan"), "mae": float("nan"), "bias": float("nan")}
        return {
            "samples": float(total),
            "coverage": float("nan"),
            "band_width": float("nan"),
            "mae": abs_err_sum / float(total),
            "bias": bias_sum / float(total),
        }

    # Full metrics: use q10/q50/q90
    q10 = list(qmap.get(0.1) or [])
    q90 = list(qmap.get(0.9) or [])
    tol = max(1, bucket_ms_int // 2)

    total = cover = 0
    bw_sum = 0.0
    abs_err_sum = 0.0
    bias_sum = 0.0

    # Prepare aligned realized values to avoid per-iteration dict lookups
    r_ts = ts_sorted
    r_vals = [realized[t] for t in r_ts]
    n_r = len(r_ts)
    if n_r == 0:
        return {"samples": 0, "coverage": float("nan"), "band_width": float("nan"), "mae": float("nan"), "bias": float("nan")}
    last_ts = r_ts[-1]
    p = 0
    n_use = min(len(times), len(q10), len(q50), len(q90))
    for i in range(n_use):
        jt = int(times[i])
        if jt > last_ts + tol:
            break
        while p < n_r and r_ts[p] < jt:
            p += 1
        best_idx = None
        best_d = None
        if p < n_r:
            d0 = abs(r_ts[p] - jt)
            best_idx = p
            best_d = d0
        if p > 0:
            d1 = abs(r_ts[p-1] - jt)
            if best_d is None or d1 < best_d:
                best_idx = p-1
                best_d = d1
        if best_idx is None or best_d is None or best_d > tol:
            continue
        rv = float(r_vals[best_idx])
        try:
            lo = float(q10[i]); mid = float(q50[i]); hi = float(q90[i])
        except Exception:
            continue
        total += 1
        if lo <= rv <= hi:
            cover += 1
        bw_sum += (hi - lo)
        abs_err_sum += abs(mid - rv)
        bias_sum += (mid - rv)

    if total <= 0:
        return {"samples": 0, "coverage": float("nan"), "band_width": float("nan"), "mae": float("nan"), "bias": float("nan")}
    return {
        "samples": float(total),
        "coverage": cover / float(total),
        "band_width": bw_sum / float(total),
        "mae": abs_err_sum / float(total),
        "bias": bias_sum / float(total),
    }


def run(cfg: EvalConfig) -> None:
    root = _project_root()
    rows_out: List[Dict[str, object]] = []

    all_dates: List[date] = []
    d = cfg.start
    while d <= cfg.end:
        all_dates.append(d)
        d = d + timedelta(days=1)

    scales = cfg.scales or [1.0]
    combos = list(itertools.product(cfg.horizons, cfg.windows, cfg.ks, cfg.modes, scales))

    for d in all_dates:
        p = _live_csv_path(root, cfg.index, cfg.expiry_tag, cfg.offset, d)
        if not p.exists():
            if getattr(cfg, "_verbose", False):
                print(f"[skip] {d} file_missing {p}")
            continue
        rows = load_csv_rows_full(p)
        if not rows:
            if getattr(cfg, "_verbose", False):
                print(f"[skip] {d} empty_rows")
            continue
        now_ms = _choose_now_ms(rows, cfg.at)
        if not now_ms:
            if getattr(cfg, "_verbose", False):
                print(f"[skip] {d} no_now_ms at={cfg.at}")
            continue
        # Evaluate all horizon/window/k/mode/scale combos for this date
        for h, win, k, mode, scale in combos:
            # Effective window: 0 => since open
            win_eff = int(win)
            if int(win) == 0:
                # help type checker; runtime ensured by earlier guard in date loop
                now_ms_i = cast(int, now_ms)
                win_eff = _since_open_minutes(now_ms_i)
            # help type checker; runtime ensured by earlier guard in date loop
            now_ms_i = cast(int, now_ms)
            rec = _prepare_recent(rows, now_ms_i, win_eff)
            if len(rec) < max(10, win_eff // 2):
                if getattr(cfg, "_verbose", False):
                    print(f"[skip] {d} insufficient_recent len={len(rec)} win_eff={win_eff}")
                # skip if insufficient recent window
                continue
            try:
                t0 = time.perf_counter()
                # Determine per-mode ann_max override
                local_ann_max = None
                if cfg.ann_max_candidates_per_mode and mode in cfg.ann_max_candidates_per_mode:
                    local_ann_max = int(cfg.ann_max_candidates_per_mode[mode])
                else:
                    local_ann_max = (int(cfg.ann_max_candidates) if cfg.ann_max_candidates is not None else None)
                if mode in ("auto", "hybrid"):
                    fcfg = CompositeConfig(
                        root=root / "data" / "g6_data",
                        expiry_tag=cfg.expiry_tag,
                        offset=cfg.offset,
                        window=win_eff,
                        k=int(k),
                        distance_metric=(cfg.distance_metric or "l2"),
                        weight_mode=cfg.weight_mode,
                        recent_gamma=(cfg.recent_gamma if cfg.recent_gamma is not None else 0.9),
                        regime_tolerance=cfg.regime_tolerance,
                        regime_penalty=(cfg.regime_penalty if cfg.regime_penalty is not None else 1.25),
                        use_ann=bool(cfg.use_ann),
                        ann_space=(cfg.ann_space or "cosine"),
                        ann_max_candidates=local_ann_max,
                    )
                    fore = CompositePathForecaster(fcfg)
                elif mode == "retrieval":
                    fcfg = RetrievalConfig(
                        root=root / "data" / "g6_data",
                        expiry_tag=cfg.expiry_tag,
                        offset=cfg.offset,
                        window=win_eff,
                        k=int(k),
                        distance_metric=(cfg.distance_metric or "l2"),
                        weight_mode=cfg.weight_mode,
                        recent_gamma=(cfg.recent_gamma if cfg.recent_gamma is not None else 0.9),
                        regime_tolerance=cfg.regime_tolerance,
                        regime_penalty=(cfg.regime_penalty if cfg.regime_penalty is not None else 1.25),
                        use_ann=bool(cfg.use_ann),
                        ann_space=(cfg.ann_space or "cosine"),
                        ann_max_candidates=local_ann_max,
                    )
                    fore = RetrievalPathForecaster(fcfg)
                else:
                    continue
                times, qmap = fore.forecast_path(
                    rec,
                    context={"index": cfg.index, "now_ms": now_ms, "live_rows": rows},
                    quantiles=(0.1, 0.5, 0.9),
                    horizon_minutes=int(h),
                    bucket_ms=int(cfg.bucket_ms),
                )
                latency_ms = int((time.perf_counter() - t0) * 1000)
                qmap = _apply_band_scale(qmap, float(scale))
                # Optional baseline (exact) comparison when ANN enabled
                baseline_latency_ms = None
                ann_q50_mad = None
                ann_speedup = None
                # Run baseline if compare requested or guard set
                b_times = b_qmap = None
                if cfg.use_ann and (cfg.ann_compare or cfg.ann_mad_guard is not None):
                    try:
                        t1 = time.perf_counter()
                        if mode in ("auto", "hybrid"):
                            bcfg = CompositeConfig(
                                root=root / "data" / "g6_data",
                                expiry_tag=cfg.expiry_tag,
                                offset=cfg.offset,
                                window=win_eff,
                                k=int(k),
                                distance_metric=(cfg.distance_metric or "l2"),
                                weight_mode=cfg.weight_mode,
                                recent_gamma=(cfg.recent_gamma if cfg.recent_gamma is not None else 0.9),
                                regime_tolerance=cfg.regime_tolerance,
                                regime_penalty=(cfg.regime_penalty if cfg.regime_penalty is not None else 1.25),
                                use_ann=False,
                            )
                            bfore = CompositePathForecaster(bcfg)
                        elif mode == "retrieval":
                            bcfg = RetrievalConfig(
                                root=root / "data" / "g6_data",
                                expiry_tag=cfg.expiry_tag,
                                offset=cfg.offset,
                                window=win_eff,
                                k=int(k),
                                distance_metric=(cfg.distance_metric or "l2"),
                                weight_mode=cfg.weight_mode,
                                recent_gamma=(cfg.recent_gamma if cfg.recent_gamma is not None else 0.9),
                                regime_tolerance=cfg.regime_tolerance,
                                regime_penalty=(cfg.regime_penalty if cfg.regime_penalty is not None else 1.25),
                                use_ann=False,
                            )
                            bfore = RetrievalPathForecaster(bcfg)
                        else:
                            bfore = None
                        if bfore is not None:
                            b_times, b_qmap = bfore.forecast_path(
                                rec,
                                context={"index": cfg.index, "now_ms": now_ms, "live_rows": rows},
                                quantiles=(0.1, 0.5, 0.9),
                                horizon_minutes=int(h),
                                bucket_ms=int(cfg.bucket_ms),
                            )
                            baseline_latency_ms = int((time.perf_counter() - t1) * 1000)
                            # Compute mean absolute diff of q50 paths if lengths match
                            b_q50 = list(b_qmap.get(0.5) or [])
                            a_q50 = list(qmap.get(0.5) or [])
                            n_mad = min(len(b_q50), len(a_q50))
                            if n_mad > 0:
                                ann_q50_mad = sum(abs(float(a_q50[i]) - float(b_q50[i])) for i in range(n_mad)) / n_mad
                            if baseline_latency_ms and baseline_latency_ms > 0 and latency_ms > 0:
                                ann_speedup = baseline_latency_ms / float(latency_ms)
                    except Exception:
                        pass
            except Exception as e:
                if getattr(cfg, "_verbose", False):
                    print(f"[error] {d} combo h={h} win={win} k={k} mode={mode} scale={scale} err={type(e).__name__}:{e}")
                continue
            m = _metrics({0.1: qmap.get(0.1) or [], 0.5: qmap.get(0.5) or [], 0.9: qmap.get(0.9) or []}, times, rows, int(cfg.bucket_ms), minimal=bool(getattr(cfg, "metrics_minimal", False)))
            # Extract ANN diagnostics when available
            ann_enabled = False
            ann_total = 0
            ann_short = 0
            try:
                meta = getattr(fore, "last_meta", {}) or {}
                ann_enabled = bool(meta.get("ann_enabled") or cfg.use_ann)
                ann_total = int(meta.get("ann_total_windows") or 0)
                ann_short = int(meta.get("ann_shortlisted") or 0)
            except Exception:
                pass
            # New ANN metrics
            ann_build_ms = None
            ann_index_mem_bytes = None
            ann_prune_ratio = None
            try:
                v_build = meta.get("ann_build_ms")
                ann_build_ms = int(v_build) if v_build is not None else None
            except Exception:
                ann_build_ms = None
            try:
                v_mem = meta.get("ann_index_mem_bytes")
                ann_index_mem_bytes = int(v_mem) if v_mem is not None else None
            except Exception:
                ann_index_mem_bytes = None
            try:
                v = meta.get("ann_prune_ratio")
                ann_prune_ratio = float(v) if v is not None else None
            except Exception:
                ann_prune_ratio = None
            # Composite effectiveness score via helper
            ann_effectiveness = compute_ann_effectiveness(
                ann_speedup,
                ann_prune_ratio,
                ann_q50_mad,
                cfg.ann_effect_tolerance,
            )
            # Guard fallback
            ann_guard_triggered = 0
            ann_guard_original_mad = None
            if cfg.ann_mad_guard is not None:
                qmap, times, ann_speedup, ann_q50_mad, ann_guard_triggered, ann_guard_original_mad, latency_ms = _apply_ann_mad_guard(
                    qmap,
                    times,
                    b_qmap,
                    b_times,
                    ann_q50_mad,
                    cfg.ann_mad_guard,
                    ann_speedup,
                    latency_ms,
                    baseline_latency_ms,
                )
            rows_out.append({
                "date": d.isoformat(),
                "index": cfg.index,
                "expiry_tag": cfg.expiry_tag,
                "offset": cfg.offset,
                "horizon": int(h),
                "window": int(win_eff),
                "k": int(k),
                "mode": str(mode),
                "scale": float(scale),
                "bucket_ms": int(cfg.bucket_ms),
                "distance_metric": str(cfg.distance_metric or "l2"),
                "weight_mode": str(cfg.weight_mode or "none"),
                "recent_gamma": float(cfg.recent_gamma if cfg.recent_gamma is not None else 0.9),
                "regime_tolerance": (float(cfg.regime_tolerance) if cfg.regime_tolerance is not None else None),
                "regime_penalty": float(cfg.regime_penalty if cfg.regime_penalty is not None else 1.25),
                "at": cfg.at,
                # ANN config echo
                "ann_use": int(1 if cfg.use_ann else 0),
                "ann_space": str(cfg.ann_space or "cosine"),
                "ann_max_candidates": (int(local_ann_max) if local_ann_max is not None else None),
                # Diagnostics and timing
                "ann_enabled": int(1 if ann_enabled else 0),
                "ann_total_windows": int(ann_total),
                "ann_shortlisted": int(ann_short),
                "ann_build_ms": ann_build_ms,
                "ann_index_mem_bytes": ann_index_mem_bytes,
                "ann_prune_ratio": ann_prune_ratio,
                "ann_effectiveness": (float(ann_effectiveness) if ann_effectiveness is not None else None),
                "latency_ms": int(latency_ms),
                "baseline_latency_ms": (int(baseline_latency_ms) if baseline_latency_ms is not None else None),
                "ann_speedup": (float(ann_speedup) if ann_speedup is not None else None),
                "ann_q50_mad": (float(ann_q50_mad) if ann_q50_mad is not None else None),
                "ann_guard_triggered": ann_guard_triggered,
                "ann_guard_original_mad": ann_guard_original_mad,
                **{k: v for k, v in m.items()},
            })
            if getattr(cfg, "_verbose", False):
                print(f"[row] {d} h={h} w={win_eff} k={k} mode={mode} scale={scale} latency_ms={latency_ms} coverage={m.get('coverage')} samples={m.get('samples')}")

    # Ensure output dir
    if rows_out:
        cfg.out.parent.mkdir(parents=True, exist_ok=True)
        with cfg.out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
            w.writeheader()
            for r in rows_out:
                w.writerow(r)

        # Aggregate summary by (h,window,k,mode,scale,phaseC...)
        from collections import defaultdict
        # Group by config + ANN knobs
        agg: Dict[Tuple[int,int,int,str,float,str,str,float,float,float,int,str,object], Dict[str, float]] = defaultdict(lambda: {
            "n": 0,
            "coverage": 0.0,
            "band_width": 0.0,
            "mae": 0.0,
            "bias": 0.0,
            "samples": 0.0,
            "ann_total_windows": 0.0,
            "ann_shortlisted": 0.0,
            "latency_ms": 0.0,
            "baseline_latency_ms": 0.0,
            "ann_speedup": 0.0,
            "ann_q50_mad": 0.0,
            "ann_build_ms": 0.0,
            "ann_index_mem_bytes": 0.0,
            "ann_prune_ratio": 0.0,
            "ann_effectiveness": 0.0,
        })
        for r in rows_out:
            try:
                h_key = int(str(r["horizon"]))
            except Exception:
                h_key = int(float(str(r.get("horizon", "0"))))
            try:
                w_key = int(str(r["window"]))
            except Exception:
                w_key = int(float(str(r.get("window", "0"))))
            try:
                k_key = int(str(r["k"]))
            except Exception:
                k_key = int(float(str(r.get("k", "0"))))
            m_key = str(r.get("mode", ""))
            try:
                s_key = float(str(r.get("scale", "1.0")))
            except Exception:
                s_key = 1.0
            dm_key = str(r.get("distance_metric","l2"))
            wm_key = str(r.get("weight_mode","none"))
            rg_key = float(str(r.get("recent_gamma","0.9")) or 0.9)
            rt_val = r.get("regime_tolerance")
            try:
                rt_key = float(str(rt_val)) if rt_val not in (None,"") else float('nan')
            except Exception:
                rt_key = float('nan')
            rp_key = float(str(r.get("regime_penalty","1.25")) or 1.25)
            ann_use_key = int(str(r.get("ann_use", "0")) or 0)
            ann_space_key = str(r.get("ann_space", "cosine"))
            ann_max_key = r.get("ann_max_candidates")
            # keep None as-is to avoid conflating unset with 0
            try:
                ann_max_key = int(str(ann_max_key)) if ann_max_key not in (None, "") else None
            except Exception:
                ann_max_key = None
            key = (h_key, w_key, k_key, m_key, s_key, dm_key, wm_key, rg_key, rt_key, rp_key, ann_use_key, ann_space_key, ann_max_key)
            a = agg[key]
            a["n"] += 1
            for mkey in ("coverage","band_width","mae","bias","samples"):
                v = r.get(mkey)
                try:
                    a[mkey] += float(str(v)) if v is not None else 0.0
                except Exception:
                    pass
            # aggregate diagnostics
            for dkey in ("ann_total_windows","ann_shortlisted","latency_ms","baseline_latency_ms","ann_speedup","ann_q50_mad","ann_build_ms","ann_index_mem_bytes","ann_prune_ratio"):
                v = r.get(dkey)
                try:
                    a[dkey] += float(str(v)) if v is not None else 0.0
                except Exception:
                    pass
            # effectiveness
            v_eff = r.get("ann_effectiveness")
            try:
                a["ann_effectiveness"] += float(str(v_eff)) if v_eff is not None else 0.0
            except Exception:
                pass
        cfg.summary.parent.mkdir(parents=True, exist_ok=True)
        with cfg.summary.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "horizon","window","k","mode","scale",
                "distance_metric","weight_mode","recent_gamma","regime_tolerance","regime_penalty",
                "ann_use","ann_space","ann_max_candidates",
                "n","coverage_avg","band_width_avg","mae_avg","bias_avg","samples_avg",
                "ann_total_windows_avg","ann_shortlisted_avg","latency_ms_avg","baseline_latency_ms_avg","ann_speedup_avg","ann_q50_mad_avg",
                "ann_build_ms_avg","ann_index_mem_bytes_avg","ann_prune_ratio_avg","ann_effectiveness_avg"
            ])
            for (h,win,k,mode,scale,dm,wm,rg,rt,rp,ann_use,ann_space,ann_max), a in sorted(agg.items()):
                n = max(1, int(a["n"]))
                w.writerow([
                    h, win, k, mode, scale, dm, wm, rg, rt, rp,
                    ann_use, ann_space, ann_max,
                    int(a["n"]), a["coverage"]/n, a["band_width"]/n, a["mae"]/n, a["bias"]/n, a["samples"]/n,
                    a["ann_total_windows"]/n, a["ann_shortlisted"]/n, a["latency_ms"]/n, a["baseline_latency_ms"]/n, a["ann_speedup"]/n, a["ann_q50_mad"]/n,
                    a["ann_build_ms"]/n, a["ann_index_mem_bytes"]/n, a["ann_prune_ratio"]/n, a["ann_effectiveness"]/n
                ])


def parse_args() -> EvalConfig:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index")
    ap.add_argument("--expiry-tag")
    ap.add_argument("--offset", default="0")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--horizons", default="60")
    ap.add_argument("--windows", default="60,120,180")
    ap.add_argument("--k", dest="ks", default="15")
    ap.add_argument("--modes", default="auto,hybrid,retrieval")
    ap.add_argument("--bucket-ms", type=int, default=60000)
    ap.add_argument("--at", choices=["end","mid"], default="end")
    ap.add_argument("--out", default="results/path_grid_eval.csv")
    ap.add_argument("--summary", default="results/path_grid_summary.csv")
    ap.add_argument("--verbose", action="store_true", help="Log skip reasons and per-day progress")
    ap.add_argument("--out-root", default=None, help="For --discover: base output directory (default: results/grid)")
    # Phase C knobs (optional; applied uniformly across grid combos this run)
    ap.add_argument("--distance-metric", default=None, help="Distance metric: l2|cosine|recent_l2")
    ap.add_argument("--weight-mode", default=None, help="Weighted quantiles: inv_dist or blank")
    ap.add_argument("--recent-gamma", type=float, default=None, help="Decay factor for recent_l2 distance")
    ap.add_argument("--regime-tolerance", type=float, default=None, help="Relative std deviation tolerance for regime penalty")
    ap.add_argument("--regime-penalty", type=float, default=None, help="Penalty multiplier when regime mismatch detected")
    # Phase D ANN knobs
    ap.add_argument("--use-ann", action="store_true", help="Enable ANN shortlist in retrieval/composite")
    ap.add_argument("--ann-space", default=None, help="ANN space: cosine|l2 (defaults to cosine)")
    ap.add_argument("--ann-max-candidates", type=int, default=None, help="Limit number of ANN neighbors forwarded for exact scoring (global)")
    ap.add_argument("--ann-max-candidates-per-mode", default=None, help="Overrides per mode e.g. retrieval=10,auto=30,hybrid=30")
    ap.add_argument("--ann-compare", action="store_true", help="Also run exact (no ANN) baseline for latency & q50 MAD comparison")
    ap.add_argument("--ann-effect-tolerance", type=float, default=None, help="Tolerance for q50 MAD when computing ann_effectiveness (units of price; larger=more tolerant)")
    ap.add_argument("--ann-mad-guard", type=float, default=None, help="If ann_q50_mad exceeds this threshold, replace ANN output with exact baseline (implies baseline run)")
    # perf: compute minimal metrics only
    ap.add_argument("--metrics-minimal", action="store_true", help="Compute only q50-based metrics (MAE, bias); coverage and band_width set to NaN")
    # discovery mode
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--indices", help="Comma separated filter for indices", default=None)
    ap.add_argument("--tags", help="Comma separated filter for tags", default=None)
    ap.add_argument("--offsets", help="Comma separated filter for offsets", default=None)
    ap.add_argument("--last-days", type=int, default=None, help="Limit discovery to the last N available trading days per folder")
    ap.add_argument("--scales", default="1.0", help="Comma separated band scale factors (1.0=no change). Applies to q10/q90 around q50.")
    ns = ap.parse_args()

    def to_date(s: str) -> date:
        return datetime.strptime(s, "%Y-%m-%d").date()
    horizons = [int(x) for x in str(ns.horizons).split(',') if x.strip()]
    windows = [int(x) for x in str(ns.windows).split(',') if x.strip()]
    ks = [int(x) for x in str(ns.ks).split(',') if x.strip()]
    modes = [x.strip() for x in str(ns.modes).split(',') if x.strip()]

    idx = str(ns.index).upper() if ns.index else ""
    tag = str(ns.expiry_tag) if ns.expiry_tag else ""
    start_d = to_date(ns.start) if ns.start else date.today()
    end_d = to_date(ns.end) if ns.end else date.today()
    scales = []
    for s in str(ns.scales).split(','):
        s = s.strip()
        if not s:
            continue
        try:
            scales.append(float(s))
        except Exception:
            continue
    if not scales:
        scales = [1.0]

    # Per-mode mapping parsing
    per_mode_map: Dict[str, int] | None = None
    if ns.ann_max_candidates_per_mode:
        per_mode_map = {}
        for part in str(ns.ann_max_candidates_per_mode).split(','):
            part = part.strip()
            if not part or '=' not in part:
                continue
            m, v = part.split('=', 1)
            try:
                per_mode_map[m.strip()] = int(v.strip())
            except Exception:
                continue

    cfg = EvalConfig(
        index=idx,
        expiry_tag=tag,
        offset=str(ns.offset),
        start=start_d,
        end=end_d,
        horizons=horizons,
        windows=windows,
        ks=ks,
        modes=modes,
        bucket_ms=int(ns.bucket_ms),
        at=str(ns.at),
        out=Path(ns.out),
        summary=Path(ns.summary),
        discover=bool(ns.discover),
        indices_filter=[s.strip().upper() for s in str(ns.indices).split(',')] if ns.indices else None,
        tags_filter=[s.strip() for s in str(ns.tags).split(',')] if ns.tags else None,
        offsets_filter=[s.strip() for s in str(ns.offsets).split(',')] if ns.offsets else None,
        last_days=int(ns.last_days) if ns.last_days is not None else None,
        scales=scales,
        distance_metric=(ns.distance_metric if ns.distance_metric else None),
        weight_mode=(ns.weight_mode if ns.weight_mode else None),
        recent_gamma=(ns.recent_gamma if ns.recent_gamma is not None else None),
        regime_tolerance=(ns.regime_tolerance if ns.regime_tolerance is not None else None),
        regime_penalty=(ns.regime_penalty if ns.regime_penalty is not None else None),
        use_ann=bool(ns.use_ann),
        ann_space=(ns.ann_space if ns.ann_space else None),
        ann_max_candidates=(int(ns.ann_max_candidates) if ns.ann_max_candidates is not None else None),
        ann_compare=bool(ns.ann_compare),
        ann_effect_tolerance=(float(ns.ann_effect_tolerance) if ns.ann_effect_tolerance is not None else None),
        metrics_minimal=bool(ns.metrics_minimal),
        ann_max_candidates_per_mode=per_mode_map,
        ann_mad_guard=(float(ns.ann_mad_guard) if ns.ann_mad_guard is not None else None),
    )
    # Attach extra flags on the object for internal use via setattr to avoid changing dataclass
    setattr(cfg, "_verbose", bool(getattr(ns, "verbose", False)))
    setattr(cfg, "_out_root", (str(getattr(ns, "out_root", "") or "") or None))
    return cfg


def _apply_ann_mad_guard(qmap, times, b_qmap, b_times, ann_q50_mad, threshold, ann_speedup, latency_ms, baseline_latency_ms):
    """Apply MAD guard: if ANN MAD exceeds threshold fall back to baseline outputs.

    Returns updated (qmap, times, ann_speedup, ann_q50_mad, guard_triggered, original_mad, latency_ms).
    Designed as a helper for unit testing.
    """
    guard_triggered = 0
    original_mad = None
    try:
        if threshold is not None and ann_q50_mad is not None and ann_q50_mad > threshold and b_qmap is not None and b_times is not None:
            guard_triggered = 1
            original_mad = float(ann_q50_mad)
            qmap = b_qmap
            times = b_times
            latency_ms = baseline_latency_ms if baseline_latency_ms is not None else latency_ms
            ann_speedup = None
            ann_q50_mad = None
    except Exception:
        pass
    return qmap, times, ann_speedup, ann_q50_mad, guard_triggered, original_mad, latency_ms


def _dates_in_folder(folder: Path) -> list[date]:
    out: list[date] = []
    if not folder.exists():
        return out
    for p in folder.glob("*.csv"):
        try:
            out.append(datetime.strptime(p.stem, "%Y-%m-%d").date())
        except Exception:
            continue
    return sorted(out)


def _discover_and_run(cfg: EvalConfig) -> None:
    root = _project_root()
    base = root / "data" / "g6_data"
    if not base.exists():
        print(f"No g6_data at {base}")
        return
    indices = [d.name for d in base.iterdir() if d.is_dir()]
    if cfg.indices_filter:
        indices = [i for i in indices if i.upper() in set(cfg.indices_filter)]
    tags_default = ["this_week","next_week","this_month","next_month"]
    for idx in sorted(indices):
        idx_dir = base / idx
        tags = [d.name for d in idx_dir.iterdir() if d.is_dir()]
        if cfg.tags_filter:
            tags = [t for t in tags if t in set(cfg.tags_filter)]
        else:
            tags = [t for t in tags if t in tags_default]
        for tag in sorted(tags):
            tag_dir = idx_dir / tag
            offsets = [d.name for d in tag_dir.iterdir() if d.is_dir()]
            if cfg.offsets_filter:
                offsets = [o for o in offsets if o in set(cfg.offsets_filter)]
            for off in sorted(offsets):
                off_dir = tag_dir / off
                dates = _dates_in_folder(off_dir)
                if not dates:
                    continue
                if cfg.start and cfg.end and cfg.start <= cfg.end:
                    start = cfg.start
                    end = cfg.end
                else:
                    if cfg.last_days:
                        n = int(cfg.last_days or 0)
                        if n > 0:
                            start = dates[max(0, len(dates)-n)]
                            end = dates[-1]
                        else:
                            start = dates[0]
                            end = dates[-1]
                    else:
                        start = dates[0]
                        end = dates[-1]
                sub = EvalConfig(
                    index=idx,
                    expiry_tag=tag,
                    offset=off,
                    start=start,
                    end=end,
                    horizons=cfg.horizons,
                    windows=cfg.windows,
                    ks=cfg.ks,
                    modes=cfg.modes,
                    bucket_ms=cfg.bucket_ms,
                    at=cfg.at,
                    out=((root / getattr(cfg, "_out_root") / idx / tag / off / "eval.csv") if getattr(cfg, "_out_root", None) else (root / "results" / "grid" / idx / tag / off / "eval.csv")),
                    summary=((root / getattr(cfg, "_out_root") / idx / tag / off / "summary.csv") if getattr(cfg, "_out_root", None) else (root / "results" / "grid" / idx / tag / off / "summary.csv")),
                    last_days=cfg.last_days,
                    scales=cfg.scales,
                    distance_metric=cfg.distance_metric,
                    weight_mode=cfg.weight_mode,
                    recent_gamma=cfg.recent_gamma,
                    regime_tolerance=cfg.regime_tolerance,
                    regime_penalty=cfg.regime_penalty,
                    use_ann=cfg.use_ann,
                    ann_space=cfg.ann_space,
                    ann_max_candidates=cfg.ann_max_candidates,
                    ann_max_candidates_per_mode=cfg.ann_max_candidates_per_mode,
                    ann_mad_guard=cfg.ann_mad_guard,
                )
                print(f"[grid] {idx}/{tag}/{off} {start}..{end}")
                run(sub)


if __name__ == "__main__":
    cfg = parse_args()
    if cfg.discover:
        _discover_and_run(cfg)
    else:
        if not cfg.index or not cfg.expiry_tag or not cfg.start or not cfg.end:
            raise SystemExit("index, expiry-tag, start, end are required unless --discover is used")
        run(cfg)
