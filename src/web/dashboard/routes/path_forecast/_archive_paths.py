from __future__ import annotations

from collections.abc import Callable
from datetime import date as _date
from pathlib import Path


def path_forecasts_root(*, project_root: Callable[[], object]) -> Path:
    root = project_root()
    return Path(str(root)) / "data" / "ml" / "path_forecasts"


def forecast_archive_dir(*, project_root: Callable[[], object], index: str) -> Path:
    return path_forecasts_root(project_root=project_root) / str(index)


def day_str(d: _date) -> str:
    return d.strftime("%Y-%m-%d")


def forecast_archive_path(*, project_root: Callable[[], object], index: str, d: _date) -> Path:
    arch_dir = forecast_archive_dir(project_root=project_root, index=index)
    return arch_dir / f"{day_str(d)}.csv"


def bands_archive_path(*, project_root: Callable[[], object], index: str, d: _date) -> Path:
    arch_dir = forecast_archive_dir(project_root=project_root, index=index)
    return arch_dir / f"{day_str(d)}_bands.csv"


def calibration_dir(*, project_root: Callable[[], object]) -> Path:
    return path_forecasts_root(project_root=project_root) / "_calibration"


def calibration_history_dir(*, project_root: Callable[[], object]) -> Path:
    return path_forecasts_root(project_root=project_root) / "_calibration_history"
