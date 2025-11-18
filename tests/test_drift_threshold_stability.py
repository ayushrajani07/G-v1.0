import json
import os
import time
from pathlib import Path

import pytest

from scripts.ml import validate_drift_threshold_stability as stability


def _write_artifact(dirpath: Path, ts_suffix: str, agg: dict):
    fname = f"calibrated_thresholds_{ts_suffix}.json"
    data = {
        "aggregate": agg,
        "indices": ["NIFTY"],
        "rows": [],
    }
    with open(dirpath / fname, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return dirpath / fname


def test_stability_insufficient_artifacts(tmp_path: Path):
    # Single artifact -> status should be 'insufficient'
    _write_artifact(tmp_path, "20250101_000000", {
        "mae_warn": 1.5,
        "mae_crit": 2.0,
        "norm_warn": 1.3,
        "norm_crit": 1.7,
        "coverage_drop_warn": -10,
        "coverage_drop_crit": -20,
        "horizons_used": 3,
    })
    artifacts = stability.load_artifacts(str(tmp_path))
    report = stability.compute_report(artifacts, max_pct=0.15, min_horizons=1)
    assert report["status"] == "insufficient"


def test_stability_detects_unstable_shift(tmp_path: Path):
    # Two prior stable artifacts + one large shift in latest -> 'unstable'
    _write_artifact(tmp_path, "20250101_000000", {
        "mae_warn": 1.50,
        "mae_crit": 2.00,
        "norm_warn": 1.30,
        "norm_crit": 1.70,
        "coverage_drop_warn": -10.0,
        "coverage_drop_crit": -20.0,
        "horizons_used": 5,
    })
    _write_artifact(tmp_path, "20250102_000000", {
        "mae_warn": 1.52,
        "mae_crit": 2.02,
        "norm_warn": 1.31,
        "norm_crit": 1.69,
        "coverage_drop_warn": -10.5,
        "coverage_drop_crit": -19.5,
        "horizons_used": 5,
    })
    # Latest with >30% jump in mae_warn (1.50 -> 2.0) > 15% threshold
    _write_artifact(tmp_path, "20250103_000000", {
        "mae_warn": 2.00,
        "mae_crit": 2.40,
        "norm_warn": 1.35,
        "norm_crit": 1.80,
        "coverage_drop_warn": -12.0,
        "coverage_drop_crit": -25.0,
        "horizons_used": 5,
    })
    artifacts = stability.load_artifacts(str(tmp_path))
    report = stability.compute_report(artifacts, max_pct=0.15, min_horizons=1)
    assert report["status"] == "unstable"
    assert report["violations"] > 0
    # Ensure mae_warn key recorded with violation
    mae_entry = next(e for e in report["keys"] if e["key"] == "mae_warn")
    assert mae_entry["violation"] is True


def test_stability_stable_with_small_fluctuations(tmp_path: Path):
    # Small <5% shifts should remain stable
    _write_artifact(tmp_path, "20250101_000000", {
        "mae_warn": 1.50,
        "mae_crit": 2.00,
        "norm_warn": 1.30,
        "norm_crit": 1.70,
        "coverage_drop_warn": -10.0,
        "coverage_drop_crit": -20.0,
        "horizons_used": 4,
    })
    _write_artifact(tmp_path, "20250102_000000", {
        "mae_warn": 1.52,
        "mae_crit": 1.98,
        "norm_warn": 1.31,
        "norm_crit": 1.69,
        "coverage_drop_warn": -10.3,
        "coverage_drop_crit": -19.8,
        "horizons_used": 4,
    })
    _write_artifact(tmp_path, "20250103_000000", {
        "mae_warn": 1.53,
        "mae_crit": 2.01,
        "norm_warn": 1.32,
        "norm_crit": 1.68,
        "coverage_drop_warn": -10.2,
        "coverage_drop_crit": -20.2,
        "horizons_used": 4,
    })
    artifacts = stability.load_artifacts(str(tmp_path))
    report = stability.compute_report(artifacts, max_pct=0.15, min_horizons=1)
    assert report["status"] == "stable"
    assert report["violations"] == 0
