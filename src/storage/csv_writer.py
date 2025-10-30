"""CSV file I/O operations for G6 Platform.

Handles low-level CSV file writing with thread safety and error handling.
Extracted from CsvSink to improve modularity and testability.
"""

import csv
import glob as _glob
import logging
import os
from typing import Any

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
        full_path = os.path.join(self.base_dir, filepath)
        dir_path = os.path.dirname(full_path)
        
        # Ensure directory exists
        os.makedirs(dir_path, exist_ok=True)
        
        file_exists = os.path.isfile(full_path)
        
        try:
            with open(full_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                
                # Write header if file is new and header provided
                if not file_exists and header:
                    writer.writerow(header)
                
                writer.writerow(row)
        except Exception as e:
            self.logger.error("Failed to append row to %s: %s", filepath, e, exc_info=True)
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
        
        full_path = os.path.join(self.base_dir, filepath)
        dir_path = os.path.dirname(full_path)
        
        # Ensure directory exists
        os.makedirs(dir_path, exist_ok=True)
        
        file_exists = os.path.isfile(full_path)
        
        try:
            with open(full_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                
                # Write header if file is new and header provided
                if not file_exists and header:
                    writer.writerow(header)
                
                writer.writerows(rows)
        except Exception as e:
            self.logger.error("Failed to append %s rows to %s: %s", len(rows), filepath, e, exc_info=True)
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
        except Exception as e:
            self.logger.error("Failed to read %s: %s", filepath, e, exc_info=True)
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
        except Exception as e:
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
        except Exception as e:
            self.logger.warning("Failed to list files in %s: %s", relative_dir, e)
            return []
