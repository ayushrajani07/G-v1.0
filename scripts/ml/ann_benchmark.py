from __future__ import annotations

import argparse
import json
import time
from typing import Optional, Sequence, Any

from src.web.dashboard.core.paths import project_root
from src.web.dashboard.core.csv_io import find_live_csv, load_csv_rows_full
from src.path_forecast.retrieval import RetrievalPathForecaster, RetrievalConfig
from src.path_forecast.common import extract_tp


def build_recent_tp(rows: list[dict], limit: int = 180) -> list[list[float]]:
    seq: list[list[float]] = []
    for r in rows[-limit:]:
        v = extract_tp(r)
        if isinstance(v, (int, float)):
            seq.append([float(v)])
    return seq


def run_once(index: str, expiry_tag: str, offset: str, window: int, k: int, horizon_minutes: int,
             bucket_ms: int, use_ann: bool, ann_space: str, ann_max_candidates: Optional[int], day: Optional[str] = None) -> tuple[float, dict[float, Sequence[float]], dict[str, Any]]:
    """Run a single retrieval forecast and return (latency_ms, qmap).

    Adaptive to updated find_live_csv signature requiring a date. If the underlying
    csv_io.find_live_csv expects a 'day' argument, we supply either the parsed
    YYYY-MM-DD from `day` or `date.today()`.
    """
    from datetime import date as _date
    root = project_root() / "data" / "g6_data"
    # Determine target day
    day_obj = _date.today()
    if day:
        try:
            day_obj = _date.fromisoformat(str(day))
        except Exception:
            pass
    # Locate live CSV (new signature: includes day)
    meta: dict[str, Any] = {"day": day_obj.isoformat(), "index": index, "expiry_tag": expiry_tag, "offset": offset}
    try:
        p = find_live_csv(root, index, expiry_tag, offset, day_obj)
    except TypeError:
        # Fallback for legacy signature without day
        p = find_live_csv(root, index, expiry_tag, offset)  # type: ignore[arg-type]
    if not p or not p.exists():
        meta["error"] = "live_csv_not_found"
        return float('nan'), {}, meta
    rows = load_csv_rows_full(p)
    if not rows:
        meta["error"] = "empty_rows"
        return float('nan'), {}, meta
    recent = build_recent_tp(rows, limit=max(60, window))
    cfg = RetrievalConfig(
        root=root,
        expiry_tag=expiry_tag,
        offset=offset,
        window=window,
        k=k,
        distance_metric="recent_l2",
        weight_mode="inv_dist",
        recent_gamma=0.9,
        use_ann=use_ann,
        ann_space=ann_space,
        ann_max_candidates=ann_max_candidates,
    )
    retr = RetrievalPathForecaster(cfg)
    t0 = time.perf_counter()
    ts, qmap = retr.forecast_path(recent, context={"index": index}, quantiles=[0.5], horizon_minutes=horizon_minutes, bucket_ms=bucket_ms)
    dt = (time.perf_counter() - t0) * 1000.0
    meta["latency_ms"] = dt
    meta["n_q50"] = len(list(qmap.get(0.5) or []))
    meta["n_points"] = len(ts)
    return dt, qmap, meta


def main() -> None:
    ap = argparse.ArgumentParser(description="Benchmark Retrieval exact vs ANN shortlist")
    ap.add_argument("--index", default="NIFTY")
    ap.add_argument("--expiry_tag", default="this_week")
    ap.add_argument("--offset", default="0")
    ap.add_argument("--window", type=int, default=180)
    ap.add_argument("--k", type=int, default=20)
    ap.add_argument("--horizon", type=int, default=60)
    ap.add_argument("--bucket-ms", type=int, default=60000)
    ap.add_argument("--ann-space", default="cosine")
    ap.add_argument("--ann-max-candidates", type=int, default=64)
    ap.add_argument("--date", default=None, help="Optional YYYY-MM-DD trading date (defaults to today)")
    args = ap.parse_args()

    exact_ms, exact_q, exact_meta = run_once(
        args.index, args.expiry_tag, args.offset, args.window, args.k, args.horizon,
        args.__dict__["bucket-ms"], False, args.__dict__["ann-space"], args.__dict__["ann-max-candidates"], args.date
    )  # type: ignore[index]
    ann_ms, ann_q, ann_meta = run_once(
        args.index, args.expiry_tag, args.offset, args.window, args.k, args.horizon,
        args.__dict__["bucket-ms"], True, args.__dict__["ann-space"], args.__dict__["ann-max-candidates"], args.date
    )  # type: ignore[index]

    def _mean_abs_diff(a: Sequence[float], b: Sequence[float]) -> float:
        n = min(len(a), len(b))
        if n == 0:
            return float("nan")
        s = 0.0
        for i in range(n):
            try:
                av = float(a[i])
                bv = float(b[i])
            except Exception:
                continue
            s += abs(av - bv)
        return s / n if n else float("nan")

    exact = list(exact_q.get(0.5) or [])
    ann = list(ann_q.get(0.5) or [])
    diff = _mean_abs_diff(exact, ann)

    result = {
        "schema": "bench.ann.v1",
        "index": args.index,
        "expiry_tag": args.expiry_tag,
        "offset": args.offset,
        "window": args.window,
        "k": args.k,
        "horizon": args.horizon,
        "bucket_ms": args.__dict__["bucket-ms"],
        "ann_space": args.__dict__["ann-space"],
        "ann_max_candidates": args.__dict__["ann-max-candidates"],
        "exact_ms": exact_ms,
        "ann_ms": ann_ms,
        "speedup": (exact_ms/ann_ms if ann_ms and ann_ms > 0 else float('inf')),
        "q50_mean_abs_diff": diff,
        "exact_meta": exact_meta,
        "ann_meta": ann_meta,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
