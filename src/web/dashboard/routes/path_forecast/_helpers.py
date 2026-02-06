from __future__ import annotations

import logging
from pathlib import Path

from src.web.dashboard.core.paths import project_root as _project_root

from .._index_norm import normalize_index

logger = logging.getLogger(__name__)


def _normalize_expiry_tag(index: str, expiry_tag: str) -> str:
    idx = normalize_index(index)
    tag = str(expiry_tag or "auto").strip().lower()
    if tag == "auto":
        # Explicit defaults per index as requested
        if idx in {"NIFTY", "SENSEX"}:
            return "this_week"
        if idx in {"BANKNIFTY", "FINNIFTY"}:
            return "this_month"
        # Fallback for any other index
        return "this_month"
    return tag


def _load_profiles() -> dict[str, dict]:
    """Load forecast parameter profiles from configs/ml/path_forecast_profiles.json.

    Supports Phase C knobs when present:
      distance_metric | weight_mode | recent_gamma | regime_tolerance | regime_penalty

    Provides built-ins if file missing for resiliency.
    """

    import json

    path = _project_root() / "configs" / "ml" / "path_forecast_profiles.json"
    profiles: dict[str, dict] = {
        "optimized": {
            "window": 180,
            "k": 20,
            "fallback_band_pct": 0.05,
            "distance_metric": "recent_l2",
            "weight_mode": "inv_dist",
            "recent_gamma": 0.9,
            "regime_tolerance": 0.25,
            "regime_penalty": 1.25,
        },
        "base": {
            "window": 120,
            "k": 15,
            "fallback_band_pct": 0.08,
            "distance_metric": "l2",
            "weight_mode": None,
            "recent_gamma": 0.9,
            "regime_tolerance": None,
            "regime_penalty": 1.25,
        },
    }
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, dict):
                        # Merge allowing file to override built-ins
                        profiles[k.lower()] = {**profiles.get(k.lower(), {}), **v}
    except (OSError, PermissionError, TypeError, ValueError) as e:
        logger.warning(
            "path_forecast: failed to load profiles; using defaults",
            extra={"path": str(path), "error": str(e)},
        )
    return profiles


def _calibration_dirs() -> tuple[Path, Path]:
    base = _project_root() / "data" / "ml" / "path_forecasts"
    cal_dir = base / "_calibration"
    hist_dir = base / "_calibration_history"
    try:
        cal_dir.mkdir(parents=True, exist_ok=True)
        hist_dir.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError) as e:
        logger.warning(
            "path_forecast: failed to ensure calibration dirs",
            extra={"error": str(e), "cal_dir": str(cal_dir), "hist_dir": str(hist_dir)},
        )
    return cal_dir, hist_dir
