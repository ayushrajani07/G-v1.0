from __future__ import annotations

"""Legacy ML router.

This module intentionally contains *only* route wiring.
All handler implementations live in the `src.web.dashboard.routes.ml` package.

Kept for backward compatibility because older imports expect `ml_legacy.router`.
"""

from fastapi import APIRouter

from .ml.correlations import api_ml_correlations
from .ml.delta import api_ml_delta
from .ml.diagnostics import api_ml_diagnostics
from .ml.ensemble import (
    api_ml_ensemble,
    api_ml_ensemble_k_applied,
    api_ml_ensemble_k_calibration,
    api_ml_ensemble_k_override,
    api_ml_ensemble_k_overrides,
    api_ml_ensemble_quarantine_log,
    api_ml_ensemble_weights,
)
from .ml.forecast_path import api_ml_forecast_path
from .ml.model_matrix import api_ml_model_matrix
from .ml.move_stats import api_ml_move_stats, api_ml_move_stats_archive
from .ml.predictions import api_ml_predictions

router = APIRouter()

router.get("/api/ml/predictions")(api_ml_predictions)
router.get("/api/ml/ensemble")(api_ml_ensemble)
router.get("/api/ml/ensemble/weights")(api_ml_ensemble_weights)
router.get("/api/ml/ensemble/quarantine_log")(api_ml_ensemble_quarantine_log)
router.get("/api/ml/ensemble/k_calibration")(api_ml_ensemble_k_calibration)
router.get("/api/ml/ensemble/k_applied")(api_ml_ensemble_k_applied)
router.get("/api/ml/ensemble/k_overrides")(api_ml_ensemble_k_overrides)
router.post("/api/ml/ensemble/k_override", response_model=None)(api_ml_ensemble_k_override)
router.get("/api/ml/delta")(api_ml_delta)
router.get("/api/ml/correlations")(api_ml_correlations)
router.get("/api/ml/model_matrix")(api_ml_model_matrix)
router.get("/api/ml/diagnostics")(api_ml_diagnostics)
router.get("/api/ml/move_stats")(api_ml_move_stats)
router.get("/api/ml/move_stats_archive")(api_ml_move_stats_archive)
router.get("/api/ml/forecast/path")(api_ml_forecast_path)

__all__ = ["router"]
