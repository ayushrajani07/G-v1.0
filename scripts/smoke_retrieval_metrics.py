"""Smoke test script for retrieval Prometheus metrics.

1. Sets required environment flags.
2. Constructs a minimal synthetic forecast call using in-memory data.
3. Prints a filtered subset of /metrics output for path_forecast metrics names.

Run:
    python scripts/smoke_retrieval_metrics.py

Prerequisites:
    - prometheus_client must be installed in the environment.
    - The main application should have already started the Prometheus HTTP server
      (if not, this script will still exercise the metrics registration but you
      may not see them at a global /metrics endpoint unless the server is running).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import time
import re

from src.path_forecast.retrieval import RetrievalPathForecaster, RetrievalConfig
from src.path_forecast.composite import CompositePathForecaster, CompositeConfig

# Enable metrics and profiling for richer last_meta
os.environ.setdefault("ENABLE_PATH_FORECAST_PROM_METRICS", "1")
os.environ.setdefault("ENABLE_PATH_FORECAST_PROFILING", "1")
os.environ.setdefault("ANN_MAD_GUARD_THRESHOLD", "0.5")

# Minimal synthetic recent window (list-of-lists as expected by forecast_path)
N_TODAY = 25
W = 10
H = 5
recent_scalar = [float(i) for i in range(N_TODAY)]
recent_window = [[v] for v in recent_scalar]

# Fake day files; monkeypatch _list_day_files and cache loader to avoid disk IO
fake_days = [Path(f"/fake/2025-11-{str(i+1).zfill(2)}.csv") for i in range(8)]

RetrievalPathForecaster._list_day_files = lambda self, index: fake_days  # type: ignore

import src.path_forecast.retrieval as retrieval_mod

def _fake_get_day_tp(root: Path, index: str, expiry: str, offset: str, dstr: str):
    # Create candidate days: last one is an outlier to trigger MAD guard filtering
    base = recent_scalar
    if dstr.endswith("08"):
        base = [x + 120.0 for x in base]
    # Append simple future continuation
    last = base[-1]
    future = [last + (i+1) for i in range(H)]
    return list(base) + future

retrieval_mod._cache_get_day_tp = _fake_get_day_tp  # type: ignore

cfg = RetrievalConfig(root=Path("/fake_root"), window=W, k=4, use_ann=True, ann_space="cosine", ann_max_candidates=8)
fore = RetrievalPathForecaster(cfg)

now_ms = int(time.time()*1000)
# Execute retrieval forecast
_ = fore.forecast_path(recent_window, context={"index": "TEST", "now_ms": now_ms}, horizon_minutes=H, bucket_ms=60_000)
print("retrieval last_meta keys:", sorted(fore.last_meta.keys()))

# Execute composite forecast using same synthetic rows
live_rows = [{"tp": v, "time_ms": now_ms - (len(recent_scalar)-i)*60_000} for i, v in enumerate(recent_scalar)]
ccfg = CompositeConfig(
    root=Path("/fake_root"), expiry_tag="this_week", offset="0",
    window=W, k=4, min_days=3, max_days_scan=10,
    use_ann=True, ann_space="cosine", ann_max_candidates=8,
)
cfore = CompositePathForecaster(ccfg)
_ = cfore.forecast_path(recent_window, context={"index": "TEST", "now_ms": now_ms, "live_rows": live_rows}, horizon_minutes=H, bucket_ms=60_000)
print("composite last_meta keys:", sorted(cfore.last_meta.keys()))

# Try to scrape metrics from default registry using prometheus_client exposition format
try:
    from prometheus_client import generate_latest  # type: ignore
    payload = generate_latest().decode("utf-8", errors="replace")
    wanted_prefixes = [
        "pf_retrieval_latency_ms",
        "pf_retrieval_candidates_total",
        "pf_ann_prune_ratio",
        "pf_ann_build_ms",
        "pf_exact_scoring_ms",
        "pf_quantile_agg_ms",
        # composite
        "pf_composite_latency_ms",
        "pf_composite_prior_cache_hit",
        "pf_composite_alpha",
        "pf_composite_prior_days",
        "pf_composite_retained_days",
    ]
    print("\nFiltered metrics (path_forecast):")
    for line in payload.splitlines():
        if any(line.startswith(p) for p in wanted_prefixes):
            print(line)
except Exception as e:
    print("[WARN] Could not generate metrics output:", e)
    print("Install prometheus_client if you need local scraping: pip install prometheus_client")

