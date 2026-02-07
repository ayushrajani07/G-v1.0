from __future__ import annotations

# Package split from legacy monolithic routes/path_forecast.py.
# Compatibility policy:
# - Keep the primary FastAPI entrypoint as `router`.
# - Preserve historical imports like:
#     from src.web.dashboard.routes.path_forecast import api_ml_path_advisor
#     from src.web.dashboard.routes.path_forecast import _save_calibration
#   by delegating attribute access to the underlying implementation module.

from . import _router as _router

router = _router.router


def __getattr__(name: str):  # pragma: no cover
    return getattr(_router, name)


def __dir__() -> list[str]:  # pragma: no cover
    return sorted(set(globals().keys()) | set(dir(_router)))


__all__ = ["router"]
