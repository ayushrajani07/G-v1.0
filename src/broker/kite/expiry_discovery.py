"""Expiry discovery & ATM strike helpers (Phase A7 Step 2 extraction).

Responsibilities moved from `kite_provider.KiteProvider`:
  * get_expiry_dates (instrument scan + fabrication fallback + auth handling)
  * get_weekly_expiries (first two future expiries)
  * get_monthly_expiries (last expiry per future month)
  * get_atm_strike (rounding heuristic with price fetch)

Design notes:
  * Provider object passed in must expose: get_instruments(exch), get_ltp(instruments),
    _state.expiry_dates_cache (dict), _auth_failed flag, _rl_fallback() throttle helper,
    INDEX_MAPPING & POOL_FOR constants visible via module import (we re-import to avoid coupling).
  * Logging + fabrication semantics preserved exactly (including shortened TTL logic & warnings).
"""
from __future__ import annotations

import datetime as _dt
import logging

logger = logging.getLogger(__name__)

# NOTE: Do NOT import INDEX_MAPPING/POOL_FOR from kite_provider at module import time.
# kite_provider imports this module early during its own initialization, which can
# result in partially initialized symbols and an empty mapping.
# We resolve these lazily at runtime to avoid circular-import fallout.

_DEFAULT_INDEX_MAPPING: dict[str, tuple[str, str]] = {
    "NIFTY": ("NSE", "NIFTY 50"),
    "BANKNIFTY": ("NSE", "NIFTY BANK"),
    "FINNIFTY": ("NSE", "NIFTY FIN SERVICE"),
    "MIDCPNIFTY": ("NSE", "NIFTY MIDCAP SELECT"),
    "SENSEX": ("BSE", "SENSEX"),
}

_DEFAULT_POOL_FOR: dict[str, str] = {
    "NIFTY": "NFO",
    "BANKNIFTY": "NFO",
    "FINNIFTY": "NFO",
    "MIDCPNIFTY": "NFO",
    "SENSEX": "BFO",
}


def _runtime_index_mapping() -> dict[str, tuple[str, str]]:
    try:
        from src.broker import kite_provider as _kp  # type: ignore
        m = getattr(_kp, 'INDEX_MAPPING', None)
        if isinstance(m, dict) and m:
            return m
    except Exception:
        pass
    return _DEFAULT_INDEX_MAPPING


def _runtime_pool_for() -> dict[str, str]:
    try:
        from src.broker import kite_provider as _kp  # type: ignore
        p = getattr(_kp, 'POOL_FOR', None)
        if isinstance(p, dict) and p:
            return p
    except Exception:
        pass
    return _DEFAULT_POOL_FOR


def _is_auth_error(e: BaseException) -> bool:  # fallback heuristic
    return 'auth' in str(e).lower() or 'token' in str(e).lower()

try:
    from src.error_handling import handle_data_collection_error
except ImportError:
    handle_data_collection_error = None  # type: ignore


def get_atm_strike(provider, index_symbol: str) -> int:
    index_mapping = _runtime_index_mapping()
    ltp_data = provider.get_ltp([index_mapping.get(index_symbol, ("NSE", index_symbol))])
    if isinstance(ltp_data, dict):
        for v in ltp_data.values():
            if isinstance(v, dict):
                lp = v.get('last_price')
                if isinstance(lp, (int, float)) and lp > 0:
                    step = 100 if lp > 20000 else 50
                    return int(round(lp / step) * step)
    defaults = {"NIFTY": 24800, "BANKNIFTY": 54000, "FINNIFTY": 26000, "MIDCPNIFTY": 12000, "SENSEX": 81000}
    return defaults.get(index_symbol, 20000)


def get_expiry_dates(provider, index_symbol: str) -> list[_dt.date]:
    try:
        if provider._auth_failed:
            raise RuntimeError("kite_auth_failed")
        cache = provider._state.expiry_dates_cache.get(index_symbol)
        if cache:
            return cache
        atm = get_atm_strike(provider, index_symbol)
        pool_for = _runtime_pool_for()
        exch = pool_for.get(index_symbol, "NFO")
        instruments = provider.get_instruments(exch)
        today = _dt.date.today()
        opts = [
            inst for inst in instruments
            if isinstance(inst, dict)
            and str(inst.get("segment", "")).endswith("-OPT")
            and index_symbol in str(inst.get("tradingsymbol", ""))
            and abs(float(inst.get("strike", 0) or 0) - atm) <= 500
        ]
        expiries: set[_dt.date] = set()
        for inst in opts:
            exp = inst.get('expiry')
            if isinstance(exp, _dt.date):
                if exp >= today:
                    expiries.add(exp)
            elif isinstance(exp, str):
                try:
                    dtp = _dt.datetime.strptime(exp[:10], '%Y-%m-%d').date()
                    if dtp >= today:
                        expiries.add(dtp)
                except Exception:
                    pass
        sorted_dates = sorted(expiries)
        if not sorted_dates:
            if instruments:
                # Do not fabricate based on weekday; return empty and let upstream logic handle it.
                logger.warning("no_expiries_extracted_from_instruments index=%s", index_symbol)
                sorted_dates = []
            else:
                logger.warning("empty_instrument_universe_no_expiries index=%s", index_symbol)
                sorted_dates = []
        provider._state.expiry_dates_cache[index_symbol] = sorted_dates
        return sorted_dates
    except Exception as e:
        if _is_auth_error(e) or str(e) == 'kite_auth_failed':
            provider._auth_failed = True
            if provider._rl_fallback():
                logger.warning("Kite auth failed; using synthetic expiry dates.")
            # Do not fabricate dates here; return empty and let callers handle gracefully
            provider._state.expiry_dates_cache[index_symbol] = []
            return []
        logger.error("Failed to get expiry dates: %s", e, exc_info=True)
        if handle_data_collection_error:
            try:
                handle_data_collection_error(e, component="kite_provider.get_expiry_dates", index_name=index_symbol, data_type="expiries")
            except Exception:
                pass
        # Avoid weekday-based fabrication; return empty list
        return []


def get_weekly_expiries(provider, index_symbol: str) -> list[_dt.date]:
    try:
        all_exp = get_expiry_dates(provider, index_symbol)
        return all_exp[:2] if len(all_exp) >= 2 else all_exp
    except Exception:
        return []


def get_monthly_expiries(provider, index_symbol: str) -> list[_dt.date]:
    try:
        all_exp = get_expiry_dates(provider, index_symbol)
        today = _dt.date.today()
        by_month: dict[tuple[int,int], list[_dt.date]] = {}
        for d in all_exp:
            if d >= today:
                by_month.setdefault((d.year, d.month), []).append(d)
        out: list[_dt.date] = []
        for _, vals in sorted(by_month.items()):
            out.append(max(vals))
        return out
    except Exception:
        return []


__all__ = [
    'get_atm_strike',
    'get_expiry_dates',
    'get_weekly_expiries',
    'get_monthly_expiries',
]
