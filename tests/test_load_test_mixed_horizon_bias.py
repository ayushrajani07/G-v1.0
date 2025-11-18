"""Test horizon-biased sampling logic from load_test_ensemble_mixed harness.

Validates that weighted choice produces distribution respecting relative weights.
Uses internal helper functions via import.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

HARNESS_PATH = Path("scripts/ml/load_test_ensemble_mixed.py").resolve()


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location("_mixed_harness", str(path))
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError("Cannot load harness module")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_weighted_choice_distribution():
    mod = _load_module(HARNESS_PATH)
    rng = mod.random.Random(123)
    horizons = [15, 30, 60, 120]
    weights = {15: 0.1, 30: 0.4, 60: 0.4, 120: 0.1}
    counts = {h: 0 for h in horizons}
    N = 2000
    for _ in range(N):
        h = mod._weighted_choice(rng, weights)
        counts[h] += 1
    # Convert to proportions
    props = {h: counts[h] / N for h in horizons}
    # Assert ordering matches weights (allow small drift)
    assert props[30] >= props[15]
    assert props[60] >= props[30] * 0.9  # close to equal or higher
    assert props[120] <= props[30] * 0.5  # much smaller than heavier weights
    # Check each within reasonable tolerance of target (±40% relative tolerance given randomness)
    for h, target in weights.items():
        if target == 0:
            continue
        rel_err = abs(props[h] - target) / target
        assert rel_err < 0.4, f"Horizon {h} proportion {props[h]:.3f} deviates too much from target {target:.3f}"  # wide tolerance for CI speed
