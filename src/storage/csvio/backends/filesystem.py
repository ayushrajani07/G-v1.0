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
    # Check if writer thread is enabled
    try:
        from ..writer_thread import get_writer_thread, WriteRequest
        wt = get_writer_thread()
        if wt is not None:
            # Use writer thread for async batched writes
            request = WriteRequest(filepath=filepath, rows=[row], header=header)
            if wt.enqueue(request, timeout=0.5):
                return
            # Fall through to sync write if queue full
    except Exception:
        # Fall back to sync write on any error
        pass
    
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
    rows_list = list(rows)
    
    # Check if writer thread is enabled
    try:
        from ..writer_thread import get_writer_thread, WriteRequest
        wt = get_writer_thread()
        if wt is not None:
            # Use writer thread for async batched writes
            request = WriteRequest(filepath=filepath, rows=rows_list, header=header)
            if wt.enqueue(request, timeout=0.5):
                return
            # Fall through to sync write if queue full
    except Exception:
        # Fall back to sync write on any error
        pass
    
    helper = CsvWriterHelper(
        logger=_get_logger(logger),
        base_dir=base_dir or "",
        writer=writer,
        metrics=metrics,
    )
    helper.append_many_csv_rows(filepath, rows_list, header)
