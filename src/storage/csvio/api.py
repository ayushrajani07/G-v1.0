from __future__ import annotations

import logging
import os
from typing import Any, Iterable, Optional

from .backends import filesystem as fs_backend
from .backends import atomic_fs as atomic_backend
from src.config.env_config import EnvConfig


class CsvWriteError(Exception):
    pass


class CsvSchemaError(CsvWriteError):
    pass


class CsvRetryExhausted(CsvWriteError):
    pass


def _select_backend(preferred: str | None = None) -> str:
    """Resolve backend name considering environment override.

    Order of precedence:
    - G6_CSVIO_BACKEND env var when set (e.g., 'filesystem', 'atomic', 'atomic_fs')
    - Explicit preferred parameter when provided
    - Default 'filesystem'
    """
    env_val = EnvConfig.get_str("G6_CSVIO_BACKEND", "").strip().lower()
    if env_val in {"filesystem", "fs"}:
        return "filesystem"
    if env_val in {"atomic", "atomic_fs", "atomic-fs"}:
        return "atomic"
    if preferred:
        p = preferred.strip().lower()
        if p in {"filesystem", "fs"}:
            return "filesystem"
        if p in {"atomic", "atomic_fs", "atomic-fs"}:
            return "atomic"
    return "filesystem"


def append_one(
    filepath: str,
    row: list[Any],
    header: Optional[list[str]] = None,
    *,
    logger: Optional[logging.Logger] = None,
    base_dir: Optional[str] = None,
    writer: Any | None = None,
    metrics: Any | None = None,
    backend: str = "filesystem",
) -> None:
    """Append a single row to a CSV file via the selected backend.

    Parameters
    - filepath: absolute path to CSV file
    - row: list of values
    - header: optional header row (written only when file is created)
    - logger, base_dir, writer, metrics: optional context from callers like csv_sink
    - backend: backend name (default 'filesystem')
    """
    resolved = _select_backend(backend)
    if resolved == "filesystem":
        return fs_backend.append_one(
            filepath,
            row,
            header,
            logger=logger,
            base_dir=base_dir,
            writer=writer,
            metrics=metrics,
        )
    if resolved == "atomic":
        return atomic_backend.append_one(
            filepath,
            row,
            header,
            logger=logger,
            base_dir=base_dir,
            writer=writer,
            metrics=metrics,
        )
    raise ValueError(f"Unsupported CSV backend: {backend}")


def append_many(
    filepath: str,
    rows: Iterable[list[Any]],
    header: Optional[list[str]] = None,
    *,
    logger: Optional[logging.Logger] = None,
    base_dir: Optional[str] = None,
    writer: Any | None = None,
    metrics: Any | None = None,
    backend: str = "filesystem",
) -> None:
    """Append multiple rows to a CSV file via the selected backend."""
    resolved = _select_backend(backend)
    if resolved == "filesystem":
        return fs_backend.append_many(
            filepath,
            rows,
            header,
            logger=logger,
            base_dir=base_dir,
            writer=writer,
            metrics=metrics,
        )
    if resolved == "atomic":
        return atomic_backend.append_many(
            filepath,
            rows,
            header,
            logger=logger,
            base_dir=base_dir,
            writer=writer,
            metrics=metrics,
        )
    raise ValueError(f"Unsupported CSV backend: {backend}")
