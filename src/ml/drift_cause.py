"""Drift root-cause classifier (Phase 13).

Derives coarse categorical cause of elevated drift:
- stable: no significant tail deterioration
- data: tail deterioration with low weight divergence & stable regime
- model: elevated tail & high weight divergence (components disagree)
- regime: regime classification high and tail accel present
- mixed: multiple competing signals

Inputs: attribution dict from compute_drift_components.
"""
from __future__ import annotations
from typing import Dict

_DEF_THRESHOLDS = {
    'tail_ratio_warn': 1.05,      # >5% above target baseline adjusted
    'accel_warn': 0.03,           # tail acceleration moderate
    'divergence_high': 0.25,      # weight divergence high
    'regime_high': 1.2            # regime_class score threshold (placeholder scaling)
}

def classify_drift(attribution: Dict[str, float], thresholds: Dict[str, float] | None = None) -> str:
    t = {**_DEF_THRESHOLDS, **(thresholds or {})}
    tail = attribution.get('tail_ratio', 1.0)
    accel = attribution.get('tail_burn_accel', attribution.get('burn_rate', 0.0))
    divergence = attribution.get('weight_divergence', 0.0)
    regime = attribution.get('regime_class', 1.0)
    trend = attribution.get('trend_ratio', 1.0)

    # Basic severity gate
    significant_tail = tail > t['tail_ratio_warn'] or trend > 1.05
    accel_present = accel > t['accel_warn']
    high_divergence = divergence > t['divergence_high']
    regime_elevated = regime > t['regime_high']

    if not significant_tail and not accel_present:
        return 'stable'
    # Exclusive patterns
    if significant_tail and not high_divergence and not regime_elevated and accel_present:
        return 'data'
    if significant_tail and high_divergence and not regime_elevated:
        return 'model'
    if regime_elevated and accel_present and not high_divergence:
        return 'regime'
    return 'mixed'
