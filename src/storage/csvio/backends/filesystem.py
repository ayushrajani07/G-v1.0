from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from ...csv_writer_helper import CsvWriterHelper


def _get_logger(logger: Optional[logging.Logger]) -> logging.Logger:
    return logger or logging.getLogger("storage.csvio.filesystem")


def append_one(
    filepath: str,
    row: list[Any],
    header: Optional[list[str]] = None,
    *,
    logger: Optional[logging.Logger] = None,
    base_dir: Optional[str] = None,
    writer: Any | None = None,
    metrics: Any | None = None,
) -> None:
    helper = CsvWriterHelper(
        logger=_get_logger(logger),
        base_dir=base_dir or "",
        writer=writer,
        metrics=metrics,
    )
    helper.append_csv_row(filepath, row, header)


def append_many(
    filepath: str,
    rows: Iterable[list[Any]],
    header: Optional[list[str]] = None,
    *,
    logger: Optional[logging.Logger] = None,
    base_dir: Optional[str] = None,
    writer: Any | None = None,
    metrics: Any | None = None,
) -> None:
    helper = CsvWriterHelper(
        logger=_get_logger(logger),
        base_dir=base_dir or "",
        writer=writer,
        metrics=metrics,
    )
    helper.append_many_csv_rows(filepath, list(rows), header)
