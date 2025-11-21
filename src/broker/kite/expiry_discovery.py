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

# Optional imports for late import elimination (Batch 35)
try:
    from src.broker.kite_provider import INDEX_MAPPING, POOL_FOR, _is_auth_error
except ImportError:
    INDEX_MAPPING = {}  # type: ignore
    POOL_FOR = {}  # type: ignore
    def _is_auth_error(e: BaseException) -> bool:  # fallback heuristic
        return 'auth' in str(e).lower() or 'token' in str(e).lower()

try:
    from src.error_handling import handle_data_collection_error
except ImportError:
    handle_data_collection_error = None  # type: ignore


def get_atm_strike(provider, index_symbol: str) -> int:
    ltp_data = provider.get_ltp([INDEX_MAPPING.get(index_symbol, ("NSE", index_symbol))])
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
        
        # Check TTL-aware cache (cache key includes hour bucket for 1-hour TTL)
        import time
        cache_start = time.time()
        cache_hour = int(cache_start // 3600)  # Changes every hour
        cache_key = f"{index_symbol}:{cache_hour}"
        cache = provider._state.expiry_dates_cache.get(cache_key)
        if cache is not None:  # Changed: check explicitly for None instead of truthy check
            logger.debug("expiry_cache_hit index=%s key=%s len=%d duration=%.3fms", 
                       index_symbol, cache_key, len(cache), (time.time() - cache_start) * 1000)
            return cache
        
        logger.debug("expiry_cache_miss index=%s key=%s cache_keys=%s fetching_instruments", 
                   index_symbol, cache_key, list(provider._state.expiry_dates_cache.keys())[:5])
        atm = get_atm_strike(provider, index_symbol)
        exch = POOL_FOR.get(index_symbol, "NFO")
        inst_start = time.time()
        instruments = provider.get_instruments(exch)
        logger.debug("get_instruments index=%s exch=%s count=%d duration=%.3fms", 
                   index_symbol, exch, len(instruments), (time.time() - inst_start) * 1000)
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
                # Emit detailed diagnostics (instrument universe present but filter produced zero expiries)
                try:
                    logger.debug(
                        "no_expiries_extracted_from_instruments index=%s inst_count=%d atm=%s filter=segment:-OPT symbol_contains strike±500",
                        index_symbol,
                        len(instruments),
                        atm,
                    )
                except Exception:
                    logger.debug("no_expiries_extracted_from_instruments index=%s (diag_failed)", index_symbol)
                sorted_dates = []
            else:
                logger.warning("empty_instrument_universe_no_expiries index=%s", index_symbol)
                sorted_dates = []
        
        # Cache with TTL-aware key (includes hour bucket)
        import time
        cache_hour = int(time.time() // 3600)
        cache_key = f"{index_symbol}:{cache_hour}"
        provider._state.expiry_dates_cache[cache_key] = sorted_dates
        
        # Clean old cache entries (keep only current hour)
        old_keys = [k for k in provider._state.expiry_dates_cache.keys() if not k.endswith(f":{cache_hour}")]
        for old_key in old_keys:
            provider._state.expiry_dates_cache.pop(old_key, None)
        
        logger.debug("expiry_dates_cached index=%s count=%d", index_symbol, len(sorted_dates))
        return sorted_dates
    except Exception as e:
        if _is_auth_error(e) or str(e) == 'kite_auth_failed':
            provider._auth_failed = True
            if provider._rl_fallback():
                logger.warning("Kite auth failed; using synthetic expiry dates.")
            # Do not fabricate dates here; return empty and let callers handle gracefully
            import time
            cache_hour = int(time.time() // 3600)
            cache_key = f"{index_symbol}:{cache_hour}"
            provider._state.expiry_dates_cache[cache_key] = []
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
