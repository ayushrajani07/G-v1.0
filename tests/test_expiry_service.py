"""Tests for utils.expiry_service module."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date, timedelta
from unittest.mock import Mock, patch

import pytest

from src.utils.expiry_service import (
    ExpiryService,
    build_expiry_service,
    is_monthly_expiry,
    is_weekly_expiry,
    load_holiday_calendar,
    select_expiries,
)


class TestExpiryServiceSelect:
    """Test ExpiryService.select() method."""

    def test_select_this_week(self):
        """Test selecting this_week expiry."""
        today = date(2025, 10, 27)  # Monday
        candidates = [
            date(2025, 10, 30),  # Thursday (this week)
            date(2025, 11, 6),   # Next Thursday
        ]
        
        service = ExpiryService(today=today)
        result = service.select("this_week", candidates)
        
        assert result == date(2025, 10, 30)

    def test_select_next_week(self):
        """Test selecting next_week expiry."""
        today = date(2025, 10, 27)
        candidates = [
            date(2025, 10, 30),
            date(2025, 11, 6),
            date(2025, 11, 13),
        ]
        
        service = ExpiryService(today=today)
        result = service.select("next_week", candidates)
        
        assert result == date(2025, 11, 6)

    def test_select_next_week_only_one_future(self):
        """Test next_week falls back to first if only one future expiry."""
        today = date(2025, 10, 27)
        candidates = [date(2025, 10, 30)]
        
        service = ExpiryService(today=today)
        result = service.select("next_week", candidates)
        
        # Should fallback to first available
        assert result == date(2025, 10, 30)

    def test_select_this_month(self):
        """Test selecting this_month expiry."""
        today = date(2025, 10, 15)
        candidates = [
            date(2025, 10, 23),  # In current month
            date(2025, 10, 30),  # Last in month
            date(2025, 11, 6),   # Next month
        ]
        
        service = ExpiryService(today=today)
        result = service.select("this_month", candidates)
        
        # Should select last expiry in current month
        assert result == date(2025, 10, 30)

    def test_select_this_month_no_current_month_expiry(self):
        """Test this_month when no expiries in current month."""
        today = date(2025, 10, 27)
        candidates = [
            date(2025, 11, 6),   # Next month
            date(2025, 11, 27),  # Next month
            date(2025, 12, 25),  # Month after
        ]
        
        service = ExpiryService(today=today)
        result = service.select("this_month", candidates)
        
        # Should fallback to first monthly anchor
        assert result == date(2025, 11, 27)

    def test_select_next_month(self):
        """Test selecting next_month expiry."""
        today = date(2025, 10, 15)
        candidates = [
            date(2025, 10, 23),
            date(2025, 10, 30),  # Last in October
            date(2025, 11, 6),
            date(2025, 11, 27),  # Last in November
            date(2025, 12, 25),  # Last in December
        ]
        
        service = ExpiryService(today=today)
        result = service.select("next_month", candidates)
        
        # Should select second monthly anchor
        assert result == date(2025, 11, 27)

    def test_select_next_month_only_one_monthly_anchor(self):
        """Test next_month falls back to first anchor if only one."""
        today = date(2025, 10, 15)
        candidates = [
            date(2025, 10, 23),
            date(2025, 10, 30),  # Only monthly anchor
        ]
        
        service = ExpiryService(today=today)
        result = service.select("next_month", candidates)
        
        # Should fallback to first anchor
        assert result == date(2025, 10, 30)

    def test_select_filters_past_dates(self):
        """Test that past dates are filtered out."""
        today = date(2025, 10, 27)
        candidates = [
            date(2025, 10, 20),  # Past
            date(2025, 10, 25),  # Past
            date(2025, 10, 30),  # Future
            date(2025, 11, 6),   # Future
        ]
        
        service = ExpiryService(today=today)
        result = service.select("this_week", candidates)
        
        # Should only consider future dates
        assert result == date(2025, 10, 30)

    def test_select_removes_duplicates(self):
        """Test that duplicate dates are handled."""
        today = date(2025, 10, 27)
        candidates = [
            date(2025, 10, 30),
            date(2025, 10, 30),  # Duplicate
            date(2025, 11, 6),
        ]
        
        service = ExpiryService(today=today)
        result = service.select("this_week", candidates)
        
        assert result == date(2025, 10, 30)

    def test_select_with_holiday_function(self):
        """Test selection with holiday filtering."""
        today = date(2025, 10, 27)
        candidates = [
            date(2025, 10, 30),  # Thursday (holiday)
            date(2025, 11, 6),   # Next Thursday
        ]
        
        def is_holiday(d: date) -> bool:
            return d == date(2025, 10, 30)
        
        service = ExpiryService(today=today, holiday_fn=is_holiday)
        result = service.select("this_week", candidates)
        
        # Should skip holiday and select next
        assert result == date(2025, 11, 6)

    def test_select_no_future_expiries_error(self):
        """Test error when no future expiries available."""
        today = date(2025, 10, 27)
        candidates = [
            date(2025, 10, 20),
            date(2025, 10, 25),
        ]
        
        service = ExpiryService(today=today)
        
        with pytest.raises(ValueError, match="no future expiries available"):
            service.select("this_week", candidates)

    def test_select_unsupported_rule_error(self):
        """Test error with unsupported rule."""
        today = date(2025, 10, 27)
        candidates = [date(2025, 10, 30)]
        
        service = ExpiryService(today=today)
        
        with pytest.raises(ValueError, match="unsupported expiry rule"):
            service.select("invalid_rule", candidates)

    def test_select_empty_rule_error(self):
        """Test error with empty rule."""
        today = date(2025, 10, 27)
        candidates = [date(2025, 10, 30)]
        
        service = ExpiryService(today=today)
        
        with pytest.raises(ValueError, match="unsupported expiry rule"):
            service.select("", candidates)

    def test_select_case_insensitive(self):
        """Test rule names are case-insensitive."""
        today = date(2025, 10, 27)
        candidates = [date(2025, 10, 30)]
        
        service = ExpiryService(today=today)
        
        # Should work with different cases
        assert service.select("THIS_WEEK", candidates) == date(2025, 10, 30)
        assert service.select("This_Week", candidates) == date(2025, 10, 30)
        assert service.select("  this_week  ", candidates) == date(2025, 10, 30)

    def test_select_uses_default_today(self):
        """Test select uses current date when today=None."""
        candidates = [
            date(2030, 1, 1),  # Far future
            date(2030, 1, 8),
        ]
        
        service = ExpiryService(today=None)  # Will use system date
        result = service.select("this_week", candidates)
        
        # Should return first future date
        assert result == date(2030, 1, 1)

    def test_select_non_date_candidates_filtered(self):
        """Test that non-date candidates are filtered out."""
        today = date(2025, 10, 27)
        candidates = [
            "2025-10-30",  # String (should be filtered)
            date(2025, 10, 30),
            None,  # None (should be filtered)
            date(2025, 11, 6),
        ]
        
        service = ExpiryService(today=today)
        result = service.select("this_week", candidates)
        
        assert result == date(2025, 10, 30)


class TestExpiryServiceClassify:
    """Test ExpiryService.classify() method."""

    def test_classify_weekly_expiry(self):
        """Test classifying weekly expiry (Thursday)."""
        expiry = date(2025, 10, 16)  # Thursday (not last of month - Oct 30 is last)
        service = ExpiryService(weekly_dow=3, monthly_dow=3)
        
        result = service.classify(expiry)
        
        assert result["is_weekly"] is True
        # Not last Thursday of month
        assert result["is_monthly"] is False

    def test_classify_monthly_expiry(self):
        """Test classifying monthly expiry (last Thursday)."""
        expiry = date(2025, 10, 30)  # Last Thursday of October (dow=3)
        service = ExpiryService(weekly_dow=3, monthly_dow=3)
        
        result = service.classify(expiry)
        
        assert result["is_weekly"] is True  # Is a Thursday
        assert result["is_monthly"] is True  # Last Thursday

    def test_classify_neither(self):
        """Test classifying date that's neither weekly nor monthly."""
        expiry = date(2025, 10, 29)  # Wednesday
        service = ExpiryService(weekly_dow=3, monthly_dow=3)
        
        result = service.classify(expiry)
        
        assert result["is_weekly"] is False
        assert result["is_monthly"] is False

    def test_classify_custom_weekday(self):
        """Test classification with custom weekly_dow."""
        expiry = date(2025, 10, 29)  # Wednesday (dow=2)
        service = ExpiryService(weekly_dow=2, monthly_dow=2)
        
        result = service.classify(expiry)
        
        assert result["is_weekly"] is True


class TestIsWeeklyExpiry:
    """Test is_weekly_expiry function."""

    def test_is_weekly_expiry_thursday(self):
        """Test Thursday detection."""
        expiry = date(2025, 10, 30)  # Thursday
        assert is_weekly_expiry(expiry, weekly_dow=3) is True

    def test_is_weekly_expiry_not_thursday(self):
        """Test non-Thursday detection."""
        expiry = date(2025, 10, 29)  # Wednesday
        assert is_weekly_expiry(expiry, weekly_dow=3) is False

    def test_is_weekly_expiry_custom_dow(self):
        """Test custom day of week."""
        expiry = date(2025, 10, 29)  # Wednesday (dow=2)
        assert is_weekly_expiry(expiry, weekly_dow=2) is True

    def test_is_weekly_expiry_friday(self):
        """Test Friday detection."""
        expiry = date(2025, 10, 31)  # Friday
        assert is_weekly_expiry(expiry, weekly_dow=4) is True


class TestIsMonthlyExpiry:
    """Test is_monthly_expiry function."""

    def test_is_monthly_expiry_last_thursday(self):
        """Test last Thursday of month."""
        expiry = date(2025, 10, 30)  # Last Thursday of October (dow=3)
        assert is_monthly_expiry(expiry, monthly_dow=3) is True

    def test_is_monthly_expiry_not_last_thursday(self):
        """Test non-last Thursday."""
        expiry = date(2025, 10, 16)  # Thursday, but not last (Oct 23, 30 still ahead)
        assert is_monthly_expiry(expiry, monthly_dow=3) is False

    def test_is_monthly_expiry_custom_dow(self):
        """Test custom monthly dow."""
        expiry = date(2025, 10, 27)  # Last Monday of October (dow=0)
        assert is_monthly_expiry(expiry, monthly_dow=0) is True

    def test_is_monthly_expiry_not_matching_dow(self):
        """Test non-matching day of week."""
        expiry = date(2025, 10, 31)  # Friday
        assert is_monthly_expiry(expiry, monthly_dow=3) is False  # Not Thursday


class TestSelectExpiries:
    """Test select_expiries bulk selection function."""

    def test_select_expiries_multiple_rules(self):
        """Test selecting multiple rules at once."""
        today = date(2025, 10, 15)
        candidates = [
            date(2025, 10, 23),
            date(2025, 10, 30),
            date(2025, 11, 6),
            date(2025, 11, 27),
        ]
        
        service = ExpiryService(today=today)
        results = select_expiries(service, ["this_week", "next_week", "this_month"], candidates)
        
        assert results["this_week"] == date(2025, 10, 23)
        assert results["next_week"] == date(2025, 10, 30)
        assert results["this_month"] == date(2025, 10, 30)

    def test_select_expiries_tolerates_errors(self):
        """Test select_expiries handles errors gracefully."""
        today = date(2025, 10, 27)
        candidates = []  # Empty will cause errors
        
        service = ExpiryService(today=today)
        results = select_expiries(service, ["this_week", "next_week"], candidates)
        
        # Should return empty dict (no successful selections)
        assert len(results) == 0

    def test_select_expiries_empty_rules(self):
        """Test select_expiries with empty rules list."""
        today = date(2025, 10, 27)
        candidates = [date(2025, 10, 30)]
        
        service = ExpiryService(today=today)
        results = select_expiries(service, [], candidates)
        
        assert len(results) == 0


class TestLoadHolidayCalendar:
    """Test load_holiday_calendar function."""

    def test_load_holiday_calendar_valid_file(self):
        """Test loading valid holiday calendar."""
        holidays = [
            "2025-10-30",
            "2025-11-01",
            "2025-12-25",
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(holidays, f)
            temp_path = f.name
        
        try:
            result = load_holiday_calendar(temp_path)
            
            assert len(result) == 3
            assert date(2025, 10, 30) in result
            assert date(2025, 11, 1) in result
            assert date(2025, 12, 25) in result
        finally:
            os.unlink(temp_path)

    def test_load_holiday_calendar_none_path(self):
        """Test loading with None path."""
        result = load_holiday_calendar(None)
        assert result == set()

    def test_load_holiday_calendar_empty_string(self):
        """Test loading with empty string path."""
        result = load_holiday_calendar("")
        assert result == set()

    def test_load_holiday_calendar_file_not_found(self):
        """Test loading non-existent file."""
        result = load_holiday_calendar("/nonexistent/path/holidays.json")
        assert result == set()

    def test_load_holiday_calendar_invalid_json(self):
        """Test loading file with invalid JSON."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("{invalid json")
            temp_path = f.name
        
        try:
            result = load_holiday_calendar(temp_path)
            assert result == set()
        finally:
            os.unlink(temp_path)

    def test_load_holiday_calendar_invalid_dates(self):
        """Test loading with invalid date strings."""
        holidays = [
            "2025-10-30",
            "invalid-date",
            "2025-13-01",  # Invalid month
            "2025-11-01",
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(holidays, f)
            temp_path = f.name
        
        try:
            result = load_holiday_calendar(temp_path)
            
            # Should only load valid dates
            assert date(2025, 10, 30) in result
            assert date(2025, 11, 1) in result
            # Invalid dates should be skipped
            assert len(result) == 2
        finally:
            os.unlink(temp_path)

    def test_load_holiday_calendar_empty_array(self):
        """Test loading empty array."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump([], f)
            temp_path = f.name
        
        try:
            result = load_holiday_calendar(temp_path)
            assert result == set()
        finally:
            os.unlink(temp_path)


class TestBuildExpiryService:
    """Test build_expiry_service factory function."""

    @patch('src.utils.expiry_service._env_get_bool')
    def test_build_expiry_service_disabled(self, mock_env_bool):
        """Test service returns None when disabled."""
        mock_env_bool.return_value = False
        
        result = build_expiry_service()
        
        assert result is None

    @patch('src.utils.expiry_service._env_get_bool')
    @patch('src.utils.expiry_service._env_get_str')
    @patch('src.utils.expiry_service._env_get_int')
    @patch('src.utils.expiry_service.load_holiday_calendar')
    def test_build_expiry_service_enabled(self, mock_load_hol, mock_env_int, mock_env_str, mock_env_bool):
        """Test service creation when enabled."""
        mock_env_bool.return_value = True
        mock_env_str.return_value = ""
        mock_env_int.side_effect = lambda name, default: default  # Use defaults
        mock_load_hol.return_value = set()
        
        result = build_expiry_service()
        
        assert result is not None
        assert isinstance(result, ExpiryService)
        assert result.weekly_dow == 3
        assert result.monthly_dow == 3

    @patch('src.utils.expiry_service._env_get_bool')
    @patch('src.utils.expiry_service._env_get_str')
    @patch('src.utils.expiry_service._env_get_int')
    @patch('src.utils.expiry_service.load_holiday_calendar')
    def test_build_expiry_service_with_holidays(self, mock_load_hol, mock_env_int, mock_env_str, mock_env_bool):
        """Test service creation with holiday calendar."""
        mock_env_bool.return_value = True
        mock_env_str.return_value = "/path/to/holidays.json"
        mock_env_int.side_effect = lambda name, default: default
        mock_load_hol.return_value = {date(2025, 10, 30)}
        
        result = build_expiry_service()
        
        assert result is not None
        assert result.holiday_fn is not None
        mock_load_hol.assert_called_once_with("/path/to/holidays.json")

    @patch('src.utils.expiry_service._env_get_bool')
    @patch('src.utils.expiry_service._env_get_str')
    @patch('src.utils.expiry_service._env_get_int')
    @patch('src.utils.expiry_service.load_holiday_calendar')
    def test_build_expiry_service_custom_dow(self, mock_load_hol, mock_env_int, mock_env_str, mock_env_bool):
        """Test service creation with custom weekdays."""
        mock_env_bool.return_value = True
        mock_env_str.return_value = ""
        mock_env_int.side_effect = lambda name, default: 2 if "WEEKLY" in name else 4  # Wed weekly, Fri monthly
        mock_load_hol.return_value = set()
        
        result = build_expiry_service()
        
        assert result is not None
        assert result.weekly_dow == 2
        assert result.monthly_dow == 4


class TestIntegration:
    """Integration tests for expiry service."""

    def test_full_workflow(self):
        """Test complete expiry selection workflow."""
        today = date(2025, 10, 15)
        candidates = [
            date(2025, 10, 23),  # This week Thursday
            date(2025, 10, 30),  # Next week Thursday (last of month)
            date(2025, 11, 6),   # Following Thursday
            date(2025, 11, 27),  # Last Thursday of Nov
        ]
        
        service = ExpiryService(today=today)
        
        # Select various rules
        this_week = service.select("this_week", candidates)
        next_week = service.select("next_week", candidates)
        this_month = service.select("this_month", candidates)
        next_month = service.select("next_month", candidates)
        
        assert this_week == date(2025, 10, 23)
        assert next_week == date(2025, 10, 30)
        assert this_month == date(2025, 10, 30)
        assert next_month == date(2025, 11, 27)
        
        # Classify
        assert service.classify(this_week)["is_weekly"] is True  # Oct 23 is Thursday
        assert service.classify(this_week)["is_monthly"] is False  # Oct 23 is not last Thu (Oct 30 is)
        assert service.classify(date(2025, 10, 30))["is_monthly"] is True  # Oct 30 is last Thu

    def test_with_holidays_workflow(self):
        """Test workflow with holiday filtering."""
        today = date(2025, 10, 27)
        candidates = [
            date(2025, 10, 30),  # Holiday
            date(2025, 11, 1),   # Holiday
            date(2025, 11, 6),
            date(2025, 11, 13),
        ]
        
        holidays = {date(2025, 10, 30), date(2025, 11, 1)}
        
        service = ExpiryService(
            today=today,
            holiday_fn=lambda d: d in holidays
        )
        
        # Should skip holidays
        this_week = service.select("this_week", candidates)
        next_week = service.select("next_week", candidates)
        
        assert this_week == date(2025, 11, 6)
        assert next_week == date(2025, 11, 13)

    def test_edge_case_single_future_expiry(self):
        """Test edge case with single future expiry."""
        today = date(2025, 10, 27)
        candidates = [date(2025, 10, 30)]
        
        service = ExpiryService(today=today)
        
        # All rules should return the same single expiry
        assert service.select("this_week", candidates) == date(2025, 10, 30)
        assert service.select("next_week", candidates) == date(2025, 10, 30)
        assert service.select("this_month", candidates) == date(2025, 10, 30)
        assert service.select("next_month", candidates) == date(2025, 10, 30)
