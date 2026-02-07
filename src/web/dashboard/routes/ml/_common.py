from __future__ import annotations

import datetime as _dt
from pathlib import Path

from ...core import paths as _paths
from ...core.csv_io import find_live_csv as _find_live_csv
from .._live_csv import resolve_live_csv_path as _resolve_live_csv_path_impl
from .._project_root import resolve_project_root as _resolve_project_root


def project_root() -> Path:
    """Dynamic project root resolution respecting test monkeypatches."""
    return _resolve_project_root(_paths.project_root)


def resolve_live_csv_path(idx_norm: str, expiry_tag: str, offset: str, day: _dt.date) -> Path | None:
    return _resolve_live_csv_path_impl(
        project_root=project_root(),
        idx_norm=idx_norm,
        expiry_tag=expiry_tag,
        offset=offset,
        day=day,
        find_live_csv=_find_live_csv,
    )
