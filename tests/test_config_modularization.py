from pathlib import Path

from src.path_forecast.retrieval import RetrievalConfig as LegacyRetrievalConfig
from src.path_forecast.config_structs import (
    RetrievalConfig as ModularRetrievalConfig,
    PruningConfig, RegimeConfig, AnnConfig,
)


def test_modular_vs_legacy_equivalence_basic():
    # Legacy-style construction
    leg = LegacyRetrievalConfig(
        root=Path("/fake_root"),
        expiry_tag="this_week",
        offset="0",
        window=45,
        k=11,
        min_days=4,
        min_future=35,
        max_days_scan=23,
        min_hist_rows=120,
        max_time_gap_ratio=0.2,
        distance_metric="recent_l2",
        recent_gamma=0.85,
        weight_mode="inv_dist",
        regime_tolerance=0.5,
        regime_penalty=1.4,
        use_ann=True,
        ann_space="cosine",
        ann_max_candidates=50,
        ann_dim=45,
    )

    # Modular-style construction
    mod = ModularRetrievalConfig.from_modular(
        root=Path("/fake_root"),
        expiry_tag="this_week",
        offset="0",
        window=45,
        k=11,
        pruning=PruningConfig(
            min_days=4, min_future=35, max_days_scan=23, min_hist_rows=120, max_time_gap_ratio=0.2
        ),
        regime=RegimeConfig(
            distance_metric="recent_l2", recent_gamma=0.85, weight_mode="inv_dist", regime_tolerance=0.5, regime_penalty=1.4
        ),
        ann=AnnConfig(use_ann=True, ann_space="cosine", ann_max_candidates=50, ann_dim=45),
    )

    # Field equivalence for attributes used in retrieval
    assert leg.window == mod.window
    assert leg.k == mod.k

    assert mod.pruning is not None
    pr = mod.pruning
    assert leg.min_days == pr.min_days
    assert leg.min_future == pr.min_future
    assert leg.max_days_scan == pr.max_days_scan
    assert leg.min_hist_rows == pr.min_hist_rows
    assert leg.max_time_gap_ratio == pr.max_time_gap_ratio

    assert mod.regime is not None
    rg = mod.regime
    assert leg.distance_metric == rg.distance_metric
    assert abs(leg.recent_gamma - rg.recent_gamma) < 1e-9
    assert leg.weight_mode == rg.weight_mode
    assert leg.regime_tolerance == rg.regime_tolerance
    assert abs(leg.regime_penalty - rg.regime_penalty) < 1e-9

    assert mod.ann is not None
    an = mod.ann
    assert leg.use_ann == an.use_ann
    assert leg.ann_space == an.ann_space
    assert leg.ann_max_candidates == an.ann_max_candidates
    assert leg.ann_dim == an.ann_dim

    # Legacy dict provides flat representation consistent with legacy fields
    ld = mod.legacy_dict()
    assert ld["distance_metric"] == "recent_l2"
    assert ld["use_ann"] is True
    assert ld["ann_max_candidates"] == 50
