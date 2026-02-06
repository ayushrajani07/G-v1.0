"""CSV file I/O operations for G6 Platform.

Thin wrapper around CSVIO (src.storage.csvio) to provide a stable API
for callers while keeping the actual write implementation centralized.
"""
import csv
import glob as _glob
import logging
import os
from typing import Any

from src.storage.csvio import api as csvio_api

logger = logging.getLogger(__name__)


class CsvWriter:
    """Handles low-level CSV file I/O operations."""

    def __init__(self, base_dir: str):
        """
        Initialize CSV writer.
        
        Args:
            base_dir: Base directory for CSV files (absolute path)
        """
        self.base_dir = base_dir
        self.logger = logger

    def append_row(self, filepath: str, row: list[Any], header: list[str] | None) -> None:
        """
        Append a single row to a CSV file.
        
        Creates the file with header if it doesn't exist.
        Thread-safe through atomic write operations.
        
        Args:
            filepath: Relative path from base_dir (e.g., "NIFTY/2024-10-26/W0_options.csv")
            row: List of values to write
            header: Optional header row (written only if file doesn't exist)
        """
        full_path = filepath if os.path.isabs(filepath) else os.path.join(self.base_dir, filepath)
        try:
            csvio_api.append_one(full_path, row, header, logger=self.logger, base_dir=self.base_dir)
        except (OSError, IOError, ValueError, TypeError, csv.Error) as e:
            self.logger.error("Failed to append row to %s: %s", filepath, e, exc_info=True)
            raise
        except (AttributeError, RuntimeError) as e:
            self.logger.error("Unexpected error appending row to %s: %s", filepath, e, exc_info=True)
            raise

    def append_many_rows(self, filepath: str, rows: list[list[Any]], header: list[str] | None) -> None:
        """
        Append multiple rows to a CSV file.
        
        More efficient than calling append_row() multiple times.
        
        Args:
            filepath: Relative path from base_dir
            rows: List of rows to write
            header: Optional header row (written only if file doesn't exist)
        """
        if not rows:
            return
        
        full_path = filepath if os.path.isabs(filepath) else os.path.join(self.base_dir, filepath)
        try:
            csvio_api.append_many(full_path, rows, header, logger=self.logger, base_dir=self.base_dir)
        except (OSError, IOError, ValueError, TypeError, csv.Error) as e:
            self.logger.error("Failed to append %s rows to %s: %s", len(rows), filepath, e, exc_info=True)
            raise
        except (AttributeError, RuntimeError) as e:
            self.logger.error("Unexpected error appending %s rows to %s: %s", len(rows), filepath, e, exc_info=True)
            raise

    def read_csv(self, filepath: str) -> list[dict[str, Any]]:
        """
        Read CSV file and return as list of dictionaries.
        
        Args:
            filepath: Relative path from base_dir
            
        Returns:
            List of dictionaries (one per row, keys from header)
            Empty list if file doesn't exist
        """
        full_path = os.path.join(self.base_dir, filepath)
        
        if not os.path.isfile(full_path):
            return []
        
        try:
            with open(full_path, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                return list(reader)
        except (OSError, IOError, UnicodeDecodeError, csv.Error) as e:
            self.logger.error("Failed to read %s: %s", filepath, e, exc_info=True)
            return []
        except (AttributeError, TypeError, ValueError, RuntimeError) as e:
            # Defensive: preserve historical behavior (do not break callers on unexpected read failures)
            self.logger.error("Unexpected error reading %s: %s", filepath, e, exc_info=True)
            return []

    def file_exists(self, filepath: str) -> bool:
        """Check if a CSV file exists."""
        full_path = os.path.join(self.base_dir, filepath)
        return os.path.isfile(full_path)

    def get_file_mtime(self, filepath: str) -> float | None:
        """
        Get file modification time.
        
        Returns:
            Modification timestamp or None if file doesn't exist
        """
        full_path = os.path.join(self.base_dir, filepath)
        
        if not os.path.isfile(full_path):
            return None
        
        try:
            return os.path.getmtime(full_path)
        except (OSError, IOError, ValueError) as e:
            self.logger.warning("Failed to get mtime for %s: %s", filepath, e)
            return None

    def list_files_in_dir(self, relative_dir: str, pattern: str = "*.csv") -> list[str]:
        """
        List CSV files in a directory.
        
        Args:
            relative_dir: Directory path relative to base_dir
            pattern: Glob pattern for matching files
            
        Returns:
            List of filenames (not full paths)
        """
        full_dir = os.path.join(self.base_dir, relative_dir)
        
        if not os.path.isdir(full_dir):
            return []
        
        try:
            pattern_path = os.path.join(full_dir, pattern)
            files = _glob.glob(pattern_path)
            return [os.path.basename(f) for f in files]
        except (OSError, IOError, ValueError) as e:
            self.logger.warning("Failed to list files in %s: %s", relative_dir, e)
            return []
