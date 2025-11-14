#!/usr/bin/env python
import csv
from pathlib import Path
from collections import defaultdict

# Combine eval.csv from multiple result folders into one summary and concat eval.
# Usage (example):
#   .venv\Scripts\python.exe scripts\ml\combine_grid_eval.py
# It will look for results under results/grid/{NIFTY,SENSEX,BANKNIFTY}/this_week/0/
# and write combined outputs to results/grid/COMBINED/this_week/0/.

ROOT = Path(__file__).resolve().parents[2]
IN_BASE = ROOT / "results" / "grid"
OUT_DIR = ROOT / "results" / "grid" / "COMBINED" / "this_week" / "0"

INDICES = ["NIFTY", "SENSEX", "BANKNIFTY"]
TAG = "this_week"
OFFSET = "0"

def read_eval(path: Path):
    rows = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
    return rows

def to_float(x):
    try:
        return float(x)
    except Exception:
        return float('nan')

def main():
    all_rows = []
    for idx in INDICES:
        eval_path = IN_BASE / idx / TAG / OFFSET / "eval.csv"
        all_rows.extend(read_eval(eval_path))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Write concatenated eval for transparency
    if all_rows:
        with (OUT_DIR / "eval_concat.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
            w.writeheader()
            for r in all_rows:
                w.writerow(r)

    # Aggregate by (horizon,window,k,mode[,scale], ANN knobs)
    groups = defaultdict(list)
    for r in all_rows:
        try:
            scale = float(str(r.get("scale", "1.0")))
        except Exception:
            scale = 1.0
        # ANN knobs (if present)
        try:
            ann_use = int(str(r.get("ann_use", "0")) or 0)
        except Exception:
            ann_use = 0
        ann_space = str(r.get("ann_space", "cosine"))
        ann_max = r.get("ann_max_candidates")
        try:
            ann_max = int(str(ann_max)) if ann_max not in (None, "") else None
        except Exception:
            ann_max = None
        key = (
            int(str(r["horizon"])), int(str(r["window"])) , int(str(r["k"])), str(r["mode"]), scale,
            ann_use, ann_space, ann_max
        )
        groups[key].append(r)

    out_rows = []
    for (h, win, k, mode, scale, ann_use, ann_space, ann_max), rows in sorted(groups.items()):
        n = 0
        cov_sum = 0.0
        bw_sum = 0.0
        mae_sum = 0.0
        bias_sum = 0.0
        samples_sum = 0.0
        ann_tw_sum = 0.0
        ann_sh_sum = 0.0
        lat_sum = 0.0
        base_lat_sum = 0.0
        speedup_sum = 0.0
        q50_mad_sum = 0.0
        build_ms_sum = 0.0
        mem_bytes_sum = 0.0
        prune_ratio_sum = 0.0
        effect_sum = 0.0
        cnt_cov = cnt_bw = cnt_mae = cnt_bias = 0
        cnt_samples = 0
        for r in rows:
            # consider a row usable if samples > 0
            s = to_float(r.get("samples"))
            if s > 0:
                c = to_float(r.get("coverage"))
                bw = to_float(r.get("band_width"))
                mae = to_float(r.get("mae"))
                b = to_float(r.get("bias"))
                if c == c:  # not NaN
                    cov_sum += c; cnt_cov += 1
                if bw == bw:
                    bw_sum += bw; cnt_bw += 1
                if mae == mae:
                    mae_sum += mae; cnt_mae += 1
                if b == b:
                    bias_sum += b; cnt_bias += 1
            # include samples avg even if zero (for visibility)
            if s == s:
                samples_sum += s; cnt_samples += 1
            # diagnostics
            ann_tw = to_float(r.get("ann_total_windows")) if "ann_total_windows" in r else float('nan')
            ann_sh = to_float(r.get("ann_shortlisted")) if "ann_shortlisted" in r else float('nan')
            lat = to_float(r.get("latency_ms")) if "latency_ms" in r else float('nan')
            if ann_tw == ann_tw:
                ann_tw_sum += ann_tw
            if ann_sh == ann_sh:
                ann_sh_sum += ann_sh
            if lat == lat:
                lat_sum += lat
            # extended metrics
            base_lat = to_float(r.get("baseline_latency_ms")) if "baseline_latency_ms" in r else float('nan')
            if base_lat == base_lat:
                base_lat_sum += base_lat
            speedup = to_float(r.get("ann_speedup")) if "ann_speedup" in r else float('nan')
            if speedup == speedup:
                speedup_sum += speedup
            q50_mad = to_float(r.get("ann_q50_mad")) if "ann_q50_mad" in r else float('nan')
            if q50_mad == q50_mad:
                q50_mad_sum += q50_mad
            build_ms = to_float(r.get("ann_build_ms")) if "ann_build_ms" in r else float('nan')
            if build_ms == build_ms:
                build_ms_sum += build_ms
            mem_bytes = to_float(r.get("ann_index_mem_bytes")) if "ann_index_mem_bytes" in r else float('nan')
            if mem_bytes == mem_bytes:
                mem_bytes_sum += mem_bytes
            prune_ratio = to_float(r.get("ann_prune_ratio")) if "ann_prune_ratio" in r else float('nan')
            if prune_ratio == prune_ratio:
                prune_ratio_sum += prune_ratio
            effect = to_float(r.get("ann_effectiveness")) if "ann_effectiveness" in r else float('nan')
            if effect == effect:
                effect_sum += effect
            n += 1
        if n == 0:
            continue
        def avg(total, count):
            return (total / count) if count else float('nan')
        out_rows.append({
            "horizon": h,
            "window": win,
            "k": k,
            "mode": mode,
            "scale": scale,
            "ann_use": ann_use,
            "ann_space": ann_space,
            "ann_max_candidates": ann_max,
            "n": n,
            "coverage_avg": avg(cov_sum, cnt_cov),
            "band_width_avg": avg(bw_sum, cnt_bw),
            "mae_avg": avg(mae_sum, cnt_mae),
            "bias_avg": avg(bias_sum, cnt_bias),
            "samples_avg": avg(samples_sum, cnt_samples),
            "ann_total_windows_avg": avg(ann_tw_sum, n),
            "ann_shortlisted_avg": avg(ann_sh_sum, n),
            "latency_ms_avg": avg(lat_sum, n),
            "baseline_latency_ms_avg": avg(base_lat_sum, n),
            "ann_speedup_avg": avg(speedup_sum, n),
            "ann_q50_mad_avg": avg(q50_mad_sum, n),
            "ann_build_ms_avg": avg(build_ms_sum, n),
            "ann_index_mem_bytes_avg": avg(mem_bytes_sum, n),
            "ann_prune_ratio_avg": avg(prune_ratio_sum, n),
            "ann_effectiveness_avg": avg(effect_sum, n),
        })

    if out_rows:
        with (OUT_DIR / "summary.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "horizon","window","k","mode","scale","ann_use","ann_space","ann_max_candidates","n",
                "coverage_avg","band_width_avg","mae_avg","bias_avg","samples_avg",
                "ann_total_windows_avg","ann_shortlisted_avg","latency_ms_avg","baseline_latency_ms_avg","ann_speedup_avg","ann_q50_mad_avg","ann_build_ms_avg","ann_index_mem_bytes_avg","ann_prune_ratio_avg","ann_effectiveness_avg"
            ])
            w.writeheader()
            for r in out_rows:
                w.writerow(r)

if __name__ == "__main__":
    main()
