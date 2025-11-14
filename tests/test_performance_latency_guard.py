import time
from pathlib import Path

import pytest

# We import the retrieval path forecast via the dashboard route utilities to avoid duplicating setup logic.
# The latency guard focuses on the core generation timing (path + quantiles) and excludes network/server overhead.

from src.path_forecast.retrieval import RetrievalPathForecaster  # direct class
from src.path_forecast.common import build_bucketed_realized, build_recent_window


WINDOW = 60  # minutes
HORIZON = 30  # minutes
LATENCY_BUDGET_MS = 600  # conservative guard; adjust downward once stable


@pytest.fixture
def synthetic_tmp_root(tmp_path: Path):
    """Create a synthetic data root with multiple historical day CSVs and today's file.

    We only need enough rows to satisfy the recent window + horizon computations. Timestamps are spaced by 1 minute.
    """
    data_root = tmp_path / 'data' / 'g6_data' / 'LATTEST' / 'this_week' / '0'
    data_root.mkdir(parents=True, exist_ok=True)

    # Generate 4 historical days + today; each with >= WINDOW + HORIZON + buffer rows.
    import datetime
    base_days = [datetime.date(2025, 11, 3), datetime.date(2025, 11, 4), datetime.date(2025, 11, 5), datetime.date(2025, 11, 6)]
    today = datetime.date(2025, 11, 7)
    all_days = base_days + [today]

    def write_day(day: datetime.date, base_tp: float):
        rows = []
        base_ms = int(datetime.datetime(day.year, day.month, day.day, 10, 0).timestamp() * 1000)
        # Provide 120 rows; pattern introduces mild variance changes per day.
        for i in range(120):
            v = base_tp + (i % (1 + (day.day % 5))) * (1 + (day.day % 3))
            ts_ms = base_ms + i * 60_000
            ts_str = datetime.datetime.fromtimestamp(ts_ms/1000).strftime('%Y-%m-%d %H:%M:%S')
            rows.append((ts_str, v))
        # Write CSV
        fp = data_root / f'{day.isoformat()}.csv'
        with fp.open('w', encoding='utf-8') as f:
            f.write('timestamp,tp\n')
            for ts, val in rows:
                f.write(f'{ts},{val}\n')

    # Historical variety
    for d in base_days:
        write_day(d, 100.0 + (d.day % 4) * 2.5)
    # Today with different amplitude baseline
    write_day(today, 150.0)
    return data_root.parent.parent.parent  # return tmp_path / data / g6_data root ancestor


def _load_live_tp(data_root: Path, index: str, expiry: str, offset: str):
    # Minimal loader replicating expected structure (only today's file read)
    import datetime
    today = datetime.date(2025, 11, 7).isoformat()
    p = data_root / index / expiry / offset / f'{today}.csv'
    rows = []
    with p.open('r', encoding='utf-8') as f:
        next(f)  # header
        for line in f:
            ts_str, v = line.strip().split(',')
            # Convert timestamp back to ms
            dt = datetime.datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
        ts_ms = int(dt.timestamp() * 1000)
        # Use time_ms key to align with common.row_time_ms expectations
        rows.append({'time_ms': ts_ms, 'tp': float(v)})
    return rows


def test_forecast_latency_guard(synthetic_tmp_root: Path):
    """Ensures retrieval path forecaster generates a forecast within latency budget.

    Uses minimal metric mode pattern implicitly (by only timing core forecast). If exceeding budget, surfaces regression.
    """
    index = 'LATTEST'
    expiry = 'this_week'
    offset = '0'

    # Build live rows in-memory (avoid I/O variability)
    import datetime
    today = datetime.date(2025, 11, 7)
    base_ms_today = int(datetime.datetime(today.year, today.month, today.day, 10, 0).timestamp() * 1000)
    live_rows = []
    for i in range(120):
        ts_ms = base_ms_today + i * 60_000
        # Match write_day pattern for today (day=7)
        v = 150.0 + (i % (1 + (today.day % 5))) * (1 + (today.day % 3))
        live_rows.append({"time_ms": ts_ms, "tp": float(v)})
    assert len(live_rows) >= WINDOW + HORIZON

    # Extract realized/bucketed values similar to endpoint usage
    ts_sorted, rmap = build_bucketed_realized(live_rows, bucket_ms=60_000)
    assert len(ts_sorted) >= WINDOW

    # Build recent window from realized buckets (last W values), shape [[tp], ...]
    recent_window = [[float(rmap[t])] for t in ts_sorted[-WINDOW:]]
    assert len(recent_window) == WINDOW

    # Instantiate retrieval forecaster with explicit config
    from src.path_forecast.retrieval import RetrievalConfig
    cfg = RetrievalConfig(
        root=synthetic_tmp_root,
        expiry_tag=expiry,
        offset=offset,
        window=WINDOW,
        k=10,
        use_ann=False,
    )
    forecaster = RetrievalPathForecaster(cfg)

    # Time forecast generation
    now_ms = ts_sorted[-1]
    ctx = {"index": index, "now_ms": now_ms, "live_rows": live_rows}
    start = time.perf_counter()
    times, qmap = forecaster.forecast_path(recent_window, context=ctx, quantiles=(0.5,), horizon_minutes=HORIZON)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    # Basic sanity
    assert isinstance(times, list) and len(times) == HORIZON
    assert 0.5 in qmap and len(qmap[0.5]) == HORIZON

    # Latency guard
    assert elapsed_ms < LATENCY_BUDGET_MS, (
        f'Forecast latency {elapsed_ms:.2f}ms exceeded budget {LATENCY_BUDGET_MS}ms; investigate regression.'
    )

    # Provide context on worst-case threshold proximity to help tuning if needed
    margin = LATENCY_BUDGET_MS - elapsed_ms
    assert margin > 0

    # Optional: If within 10% of budget, flag for potential tightening
    if margin < LATENCY_BUDGET_MS * 0.1:
        pytest.skip(f'Latency {elapsed_ms:.2f}ms near threshold; consider lowering budget after further optimizations.')
