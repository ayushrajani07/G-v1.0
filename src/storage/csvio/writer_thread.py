"""Dedicated writer thread for CSVIO with micro-batching and periodic flush.

Implements Phase 1 Quick Win: append-only writer thread with configurable flush
intervals to amortize fsync costs and improve write throughput.

Environment Variables:
    G6_CSVIO_FLUSH_MS: Flush interval in milliseconds (default 500)
    G6_CSVIO_BATCH: Maximum batch size before forcing flush (default 2000)
    G6_CSVIO_WRITER_THREAD: Enable writer thread (default 0)
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WriteRequest:
    """Single write request for the writer thread."""
    filepath: str
    rows: list[list[Any]]
    header: list[str] | None = None


class CsvWriterThread:
    """Background writer thread with micro-batching and periodic flush.
    
    Queues write requests and flushes them periodically or when batch size
    is reached. This amortizes the cost of file I/O and fsync operations.
    """
    
    def __init__(
        self,
        flush_ms: int = 500,
        batch_size: int = 2000,
        queue_maxsize: int = 10000,
    ):
        """Initialize writer thread.
        
        Args:
            flush_ms: Flush interval in milliseconds
            batch_size: Maximum rows to batch before forcing flush
            queue_maxsize: Maximum queue size (backpressure when full)
        """
        self.flush_ms = flush_ms
        self.batch_size = batch_size
        self._queue: queue.Queue[WriteRequest | None] = queue.Queue(maxsize=queue_maxsize)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._batches: dict[str, list[list[Any]]] = {}
        self._headers: dict[str, list[str]] = {}
        self._last_flush = time.time()
        self._lock = threading.Lock()
        
    def start(self) -> None:
        """Start the writer thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker,
            name='csvio-writer',
            daemon=True
        )
        self._thread.start()
        logger.info(
            "CSV writer thread started: flush_ms=%d batch_size=%d",
            self.flush_ms,
            self.batch_size
        )
    
    def stop(self, timeout: float = 5.0) -> None:
        """Stop the writer thread and flush pending writes.
        
        Args:
            timeout: Maximum time to wait for thread to finish
        """
        if self._thread is None:
            return
        
        # Signal stop and send poison pill
        self._stop_event.set()
        try:
            self._queue.put(None, timeout=1.0)
        except queue.Full:
            pass
        
        # Wait for thread to finish
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            logger.warning("CSV writer thread did not stop cleanly within timeout")
        else:
            logger.info("CSV writer thread stopped")
        
        self._thread = None
    
    def enqueue(self, request: WriteRequest, timeout: float | None = None) -> bool:
        """Enqueue a write request.
        
        Args:
            request: Write request to queue
            timeout: Optional timeout for queue put (None = blocking)
        
        Returns:
            True if enqueued successfully, False if queue full and timed out
        """
        try:
            self._queue.put(request, timeout=timeout)
            return True
        except queue.Full:
            logger.warning("CSV writer queue full, dropping write request for %s", request.filepath)
            return False
    
    def _worker(self) -> None:
        """Worker thread main loop."""
        while not self._stop_event.is_set():
            try:
                # Calculate dynamic timeout based on next flush deadline
                elapsed = time.time() - self._last_flush
                remaining_ms = max(10, self.flush_ms - int(elapsed * 1000))
                timeout_sec = remaining_ms / 1000.0
                
                try:
                    request = self._queue.get(timeout=timeout_sec)
                except queue.Empty:
                    # Timeout reached, check if flush needed
                    self._maybe_flush()
                    continue
                
                # Poison pill = shutdown signal
                if request is None:
                    break
                
                # Accumulate request into batch
                with self._lock:
                    if request.filepath not in self._batches:
                        self._batches[request.filepath] = []
                    self._batches[request.filepath].extend(request.rows)
                    
                    if request.header and request.filepath not in self._headers:
                        self._headers[request.filepath] = request.header
                    
                    # Check if batch size threshold reached
                    total_rows = sum(len(rows) for rows in self._batches.values())
                    if total_rows >= self.batch_size:
                        self._flush_all()
                    elif time.time() - self._last_flush >= self.flush_ms / 1000.0:
                        self._flush_all()
            
            except OSError:
                logger.exception("CSV writer thread error")
        
        # Final flush before exit
        try:
            self._flush_all()
        except OSError:
            logger.exception("CSV writer thread final flush failed")
    
    def _maybe_flush(self) -> None:
        """Check if flush interval elapsed and flush if needed."""
        if time.time() - self._last_flush >= self.flush_ms / 1000.0:
            self._flush_all()
    
    def _flush_all(self) -> None:
        """Flush all batched writes to disk."""
        with self._lock:
            if not self._batches:
                return
            
            for filepath, rows in self._batches.items():
                if not rows:
                    continue
                
                header = self._headers.get(filepath)
                try:
                    self._write_batch(filepath, rows, header)
                except OSError:
                    logger.exception("Failed to write batch for %s", filepath)
            
            # Clear batches after successful flush
            self._batches.clear()
            self._last_flush = time.time()
    
    def _write_batch(self, filepath: str, rows: list[list[Any]], header: list[str] | None) -> None:
        """Write a batch of rows to file using append mode.
        
        Args:
            filepath: Absolute path to CSV file
            rows: List of rows to write
            header: Optional header (written only if file doesn't exist)
        """
        import csv
        
        # Ensure directory exists
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        
        # Check if file exists (for header logic)
        file_exists = os.path.exists(filepath)
        needs_header = False
        if header:
            if not file_exists:
                needs_header = True
            else:
                # Defensive: verify first line contains comma-joined header; if truncated externally, rewrite header.
                try:
                    with open(filepath, 'r', encoding='utf-8') as rf:
                        first_line = rf.readline().strip()
                    expected = ','.join(header)
                    if first_line.lower() != expected.lower():  # case-insensitive compare
                        # Insert header if file appears truncated or missing header
                        needs_header = True
                        # If file non-empty and missing header, we prepend by rewriting file (cheap for small test files).
                        if first_line:
                            existing = Path(filepath).read_text(encoding='utf-8')
                            # Avoid duplicate header if it already appears further down
                            if not existing.lower().startswith(expected.lower()):
                                Path(filepath).write_text(expected + '\n' + existing, encoding='utf-8')
                            needs_header = False  # header already inserted by rewrite
                except OSError:
                    # On any read failure, attempt to write header before rows
                    needs_header = True
        
        # Open in append mode
        with open(filepath, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Write header only if file is new and header provided
            if needs_header and header:
                writer.writerow(header)
            
            # Write all rows
            writer.writerows(rows)


def get_writer_thread() -> CsvWriterThread | None:
    """Get or create the global writer thread instance.
    
    Returns None if writer thread is disabled via environment.
    Thread is started lazily on first call.
    """
    # Check if feature is enabled
    from src.config.env_config import EnvConfig
    
    if not EnvConfig.get_bool('G6_CSVIO_WRITER_THREAD', False):
        return None
    
    # Get or create singleton instance
    global _WRITER_THREAD_INSTANCE
    if _WRITER_THREAD_INSTANCE is None:
        flush_ms = EnvConfig.get_int('G6_CSVIO_FLUSH_MS', 500)
        batch_size = EnvConfig.get_int('G6_CSVIO_BATCH', 2000)
        
        _WRITER_THREAD_INSTANCE = CsvWriterThread(
            flush_ms=flush_ms,
            batch_size=batch_size
        )
        _WRITER_THREAD_INSTANCE.start()
    
    return _WRITER_THREAD_INSTANCE


# Global singleton instance
_WRITER_THREAD_INSTANCE: CsvWriterThread | None = None


def shutdown_writer_thread() -> None:
    """Shutdown the global writer thread if active."""
    global _WRITER_THREAD_INSTANCE
    if _WRITER_THREAD_INSTANCE is not None:
        _WRITER_THREAD_INSTANCE.stop()
        _WRITER_THREAD_INSTANCE = None


__all__ = [
    'CsvWriterThread',
    'WriteRequest',
    'get_writer_thread',
    'shutdown_writer_thread',
]
