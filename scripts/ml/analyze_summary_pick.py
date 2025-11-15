#!/usr/bin/env python
from __future__ import annotations
import csv
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from src.error_handling import safe_write_json  # type: ignore

@dataclass
class Pick:
    horizon: int
    window: int
    k: int
    mode: str
    scale: float
    coverage: float
    band_width: float
    mae: float
    bias: float
    samples: float
    n: int
    score: float


def to_float(x, default=float("nan")):
    try:
        return float(str(x))
    except Exception:
        return default


def load_summary(path: Path):
    rows = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def best_picks(summary_path: Path, target: float = 0.8, topn: int = 3):
    rows = load_summary(summary_path)
    picks: list[Pick] = []
    for r in rows:
        cov = to_float(r.get("coverage_avg"))
        bw = to_float(r.get("band_width_avg"))
        mae = to_float(r.get("mae_avg"))
        bias = to_float(r.get("bias_avg"))
        samples = to_float(r.get("samples_avg"))
        n = int(float(r.get("n", 0) or 0))
        if math.isnan(cov) or math.isnan(bw) or samples <= 0:
            continue
        # distance to target coverage; lower is better
        dist = abs(cov - float(target))
        # combined score: prioritize dist, then bw, then mae, then |bias|
        score = (dist, bw, mae, abs(bias))
        picks.append(Pick(
            horizon=int(float(r.get("horizon", 0))),
            window=int(float(r.get("window", 0))),
            k=int(float(r.get("k", 0))),
            mode=str(r.get("mode", "")),
            scale=float(str(r.get("scale", 1.0))),
            coverage=cov,
            band_width=bw,
            mae=mae,
            bias=bias,
            samples=samples,
            n=n,
            score=0.0,
        ))
    # sort by score tuple
    picks.sort(key=lambda p: (abs(p.coverage - target), p.band_width, p.mae, abs(p.bias)))
    return picks[:topn]


def write_picks(out_dir: Path, picks: list[Pick]):
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "horizon": p.horizon,
            "window": p.window,
            "k": p.k,
            "mode": p.mode,
            "scale": p.scale,
            "coverage": p.coverage,
            "band_width": p.band_width,
            "mae": p.mae,
            "bias": p.bias,
            "samples": p.samples,
            "n": p.n,
        }
        for p in picks
    ]
    # CSV
    if rows:
        with (out_dir / "picks.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            for r in rows:
                w.writerow(r)
    # JSON
    safe_write_json(out_dir / "picks.json", rows, function_name='analyze_summary_picks_write')


def main():
    if len(sys.argv) < 4:
        print("Usage: analyze_summary_pick.py <INDEX> <TAG> <OFFSET> [<TARGET=0.8>] [<TOPN=3>]")
        raise SystemExit(2)
    index, tag, offset = sys.argv[1], sys.argv[2], sys.argv[3]
    target = float(sys.argv[4]) if len(sys.argv) > 4 else 0.8
    topn = int(sys.argv[5]) if len(sys.argv) > 5 else 3
    root = Path(__file__).resolve().parents[2]
    summ = root / "results" / "grid" / index / tag / offset / "summary.csv"
    out_dir = root / "results" / "grid" / index / tag / offset
    picks = best_picks(summ, target=target, topn=topn)
    write_picks(out_dir, picks)
    print(f"Wrote {len(picks)} picks to {out_dir}")


if __name__ == "__main__":
    main()
