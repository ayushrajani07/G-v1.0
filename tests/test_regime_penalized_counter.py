import os
from pathlib import Path
from datetime import datetime

from src.path_forecast.retrieval import RetrievalPathForecaster, RetrievalConfig


def _make_day_csv(p: Path, tps):
    p.parent.mkdir(parents=True, exist_ok=True)
    # simple epoch base for deterministic ms
    base = int(datetime(2025, 11, 1).timestamp() * 1000)
    with p.open('w', encoding='utf-8') as f:
        f.write('time,tp\n')
        for i, v in enumerate(tps):
            f.write(f"{base + i*60000},{v}\n")


def test_regime_penalized_counter(tmp_path: Path):
    # Layout: root/TESTIDX/this_week/0/<date>.csv
    root = tmp_path / 'data'
    idx = 'TESTIDX'
    expiry_tag = 'this_week'
    offset = '0'
    base_dir = root / idx / expiry_tag / offset

    # Candidate day 1: similar variance to today (should NOT be penalized)
    day1 = base_dir / '2025-11-01.csv'
    tps1 = [100, 101, 99, 100, 101, 100, 100, 101, 99, 100]  # std ~0.8
    _make_day_csv(day1, tps1)

    # Candidate day 2: very different variance (should be penalized)
    day2 = base_dir / '2025-11-02.csv'
    tps2 = [100, 104, 96, 105, 95, 106, 94, 107, 93, 108]  # higher std
    _make_day_csv(day2, tps2)

    # Today's live rows (simulate mid-session with moderate variance ~0.8 similar to day1)
    live_rows = []
    base_now = int(datetime(2025, 11, 3, 10, 30).timestamp() * 1000)  # 'today' = 2025-11-03 (no file present -> both historical days considered)
    todays_tp = [200, 201, 199, 200, 201, 200]  # window=5 will use last 5 -> std similar to ~0.8
    for i, v in enumerate(todays_tp):
        live_rows.append({'time': base_now + i*60000, 'tp': v})

    cfg = RetrievalConfig(
        root=root,
        expiry_tag=expiry_tag,
        offset=offset,
        window=5,
        k=2,
        min_days=2,
        max_days_scan=None,
        min_hist_rows=None,
        max_time_gap_ratio=None,
        distance_metric='l2',
        recent_gamma=0.9,
        weight_mode=None,
        regime_tolerance=0.3,  # penalize if relative std delta > 0.3
        regime_penalty=1.5,
    )
    retr = RetrievalPathForecaster(cfg)
    # Build recent window from live_rows
    recent_window = [[float(r['tp'])] for r in live_rows]
    times, qmap = retr.forecast_path(
        recent_window,
        context={'index': idx, 'now_ms': base_now + len(live_rows)*60000, 'live_rows': live_rows},
        quantiles=(0.5,),
        horizon_minutes=3,
        bucket_ms=60000,
    )

    # Assert meta contains regime_penalized and it's at least 1 (day2 should trigger)
    rp = retr.last_meta.get('regime_penalized')
    assert isinstance(rp, int)
    assert rp >= 1, f"Expected at least one penalized candidate, got {rp} meta={retr.last_meta}"

    # Sanity: candidates_total should equal retained_days and be >= min_days
    ctot = int(retr.last_meta.get('candidates_total') or 0)
    rdays = int(retr.last_meta.get('retained_days') or 0)
    assert ctot == rdays and ctot >= 2

    # Ensure header-related fields present
    assert 'distance_metric' in retr.last_meta
    assert 'window_used' in retr.last_meta
