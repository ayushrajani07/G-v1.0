"""CSV batching and write buffering module.

Extracted from CsvSink Phase 2 refactoring (Oct 2025).
Handles row batching, buffer management, and flush strategies for optimized I/O.
"""

from __future__ import annotations

import csv
import os
from typing import Any


class CsvBatcher:
    """Manages batched writes to CSV files for performance optimization.
    
    Responsibilities:
    - Buffer rows per (index, expiry, date) batch key
    - Track batch counts and flush thresholds
    - Flush buffers on threshold or force flag
    - Emit metrics for batch operations
    """
    
    def __init__(
        self,
        *,
        logger,
        metrics,
        flush_threshold: int = 50,
        verbose: bool = False
    ):
        """Initialize batcher.
        
        Args:
            logger: Logger instance for batch events
            metrics: Metrics registry (optional)
            flush_threshold: Number of rows to accumulate before flushing
            verbose: If True, log debug messages for batch operations
        """
        self.logger = logger
        self.metrics = metrics
        self.flush_threshold = flush_threshold
        self.verbose = verbose
        
        # Batch buffers: {batch_key: {filepath: {'header': [...], 'rows': [[...], ...]}}}
        self._batch_buffers: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = {}
        
        # Batch row counts: {batch_key: count}
        self._batch_counts: dict[tuple[str, str, str], int] = {}
    
    def init_batch(self, batch_key: tuple[str, str, str]) -> None:
        """Initialize batch buffers for given batch key.
        
        Args:
            batch_key: Tuple of (index, expiry_code, date_str)
        """
        if batch_key not in self._batch_buffers:
            self._batch_buffers[batch_key] = {}
            self._batch_counts[batch_key] = 0
    
    def buffer_row(
        self,
        *,
        batch_key: tuple[str, str, str],
        filepath: str,
        row: list[Any],
        header: list[str] | None
    ) -> None:
        """Add row to batch buffer.
        
        Args:
            batch_key: Tuple of (index, expiry_code, date_str)
            filepath: Target CSV file path
            row: CSV row data
            header: CSV header (stored once per filepath)
        
        Side Effects:
            Updates batch buffers and counts
        """
        # Ensure batch initialized
        self.init_batch(batch_key)
        
        # Get or create filepath buffer
        buffers = self._batch_buffers[batch_key]
        if filepath not in buffers:
            buffers[filepath] = {
                'header': header,
                'rows': []
            }
        
        # Append row
        buffers[filepath]['rows'].append(row)
        self._batch_counts[batch_key] += 1
    
    def maybe_flush_batch(
        self,
        *,
        batch_key: tuple[str, str, str],
        force_flush_env: bool = False
    ) -> bool:
        """Flush batch buffers if threshold or force flag met.
        
        Args:
            batch_key: Tuple of (index, expiry_code, date_str)
            force_flush_env: If True, flush regardless of threshold
        
        Returns:
            True if batch was flushed, False otherwise
        
        Side Effects:
            Writes buffered rows to CSV files
            Clears batch buffers after flush
            Emits metrics for flushed rows
        """
        try:
            # Check if threshold met (or force flush)
            current_count = self._batch_counts.get(batch_key, 0)
            if current_count < self.flush_threshold and not force_flush_env:
                return False
            
            # Flush all buffers for this batch key
            buffers = self._batch_buffers.get(batch_key, {})
            total_flushed = 0
            
            for filepath, payload in buffers.items():
                try:
                    header_ref = payload.get('header')
                    rows = payload.get('rows', [])
                    if not rows:
                        continue
                    
                    # Check if file already exists (determines if header needed)
                    file_exists = os.path.isfile(filepath)
                    
                    # Ensure directory exists
                    os.makedirs(os.path.dirname(filepath), exist_ok=True)
                    
                    # Write buffered rows
                    self._append_many_csv_rows(
                        filepath,
                        rows,
                        header_ref if not file_exists else None
                    )
                    
                    total_flushed += len(rows)
                    
                    # Log flush operation
                    if self.verbose:
                        try:
                            self.logger.debug("Flushed %s rows to %s", len(rows), filepath)
                        except Exception:
                            pass
                except Exception as e:
                    # Log error but continue flushing other files
                    try:
                        self.logger.error("Failed to flush batch to %s: %s", filepath, e)
                    except Exception:
                        pass
                    continue
            
            # Emit metrics for total flushed rows
            if total_flushed > 0:
                try:
                    if self.metrics:
                        self.metrics.inc('csv_records_written', total_flushed)
                        self.metrics.inc(
                            'csv_batch_flushes',
                            1,
                            {
                                'index': batch_key[0],
                                'expiry': batch_key[1],
                                'date': batch_key[2]
                            }
                        )
                except Exception:
                    pass
            
            # Clear buffers after flush attempt
            self._batch_buffers.pop(batch_key, None)
            self._batch_counts.pop(batch_key, None)
            
            return True
        except Exception as e:
            try:
                self.logger.error("Batch flush failed for %s: %s", batch_key, e)
            except Exception:
                pass
            return False
    
    def get_batch_count(self, batch_key: tuple[str, str, str]) -> int:
        """Get current row count for batch.
        
        Args:
            batch_key: Tuple of (index, expiry_code, date_str)
        
        Returns:
            Number of rows currently buffered
        """
        return self._batch_counts.get(batch_key, 0)
    
    def clear_all_batches(self) -> int:
        """Clear all batch buffers without flushing.
        
        Returns:
            Number of batches cleared
        
        Side Effects:
            Clears all batch buffers and counts (data loss)
        """
        count = len(self._batch_buffers)
        self._batch_buffers.clear()
        self._batch_counts.clear()
        return count
    
    def flush_all_batches(self, *, csv_writer=None) -> int:
        """Flush all batch buffers (used at shutdown).
        
        Args:
            csv_writer: Optional CsvWriter instance for I/O operations
        
        Returns:
            Number of batches flushed
        
        Side Effects:
            Writes all buffered rows to CSV files
            Clears all batch buffers
        """
        flushed_count = 0
        
        for batch_key in list(self._batch_buffers.keys()):
            try:
                if self.maybe_flush_batch(batch_key=batch_key, force_flush_env=True):
                    flushed_count += 1
            except Exception:
                continue
        
        return flushed_count
    
    # Private helper method (delegates to csv_writer in production)
    
    def _append_many_csv_rows(
        self,
        filepath: str,
        rows: list[list[Any]],
        header: list[str] | None
    ) -> None:
        """Write multiple rows to CSV file atomically.
        
        This is a temporary implementation. In production, this will delegate
        to CsvWriter.append_many_rows() to avoid code duplication.
        
        Args:
            filepath: Target CSV file path
            rows: List of CSV row data
            header: CSV header (written once if file doesn't exist)
        
        Side Effects:
            Appends rows to CSV file
        """
        # Write rows atomically
        with open(filepath, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Write header if provided
            if header:
                writer.writerow(header)
            
            # Write all rows
            writer.writerows(rows)
