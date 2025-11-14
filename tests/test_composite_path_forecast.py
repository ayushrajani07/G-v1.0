import time
from pathlib import Path

import pytest

from src.path_forecast.composite import CompositePathForecaster, CompositeConfig
from src.path_forecast.retrieval import RetrievalPathForecaster, RetrievalConfig


def _dummy_init(self, rcfg):  # rcfg: RetrievalConfig
    # Minimal init replicating needed attributes
    self.cfg = rcfg
    self.last_meta = {}
    # forced counts placeholder (set externally)
    if not hasattr(self, '_forced_candidates'):
        self._forced_candidates = 0
    if not hasattr(self, '_forced_threshold'):
        self._forced_threshold = 1

def _dummy_forecast(self, recent_window, *, context, quantiles=(0.1,0.5,0.9), horizon_minutes=60, bucket_ms=60_000):
    H = horizon_minutes
    now_ms = int(context.get('now_ms') or 0)
    times = [now_ms + (i+1)*bucket_ms for i in range(H)]
    qmap = {q: tuple(float(i+1) for i in range(H)) for q in quantiles}
    self.last_meta = {
        'candidates_total': self._forced_candidates,
        'threshold_needed': self._forced_threshold,
        'k_used': 5,
        'window_used': 30,
    }
    return times, qmap


def test_alpha_clamped_low_high(monkeypatch, tmp_path):
    """Alpha should clamp to [0.3,0.9] for extreme candidate richness scenarios."""
    root = tmp_path
    # Monkeypatch RetrievalPathForecaster with our dummy for two scenarios
    def run_case(cands, thresh):
        cfg = CompositeConfig(root=root, window=30, k=15, min_days=3)
        comp = CompositePathForecaster(cfg)
        # Replace retrieval class instance with dummy
        def assign_forced(self, rcfg):
            _dummy_init(self, rcfg)
            self._forced_candidates = cands
            self._forced_threshold = thresh
        monkeypatch.setattr('src.path_forecast.composite.RetrievalPathForecaster.__init__', assign_forced)
        monkeypatch.setattr('src.path_forecast.composite.RetrievalPathForecaster.forecast_path', _dummy_forecast)
        now_ms = int(time.time()*1000)
        recent_window = [[1.0],[2.0],[3.0]]  # minimal window
        times, qmap = comp.forecast_path(recent_window, context={'index':'NIFTY','now_ms':now_ms,'live_rows':[]}, horizon_minutes=10)
        return comp.last_meta.get('alpha'), times, qmap

    alpha_low, _, _ = run_case(1, 10)        # raw ~0.09 -> clamp to 0.3
    alpha_high, _, _ = run_case(100, 10)     # raw ~0.91 -> clamp to 0.9
    assert alpha_low == pytest.approx(0.3, rel=1e-6)
    assert alpha_high == pytest.approx(0.9, rel=1e-6)


def test_ann_space_fallback(monkeypatch, tmp_path):
    """Invalid ann_space should fall back to 'cosine' and be reflected in meta."""
    root = tmp_path
    # Monkeypatch list_day_files to avoid filesystem dependencies
    def fake_list(self, index):
        # Return two synthetic day files (names only)
        return [Path('2025-01-01.csv'), Path('2025-01-02.csv')]
    monkeypatch.setattr('src.path_forecast.retrieval.RetrievalPathForecaster._list_day_files', fake_list)

    # Monkeypatch cache get to produce long enough tp series
    def fake_get(root, idx, expiry_tag, offset, dstr):
        return list(range(0, 5000))  # plenty of rows
    monkeypatch.setattr('src.path_forecast.retrieval._cache_get_day_tp', fake_get)

    rcfg = RetrievalConfig(root=root, window=30, k=5, min_days=2, ann_space='BADSPACE', use_ann=True)
    retr = RetrievalPathForecaster(rcfg)
    now_ms = int(time.time()*1000)
    recent_window = [[float(i)] for i in range(30)]
    times, qmap = retr.forecast_path(recent_window, context={'index':'NIFTY','now_ms':now_ms,'live_rows':recent_window}, horizon_minutes=5)
    assert retr.last_meta.get('ann_space_used') == 'cosine'
    assert 'ann_space_used' in retr.last_meta
    # Basic sanity on outputs
    assert len(times) == 5
    for q, path in qmap.items():
        assert len(path) == 5
