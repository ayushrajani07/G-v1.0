import math
from scripts.ml import ann_auto_tune_candidates as tuner


def test_pick_prefers_smallest_meeting_constraints():
    # Construct synthetic rows resembling ladder comparison
    rows = [
        {'ann_max_candidates': 50, 'prune_ratio_avg': 1.0, 'q50_mad_avg': 0.0, 'speedup_avg': 0.92},
        {'ann_max_candidates': 30, 'prune_ratio_avg': 0.98, 'q50_mad_avg': 0.02, 'speedup_avg': 0.93},
        {'ann_max_candidates': 20, 'prune_ratio_avg': 0.92, 'q50_mad_avg': 0.05, 'speedup_avg': 0.93},
        {'ann_max_candidates': 10, 'prune_ratio_avg': 0.55, 'q50_mad_avg': 0.65, 'speedup_avg': 0.94},
    ]
    # min_prune_gain = 0.05 => requires prune_ratio <= 0.95
    # target_mad = 0.1 => allows 20 and 30, but not 10 (mad too high)
    pick_row = tuner.pick(rows, target_mad=0.1, min_prune_gain=0.05, prefer_speedup=False)
    assert pick_row['ann_max_candidates'] == 20


def test_pick_fallback_to_largest_when_none_valid():
    rows = [
        {'ann_max_candidates': 50, 'prune_ratio_avg': 1.0, 'q50_mad_avg': 0.2, 'speedup_avg': 0.9},
        {'ann_max_candidates': 30, 'prune_ratio_avg': 0.99, 'q50_mad_avg': 0.3, 'speedup_avg': 0.9},
    ]
    pick_row = tuner.pick(rows, target_mad=0.1, min_prune_gain=0.2)
    assert pick_row['ann_max_candidates'] == 50


def test_pick_per_mode_uses_mode_columns():
    rows = [
        # Candidate 50 (no pruning) mode stats
        {'ann_max_candidates': 50, 'prune_ratio_avg': 1.0, 'q50_mad_avg': 0.0, 'speedup_avg': 0.9,
         'retrieval_prune_ratio_avg': 0.95, 'retrieval_q50_mad_avg': 0.02, 'retrieval_speedup_avg': 0.9,
         'auto_prune_ratio_avg': 0.99, 'auto_q50_mad_avg': 0.01, 'auto_speedup_avg': 0.9,
         'hybrid_prune_ratio_avg': 0.99, 'hybrid_q50_mad_avg': 0.01, 'hybrid_speedup_avg': 0.9},
        # Candidate 30 (still little pruning)
        {'ann_max_candidates': 30, 'prune_ratio_avg': 0.98, 'q50_mad_avg': 0.01, 'speedup_avg': 0.92,
         'retrieval_prune_ratio_avg': 0.90, 'retrieval_q50_mad_avg': 0.03, 'retrieval_speedup_avg': 0.93,
         'auto_prune_ratio_avg': 0.95, 'auto_q50_mad_avg': 0.02, 'auto_speedup_avg': 0.92,
         'hybrid_prune_ratio_avg': 0.95, 'hybrid_q50_mad_avg': 0.02, 'hybrid_speedup_avg': 0.92},
        # Candidate 20 (meets pruning for retrieval, borderline others)
        {'ann_max_candidates': 20, 'prune_ratio_avg': 0.90, 'q50_mad_avg': 0.05, 'speedup_avg': 0.93,
         'retrieval_prune_ratio_avg': 0.70, 'retrieval_q50_mad_avg': 0.06, 'retrieval_speedup_avg': 0.94,
         'auto_prune_ratio_avg': 0.85, 'auto_q50_mad_avg': 0.08, 'auto_speedup_avg': 0.93,
         'hybrid_prune_ratio_avg': 0.85, 'hybrid_q50_mad_avg': 0.08, 'hybrid_speedup_avg': 0.93},
        # Candidate 10 (aggressive pruning but high MAD for auto/hybrid)
        {'ann_max_candidates': 10, 'prune_ratio_avg': 0.55, 'q50_mad_avg': 0.65, 'speedup_avg': 0.94,
         'retrieval_prune_ratio_avg': 0.50, 'retrieval_q50_mad_avg': 0.07, 'retrieval_speedup_avg': 0.95,
         'auto_prune_ratio_avg': 0.40, 'auto_q50_mad_avg': 0.60, 'auto_speedup_avg': 0.94,
         'hybrid_prune_ratio_avg': 0.40, 'hybrid_q50_mad_avg': 0.60, 'hybrid_speedup_avg': 0.94},
    ]
    per_mode = tuner.pick_per_mode(rows, target_mad=0.1, min_prune_gain=0.05)
    # retrieval should choose smallest (10) though MAD still acceptable (<0.1) is false; retrieval MAD 0.07 < 0.1 and prune gain 0.50 >= 0.05
    assert per_mode['retrieval'] == 10
    # auto/hybrid should not pick 10 due to MAD 0.60 > 0.1; next candidate satisfying constraints is 20 (MAD 0.08, prune gain 0.15)
    assert per_mode['auto'] == 20
    assert per_mode['hybrid'] == 20
