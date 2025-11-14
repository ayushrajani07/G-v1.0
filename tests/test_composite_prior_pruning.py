from pathlib import Path
import time

from src.path_forecast.composite import CompositePathForecaster, CompositeConfig

# Lightweight dummy retrieval to bypass real retrieval path in tests
def _dummy_init(self, rcfg):
    self.cfg = rcfg
    self.last_meta = {}

def _dummy_forecast(self, recent_window, *, context, quantiles=(0.1,0.5,0.9), horizon_minutes=60, bucket_ms=60_000):
    H = horizon_minutes
    now_ms = int(context.get('now_ms') or 0)
    times = [now_ms + (i+1)*bucket_ms for i in range(H)]
    qmap = {q: tuple(float(i+1) for i in range(H)) for q in quantiles}
    self.last_meta = {
        'candidates_total': 10,
        'threshold_needed': 1,
        'k_used': 5,
        'window_used': 30,
    }
    return times, qmap


def test_prior_pruning_min_hist_rows(monkeypatch, tmp_path):
    """Prior should prune all days if min_hist_rows sanitized exceeds available rows."""
    root = tmp_path
    cfg = CompositeConfig(root=root, window=30, k=5, min_days=2, min_hist_rows=10_000)
    comp = CompositePathForecaster(cfg)
    # Bypass retrieval to avoid candidate exceptions
    monkeypatch.setattr('src.path_forecast.composite.RetrievalPathForecaster.__init__', _dummy_init)
    monkeypatch.setattr('src.path_forecast.composite.RetrievalPathForecaster.forecast_path', _dummy_forecast)

    # Two synthetic day files
    monkeypatch.setattr('src.path_forecast.composite.CompositePathForecaster._list_day_files',
                        lambda self, idx: [Path('2025-01-01.csv'), Path('2025-01-02.csv')])
    # Historical series too short to pass min_hist_rows
    monkeypatch.setattr('src.path_forecast.composite.CompositePathForecaster._load_tp_series',
                        lambda self, p, idx: list(range(2000)))

    # Control today's position via parse_today_tp monkeypatch
    monkeypatch.setattr('src.path_forecast.composite._parse_today_tp',
                        lambda today, live: (list(range(1000)), []))

    now_ms = int(time.time()*1000)
    times, out = comp.forecast_path([[1.0] for _ in range(30)], context={'index':'NIFTY','now_ms':now_ms,'live_rows':[]}, horizon_minutes=10)
    meta = comp.last_meta
    # All pruned due to min_hist_rows gate (prior perspective)
    assert meta.get('prior_days') == 0
    # Sanitized meta present
    assert (meta.get('prior_min_hist_rows_sanitized') or 0) >= 10_000
    assert 'prior_max_time_gap_ratio_sanitized' in meta


def test_prior_pruning_max_time_gap_ratio(monkeypatch, tmp_path):
    """Prior should prune days when time gap ratio difference exceeds sanitized tolerance."""
    root = tmp_path
    # Tolerance 0 forces strict equality; any difference prunes
    cfg = CompositeConfig(root=root, window=30, k=5, min_days=2, max_time_gap_ratio=0.0)
    comp = CompositePathForecaster(cfg)
    monkeypatch.setattr('src.path_forecast.composite.RetrievalPathForecaster.__init__', _dummy_init)
    monkeypatch.setattr('src.path_forecast.composite.RetrievalPathForecaster.forecast_path', _dummy_forecast)

    monkeypatch.setattr('src.path_forecast.composite.CompositePathForecaster._list_day_files',
                        lambda self, idx: [Path('2025-01-01.csv')])
    # Large historical series; we set now_pos later to mismatch ratio
    monkeypatch.setattr('src.path_forecast.composite.CompositePathForecaster._load_tp_series',
                        lambda self, p, idx: list(range(5000)))
    # Force now_pos smaller so ratio_hist != 1.0 -> pruned with tol=0.0
    monkeypatch.setattr('src.path_forecast.composite._parse_today_tp',
                        lambda today, live: (list(range(1000)), []))

    now_ms = int(time.time()*1000)
    times, out = comp.forecast_path([[1.0] for _ in range(30)], context={'index':'NIFTY','now_ms':now_ms,'live_rows':[]}, horizon_minutes=10)
    meta = comp.last_meta
    # Expect pruning occurred due to ratio tolerance (prior perspective)
    assert meta.get('prior_days') == 0
    # Sanitized meta present and tolerance recorded
    assert meta.get('prior_max_time_gap_ratio_sanitized') == 0.0
    assert meta.get('prior_min_hist_rows_sanitized') is not None
