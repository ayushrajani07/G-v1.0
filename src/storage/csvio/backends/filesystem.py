from __future__ import annotations

import csv
import logging
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Optional


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
    except (ImportError, AttributeError, RuntimeError):
        # Fall back to sync write if writer thread unavailable or queue error
        pass
    
    # Direct append write (original behavior)
    _write_csv_append(filepath, [row], header, _get_logger(logger))


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
    except (ImportError, AttributeError, RuntimeError):
        # Fall back to sync write if writer thread unavailable or queue error
        pass
    
    # Direct append write (original behavior)
    _write_csv_append(filepath, rows_list, header, _get_logger(logger))


def _write_csv_append(
    filepath: str,
    rows: list[list[Any]],
    header: Optional[list[str]],
    logger: logging.Logger
) -> None:
    """Write rows to CSV file in append mode.
    
    Args:
        filepath: Absolute path to CSV file
        rows: Rows to write
        header: Optional header (written only if file doesn't exist)
        logger: Logger instance
    """
    # Ensure directory exists
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    
    # Check if file exists (for header logic)
    file_exists = os.path.exists(filepath)
    
    try:
        # Open in append mode
        with open(filepath, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Write header only if file is new and header provided
            if not file_exists and header:
                writer.writerow(header)
            
            # Write all rows
            writer.writerows(rows)
    except (OSError, IOError) as e:
        try:
            logger.error("Failed to write CSV to %s: %s", filepath, e, exc_info=True)
        except Exception:
            # Critical: CSV write failed AND logging failed - use stderr fallback
            print(f"CRITICAL: Failed to write CSV to {filepath}: {e}", file=sys.stderr)
