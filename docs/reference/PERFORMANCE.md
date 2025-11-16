# Performance & Benchmarks (2025-11-08)

This document captures reproducible performance snapshots and guardrails for path forecasting, metrics initialization, and ancillary benchmarks. It now includes a latency guard test and ANN diagnostics.

## Summary of Current Benchmarks

| Component | Scenario | Result (latest) | Notes |
|-----------|----------|-----------------|-------|
| Retrieval forecast | NIFTY this_week, window=60, k=15, horizon=60 | 360–405 ms (optimized path) | Two‑pointer metrics scan + minimal mode reduces overhead |
| Latency guard test | Synthetic 60/30 retrieval run | PASS (<600 ms) | `tests/test_performance_latency_guard.py` enforces threshold |
| ANN run (small corpus) | NIFTY this_week 2025-11-06, 24 windows | ann_speedup ≈ 0.004 | Corpus too small; baseline exact scan latency trivial |
| ANN prune ratio | Same run | 0.8333 | 20 shortlisted / 24 total windows |
| Panels JSON parse bench | 30 iterations/panel | Mean ≈ 0.34 ms | Occasional single-digit ms outliers |
| Metrics import latency | registry init | Mean ≈ 336 ms | p95 ≈ 382 ms |

## Recent Optimizations

1. Band scaling via list comprehensions to reduce per-row Python overhead.
2. Metrics computation rewritten (two‑pointer alignment scan) replacing repeated bisect searches.
3. Minimal metrics mode (`--metrics-minimal`) computes only MAE + bias (q50 path), setting coverage/band width to NaN — reduces evaluation latency.
4. ANN diagnostics integrated: build time, memory footprint (vectors or index object), prune ratio, speedup, q50 MAD, effectiveness composite metric.

## Latency Guard

The latency guard test (`tests/test_performance_latency_guard.py`) asserts forecast generation (retrieval, 60m window, 30m horizon, k=10) completes under 600 ms. This conservative threshold protects against regressions; once further gains are stable, we can lower it (e.g. 450 ms). Failing the guard should trigger investigation of:

- Excessive candidate day scan (e.g. misconfigured offset/tag ballooning file count)
- ANN index build dominating small queries (consider disabling ANN for tiny corpora)
- Accidental reintroduction of per-target bisect or dict lookups inside metric loop

## ANN Metrics & Interpretation

Columns emitted by `path_forecast_grid_eval.py` when ANN enabled:

| Column | Meaning |
|--------|---------|
| ann_total_windows | Historical windows considered for ANN index build |
| ann_shortlisted | Windows forwarded for exact scoring (post ANN query) |
| ann_prune_ratio | ann_shortlisted / ann_total_windows (higher = more pruning) |
| ann_build_ms | Time to build ANN index (one per run) |
| ann_index_mem_bytes | Approximate memory footprint of index vectors/object |
| ann_speedup | baseline_latency_ms / latency_ms ( >1 indicates win ) |
| ann_q50_mad | Mean absolute deviation of ANN vs exact q50 path (lower is better) |
| ann_effectiveness | Composite score combining speedup, prune_ratio, and q50 MAD penalty |

To observe meaningful speedups, ensure a sufficiently deep historical slice (e.g. >150 day windows). With only a few dozen windows, baseline exact scoring is already very fast, and ANN overhead dwarfs gains.

Recommended larger-slice invocation (adjust dates to available data):

```powershell
cmd /c "cd /d C:\Users\Asus\Desktop\g6_reorganized && set PYTHONPATH=C:\Users\Asus\Desktop\g6_reorganized && C:\Users\Asus\Desktop\g6_reorganized\.venv\Scripts\python.exe scripts\ml\path_forecast_grid_eval.py --index NIFTY --expiry-tag this_week --offset 0 --start 2025-10-01 --end 2025-11-06 --horizons 60 --windows 60 --k 15 --modes retrieval --bucket-ms 60000 --at mid --use-ann --ann-compare --ann-max-candidates 50 --scales 1.0"
```

## Benchmark Reproduction (PowerShell)

Ensure `PYTHONPATH` includes the project root.

- Single retrieval timing (Python snippet):

```powershell
$env:PYTHONPATH = "C:\Users\Asus\Desktop\g6_reorganized"
& "C:/Users/Asus/Desktop/g6_reorganized/.venv/Scripts/python.exe" - <<'PY'
import time
from datetime import date
from pathlib import Path
import sys
root_repo = Path(r"C:\Users\Asus\Desktop\g6_reorganized")
sys.path.insert(0, str(root_repo))
from src.web.dashboard.core.paths import project_root
from src.web.dashboard.core.csv_io import find_live_csv, load_csv_rows_full
from src.path_forecast.retrieval import RetrievalPathForecaster, RetrievalConfig
from src.path_forecast.common import build_recent_window
root = project_root() / 'data' / 'g6_data'
p = find_live_csv(root, 'NIFTY', 'this_week', '0', date.fromisoformat('2025-11-05'))
rows = load_csv_rows_full(p)
now_ms = max([r['ts'] for r in rows if isinstance(r.get('ts'), int)])
rec = build_recent_window(rows, now_ms, 60)
cfg = RetrievalConfig(root=root, expiry_tag='this_week', offset='0', window=60, k=15, distance_metric='l2', recent_gamma=0.9, regime_penalty=1.25, use_ann=False)
retr = RetrievalPathForecaster(cfg)
t0=time.perf_counter(); ts,qmap = retr.forecast_path(rec, {'index':'NIFTY','now_ms':now_ms,'live_rows':rows}, (0.1,0.5,0.9), 60, 60000); dt=(time.perf_counter()-t0)*1000
print({'latency_ms': int(dt), 'points': len(ts), 'q50_len': len(list(qmap.get(0.5) or []))})
PY
```

- ANN benchmark (exact vs ANN) — structured JSON output:

```powershell
cmd /c "cd /d C:\Users\Asus\Desktop\g6_reorganized && set PYTHONPATH=C:\Users\Asus\Desktop\g6_reorganized && C:\Users\Asus\Desktop\g6_reorganized\.venv\Scripts\python.exe scripts\ml\ann_benchmark.py --index NIFTY --expiry_tag this_week --offset 0 --window 180 --k 20 --horizon 60 --bucket-ms 60000 --date 2025-11-05"
```

- Grid evaluation (discovery, last 1 day, moderate sample):

```powershell
cmd /c "cd /d C:\Users\Asus\Desktop\g6_reorganized && set PYTHONPATH=C:\Users\Asus\Desktop\g6_reorganized && C:\Users\Asus\Desktop\g6_reorganized\.venv\Scripts\python.exe scripts\ml\path_forecast_grid_eval.py --discover --indices NIFTY,BANKNIFTY --tags this_week --offsets 0 --horizons 30,60 --windows 0,60,120 --k 10,15 --modes auto,retrieval --bucket-ms 60000 --at end --last-days 1 --scales 1.0 --verbose"
```

- Panels read benchmark:

```powershell
cmd /c "cd /d C:\Users\Asus\Desktop\g6_reorganized && set PYTHONPATH=C:\Users\Asus\Desktop\g6_reorganized && C:\Users\Asus\Desktop\g6_reorganized\.venv\Scripts\python.exe scripts\bench_panels.py --panels-dir data\panels --iterations 30 --output panels_bench.json --json"
```

## Maintenance & Next Steps

- Tighten latency guard threshold after broader ANN & composite optimization pass.
- Persist comparative ANN results (large slice) and track ann_effectiveness trend over time.
- Consider a periodic task to auto-calibrate ANN candidate limits based on observed prune_ratio distribution.
- Add CI step to fail if ann_q50_mad exceeds tolerance (e.g. > 1.0 price units) while ann_speedup < target.

---
Last updated: 2025-11-08
