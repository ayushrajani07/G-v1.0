"""CSV overview aggregation module.

Extracted from CsvSink Phase 3 refactoring (Oct 2025).
Handles overview CSV generation, aggregation state tracking, and expiry coverage masks.
"""

from __future__ import annotations

import csv
import datetime
import os
from typing import Any


class CsvAggregator:
    """Manages overview CSV aggregation and snapshot writes.
    
    Responsibilities:
    - Track aggregation state (PCR snapshots, day_width)
    - Write aggregated overview snapshots with multiple expiry PCRs
    - Compute expiry coverage masks (expected, collected, missing)
    - Load previous close values for net change calculations
    - Round timestamps to 30s IST format for overview consistency
    """
    
    def __init__(
        self,
        *,
        base_dir: str,
        logger,
        metrics,
        overview_interval_seconds: int = 30,
        concise_mode: bool = False
    ):
        """Initialize aggregator.
        
        Args:
            base_dir: Base directory for CSV storage
            logger: Logger instance for aggregation events
            metrics: Metrics registry (optional)
            overview_interval_seconds: Minimum interval between overview writes
            concise_mode: If True, use debug-level logs instead of info
        """
        self.base_dir = base_dir
        self.logger = logger
        self.metrics = metrics
        self.overview_interval_seconds = overview_interval_seconds
        self._concise = concise_mode
        
        # Aggregation state tracking
        self._agg_pcr_snapshot: dict[str, dict[str, float]] = {}  # {index: {expiry_code: pcr}}
        self._agg_day_width: dict[str, float] = {}  # {index: max_day_width}
        self._agg_last_write: dict[str, datetime.datetime] = {}  # {index: last_write_timestamp}
        
        # Previous close tracking
        self._index_prev_close: dict[str, float] = {}  # {index: prev_close_price}
        self._tp_prev_close: dict[str, float] = {}  # {index: prev_tp_close}
        self._prev_close_loaded_date: dict[str, str] = {}  # {index: date_key}
        
        # Last seen values (injected from write_options_data)
        self._index_last_price: dict[str, float] = {}
        self._index_open_price: dict[str, float] = {}
        self._last_vix: float | None = None
    
    def update_aggregation_state(
        self,
        *,
        index: str,
        expiry_code: str,
        pcr: float,
        day_width: float,
        timestamp: datetime.datetime
    ) -> None:
        """Update aggregation state for index and expiry.
        
        Tracks PCR snapshot per expiry and max day_width across expiries.
        
        Args:
            index: Index symbol
            expiry_code: Expiry classification
            pcr: Put-Call ratio value
            day_width: Market day fraction (0.0-1.0)
            timestamp: Current timestamp (for last_write tracking)
        
        Side Effects:
            Updates internal aggregation state dictionaries
        """
        snap = self._agg_pcr_snapshot.setdefault(index, {})
        snap[expiry_code] = pcr
        
        # Track max day_width across expiries (or last non-zero)
        prev: float = self._agg_day_width.get(index, 0.0)
        if day_width >= prev:
            self._agg_day_width[index] = day_width
        
        self._agg_last_write.setdefault(index, timestamp)
    
    def maybe_write_aggregated_overview(
        self,
        *,
        index: str,
        timestamp: datetime.datetime
    ) -> bool:
        """Write aggregated overview if interval elapsed and snapshot available.
        
        Args:
            index: Index symbol
            timestamp: Current timestamp
        
        Returns:
            True if overview was written, False otherwise
        
        Side Effects:
            Writes overview CSV file if conditions met
            Resets aggregation snapshot after write
        """
        last = self._agg_last_write.get(index)
        if not last:
            self._agg_last_write[index] = timestamp
            return False
        
        # Check if interval elapsed
        if (timestamp - last).total_seconds() < self.overview_interval_seconds:
            return False
        
        # Check if snapshot available
        snapshot = self._agg_pcr_snapshot.get(index, {})
        if not snapshot:
            return False
        
        # Get day_width
        day_width = self._agg_day_width.get(index, 0.0)
        
        # Write snapshot
        try:
            self.write_overview_snapshot(
                index=index,
                pcr_snapshot=snapshot,
                timestamp=timestamp,
                day_width=day_width,
                expected_expiries=list(snapshot.keys())
            )
        except Exception as e:
            self.logger.error("Error writing aggregated overview for %s: %s", index, e)
            return False
        
        # Update last write and reset snapshot
        self._agg_last_write[index] = timestamp
        self._agg_pcr_snapshot[index] = {}
        self._agg_day_width[index] = 0.0
        
        return True
    
    def write_overview_snapshot(
        self,
        *,
        index: str,
        pcr_snapshot: dict[str, float],
        timestamp: datetime.datetime,
        day_width: float = 0.0,
        expected_expiries: list[str] | None = None,
        vix: float | None = None
    ) -> None:
        """Write single aggregated overview row with multiple expiry PCRs.
        
        Args:
            index: Index symbol
            pcr_snapshot: Mapping of expiry_code → pcr value
            timestamp: Base timestamp (will be rounded to 30s IST)
            day_width: Representative day width (0.0-1.0)
            expected_expiries: List of expected expiry codes for coverage calculation
            vix: VIX value (optional, uses last seen if not provided)
        
        Side Effects:
            Appends row to overview/{index}/{date}.csv
            Emits metrics for overview write
        """
        # Unified IST rounding for aggregate snapshot
        ts_str = self._overview_round_ts(timestamp)
        
        # Ensure overview directory exists
        overview_dir = os.path.join(self.base_dir, "overview", index)
        os.makedirs(overview_dir, exist_ok=True)
        
        # Determine file path
        overview_file = os.path.join(overview_dir, f"{timestamp.strftime('%Y-%m-%d')}.csv")
        file_exists = os.path.isfile(overview_file)
        
        # Compute coverage masks
        expected_mask, collected_mask, missing_mask, expiries_expected, expiries_collected = (
            self.compute_coverage_masks(list(pcr_snapshot.keys()), expected_expiries)
        )
        
        # Load previous close values
        date_key = timestamp.strftime('%Y-%m-%d')
        try:
            self._ensure_prev_close_loaded(index=index, date_key=date_key)
        except Exception:
            pass
        
        # Get index price and compute changes
        idx_price = float(self._index_last_price.get(index, 0.0))
        idx_day_ch = float(idx_price - float(self._index_open_price.get(index, idx_price)))
        idx_prev_close = self._index_prev_close.get(index)
        idx_net = float(idx_price - float(idx_prev_close)) if idx_prev_close is not None else 0.0
        
        # Use provided VIX or last seen
        use_vix = float(vix) if vix is not None else float(self._last_vix or 0.0)
        
        # Write CSV row
        with open(overview_file, 'a' if file_exists else 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Write header if new file
            if not file_exists:
                writer.writerow([
                    'timestamp', 'index',
                    'pcr_this_week', 'pcr_next_week', 'pcr_this_month', 'pcr_next_month',
                    'day_width',
                    'index_price', 'index_net_change', 'index_day_change',
                    'VIX',
                    'expiries_expected', 'expiries_collected',
                    'expected_mask', 'collected_mask', 'missing_mask'
                ])
            
            # Write data row
            writer.writerow([
                ts_str, index,
                pcr_snapshot.get('this_week', 0),
                pcr_snapshot.get('next_week', 0),
                pcr_snapshot.get('this_month', 0),
                pcr_snapshot.get('next_month', 0),
                day_width,
                idx_price, idx_net, idx_day_ch,
                use_vix,
                expiries_expected, expiries_collected,
                expected_mask, collected_mask, missing_mask
            ])
        
        # Log write
        if self._concise:
            self.logger.debug("Aggregated overview snapshot written for %s -> %s", index, overview_file)
        else:
            self.logger.info("Aggregated overview snapshot written for %s -> %s", index, overview_file)
        
        # Emit metric
        try:
            if self.metrics:
                self.metrics.inc('csv_overview_aggregate_writes', 1, {'index': index})
        except Exception:
            pass
    
    def compute_coverage_masks(
        self,
        collected_keys: list[str],
        expected_keys: list[str] | None
    ) -> tuple[int, int, int, int, int]:
        """Compute bit masks and counts for expiry coverage summary.
        
        Args:
            collected_keys: List of collected expiry codes
            expected_keys: List of expected expiry codes (None means use collected)
        
        Returns:
            Tuple of (expected_mask, collected_mask, missing_mask, expiries_expected, expiries_collected):
                - expected_mask: Bitmask of expected expiries
                - collected_mask: Bitmask of collected expiries
                - missing_mask: Bitmask of missing expiries (expected & ~collected)
                - expiries_expected: Count of expected expiries
                - expiries_collected: Count of collected expiries
        """
        expiry_bit_map = {
            'this_week': 1,
            'next_week': 2,
            'this_month': 4,
            'next_month': 8
        }
        
        # Compute collected mask
        collected_mask = 0
        for k in collected_keys:
            collected_mask |= expiry_bit_map.get(k, 0)
        
        # Compute expected mask
        if expected_keys is not None and expected_keys:
            expected_mask = 0
            for k in expected_keys:
                expected_mask |= expiry_bit_map.get(k, 0)
            expiries_expected = len(expected_keys)
        else:
            expected_mask = collected_mask
            expiries_expected = len(collected_keys)
        
        # Compute missing mask
        missing_mask = expected_mask & (~collected_mask)
        
        return expected_mask, collected_mask, missing_mask, expiries_expected, len(collected_keys)
    
    def inject_last_prices(
        self,
        *,
        index: str,
        index_price: float,
        index_open: float,
        vix: float | None = None
    ) -> None:
        """Inject last seen price values for aggregation calculations.
        
        Called by write_options_data to provide current index/VIX values.
        
        Args:
            index: Index symbol
            index_price: Current index price
            index_open: Index opening price
            vix: Current VIX value (optional)
        """
        self._index_last_price[index] = index_price
        self._index_open_price[index] = index_open
        if vix is not None:
            self._last_vix = vix
    
    # Private helper methods
    
    def _overview_round_ts(self, timestamp: datetime.datetime) -> str:
        """Round timestamp to 30s IST format.
        
        Centralizes duplicated try/except used by overview writers.
        Behavior preserved: on failure, emulate legacy rounding logic.
        
        Args:
            timestamp: Timestamp to round
        
        Returns:
            Formatted timestamp string (dd-mm-YYYY HH:MM:SS)
        """
        try:
            # Try primary helper (format_ist_dt_30s)
            from src.utils.timeutils import format_ist_dt_30s
            return str(format_ist_dt_30s(timestamp))
        except Exception:
            # Fallback: legacy rounding logic
            second = timestamp.second
            if second % 30 < 15:
                rounded_second = (second // 30) * 30
                rounded_timestamp = timestamp.replace(second=rounded_second, microsecond=0)
            else:
                rounded_second = ((second // 30) + 1) * 30
                if rounded_second == 60:
                    rounded_second = 0
                    rounded_timestamp = timestamp.replace(second=rounded_second, microsecond=0)
                    rounded_timestamp = rounded_timestamp + datetime.timedelta(minutes=1)
                else:
                    rounded_timestamp = timestamp.replace(second=rounded_second, microsecond=0)
            return rounded_timestamp.strftime('%d-%m-%Y %H:%M:%S')
    
    def _ensure_prev_close_loaded(self, *, index: str, date_key: str) -> None:
        """Load previous day's close values for index_price and tp from overview CSV.
        
        Caches results per (index, date_key) to avoid repeated disk I/O.
        Falls back gracefully if no file or columns present.
        
        Args:
            index: Index symbol
            date_key: Date key (YYYY-MM-DD format)
        
        Side Effects:
            Updates _index_prev_close and _tp_prev_close caches
        """
        try:
            # Already loaded for this date?
            if self._prev_close_loaded_date.get(index) == date_key:
                return
            
            # Walk back up to 5 prior calendar days to find last available overview file
            today = datetime.datetime.strptime(date_key, '%Y-%m-%d').date()
            base_dir = os.path.join(self.base_dir, 'overview', index)
            prev_idx_close = None
            prev_tp_close = None
            
            for back in range(1, 6):
                prev_day = today - datetime.timedelta(days=back)
                fp = os.path.join(base_dir, f"{prev_day.strftime('%Y-%m-%d')}.csv")
                
                if not os.path.isfile(fp):
                    continue
                
                try:
                    with open(fp, encoding='utf-8') as fh:
                        rdr = csv.DictReader(fh)
                        last_row = None
                        for r in rdr:
                            last_row = r
                        
                        if last_row:
                            # Index price prev close
                            try:
                                prev_idx_close = float(last_row.get('index_price', '') or 0.0)
                            except Exception:
                                prev_idx_close = None
                            
                            # TP prev close (may be absent on older schema)
                            try:
                                prev_tp_close = float(last_row.get('tp', '') or 0.0)
                            except Exception:
                                prev_tp_close = None
                            
                            break
                except Exception:
                    continue
                
                # Found a file with data
                if prev_idx_close is not None:
                    break
            
            # Cache results
            if prev_idx_close is not None:
                self._index_prev_close[index] = prev_idx_close
            if prev_tp_close is not None:
                self._tp_prev_close[index] = prev_tp_close
            
            self._prev_close_loaded_date[index] = date_key
        except Exception:
            # Best-effort; leave unset on failure
            self._prev_close_loaded_date[index] = date_key
