from __future__ import annotations

# ML routes package.
#
# This package is the refactor-friendly home for ML endpoints.
# Import compatibility goal:
# - Existing code that did `from src.web.dashboard.routes import ml`
# - or `from src.web.dashboard.routes.ml import api_ml_predictions`
# should keep working.

from ._router import router

from .correlations import api_ml_correlations
from .delta import api_ml_delta
from .diagnostics import api_ml_diagnostics
from .ensemble import (

    KOverrideRequest,
    api_ml_ensemble,
    api_ml_ensemble_k_applied,
    api_ml_ensemble_k_calibration,
    api_ml_ensemble_k_override,
    api_ml_ensemble_k_overrides,
    api_ml_ensemble_quarantine_log,
    api_ml_ensemble_weights,
)
from .forecast_path import api_ml_forecast_path
from .model_matrix import api_ml_model_matrix
from .move_stats import api_ml_move_stats, api_ml_move_stats_archive
from .predictions import api_ml_predictions

__all__ = [

    "router",
    "KOverrideRequest",
    "api_ml_predictions",
    "api_ml_ensemble",
    "api_ml_ensemble_weights",
    "api_ml_ensemble_quarantine_log",
    "api_ml_ensemble_k_calibration",
    "api_ml_ensemble_k_applied",
    "api_ml_ensemble_k_override",
    "api_ml_ensemble_k_overrides",
    "api_ml_delta",
    "api_ml_correlations",
    "api_ml_model_matrix",
    "api_ml_diagnostics",
    "api_ml_move_stats",
    "api_ml_move_stats_archive",
    "api_ml_forecast_path",
]
