import pytest
from pathlib import Path

from src.path_forecast.config_structs import RetrievalConfig
from src.path_forecast.retrieval import RetrievalPathForecaster
from src.path_forecast.composite import CompositeConfig, CompositePathForecaster


def make_rows(tp_values, start_ms=0, bucket_ms=60_000):
    rows = []
    t = start_ms
    for v in tp_values:
        rows.append({"ts": t, "tp": float(v)})
        t += bucket_ms
    return rows


def write_day(root: Path, index: str, expiry: str, offset: str, date_str: str, tp_values):
    day_dir = root / index / expiry / offset
    day_dir.mkdir(parents=True, exist_ok=True)
    p = day_dir / f"{date_str}.csv"
    rows = make_rows(tp_values)
    with p.open("w", encoding="utf-8") as f:
        f.write("ts,tp\n")
        for r in rows:
            f.write(f"{r['ts']},{r['tp']}\n")
    return p


def build_recent(tp_values):
    return [[float(v)] for v in tp_values]


@pytest.fixture
def tmp_root(tmp_path: Path):
    root = tmp_path / "data" / "g6_data"
    root.mkdir(parents=True)
    return root


SANITIZED_KEYS_RETR = {
    "window_sanitized",
    "horizon_sanitized",
    "bucket_ms_sanitized",
    "k_sanitized",
    "min_days_sanitized",
    "recent_gamma_sanitized",
    "regime_tolerance_sanitized",
    "regime_penalty_sanitized",
    "min_hist_rows_sanitized",
    "max_time_gap_ratio_sanitized",
    "ann_dim_sanitized",
    "ann_space_used",
}

SANITIZED_KEYS_COMP = {
    "horizon_sanitized",
    "bucket_ms_sanitized",
    "k_sanitized",
    "min_days_sanitized",
    # Composite mirrors retrieval diagnostics; alpha-specific meta also present
}


def _prepare_hist_days(tmp_root: Path, index: str, expiry: str, offset: str, recent, future_span: int, days: int = 3):
    for i in range(days):
        # create slight variation per day
        base = [v + i * 0.5 for v in recent]
        fut = [base[-1] + (j + 1) * (0.1 + 0.05 * i) for j in range(future_span)]
        write_day(tmp_root, index, expiry, offset, f"2025-11-0{7-i}", base + fut)


def test_retrieval_meta_sanitized_presence(tmp_root):
    index = "NIFTY"
    expiry = "this_week"
    offset = "0"
    recent = [100 + i * 0.2 for i in range(60)]
    horizon = 30
    _prepare_hist_days(tmp_root, index, expiry, offset, recent, horizon, days=3)

    cfg = RetrievalConfig(root=tmp_root, expiry_tag=expiry, offset=offset, window=60, k=3, use_ann=True, ann_dim=40, ann_space="l2")
    f = RetrievalPathForecaster(cfg)  # type: ignore[arg-type]
    now_ms = (len(recent) - 1) * 60_000
    f.forecast_path(build_recent(recent), context={"index": index, "now_ms": now_ms, "live_rows": []}, horizon_minutes=horizon)

    meta = f.last_meta
    missing = [k for k in SANITIZED_KEYS_RETR if k not in meta]
    assert not missing, f"Missing sanitized meta keys: {missing}"
    # Range sanity
    assert 1 <= meta["window_sanitized"] <= 720
    assert 1 <= meta["horizon_sanitized"] <= 720
    assert 1 <= meta["bucket_ms_sanitized"] <= 300_000
    assert 1 <= meta["ann_dim_sanitized"] <= meta["window_sanitized"]
    assert meta["ann_space_used"] in {"cosine", "l2"}


def test_retrieval_ann_dim_fallback(tmp_root):
    # ann_dim omitted -> should fallback to window
    index = "NIFTY"
    expiry = "this_week"
    offset = "0"
    recent = [200 + i * 0.1 for i in range(50)]
    horizon = 20
    _prepare_hist_days(tmp_root, index, expiry, offset, recent, horizon, days=2)
    cfg = RetrievalConfig(root=tmp_root, expiry_tag=expiry, offset=offset, window=50, k=2, use_ann=True)
    f = RetrievalPathForecaster(cfg)  # type: ignore[arg-type]
    now_ms = (len(recent) - 1) * 60_000
    f.forecast_path(build_recent(recent), context={"index": index, "now_ms": now_ms, "live_rows": []}, horizon_minutes=horizon)
    meta = f.last_meta
    assert meta.get("ann_dim_sanitized") == meta.get("window_sanitized"), "ANN dim fallback to window failed"


def test_composite_meta_sanitized_subset(tmp_root):
    index = "NIFTY"
    expiry = "this_week"
    offset = "0"
    recent = [300 + i * 0.15 for i in range(60)]
    horizon = 25
    _prepare_hist_days(tmp_root, index, expiry, offset, recent, horizon, days=3)
    ccfg = CompositeConfig(root=tmp_root, expiry_tag=expiry, offset=offset, window=60, k=4, min_days=3, use_ann=False)
    comp = CompositePathForecaster(ccfg)
    now_ms = (len(recent) - 1) * 60_000
    # Composite forecaster derives today's TP from live_rows, not the passed recent_window.
    live_rows = [{"ts": i * 60_000, "tp": float(v)} for i, v in enumerate(recent)]
    comp.forecast_path(build_recent(recent), context={"index": index, "now_ms": now_ms, "live_rows": live_rows}, horizon_minutes=horizon)
    meta = comp.last_meta
    missing = [k for k in SANITIZED_KEYS_COMP if k not in meta]
    assert not missing, f"Composite missing sanitized meta keys: {missing}"
    alpha_val = meta.get("alpha")
    assert isinstance(alpha_val, (float, int))
    assert 0.3 <= float(alpha_val) <= 0.9
    assert meta.get("horizon_sanitized") == horizon