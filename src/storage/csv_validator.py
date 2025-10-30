"""CSV validation and schema enforcement module.

Extracted from CsvSink Phase 2 refactoring (Oct 2025).
Handles schema validation, junk filtering, zero-row detection, and duplicate suppression.
Pure business logic with no I/O dependencies.
"""

from __future__ import annotations

import datetime
import os
from typing import Any

from src.errors.error_routing import route_error


class CsvValidator:
    """Validates CSV data and filters invalid/junk records.
    
    Responsibilities:
    - Schema validation (strike, instrument_type checks)
    - Junk filtering (missing critical fields, stale data)
    - Zero-row detection (all prices zero)
    - Duplicate suppression (same timestamp within hour)
    - Mixed expiry pruning (embedded expiry mismatch)
    """
    
    def __init__(self, *, logger, metrics, concise_mode: bool = False):
        """Initialize validator with logging and metrics dependencies.
        
        Args:
            logger: Logger instance for validation events
            metrics: Metrics registry for validation counters (optional)
            concise_mode: If True, use debug-level logs instead of info
        """
        self.logger = logger
        self.metrics = metrics
        self._concise = concise_mode
        
        # Duplicate suppression state: {(index, expiry, offset, hour_key): timestamp}
        self._duplicate_cache: dict[tuple[str, str, int, str], str] = {}
    
    def validate_schema(
        self,
        *,
        index: str,
        expiry_code: str,
        strike_data: dict[float, dict[str, Any]]
    ) -> list[str]:
        """Validate grouped strike → leg map structure and prune invalid entries.
        
        Mirrors legacy inline 'Schema Assertions Layer (Task 11)' logic:
        - Remove strikes <= 0
        - Drop legs with missing/invalid instrument_type (not CE/PE)
        - Collect issue codes in list (ordering preserved by iteration)
        
        Args:
            index: Index symbol (NIFTY, BANKNIFTY, etc.)
            expiry_code: Expiry classification (this_week, next_week, etc.)
            strike_data: Dict mapping strike → {CE: data, PE: data}
        
        Returns:
            List of issue identifiers (e.g., "invalid_strike:0", "missing_or_bad_type:50000:CE")
        
        Side Effects:
            Mutates strike_data in-place (removes invalid strikes/legs)
        """
        schema_issues: list[str] = []
        
        for strike_key, leg_map in list(strike_data.items()):
            try:
                # Invalid strike check (≤ 0)
                if strike_key <= 0:
                    schema_issues.append(f"invalid_strike:{strike_key}")
                    strike_data.pop(strike_key, None)
                    continue
                
                # Validate instrument_type for CE/PE legs
                for leg_type in ('CE', 'PE'):
                    leg = leg_map.get(leg_type)
                    if leg:
                        inst_type = (leg.get('instrument_type') or '').upper()
                        if inst_type not in ('CE', 'PE'):
                            schema_issues.append(f"missing_or_bad_type:{strike_key}:{leg_type}")
                            leg_map[leg_type] = None
            except Exception:
                # Defensive: continue collecting other issues
                continue
        
        # Emit validation events if issues found
        if schema_issues:
            try:
                route_error(
                    'csv.schema.issues',
                    self.logger,
                    self.metrics,
                    index=index,
                    expiry=expiry_code,
                    count=len(schema_issues)
                )
            except Exception:
                self.logger.warning(
                    "CSV_SCHEMA_ISSUES index=%s expiry=%s count=%d issues=%s",
                    index, expiry_code, len(schema_issues),
                    ','.join(schema_issues[:25]) + (f"+{len(schema_issues)-25}" if len(schema_issues) > 25 else "")
                )
            
            # Emit metrics (cap at 50 issues to prevent cardinality explosion)
            try:
                if self.metrics:
                    for issue in schema_issues[:50]:
                        self.metrics.inc(
                            'data_errors_labeled',
                            1,
                            {
                                'index': index,
                                'component': 'csv_sink.schema',
                                'error_type': issue.split(':', 1)[0]
                            }
                        )
            except Exception:
                pass
        
        return schema_issues
    
    def maybe_skip_as_junk(
        self,
        *,
        index: str,
        expiry_code: str,
        offset: int,
        call_data: dict[str, Any],
        put_data: dict[str, Any],
        row_ts: str
    ) -> bool:
        """Determine if row should be filtered as junk data.
        
        Junk categories:
        - missing_prices: No last_price for either leg
        - missing_oi: No oi (open interest) for either leg
        - stale_update: Both legs have update_time ≥ 3 hours before row timestamp
        
        Args:
            index: Index symbol
            expiry_code: Expiry classification
            offset: Strike offset from ATM
            call_data: CE leg data dict
            put_data: PE leg data dict
            row_ts: Row timestamp string (ISO format)
        
        Returns:
            True if row should be skipped as junk, False otherwise
        
        Side Effects:
            Emits metrics for filtered junk (category breakdown)
        """
        # Check for missing prices
        if not call_data.get('last_price') and not put_data.get('last_price'):
            self._record_junk_filtered(index, expiry_code, offset, 'missing_prices')
            return True
        
        # Check for missing OI
        if not call_data.get('oi') and not put_data.get('oi'):
            self._record_junk_filtered(index, expiry_code, offset, 'missing_oi')
            return True
        
        # Stale update check (3+ hours old)
        try:
            row_dt = datetime.datetime.fromisoformat(row_ts)
            stale_threshold = row_dt - datetime.timedelta(hours=3)
            
            for leg_data in (call_data, put_data):
                if not leg_data:
                    continue
                upd_time = leg_data.get('last_update') or leg_data.get('update_time')
                if upd_time:
                    # Parse update time
                    if isinstance(upd_time, datetime.datetime):
                        upd_dt = upd_time
                    elif isinstance(upd_time, str):
                        upd_dt = datetime.datetime.fromisoformat(upd_time.replace('Z', '+00:00'))
                    else:
                        continue
                    
                    # If any leg is fresh, row is not stale
                    if upd_dt >= stale_threshold:
                        return False
            
            # Both legs are stale (or no update times)
            self._record_junk_filtered(index, expiry_code, offset, 'stale_update')
            return True
        except Exception:
            # Failed to parse timestamps → don't filter
            return False
    
    def handle_zero_row(
        self,
        *,
        index: str,
        expiry_code: str,
        expiry_date_str: str,
        offset: int,
        call_data: dict[str, Any],
        put_data: dict[str, Any]
    ) -> tuple[bool, bool]:
        """Detect and optionally filter zero-price rows.
        
        Zero-row defined as: all prices (last_price, bid, ask) are 0 or None for both legs.
        
        Args:
            index: Index symbol
            expiry_code: Expiry classification
            expiry_date_str: Expiry date string (YYYY-MM-DD)
            offset: Strike offset from ATM
            call_data: CE leg data
            put_data: PE leg data
        
        Returns:
            Tuple of (is_zero_row, skip_row):
                - is_zero_row: True if all prices are zero
                - skip_row: True if row should be filtered (always False per legacy behavior)
        
        Side Effects:
            Emits metrics for detected zero rows
        """
        # Collect all price fields from both legs
        price_fields = []
        for leg_data in (call_data, put_data):
            if leg_data:
                price_fields.extend([
                    leg_data.get('last_price'),
                    leg_data.get('bid'),
                    leg_data.get('ask')
                ])
        
        # Check if all prices are zero or None
        is_zero_row = all(p == 0 or p is None for p in price_fields)
        
        if is_zero_row:
            # Emit metric
            try:
                if self.metrics:
                    self.metrics.inc(
                        'csv_zero_row_detected',
                        1,
                        {
                            'index': index,
                            'expiry': expiry_code,
                            'offset': str(offset)
                        }
                    )
            except Exception:
                pass
            
            # Log detection (legacy behavior: warn but don't skip)
            try:
                if self._concise:
                    self.logger.debug(
                        "CSV_ZERO_ROW index=%s expiry=%s exp_date=%s offset=%s",
                        index,
                        expiry_code,
                        expiry_date_str,
                        offset,
                    )
                else:
                    self.logger.warning(
                        "Zero-price row detected: %s %s exp=%s offset=%s (preserved)",
                        index,
                        expiry_code,
                        expiry_date_str,
                        offset,
                    )
            except Exception:
                pass
        
        # Legacy behavior: detect but don't skip (return False for skip_row)
        return is_zero_row, False
    
    def check_duplicate(
        self,
        *,
        index: str,
        expiry_code: str,
        offset: int,
        timestamp_str: str
    ) -> bool:
        """Check if row is duplicate within same hour window.
        
        Duplicate defined as: same (index, expiry, offset, hour, timestamp_str).
        Uses in-memory cache keyed by hour window.
        
        Args:
            index: Index symbol
            expiry_code: Expiry classification
            offset: Strike offset from ATM
            timestamp_str: Row timestamp string (ISO format)
        
        Returns:
            True if duplicate (should be suppressed), False otherwise
        
        Side Effects:
            Updates internal duplicate cache
            Emits metrics for suppressed duplicates
        """
        try:
            # Extract hour key from timestamp
            ts_dt = datetime.datetime.fromisoformat(timestamp_str)
            hour_key = ts_dt.strftime('%Y-%m-%d-%H')
            
            cache_key = (index, expiry_code, offset, hour_key)
            
            # Check if already seen
            if cache_key in self._duplicate_cache:
                existing_ts = self._duplicate_cache[cache_key]
                if existing_ts == timestamp_str:
                    # Exact duplicate
                    self._record_duplicate_suppressed(index, expiry_code, offset)
                    return True
            
            # Not a duplicate → cache it
            self._duplicate_cache[cache_key] = timestamp_str
            return False
        except Exception:
            # Failed to parse timestamp → don't suppress
            return False
    
    def prune_mixed_expiry(
        self,
        options_data: dict[str, dict[str, Any]] | None,
        exp_date: datetime.date,
        *,
        index: str,
        expiry_code: str
    ) -> int:
        """Remove instruments whose embedded expiry does not match expected expiry date.
        
        Mirrors legacy inlined mixed-expiry pruning logic (Task 31/34) without behavior change.
        Checks expiry/expiry_date/instrument_expiry fields in each instrument.
        
        Args:
            options_data: Dict of symbol → instrument data
            exp_date: Expected expiry date
            index: Index symbol (for logging/metrics)
            expiry_code: Expiry classification (for logging/metrics)
        
        Returns:
            Number of instruments dropped
        
        Side Effects:
            Mutates options_data in-place (removes mismatched instruments)
            Emits metrics/logs for dropped instruments
        """
        if not options_data:
            return 0
        
        dropped = 0
        safe_expected = exp_date
        
        for sym, data in list(options_data.items()):
            try:
                # Extract embedded expiry from instrument data
                raw_exp = (
                    data.get('expiry') or
                    data.get('expiry_date') or
                    data.get('instrument_expiry')
                )
                if not raw_exp:
                    continue
                
                # Normalize candidate to date
                if isinstance(raw_exp, datetime.datetime):
                    cand_date = raw_exp.date()
                elif isinstance(raw_exp, datetime.date):
                    cand_date = raw_exp
                else:
                    cand_date = None
                    # Try multiple date formats
                    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%Y-%m-%d %H:%M:%S'):
                        try:
                            cand_date = datetime.datetime.strptime(str(raw_exp), fmt).date()
                            break
                        except Exception:
                            continue
                    if cand_date is None:
                        continue
                
                # Check for mismatch
                if cand_date != safe_expected:
                    options_data.pop(sym, None)
                    dropped += 1
            except Exception:
                continue
        
        # Emit metrics/logs if instruments were dropped
        if dropped:
            try:
                route_error(
                    'csv.mixed_expiry.prune',
                    self.logger,
                    self.metrics,
                    _count=dropped,
                    index=index,
                    expiry=expiry_code,
                    dropped=dropped
                )
            except Exception:
                if self._concise:
                    self.logger.debug(
                        "CSV_MIXED_EXPIRY_PRUNE index=%s tag=%s dropped=%s", index, expiry_code, dropped
                    )
                else:
                    self.logger.info(
                        "Pruned %s mixed-expiry records for %s %s", dropped, index, expiry_code
                    )
                
                # Emit metric directly
                try:
                    if self.metrics:
                        self.metrics.inc(
                            'csv_mixed_expiry_dropped',
                            dropped,
                            {'index': index, 'expiry': expiry_code}
                        )
                except Exception:
                    pass
        
        return dropped
    
    # Private helper methods
    
    def _record_junk_filtered(
        self,
        index: str,
        expiry_code: str,
        offset: int,
        category: str
    ) -> None:
        """Emit metric for filtered junk row."""
        try:
            if self.metrics:
                self.metrics.inc(
                    'csv_junk_filtered',
                    1,
                    {
                        'index': index,
                        'expiry': expiry_code,
                        'offset': str(offset),
                        'category': category
                    }
                )
        except Exception:
            pass
    
    def _record_duplicate_suppressed(
        self,
        index: str,
        expiry_code: str,
        offset: int
    ) -> None:
        """Emit metric for suppressed duplicate."""
        try:
            if self.metrics:
                self.metrics.inc(
                    'csv_duplicate_suppressed',
                    1,
                    {
                        'index': index,
                        'expiry': expiry_code,
                        'offset': str(offset)
                    }
                )
        except Exception:
            pass
