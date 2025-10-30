"""Utility functions for CSV data transformation.

Pure helper functions with no side effects.
Extracted from CsvSink to improve testability.
"""

import datetime
from typing import Any


def clean_for_json(obj: Any) -> Any:
    """
    Recursively clean data structures for JSON serialization.
    
    Converts datetime objects to ISO strings, removes NaN/Inf values.
    
    Args:
        obj: Object to clean (can be dict, list, primitive, etc.)
        
    Returns:
        JSON-serializable version of the object
    """
    if isinstance(obj, dict):
        return {k: clean_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_for_json(item) for item in obj]
    elif isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    elif isinstance(obj, float):
        # Handle NaN and Inf
        if obj != obj:  # NaN check
            return None
        if obj == float('inf') or obj == float('-inf'):
            return None
        return obj
    else:
        return obj


def group_by_strike(options_data: dict[str, dict[str, Any]]) -> dict[float, dict[str, Any]]:
    """
    Group options data by strike price.
    
    Converts instrument-keyed dict to strike-keyed dict, combining CE/PE data.
    
    Args:
        options_data: Dict mapping instrument symbols to option data
        
    Returns:
        Dict mapping strike prices to combined CE/PE data
        
    Example:
        Input: {"NIFTY24OCT18000CE": {"strike": 18000, "ltp": 100, ...}}
        Output: {18000.0: {"CE": {...}, "strike": 18000}}
    """
    strike_data: dict[float, dict[str, Any]] = {}
    
    for symbol, data in options_data.items():
        strike = data.get('strike')
        if strike is None:
            continue
        
        strike_float = float(strike)
        
        if strike_float not in strike_data:
            strike_data[strike_float] = {'strike': strike_float}
        
        # Determine if CE or PE based on symbol or option_type
        option_type = data.get('option_type', '').upper()
        if not option_type:
            # Infer from symbol (e.g., "CE" or "PE" suffix)
            if 'CE' in symbol.upper():
                option_type = 'CE'
            elif 'PE' in symbol.upper():
                option_type = 'PE'
        
        if option_type in ('CE', 'PE'):
            strike_data[strike_float][option_type] = data
    
    return strike_data


def compute_atm_strike(index: str, index_price: float) -> float:
    """
    Compute ATM strike for a given index price.
    
    Rounds to appropriate strike intervals based on index.
    
    Args:
        index: Index symbol (e.g., 'NIFTY', 'BANKNIFTY')
        index_price: Current index price
        
    Returns:
        Nearest ATM strike price
    """
    # Default strike intervals by index
    strike_intervals = {
        'NIFTY': 50,
        'BANKNIFTY': 100,
        'FINNIFTY': 50,
        'SENSEX': 100,
        'BANKEX': 100,
        'MIDCPNIFTY': 25,
    }
    
    interval = strike_intervals.get(index.upper(), 50)
    
    # Round to nearest strike interval
    atm = round(index_price / interval) * interval
    
    return float(atm)


def determine_expiry_code(exp_date: datetime.date, today: datetime.date | None = None) -> str:
    """
    Determine expiry classification code (W0, W1, M0, M1, etc.).
    
    Args:
        exp_date: Expiry date
        today: Reference date (defaults to today)
        
    Returns:
        Expiry code string (e.g., 'W0', 'W1', 'M0')
    """
    if today is None:
        today = datetime.date.today()
    
    # Calculate days until expiry
    days_delta = (exp_date - today).days
    
    # Classify based on time to expiry
    if days_delta < 0:
        return 'EXP'  # Expired
    elif days_delta <= 7:
        return 'W0'  # This week
    elif days_delta <= 14:
        return 'W1'  # Next week
    elif days_delta <= 30:
        return 'M0'  # This month
    elif days_delta <= 60:
        return 'M1'  # Next month
    else:
        return 'MF'  # Far month


def format_date_key(date: datetime.date | datetime.datetime | str) -> str:
    """
    Format a date as YYYY-MM-DD key string.
    
    Args:
        date: Date object, datetime, or string
        
    Returns:
        Date string in YYYY-MM-DD format
    """
    if isinstance(date, str):
        # Assume already formatted or parse if needed
        return date.split()[0]  # Take date part if datetime string
    elif isinstance(date, datetime.datetime):
        return date.strftime('%Y-%m-%d')
    elif isinstance(date, datetime.date):
        return date.strftime('%Y-%m-%d')
    else:
        return str(date)


def parse_offset_label(offset: int | str) -> str:
    """
    Parse offset value to standardized label.
    
    Args:
        offset: Integer offset or string label (e.g., 0, "ATM", "+3")
        
    Returns:
        Standardized offset label string
    """
    if isinstance(offset, str):
        return offset.strip()
    
    # Convert integer to signed string
    if offset == 0:
        return 'ATM'
    elif offset > 0:
        return f'+{offset}'
    else:
        return str(offset)


def compute_day_width(expiry_str: str, timestamp: datetime.datetime) -> float:
    """
    Compute day width (fraction of trading day remaining) for expiry.
    
    Args:
        expiry_str: Expiry date string (ISO format)
        timestamp: Current timestamp
        
    Returns:
        Day width value (0.0 to 1.0)
    """
    try:
        expiry_date = datetime.datetime.fromisoformat(expiry_str.replace('Z', '+00:00')).date()
        current_date = timestamp.date()
        
        if expiry_date < current_date:
            return 0.0  # Expired
        elif expiry_date > current_date:
            return 1.0  # Future expiry
        else:
            # Same day - compute fraction based on market hours
            # Assuming 9:15 AM to 3:30 PM IST (6h 15min = 375 minutes)
            market_open = datetime.datetime.combine(current_date, datetime.time(9, 15))
            market_close = datetime.datetime.combine(current_date, datetime.time(15, 30))
            
            if timestamp < market_open:
                return 1.0
            elif timestamp >= market_close:
                return 0.0
            else:
                total_minutes = 375
                elapsed = (timestamp - market_open).total_seconds() / 60
                return max(0.0, min(1.0, 1.0 - (elapsed / total_minutes)))
    except Exception:
        return 1.0  # Default to full day on error
