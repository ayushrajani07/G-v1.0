"""CSV expiry classification and resolution module.

Extracted from CsvSink Phase 2 refactoring (Oct 2025).
Handles expiry date parsing, classification, monthly anchor validation, and advisory tracking.
"""

from __future__ import annotations

import datetime
import json
import os
import re
from typing import Any


class CsvExpiryResolver:
    """Resolves and classifies expiry dates for options data.
    
    Responsibilities:
    - Parse expiry dates from various formats
    - Classify expiries (this_week, next_week, this_month, next_month)
    - Validate monthly anchor dates (last weekday of month)
    - Track and advise on missing configured expiries per day
    - Handle expiry misclassification remediation
    """
    
    def __init__(self, *, logger, metrics, concise_mode: bool = False):
        """Initialize expiry resolver.
        
        Args:
            logger: Logger instance for expiry events
            metrics: Metrics registry (optional)
            concise_mode: If True, use debug-level logs instead of info
        """
        self.logger = logger
        self.metrics = metrics
        self._concise = concise_mode
        
        # Advisory tracking: {(index, date): {seen_expiry_tags}}
        self._seen_expiry_tags: dict[tuple[str, str], set[str]] = {}
        self._advisory_emitted: dict[tuple[str, str], bool] = {}
        
        # Lazy config cache for expected expiries
        self._config_cache: dict[str, Any] | None = None
    
    def resolve_expiry_context(
        self,
        *,
        index: str,
        expiry: Any,
        expiry_rule_tag: str | None,
        options_data: dict[str, Any]
    ) -> tuple[datetime.date, str, str | None, str]:
        """Resolve expiry date, logical tag, and corrected monthly anchor.
        
        Mirrors legacy inlined logic in write_options_data (no behavior change):
        - Parse expiry to date
        - Prefer supplied logical tag unless it's a raw date string
        - Heuristic fallback when tag omitted or raw date
        - Monthly anchor diagnostic & auto-correction (adjust exp_date & mutate option legs)
        
        Args:
            index: Index symbol (NIFTY, BANKNIFTY, etc.)
            expiry: Expiry date (date object or string)
            expiry_rule_tag: Supplied logical tag (this_week, next_month, etc.)
            options_data: Dict of option instruments (mutated if monthly anchor corrected)
        
        Returns:
            Tuple of (exp_date, expiry_code, supplied_tag, expiry_str):
                - exp_date: Parsed expiry date
                - expiry_code: Final logical classification
                - supplied_tag: Original supplied tag (None if not provided or raw date)
                - expiry_str: Formatted date string (YYYY-MM-DD)
        
        Side Effects:
            May mutate options_data if monthly anchor correction applied
            Emits warnings for monthly anchor mismatches
        """
        # Parse expiry date
        try:
            exp_date = (
                expiry if isinstance(expiry, datetime.date)
                else datetime.datetime.strptime(str(expiry), '%Y-%m-%d').date()
            )
        except Exception:
            # Fallback: treat unparsable expiry as today (should be rare) to avoid crash
            try:
                self.logger.warning("CSV_EXPIRY_PARSE_FALLBACK index=%s raw=%s", index, expiry)
            except Exception:
                pass
            exp_date = datetime.date.today()
        
        # Process supplied tag (ignore if it's a raw date string)
        supplied_tag = (
            expiry_rule_tag.strip()
            if isinstance(expiry_rule_tag, str) and expiry_rule_tag.strip()
            else None
        )
        
        if supplied_tag and re.fullmatch(r"\d{4}-\d{2}-\d{2}", supplied_tag):
            try:
                self.logger.debug(
                    "CSV_EXPIRY_TAG_RAW_DATE index=%s tag=%s -> falling back to heuristic classification", index, supplied_tag
                    "-> falling back to heuristic classification"
                )
            except Exception:
                pass
            supplied_tag = None
        
        # Determine final expiry code (supplied tag or heuristic)
        expiry_code = supplied_tag or self.determine_expiry_code(exp_date)
        expiry_str = exp_date.strftime('%Y-%m-%d')
        
        # Monthly anchor diagnostic & correction
        try:
            if supplied_tag in ('this_month', 'next_month'):
                corrected_date = self._validate_monthly_anchor(exp_date, supplied_tag, index, expiry_str)
                if corrected_date != exp_date:
                    # Apply correction
                    exp_date = corrected_date
                    expiry_str = exp_date.strftime('%Y-%m-%d')
                    
                    # Mutate option legs to reflect corrected date
                    try:
                        for _sym, _data in list(options_data.items()):
                            if isinstance(_data, dict) and 'expiry' in _data:
                                _data['expiry'] = exp_date
                        self.logger.warning(
                            "CSV_EXPIRY_CORRECTED monthly_anchor index=%s tag=%s corrected_date=%s",
                            index, supplied_tag, expiry_str
                        )
                    except Exception:
                        pass
        except Exception:
            pass
        
        return exp_date, expiry_code, supplied_tag, expiry_str
    
    def determine_expiry_code(
        self,
        exp_date: datetime.date,
        today: datetime.date | None = None
    ) -> str:
        """Classify expiry date into logical bucket.
        
        Classification rules:
        - ≤ 7 days: "this_week"
        - ≤ 14 days: "next_week"
        - Same month as today: "this_month"
        - Otherwise: "next_month"
        
        Args:
            exp_date: Expiry date to classify
            today: Reference date (defaults to today)
        
        Returns:
            Expiry code string (this_week, next_week, this_month, next_month)
        """
        today = today or datetime.date.today()
        days_to_expiry = (exp_date - today).days
        
        if days_to_expiry <= 7:
            return "this_week"
        if days_to_expiry <= 14:
            return "next_week"
        if exp_date.month == today.month:
            return "this_month"
        return "next_month"
    
    def advise_missing_expiries(
        self,
        *,
        index: str,
        expiry_code: str,
        timestamp: datetime.datetime
    ) -> None:
        """One-shot advisory when not all configured expiries observed for index today.
        
        Mirrors legacy inline logic (Task 35) without behavior change:
        - Track seen expiry tags per (index, date)
        - Load config lazily (g6_config.json) to obtain expected expiries list
        - When at least one tag seen but some expected still missing, emit single advisory per day
        - Respects concise mode for log level/format
        
        Args:
            index: Index symbol
            expiry_code: Observed expiry classification
            timestamp: Current timestamp (for date key)
        
        Side Effects:
            Emits advisory log once per (index, date) if expiries missing
            Swallows all exceptions (diagnostic-only path)
        """
        try:
            date_key = timestamp.strftime('%Y-%m-%d')
            key = (index, date_key)
            
            # Track seen expiries
            seen = self._seen_expiry_tags.setdefault(key, set())
            seen.add(expiry_code)
            
            # Already emitted advisory for this day?
            if self._advisory_emitted.get(key):
                return
            
            # Lazy load config to get expected expiries
            if not self._config_cache:
                cfg_path = os.path.join(
                    os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')),
                    'config',
                    'g6_config.json'
                )
                with open(cfg_path, encoding='utf-8') as _cf:
                    self._config_cache = json.load(_cf)
            
            indices_cfg = (self._config_cache or {}).get('indices', {})
            _exp_list = indices_cfg.get(index, {}).get('expiries')
            expected_tags = set(_exp_list) if isinstance(_exp_list, list) else set()
            
            if not expected_tags:
                return  # No expected expiries configured
            
            # Check for missing expiries
            missing = expected_tags - seen
            if missing and len(seen) >= 1:  # At least one observed, others missing
                self._advisory_emitted[key] = True
                if self._concise:
                    self.logger.debug(
                        "CSV_EXPIRY_ADVISORY index=%s seen=%s missing=%s", index, sorted(seen), sorted(missing)
                    )
                else:
                    self.logger.info(
                        "Advisory: Not all configured expiries observed for %s today. Seen=%s Missing=%s", index, sorted(seen), sorted(missing)
                        f"Seen={sorted(seen)} Missing={sorted(missing)}"
                    )
        except Exception:  # pragma: no cover
            pass
    
    def handle_expiry_misclassification(
        self,
        *,
        index: str,
        expiry_code: str,
        expiry_str: str,
        offset: int,
        row: list[Any],
        atm_strike: float,
        index_price: float
    ) -> tuple[str, bool]:
        """Handle expiry misclassification remediation (Task 32).
        
        Legacy behavior: If classified as this_week but expiry date is > 7 days away,
        reclassify to next_week and emit diagnostic.
        
        Args:
            index: Index symbol
            expiry_code: Current expiry classification
            expiry_str: Expiry date string (YYYY-MM-DD)
            offset: Strike offset from ATM
            row: CSV row being processed (for timestamp extraction)
            atm_strike: ATM strike price
            index_price: Current index price
        
        Returns:
            Tuple of (new_expiry_code, skip_row):
                - new_expiry_code: Corrected expiry code (or original if no correction)
                - skip_row: True if row should be skipped (always False per legacy)
        
        Side Effects:
            Emits warnings for misclassified expiries
            Emits metrics for reclassifications
        """
        try:
            # Only check this_week → next_week reclassification
            if expiry_code != 'this_week':
                return expiry_code, False
            
            # Parse expiry date and row timestamp
            exp_date = datetime.datetime.strptime(expiry_str, '%Y-%m-%d').date()
            row_ts = datetime.datetime.fromisoformat(row[0])
            days_to_expiry = (exp_date - row_ts.date()).days
            
            # Misclassified if > 7 days away
            if days_to_expiry > 7:
                new_code = 'next_week'
                
                # Emit warning
                try:
                    if self._concise:
                        self.logger.debug(
                            "CSV_EXPIRY_MISCLASS index=%s old=%s new=%s exp_date=%s days=%s offset=%s", index, expiry_code, new_code, expiry_str, days_to_expiry, offset
                            f"exp_date={expiry_str} days={days_to_expiry} offset={offset}"
                        )
                    else:
                        self.logger.warning(
                            "Expiry misclassification detected: %s offset=%s classified=%s days_away=%s exp_date=%s -> reclassifying to %s", index, offset, expiry_code, days_to_expiry, expiry_str, new_code
                            f"classified={expiry_code} days_away={days_to_expiry} "
                            f"exp_date={expiry_str} -> reclassifying to {new_code}"
                        )
                except Exception:
                    pass
                
                # Emit metric
                try:
                    if self.metrics:
                        self.metrics.inc(
                            'csv_expiry_reclassified',
                            1,
                            {
                                'index': index,
                                'from': expiry_code,
                                'to': new_code,
                                'offset': str(offset)
                            }
                        )
                except Exception:
                    pass
                
                return new_code, False  # Don't skip row, just reclassify
            
            return expiry_code, False
        except Exception:
            # Failed to parse dates → don't reclassify
            return expiry_code, False
    
    # Private helper methods
    
    def _validate_monthly_anchor(
        self,
        exp_date: datetime.date,
        supplied_tag: str,
        index: str,
        expiry_str: str
    ) -> datetime.date:
        """Validate and correct monthly anchor date (last occurrence of weekday in month).
        
        Args:
            exp_date: Current expiry date
            supplied_tag: Logical tag (this_month or next_month)
            index: Index symbol (for logging)
            expiry_str: Formatted date string (for logging)
        
        Returns:
            Corrected expiry date (or original if no correction needed)
        
        Side Effects:
            Emits warning if mismatch detected
        """
        try:
            # Calculate expected monthly anchor (last occurrence of weekday in month)
            if exp_date.month == 12:
                nxt_first = datetime.date(exp_date.year + 1, 1, 1)
            else:
                nxt_first = datetime.date(exp_date.year, exp_date.month + 1, 1)
            
            last_day = nxt_first - datetime.timedelta(days=1)
            last_weekday = last_day
            
            # Walk back to last occurrence of exp_date's weekday
            while last_weekday.weekday() != exp_date.weekday():
                last_weekday -= datetime.timedelta(days=1)
            
            # Check for mismatch
            if last_weekday != exp_date:
                self.logger.warning(
                    "CSV_EXPIRY_DIAGNOSTIC monthly_mismatch index=%s tag=%s date=%s expected_anchor=%s",
                    index, supplied_tag, expiry_str, last_weekday.isoformat()
                )
                return last_weekday
            
            return exp_date
        except Exception:
            return exp_date
