from __future__ import annotations

import csv
import io
import logging
import os
import shutil
import tempfile
import time
from typing import Any, Iterable, Optional

# CsvWriterHelper not used in atomic backend directly
from src.utils.backoff import backoff_delays, sleep_ms

# Lightweight, optional Prometheus metrics (no hard dependency at import time)
try:  # pragma: no cover - defensive optional import
    from src.metrics import get_counter as _get_counter  # type: ignore

    _CSVIO_LOCK_WAITS = _get_counter(
        'csvio_lock_waits_total', 'CSVIO lock wait attempts', ['kind']
    )
    _CSVIO_LOCK_WAIT_MS = _get_counter(
        'csvio_lock_wait_time_ms_total', 'Total milliseconds spent waiting for CSV locks', []
    )
    _CSVIO_LOCK_FAILS = _get_counter(
        'csvio_lock_acquire_failures_total', 'CSVIO lock acquire failures (retry exhausted)', []
    )
except (ImportError, AttributeError):  # pragma: no cover - null fallbacks when metrics unavailable
    class _Null:
        def labels(self, *a, **k):
            return self
        def inc(self, *a, **k):
            return 0
    _CSVIO_LOCK_WAITS = _Null()
    _CSVIO_LOCK_WAIT_MS = _Null()
    _CSVIO_LOCK_FAILS = _Null()


def _inc_lock_wait(kind: str = 'atomic_fs') -> None:
    """Increment lock-wait counter, tolerating missing labels/metrics backends."""
    try:
        lbl = getattr(_CSVIO_LOCK_WAITS, 'labels', None)
        if callable(lbl):
            obj = lbl(kind=kind)
            inc = getattr(obj, 'inc', None)
            if callable(inc):
                inc()
                return
        # Fallback: try calling inc() directly on the counter (no labels)
        inc2 = getattr(_CSVIO_LOCK_WAITS, 'inc', None)
        if callable(inc2):
            inc2()
    except (AttributeError, TypeError):
        # Expected when metrics not available
        pass


def _get_logger(logger: Optional[logging.Logger]) -> logging.Logger:
    return logger or logging.getLogger("storage.csvio.atomic_fs")


def _read_existing_header(fp: str) -> list[str] | None:
    """Read the header row from an existing CSV file."""
    try:
        if not os.path.isfile(fp):
            return None
        with open(fp, 'r', newline='') as rf:
            rdr = csv.reader(rf)
            first = next(rdr, None)
            if isinstance(first, list) and first:
                return first
    except (IOError, OSError, PermissionError):
        # File access issues - return None to trigger header creation
        return None
    except (csv.Error, StopIteration, UnicodeDecodeError):
        # CSV parsing issues - return None
        return None
    except Exception:
        # Unexpected errors - return None for safety
        return None
    return None


def _align_row(file_header: list[str], new_header: list[str], values: list[Any]) -> list[Any]:
    if not new_header:
        return values
    mapping = {col: values[i] for i, col in enumerate(new_header) if i < len(values)}
    # Best-effort compute legacy 'atm' if requested
    if 'atm' in file_header and 'strike' in mapping and 'offset' in mapping and 'atm' not in mapping:
        try:
            mapping['atm'] = float(mapping['strike']) - int(mapping['offset'])
        except (ValueError, TypeError, KeyError):
            mapping['atm'] = ''
    return [mapping.get(c, '') for c in file_header]


def _align_rows(file_header: list[str], new_header: list[str], values_list: list[list[Any]]) -> list[list[Any]]:
    if not new_header:
        return values_list
    out: list[list[Any]] = []
    for values in values_list:
        mapping = {col: values[i] for i, col in enumerate(new_header) if i < len(values)}
        if 'atm' in file_header and 'strike' in mapping and 'offset' in mapping and 'atm' not in mapping:
            try:
                mapping['atm'] = float(mapping['strike']) - int(mapping['offset'])
            except (ValueError, TypeError, KeyError):
                mapping['atm'] = ''
        out.append([mapping.get(c, '') for c in file_header])
    return out


def _copy_original_to_temp(src: str, dst: str, *, logger: logging.Logger | None = None) -> None:
    # Retry on Windows sharing violations
    max_retries = int(os.environ.get('G6_CSV_LOCK_RETRIES', '50'))
    base_backoff_ms = float(os.environ.get('G6_CSV_LOCK_BACKOFF_MS', '100'))
    delays = backoff_delays(max_retries=max_retries, base_ms=base_backoff_ms, factor=1.3, cap_ms=2000.0)
    waited_ms_total = 0.0
    while True:
        try:
            with open(src, 'rb') as rf, open(dst, 'wb') as wf:
                shutil.copyfileobj(rf, wf, length=1024 * 1024)
            break
        except PermissionError:
            try:
                delay = next(delays)
            except StopIteration:
                try:
                    _CSVIO_LOCK_FAILS.inc()
                    if waited_ms_total:
                        _CSVIO_LOCK_WAIT_MS.inc(waited_ms_total)  # type: ignore[arg-type]
                except (AttributeError, TypeError):
                    pass  # Metrics not available
                raise
            _inc_lock_wait('atomic_fs')
            waited_ms_total += float(delay)
            sleep_ms(delay)
    if waited_ms_total:
        try:
            _CSVIO_LOCK_WAIT_MS.inc(waited_ms_total)  # type: ignore[arg-type]
        except (AttributeError, TypeError):
            pass


def _append_csv_line_binary(dst_path: str, row: list[Any]) -> None:
    # Render a single CSV row using csv module into a string with Windows-friendly newline
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator='\r\n')
    writer.writerow(row)
    data = buf.getvalue().encode('utf-8')
    with open(dst_path, 'ab') as wf:
        wf.write(data)


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
    """Append a single row using a temp-file + atomic replace strategy.

    Behavior:
    - If file doesn't exist: write header (if provided) + row to a temp file, then os.replace
    - If file exists: stream-copy original bytes to temp, then append the new row, then os.replace
    - Align row to existing header order when appending to an existing file
    - Emits csv_files_created metric on first create (best-effort)
    """
    log = _get_logger(logger)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    # Serialize concurrent writers using a simple lock file to avoid lost updates
    lock_path = filepath + '.lock'
    lock_acquired = False
    try:
        max_retries = int(os.environ.get('G6_CSV_LOCK_RETRIES', '50'))
        base_backoff_ms = float(os.environ.get('G6_CSV_LOCK_BACKOFF_MS', '100'))
        delays = backoff_delays(max_retries=max_retries, base_ms=base_backoff_ms, factor=1.3, cap_ms=2000.0)
        waited_ms_total = 0.0
        while True:
            try:
                # O_EXCL ensures exclusive creation
                fd_lock = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd_lock)
                lock_acquired = True
                break
            except FileExistsError:
                try:
                    delay = next(delays)
                except StopIteration:
                    try:
                        _CSVIO_LOCK_FAILS.inc()
                        if waited_ms_total:
                            _CSVIO_LOCK_WAIT_MS.inc(waited_ms_total)  # type: ignore[arg-type]
                    except (AttributeError, TypeError):
                        pass  # Metrics not available
                    raise
                _inc_lock_wait('atomic_fs')
                waited_ms_total += float(delay)
                sleep_ms(delay)
        if waited_ms_total:
            try:
                _CSVIO_LOCK_WAIT_MS.inc(waited_ms_total)  # type: ignore[arg-type]
            except (AttributeError, TypeError):
                pass  # Metrics not available

        file_exists = os.path.isfile(filepath)
        file_header = _read_existing_header(filepath) if file_exists else None
        if file_exists and header and file_header:
            row = _align_row(file_header, header, row)

        dir_name = os.path.dirname(filepath) or '.'
        fd, tmp_path = tempfile.mkstemp(prefix='.tmp_', suffix='.csv', dir=dir_name)
        os.close(fd)
        try:
            if file_exists:
                # Copy original bytes to temp
                _copy_original_to_temp(filepath, tmp_path, logger=log)
                # Ensure newline separation if original didn't end with newline
                try:
                    with open(filepath, 'rb') as rf:
                        rf.seek(0, os.SEEK_END)
                        size = rf.tell()
                        needs_nl = False
                        if size > 0:
                            rf.seek(-1, os.SEEK_END)
                            last = rf.read(1)
                            needs_nl = last not in (b'\n', b'\r')
                        if needs_nl:
                            with open(tmp_path, 'ab') as wf:
                                wf.write(b'\r\n')
                except Exception:
                    pass
                # Append new row
                _append_csv_line_binary(tmp_path, row)
            else:
                # Create new file with header and row using text writer for correct CSV formatting
                with open(tmp_path, 'w', newline='') as wf:
                    w = csv.writer(wf)
                    if header:
                        w.writerow(header)
                    w.writerow(row)
            # Atomic replace
            os.replace(tmp_path, filepath)

            # Metric for new file
            if not file_exists:
                try:
                    if metrics and hasattr(metrics, 'csv_files_created'):
                        metrics.csv_files_created.inc()  # type: ignore[call-arg]
                except Exception:
                    pass
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
    finally:
        # Release lock
        if lock_acquired:
            try:
                os.remove(lock_path)
            except Exception:
                pass


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
    if not rows_list:
        return
    log = _get_logger(logger)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    # Serialize concurrent writers using a simple lock file to avoid lost updates
    lock_path = filepath + '.lock'
    lock_acquired = False
    tmp_path: str | None = None
    try:
        max_retries = int(os.environ.get('G6_CSV_LOCK_RETRIES', '50'))
        base_backoff_ms = float(os.environ.get('G6_CSV_LOCK_BACKOFF_MS', '100'))
        delays = backoff_delays(max_retries=max_retries, base_ms=base_backoff_ms, factor=1.3, cap_ms=2000.0)
        waited_ms_total = 0.0
        while True:
            try:
                fd_lock = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd_lock)
                lock_acquired = True
                break
            except FileExistsError:
                try:
                    delay = next(delays)
                except StopIteration:
                    try:
                        _CSVIO_LOCK_FAILS.inc()
                        if waited_ms_total:
                            _CSVIO_LOCK_WAIT_MS.inc(waited_ms_total)  # type: ignore[arg-type]
                    except (AttributeError, TypeError):
                        pass  # Metrics not available
                    raise
                _inc_lock_wait('atomic_fs')
                waited_ms_total += float(delay)
                sleep_ms(delay)
        if waited_ms_total:
            try:
                _CSVIO_LOCK_WAIT_MS.inc(waited_ms_total)  # type: ignore[arg-type]
            except (AttributeError, TypeError):
                pass  # Metrics not available

        file_exists = os.path.isfile(filepath)
        file_header = _read_existing_header(filepath) if file_exists else None
        if file_exists and header and file_header:
            rows_list = _align_rows(file_header, header, rows_list)

        dir_name = os.path.dirname(filepath) or '.'
        fd, tmp_path_local = tempfile.mkstemp(prefix='.tmp_', suffix='.csv', dir=dir_name)
        os.close(fd)
        tmp_path = tmp_path_local
        try:
            if file_exists:
                _copy_original_to_temp(filepath, tmp_path, logger=log)
                # Ensure newline separation if original didn't end with newline
                try:
                    with open(filepath, 'rb') as rf:
                        rf.seek(0, os.SEEK_END)
                        size = rf.tell()
                        needs_nl = False
                        if size > 0:
                            rf.seek(-1, os.SEEK_END)
                            last = rf.read(1)
                            needs_nl = last not in (b'\n', b'\r')
                        if needs_nl:
                            with open(tmp_path, 'ab') as wf:
                                wf.write(b'\r\n')
                except Exception:
                    pass
                # Append all rows
                for r in rows_list:
                    _append_csv_line_binary(tmp_path, r)
            else:
                with open(tmp_path, 'w', newline='') as wf:
                    w = csv.writer(wf)
                    if header:
                        w.writerow(header)
                    w.writerows(rows_list)
            os.replace(tmp_path, filepath)
            if not file_exists:
                try:
                    if metrics and hasattr(metrics, 'csv_files_created'):
                        metrics.csv_files_created.inc()  # type: ignore[call-arg]
                except Exception:
                    pass
        finally:
            try:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
    finally:
        if lock_acquired:
            try:
                os.remove(lock_path)
            except Exception:
                pass
