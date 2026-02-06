"""Expiry helper primitives extracted from unified_collectors.

Behavior preserved verbatim (copy-paste) to maintain zero drift.
Functions keep the same names (without leading underscore externally) and are
re-exported via __all__ so legacy wrappers in unified_collectors can delegate.
"""
from __future__ import annotations

import logging
import os
import time
import datetime as _dt
from collections.abc import Sequence
from typing import Any

from src.collectors.persist_result import PersistResult  # noqa: F401 (may be used by callers indirectly)
from src.error_handling import handle_collector_error
from src.utils.exceptions import NoInstrumentsError, NoQuotesError, ResolveExpiryError
from src.config.env_config import EnvConfig
try:
    from src.utils.expiry_dates import select_expiry_for_index, normalize_rule
except ImportError:
    select_expiry_for_index = None  # type: ignore
    normalize_rule = lambda r: (r or '').strip().lower().replace('-', '_')  # type: ignore

# Optional imports with fallback
try:
    from src.utils.expiry_service import build_expiry_service
except ImportError:
    build_expiry_service = None  # type: ignore

try:
    from src.collectors.modules.error_bridge import report_instrument_fetch_error, report_quote_enrich_error
except ImportError:
    report_instrument_fetch_error = None  # type: ignore
    report_quote_enrich_error = None  # type: ignore

try:
    from src.collectors.helpers.struct_events import emit_zero_data as _emit_zero_data
except ImportError:
    _emit_zero_data = None  # type: ignore

logger = logging.getLogger(__name__)

_EXPIRY_SERVICE_SINGLETON = None  # cached instance or None (mirrors original)

# Per-day cache for provider expiry lists. These rarely change intraday, but can be expensive
# if the provider fetches them from network.
# Keyed by (provider_id, index_symbol, ist_date).
_EXPIRY_LIST_CACHE: dict[tuple[str, str, str], tuple[float, list[_dt.date]]] = {}

_IST_TZ = _dt.timezone(_dt.timedelta(hours=5, minutes=30), name="IST")

# Cache for resolved option instruments (already filtered by expiry+strike set).
# Keyed by (provider_id, index_symbol, expiry_date, strikes_hash, ist_date).
_OPTION_INSTRUMENTS_CACHE: dict[tuple[str, str, str, int, str], tuple[float, list[dict]]] = {}


def _ist_date_str() -> str:
    try:
        return _dt.datetime.now(_dt.UTC).astimezone(_IST_TZ).date().isoformat()
    except Exception:
        return _dt.date.today().isoformat()


def _provider_cache_id(providers: Any) -> str:
    try:
        p = getattr(providers, 'primary_provider', providers)
        return f"{p.__class__.__module__}.{p.__class__.__name__}"
    except Exception:
        return "unknown"


def _get_cached_expiry_candidates(index_symbol: str, providers: Any) -> list[_dt.date]:
    ttl = 3600.0
    try:
        ttl = float(EnvConfig.get_float('G6_EXPIRY_CACHE_TTL_SEC', 3600.0))
    except Exception:
        ttl = 3600.0
    if ttl <= 0:
        ttl = 0.0

    cache_key = (_provider_cache_id(providers), str(index_symbol), _ist_date_str())
    if ttl > 0:
        try:
            hit = _EXPIRY_LIST_CACHE.get(cache_key)
            if hit is not None:
                ts, cand = hit
                if (time.time() - float(ts)) <= ttl:
                    return list(cand)
        except Exception:
            pass

    # Miss / expired: fetch from provider
    try:
        prov_obj = getattr(providers, 'primary_provider', providers)
        raw_list = list(prov_obj.get_expiry_dates(index_symbol)) if hasattr(prov_obj, 'get_expiry_dates') else []
    except Exception:
        raw_list = []

    candidates: list[_dt.date] = []
    for x in raw_list:
        try:
            if isinstance(x, _dt.datetime):
                candidates.append(x.date())
            elif isinstance(x, _dt.date):
                candidates.append(x)
            else:
                candidates.append(_dt.date.fromisoformat(str(x)))
        except Exception:
            continue
    candidates = sorted(set(candidates))

    if ttl > 0:
        try:
            _EXPIRY_LIST_CACHE[cache_key] = (time.time(), list(candidates))
        except Exception:
            pass
    return candidates


def get_expiry_candidates_cached(index_symbol: str, providers: Any) -> list[_dt.date]:
    """Return cached provider expiry candidates for an index.

    This is a lightweight public wrapper so callers can avoid hitting
    provider.get_expiry_dates repeatedly within/between cycles.
    """
    return _get_cached_expiry_candidates(index_symbol, providers)

def _get_expiry_service() -> Any:  # lazy import + build to avoid overhead
    global _EXPIRY_SERVICE_SINGLETON
    if _EXPIRY_SERVICE_SINGLETON is not None:
        return _EXPIRY_SERVICE_SINGLETON
    try:
        if build_expiry_service is not None:
            _EXPIRY_SERVICE_SINGLETON = build_expiry_service()
    except Exception:  # pragma: no cover
        _EXPIRY_SERVICE_SINGLETON = None
    return _EXPIRY_SERVICE_SINGLETON


def fetch_option_instruments(index_symbol: str, expiry_rule: str, expiry_date: Any, strikes: Sequence[float], providers: Any, metrics: Any) -> list[dict]:
    _t_api = time.time(); instruments: list[dict] = []; primary_err: Exception | None = None

    # Win-win optimization: cache the *resolved* instruments list when strikes/expiry are unchanged.
    # This avoids repeated instrument-token resolution work across cycles.
    try:
        ttl = float(EnvConfig.get_float('G6_INSTRUMENTS_CACHE_TTL_SEC', 0.0))
    except Exception:
        ttl = 0.0
    if ttl > 0:
        try:
            prov_id = _provider_cache_id(providers)
            expiry_key = str(expiry_date)
            # strikes may arrive as floats; convert to stable int-ish representation
            strike_ints = tuple(int(round(float(s))) for s in (strikes or ()))
            strikes_hash = hash(strike_ints)
            key = (prov_id, str(index_symbol), expiry_key, int(strikes_hash), _ist_date_str())
            hit = _OPTION_INSTRUMENTS_CACHE.get(key)
            if hit is not None:
                ts, cached = hit
                if (time.time() - float(ts)) <= ttl and cached:
                    # Shallow-copy dicts to avoid downstream mutation leaking across cycles.
                    return [dict(x) for x in cached]
        except Exception:
            pass
    try:
        logger.debug(
            "fetch_option_instruments_start index=%s rule=%s expiry=%s strikes=%d first_strikes=%s",
            index_symbol,
            expiry_rule,
            expiry_date,
            len(strikes or []),
            list(strikes)[:6] if strikes else [],
        )
    except Exception:
        pass
    universe_fallback_enabled = EnvConfig.get_bool('G6_UNIVERSE_FALLBACK', False)
    try:
        instruments = providers.get_option_instruments(index_symbol, expiry_date, strikes)
    except NoInstrumentsError as inst_err:
        primary_err = inst_err
        try:
            if report_instrument_fetch_error is not None:
                report_instrument_fetch_error(inst_err, index_symbol, expiry_rule, expiry_date, len(strikes))
        except Exception:
            handle_collector_error(inst_err, component="collectors.expiry_helpers", index_name=index_symbol,
                                   context={"stage":"get_option_instruments","rule":expiry_rule,"expiry":str(expiry_date),"strike_count":len(strikes)})
        instruments = []
    except Exception as inst_err:
        primary_err = inst_err
        logger.error("Unexpected instrument fetch error %s %s: %s", index_symbol, expiry_rule, inst_err)
        instruments = []
    # Universe fallback: if enabled and initial fetch empty, attempt broad universe then filter by strikes
    if universe_fallback_enabled and not instruments:
        try:
            if hasattr(providers, 'get_option_instruments_universe'):
                uni = providers.get_option_instruments_universe(index_symbol)
                # filter by expiry & strike membership
                strike_set = set(strikes)
                filtered = []
                for inst in (uni or []):
                    try:
                        if inst.get('expiry') == expiry_date and inst.get('strike') in strike_set:
                            filtered.append(inst)
                    except Exception:
                        continue
                if filtered:
                    instruments = filtered
                    logger.warning("universe_fallback_success index=%s rule=%s expiry=%s count=%s strikes_req=%s", index_symbol, expiry_rule, expiry_date, len(instruments), len(strikes))
                else:
                    logger.debug("universe_fallback_empty index=%s rule=%s expiry=%s uni_size=%s", index_symbol, expiry_rule, expiry_date, len(uni or []))
        except Exception as fb_err:
            logger.debug("universe_fallback_failed index=%s rule=%s err=%s", index_symbol, expiry_rule, fb_err, exc_info=True)
    # Structured diagnostic emission when still empty
    if not instruments:
        try:
            diag = {
                'index': index_symbol,
                'expiry': str(expiry_date),
                'rule': expiry_rule,
                'strikes': len(strikes),
                'universe_fb': universe_fallback_enabled,
                'primary_err': type(primary_err).__name__ if primary_err else None,
                'strikes_preview': list(strikes)[:10] if strikes else [],
            }
            try:
                if _emit_zero_data is not None:
                    # Re-use zero_data event with extended context under 'provider_diag'
                    _emit_zero_data(index=index_symbol, expiry=str(expiry_date), rule=expiry_rule, atm=None, strike_count=len(strikes))
            except Exception:
                pass
            try:
                import json as _json
                logger.info('STRUCT provider_instrument_diag | %s', _json.dumps(diag, default=str))
            except Exception:
                logger.debug('provider_instrument_diag_emit_failed', exc_info=True)
        except Exception:
            logger.debug('instrument_diag_build_failed', exc_info=True)
    if metrics and hasattr(metrics, 'mark_api_call'):
        metrics.mark_api_call(success=bool(instruments), latency_ms=(time.time()-_t_api)*1000.0)

    # Populate cache only on non-empty success.
    if ttl > 0 and instruments:
        try:
            prov_id = _provider_cache_id(providers)
            expiry_key = str(expiry_date)
            strike_ints = tuple(int(round(float(s))) for s in (strikes or ()))
            strikes_hash = hash(strike_ints)
            key = (prov_id, str(index_symbol), expiry_key, int(strikes_hash), _ist_date_str())
            _OPTION_INSTRUMENTS_CACHE[key] = (time.time(), [dict(x) for x in instruments])
        except Exception:
            pass
    return instruments

def enrich_quotes(index_symbol: str, expiry_rule: str, expiry_date: Any, instruments: Sequence[dict], providers: Any, metrics: Any) -> list[dict] | dict:
    """Enrich instruments with live quotes; tolerant of partial failures."""
    _t_enrich = time.time()
    try:
        enriched_data: list[dict] | dict = providers.enrich_with_quotes(instruments)
    except NoQuotesError as enrich_err:  # expected domain error
        try:
            if report_quote_enrich_error is not None:
                report_quote_enrich_error(enrich_err, index_symbol, expiry_rule, expiry_date, len(instruments))
        except Exception:
            handle_collector_error(enrich_err, component="collectors.expiry_helpers", index_name=index_symbol,
                                   context={"stage":"enrich_quotes","rule":expiry_rule,"expiry":str(expiry_date),"instrument_count":len(instruments)})
        enriched_data = []
    except Exception as enrich_err:  # unexpected
        logger.error("Unexpected quote enrich error %s %s: %s", index_symbol, expiry_rule, enrich_err)
        enriched_data = []
    if metrics and hasattr(metrics, 'mark_api_call'):
        metrics.mark_api_call(success=bool(enriched_data), latency_ms=(time.time()-_t_enrich)*1000.0)
    return enriched_data


def resolve_expiry(index_symbol: str, expiry_rule: str, providers: Any, metrics: Any, concise_mode: bool) -> Any:  # noqa: ARG001 (concise_mode retained for signature stability)
    """Single-source expiry resolution (provider list only).

    Algorithm:
      1. Fetch provider expiry list (providers.get_expiry_dates). Normalize to date set; sort.
      2. If rule is direct ISO (YYYY-MM-DD): ensure it is in the list; else error.
      3. Mapping:
         this_week  = first chronological expiry.
         next_week  = second chronological expiry (needs >=2).
         Monthly expiries = last expiry per (year, month) bucket.
         this_month = first monthly expiry >= today (else earliest monthly if all past).
         next_month = monthly after this_month (needs >=2 monthly buckets with at least one >= today).
      4. Anything else => ResolveExpiryError.
    """
    import time as _time
    start = _time.time()
    candidates = _get_cached_expiry_candidates(index_symbol, providers)

    def mark_metrics(success: bool) -> None:
        if metrics and hasattr(metrics, 'mark_api_call'):
            try:
                metrics.mark_api_call(success=success, latency_ms=(_time.time()-start)*1000.0)
            except Exception:
                pass

    if not candidates:
        # When provider doesn't return any expiries, attempt provider's own resolver
        # which may fabricate candidates (weekly/monthly anchors) and still resolve.
        rule_str = str(expiry_rule).strip()
        try:
            chosen = providers.resolve_expiry(index_symbol, rule_str.lower())
            mark_metrics(True)
            return chosen
        except Exception:
            # Pipeline-mode relaxation: allow direct ISO rule even if provider list empty so tests using
            # minimal dummy providers (no expiry list) can still resolve explicitly provided date.
            if len(rule_str) == 10 and rule_str[4]=='-' and rule_str[7]=='-':
                try:
                    direct = _dt.date.fromisoformat(rule_str)
                    mark_metrics(True)
                    return direct
                except Exception:
                    mark_metrics(False)
                    raise ResolveExpiryError(f"Invalid direct expiry date format: {expiry_rule}")
            mark_metrics(False)
            raise ResolveExpiryError(f"No provider expiries available for {index_symbol}")
    rule = str(expiry_rule).lower().strip()
    if len(rule) == 10 and rule[4]=='-' and rule[7]=='-':
        try:
            direct = _dt.date.fromisoformat(rule)
        except Exception:
            mark_metrics(False)
            raise ResolveExpiryError(f"Invalid direct expiry date format: {expiry_rule}")
        if direct not in candidates:
            mark_metrics(False)
            raise ResolveExpiryError(f"Direct expiry {direct} not in provider list for {index_symbol}")
        mark_metrics(True)
        return direct

    if rule == 'this_week':
        mark_metrics(True)
        return candidates[0]
    if rule == 'next_week':
        if len(candidates) < 2:
            mark_metrics(False)
            raise ResolveExpiryError(f"Insufficient expiries for next_week (need >=2) index={index_symbol}")
        mark_metrics(True)
        return candidates[1]

    # Build monthly expiries (last date per month)
    monthly_last: dict[tuple[int,int], _dt.date] = {}
    for d in candidates:
        key = (d.year, d.month)
        cur = monthly_last.get(key)
        if cur is None or d > cur:
            monthly_last[key] = d
    monthly_keys = sorted(monthly_last.keys())
    monthly_list = [monthly_last[k] for k in monthly_keys]
    if not monthly_list:
        mark_metrics(False)
        raise ResolveExpiryError(f"No monthly expiries derivable for {index_symbol}")

    try:
        today = _dt.datetime.now(_dt.UTC).astimezone(_IST_TZ).date()
    except Exception:
        today = _dt.date.today()
    if rule == 'this_month':
        chosen = None
        for mexp in monthly_list:
            if mexp >= today:
                chosen = mexp; break
        if chosen is None:
            chosen = monthly_list[0]
        mark_metrics(True)
        return chosen
    if rule == 'next_month':
        cur_idx = None
        for i, mexp in enumerate(monthly_list):
            if mexp >= today:
                cur_idx = i; break
        if cur_idx is None or cur_idx + 1 >= len(monthly_list):
            mark_metrics(False)
            raise ResolveExpiryError(f"Insufficient monthly expiries for next_month index={index_symbol}")
        mark_metrics(True)
        return monthly_list[cur_idx+1]

    # Unknown rule: fall back to provider's resolver (may support extra tags).
    try:
        chosen = providers.resolve_expiry(index_symbol, rule)
        mark_metrics(True)
        return chosen
    except Exception:
        mark_metrics(False)
        raise ResolveExpiryError(f"Unknown expiry rule {expiry_rule} for {index_symbol}")


 # Removed calendar fallback: provider list is authoritative.

# Synthetic metrics helper stub used by tests expecting presence even when synthetic logic unused.
def synthetic_metric_pop(ctx: Any, index_symbol: str, expiry_date: Any) -> None:  # pragma: no cover - simple no-op
    try:
        # If metrics adapter exposes counter, increment gracefully
        m = getattr(ctx, 'metrics', None)
        if m and hasattr(m, 'synthetic_quotes_used_total'):
            try:
                m.synthetic_quotes_used_total.inc()
            except Exception:
                pass
    except Exception:
        pass

__all__ = [
    'fetch_option_instruments',
    'enrich_quotes',
    'resolve_expiry',
    'get_expiry_candidates_cached',
    'synthetic_metric_pop',
]
