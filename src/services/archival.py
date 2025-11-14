"""Archival helpers wrapping path_forecast.archive for route simplification.

This provides thin, stable functions the HTTP layer can call without
importing lower-level details directly. Keeps future schema changes
localized here.
"""
from __future__ import annotations

from typing import Sequence, Dict, Any
from pathlib import Path

from ..path_forecast.archive import (
    ArchiveConfig,
    append_forecast_snapshot as _append_forecast_snapshot_raw,
    append_quantile_bands_snapshot as _append_quantile_bands_snapshot_raw,
)


def archive_config(base_dir: Path) -> ArchiveConfig:
    return ArchiveConfig(base_dir=base_dir)


def archive_forecast_q50(
    acfg: ArchiveConfig,
    *,
    index: str,
    gen_ms: int,
    times: Sequence[int],
    qmap: Dict[float, Sequence[float]],
    meta: Dict[str, Any] | None = None,
) -> None:
    try:
        _append_forecast_snapshot_raw(acfg, index=index, gen_ms=gen_ms, times=times, qmap=qmap, meta=meta)
    except Exception:
        pass


def archive_forecast_bands(
    acfg: ArchiveConfig,
    *,
    index: str,
    gen_ms: int,
    times: Sequence[int],
    qmap: Dict[float, Sequence[float]],
    meta: Dict[str, Any] | None = None,
) -> None:
    try:
        _append_quantile_bands_snapshot_raw(acfg, index=index, gen_ms=gen_ms, times=times, qmap=qmap, meta=meta)
    except Exception:
        pass

__all__ = [
    "archive_config",
    "archive_forecast_q50",
    "archive_forecast_bands",
]