from __future__ import annotations

# ML routes package.
#
# This package is a refactor-friendly home for ML endpoints.
# For now, it is a behavior-preserving proxy to the legacy implementation.
#
# Import compatibility goal:
# - Existing code that did `from src.web.dashboard.routes import ml`
# - or `from src.web.dashboard.routes.ml import api_ml_predictions`
# should keep working while we gradually move endpoints into handler modules.

from .. import ml_legacy as _legacy

router = _legacy.router


def __getattr__(name: str):  # pragma: no cover
	return getattr(_legacy, name)


def __dir__() -> list[str]:  # pragma: no cover
	return sorted(set(globals().keys()) | set(dir(_legacy)))


__all__ = ["router"]
