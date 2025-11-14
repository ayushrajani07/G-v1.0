from __future__ import annotations

import argparse
import csv
import statistics as stats
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence

from src.web.dashboard.core.paths import project_root
from src.web.dashboard.core.csv_io import find_live_csv, load_csv_rows_full
from src.path_forecast.retrieval import RetrievalPathForecaster, RetrievalConfig
from src.path_forecast.common import extract_tp


@dataclass
class Result:
    index: str
    expiry_tag: str
    offset: str
    window: int
    k: int
    horizon: int
    bucket_ms: int
    ann_space: str
    ann_max_candidates: Optional[int]
    repeats: int
    n_points: int
    exact_ms: list[float]
    ann_ms: list[float]
    speedups: list[float]
    q50_mad: Optional[float]


def parse_csv_list(s: str) -> list[str]:
    return [tok.strip() for tok in str(s).split(',') if tok.strip()]


def parse_int_list(s: str) -> list[int]:
    out: list[int] = []
    for tok in parse_csv_list(s):
        try:
            out.append(int(tok))
        except Exception:
            continue
    return out


def build_recent_tp(rows: list[dict], limit: int) -> list[list[float]]:
    seq: list[list[float]] = []
    for r in rows[-limit:]:
        v = extract_tp(r)
        if isinstance(v, (int, float)):
            seq.append([float(v)])
    return seq


def forecast_once(index: str, expiry_tag: str, offset: str, window: int, k: int, horizon: int,
                  bucket_ms: int, use_ann: bool, ann_space: str, ann_max_candidates: Optional[int],
                  day: date) -> tuple[float, dict[float, Sequence[float]], int]:
    """Run retrieval once, return (latency_ms, qmap, n_points)."""
    root = project_root() / "data" / "g6_data"
    p = find_live_csv(root, index, expiry_tag, offset, day)
    if not p or not p.exists():
        raise FileNotFoundError(f"live_csv not found for {index} {expiry_tag} {offset} {day}")
    rows = load_csv_rows_full(p)
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
    ts, qmap = retr.forecast_path(recent, context={"index": index}, quantiles=[0.5], horizon_minutes=horizon, bucket_ms=bucket_ms)
    dt_ms = (time.perf_counter() - t0) * 1000.0
    n_points = min(len(list(qmap.get(0.5) or [])), len(ts))
    return dt_ms, qmap, n_points


def mean_abs_diff(a: Sequence[float], b: Sequence[float]) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return float("nan")
    s = 0.0
    m = 0
    for i in range(n):
        try:
            av = float(a[i])
            bv = float(b[i])
        except Exception:
            continue
        s += abs(av - bv)
        m += 1
    return (s / m) if m else float("nan")


def percentiles(values: Sequence[float], ps: Iterable[float]) -> dict[float, float]:
    arr = sorted(values)
    out: dict[float, float] = {}
    for p in ps:
        if not arr:
            out[p] = float("nan")
            continue
        k = (len(arr) - 1) * p
        f = int(k)
        c = min(f + 1, len(arr) - 1)
        if f == c:
            out[p] = arr[f]
        else:
            out[p] = arr[f] + (arr[c] - arr[f]) * (k - f)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="ANN multi-run benchmark (exact vs ANN)")
    ap.add_argument("--indices", default="NIFTY")
    ap.add_argument("--expiry-tags", default="this_week")
    ap.add_argument("--offsets", default="0")
    ap.add_argument("--windows", default="180")
    ap.add_argument("--ks", default="20")
    ap.add_argument("--horizons", default="60")
    ap.add_argument("--bucket-ms", type=int, default=60000)
    ap.add_argument("--ann-space", default="cosine")
    ap.add_argument("--ann-max-candidates", type=int, default=64)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--date", default=None, help="YYYY-MM-DD; defaults to today")
    ap.add_argument("--out", default=None, help="Output CSV path; defaults to benchmarks/ann_benchmark_<ts>.csv")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    indices = parse_csv_list(args.indices)
    tags = parse_csv_list(args.__dict__["expiry-tags"])  # type: ignore[index]
    offs = parse_csv_list(args.offsets)
    wins = parse_int_list(args.windows)
    ks = parse_int_list(args.ks)
    hs = parse_int_list(args.horizons)
    bucket_ms = int(args.__dict__["bucket-ms"])  # type: ignore[index]
    ann_space = str(args.__dict__["ann-space"])  # type: ignore[index]
    ann_max = int(args.__dict__["ann-max-candidates"])  # type: ignore[index]
    repeats = max(1, int(args.repeats))
    day = date.today() if not args.date else date.fromisoformat(args.date)

    out_path = args.out
    if not out_path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_dir = project_root() / "benchmarks"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = str(out_dir / f"ann_benchmark_{ts}.csv")

    results: list[Result] = []
    skipped: list[str] = []

    for idx in indices:
        for tag in tags:
            for off in offs:
                for w in wins:
                    for k in ks:
                        for h in hs:
                            try:
                                exact_times: list[float] = []
                                ann_times: list[float] = []
                                q50_mad: Optional[float] = None
                                n_points: int = 0
                                # First pass: collect qmaps and one timing each
                                e_ms, e_q, n_points = forecast_once(idx, tag, off, w, k, h, bucket_ms, False, ann_space, ann_max, day)
                                a_ms, a_q, _ = forecast_once(idx, tag, off, w, k, h, bucket_ms, True, ann_space, ann_max, day)
                                exact_times.append(e_ms)
                                ann_times.append(a_ms)
                                q50_mad = mean_abs_diff(list(e_q.get(0.5) or []), list(a_q.get(0.5) or []))
                                # Additional repeats (timing only)
                                for _rep in range(repeats - 1):
                                    e_ms2, _, _ = forecast_once(idx, tag, off, w, k, h, bucket_ms, False, ann_space, ann_max, day)
                                    a_ms2, _, _ = forecast_once(idx, tag, off, w, k, h, bucket_ms, True, ann_space, ann_max, day)
                                    exact_times.append(e_ms2)
                                    ann_times.append(a_ms2)
                                speedups = [ (et/at if at else float('inf')) for et, at in zip(exact_times, ann_times) ]
                                results.append(Result(
                                    index=idx, expiry_tag=tag, offset=off, window=w, k=k, horizon=h,
                                    bucket_ms=bucket_ms, ann_space=ann_space, ann_max_candidates=ann_max,
                                    repeats=repeats, n_points=n_points, exact_ms=exact_times, ann_ms=ann_times,
                                    speedups=speedups, q50_mad=q50_mad,
                                ))
                                if not args.quiet:
                                    print(f"OK {idx} {tag} off={off} w={w} k={k} H={h} exact_ms(p50)={stats.median(exact_times):.1f} ann_ms(p50)={stats.median(ann_times):.1f} speedup(p50)={stats.median(speedups):.2f}x mad={q50_mad:.4f} n={n_points}")
                            except FileNotFoundError:
                                skipped.append(f"{idx}:{tag}:{off}")
                                if not args.quiet:
                                    print(f"SKIP {idx} {tag} off={off} (live_csv not found)")
                            except Exception as e:
                                skipped.append(f"{idx}:{tag}:{off}:{w}:{k}:{h}:{type(e).__name__}")
                                if not args.quiet:
                                    print(f"ERR  {idx} {tag} off={off} w={w} k={k} H={h} -> {e}")

    # Write CSV summary
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "index","expiry_tag","offset","window","k","horizon","bucket_ms","ann_space","ann_max_candidates","repeats","n_points",
            "exact_ms_mean","exact_ms_p50","ann_ms_mean","ann_ms_p50","speedup_mean","speedup_p50","q50_mad"
        ])
        for r in results:
            exact_mean = stats.fmean(r.exact_ms) if r.exact_ms else float("nan")
            ann_mean = stats.fmean(r.ann_ms) if r.ann_ms else float("nan")
            p = percentiles(r.speedups, [0.5])
            p_et = percentiles(r.exact_ms, [0.5])
            p_at = percentiles(r.ann_ms, [0.5])
            w.writerow([
                r.index, r.expiry_tag, r.offset, r.window, r.k, r.horizon, r.bucket_ms, r.ann_space, r.ann_max_candidates, r.repeats, r.n_points,
                f"{exact_mean:.2f}", f"{p_et[0.5]:.2f}", f"{ann_mean:.2f}", f"{p_at[0.5]:.2f}",
                f"{(stats.fmean(r.speedups) if r.speedups else float('nan')):.2f}", f"{p[0.5]:.2f}", f"{(r.q50_mad if r.q50_mad is not None else float('nan')):.4f}"
            ])

    if not args.quiet:
        print(f"\nWrote: {out_path}")
        if skipped:
            print(f"Skipped {len(skipped)} combos (no data/errors). First few: {skipped[:5]}")


if __name__ == "__main__":
    main()
