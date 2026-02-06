from __future__ import annotations

import csv
import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

from src.storage.file_buffer_manager import FileBufferManager


class AsyncCsvWriterQueueFull(RuntimeError):
    pass


@dataclass(frozen=True)
class _WriteTask:
    filepath: str
    rows: list[list[Any]]
    header: list[str] | None


class AsyncCsvWriter:
    """Background CSV writer with a bounded queue.

    Designed to be a drop-in replacement for `CsvWriter` (same public methods)
    while moving disk I/O to a single worker thread.

    Notes:
    - Uses `FileBufferManager` to amortize open/close overhead.
    - When the queue is full, can either block briefly or fall back to sync writes.
    """

    def __init__(
        self,
        base_dir: str,
        *,
        max_queue_size: int = 5000,
        enqueue_timeout_s: float = 0.25,
        fallback_sync_on_full: bool = True,
        max_open_files: int = 64,
        flush_interval_seconds: float = 0.5,
        buffer_size: int = 0,
        newline: str = "",
        encoding: str = "utf-8",
    ) -> None:
        self.base_dir = base_dir
        self.metrics: Any | None = None
        self._queue: queue.Queue[_WriteTask | None] = queue.Queue(maxsize=max(1, int(max_queue_size)))
        self._enqueue_timeout_s = max(0.0, float(enqueue_timeout_s))
        self._fallback_sync_on_full = bool(fallback_sync_on_full)

        self._fbm = FileBufferManager(
            max_open_files=max_open_files,
            flush_interval_seconds=flush_interval_seconds,
            buffer_size=buffer_size,
            newline=newline,
            encoding=encoding,
        )

        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker_loop, name="AsyncCsvWriter", daemon=True)
        self._thread.start()

    def attach_metrics(self, metrics_registry: Any) -> None:
        """Attach a metrics registry object (typically the platform MetricsRegistry)."""
        self.metrics = metrics_registry

    # ---------------- Public API (CsvWriter-compatible) ----------------
    def append_row(self, filepath: str, row: list[Any], header: list[str] | None) -> None:
        full_path = filepath if os.path.isabs(filepath) else os.path.join(self.base_dir, filepath)
        task = _WriteTask(filepath=full_path, rows=[row], header=header)
        self._enqueue(task)

    def append_many_rows(self, filepath: str, rows: list[list[Any]], header: list[str] | None) -> None:
        if not rows:
            return
        full_path = filepath if os.path.isabs(filepath) else os.path.join(self.base_dir, filepath)
        task = _WriteTask(filepath=full_path, rows=rows, header=header)
        self._enqueue(task)

    def flush(self) -> None:
        """Block until all queued writes are processed and buffered files flushed."""
        self._queue.join()
        self._fbm.flush_all(force=True)

    def close(self) -> None:
        """Flush and stop the worker thread."""
        try:
            self.flush()
        finally:
            self._stop.set()
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                # If full, wait a bit and retry
                try:
                    self._queue.put(None, timeout=1.0)
                except queue.Full:
                    pass
            self._thread.join(timeout=5.0)
            self._fbm.close_all()

    # ---------------- Internals ----------------
    def _enqueue(self, task: _WriteTask) -> None:
        if self._stop.is_set():
            raise RuntimeError("AsyncCsvWriter is closed")
        t0 = time.perf_counter()
        try:
            self._queue.put(task, timeout=self._enqueue_timeout_s)
            dt_ms = (time.perf_counter() - t0) * 1000.0
            self._metric_observe('csv_async_enqueue_latency_ms', dt_ms)
            self._metric_set('csv_async_queue_depth', self._queue.qsize())
            return
        except queue.Full:
            self._metric_inc('csv_async_queue_full', 1)
            if not self._fallback_sync_on_full:
                raise AsyncCsvWriterQueueFull("AsyncCsvWriter queue is full")
            self._metric_inc('csv_async_sync_fallback', 1)
            self._write_sync(task)

    def _write_sync(self, task: _WriteTask) -> None:
        """Synchronous fallback for queue pressure (best-effort)."""
        # Header semantics: FileBufferManager writes header only if file doesn't exist.
        # For sync fallback, reuse the same FBM to keep behavior consistent.
        self._fbm.write_row(task.filepath, task.rows[0], task.header)
        for row in task.rows[1:]:
            self._fbm.write_row(task.filepath, row, None)
        self._fbm.flush_all(force=False)

    def _worker_loop(self) -> None:
        while True:
            if self._stop.is_set() and self._queue.empty():
                break
            try:
                item = self._queue.get(timeout=0.25)
            except queue.Empty:
                # Periodic flush to keep latency bounded
                try:
                    self._fbm.flush_all(force=False)
                except (OSError, IOError, ValueError, TypeError, csv.Error, RuntimeError):
                    pass
                continue
            if item is None:
                self._queue.task_done()
                break
            try:
                t0 = time.perf_counter()
                header = item.header
                for idx, row in enumerate(item.rows):
                    self._fbm.write_row(item.filepath, list(row), header if idx == 0 else None)
                    header = None

                dt_ms = (time.perf_counter() - t0) * 1000.0
                self._metric_observe('csv_async_write_task_latency_ms', dt_ms)
                if item.rows:
                    self._metric_observe('csv_async_write_row_latency_ms', dt_ms / max(1, len(item.rows)))
            finally:
                self._queue.task_done()

                # Keep queue depth current
                self._metric_set('csv_async_queue_depth', self._queue.qsize())

            # Small periodic flush for responsiveness
            try:
                self._fbm.flush_all(force=False)
            except (OSError, IOError, ValueError, TypeError, csv.Error, RuntimeError):
                self._metric_inc('csv_async_worker_errors', 1)
                pass

    def _metric_inc(self, name: str, amount: int | float = 1) -> None:
        if not self.metrics:
            return
        try:
            metric = getattr(self.metrics, name, None)
            if metric is None:
                return
            metric.inc(amount)  # type: ignore[attr-defined]
        except (AttributeError, TypeError, ValueError, RuntimeError):
            return

    def _metric_set(self, name: str, value: int | float) -> None:
        if not self.metrics:
            return
        try:
            metric = getattr(self.metrics, name, None)
            if metric is None:
                return
            metric.set(value)  # type: ignore[attr-defined]
        except (AttributeError, TypeError, ValueError, RuntimeError):
            return

    def _metric_observe(self, name: str, value: float) -> None:
        if not self.metrics:
            return
        try:
            metric = getattr(self.metrics, name, None)
            if metric is None:
                return
            metric.observe(value)  # type: ignore[attr-defined]
        except (AttributeError, TypeError, ValueError, RuntimeError):
            return
