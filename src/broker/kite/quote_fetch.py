"""Real quote fetch orchestration (A7 Step 8 extraction).

Encapsulates normalization, cache fast path, optional batching, rate limiting,
and cache population. Mirrors original inline logic from quotes.get_quote.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from typing import Any

from src.config.env_config import EnvConfig

from . import quote_cache
from .quotes import _normalize_instruments  # reuse helper

# Optional imports hoisted to module top
try:
    from src.broker.kite_provider import _timed_call  # lazy import
except ImportError:
    _timed_call = None  # type: ignore

try:
    from src.utils.env_flags import is_truthy_env  # type: ignore
except Exception:  # pragma: no cover
    def is_truthy_env(_name: str) -> bool:  # type: ignore
        return False

try:
    from .quote_batcher import batching_enabled, get_batcher  # type: ignore[assignment]
except Exception:  # pragma: no cover
    def batching_enabled() -> bool: return False  # type: ignore
    def get_batcher():  # type: ignore
        raise RuntimeError('batcher_unavailable')

try:
    from .rate_limit import RateLimitedError, build_default_rate_limiter  # type: ignore
except Exception:  # pragma: no cover
    build_default_rate_limiter = None  # type: ignore
    class RateLimitedError(RuntimeError): ...  # type: ignore

logger = logging.getLogger(__name__)

def fetch_real_quotes(provider, instruments: Iterable) -> dict | None:
    kite = getattr(provider, 'kite', None)
    if kite is None:
        return None
    formatted = _normalize_instruments(instruments)
    if not formatted:
        return None
    # Cache TTL from env
    cache_ttl = EnvConfig.get_float('G6_KITE_QUOTE_CACHE_SECONDS', 1.0)
    if cache_ttl < 0:
        cache_ttl = 0
    if cache_ttl > 0:
        aggregate_cached: dict[str, Any] = {}
        all_hit = True
        for sym in formatted:
            cached = quote_cache.get(sym, cache_ttl)
            if cached is None:
                all_hit = False
                break
            aggregate_cached[sym] = cached
        if all_hit and aggregate_cached:
            try:
                provider._last_quotes_synthetic = False
            except Exception:
                pass
            return aggregate_cached
    # Optional batching & limiter
    limiter = None
    if build_default_rate_limiter and is_truthy_env('G6_KITE_LIMITER'):
        limiter = getattr(provider, '_g6_quote_rate_limiter', None)
        if limiter is None:
            try:
                limiter = build_default_rate_limiter()
                provider._g6_quote_rate_limiter = limiter
            except Exception:
                limiter = None

    def _direct_fetch() -> Any:
        rl = getattr(provider, '_api_rl', None)
        if callable(rl):
            rl()
        if limiter is not None:
            try:
                limiter.acquire()
            except RateLimitedError:
                raise
        if _timed_call is not None:
            return _timed_call(lambda: kite.quote(formatted), getattr(provider._settings, 'kite_timeout_sec', 5.0))
        else:
            return kite.quote(formatted)

    def _fetch_with_batch() -> Any:
        if batching_enabled():
            try:
                batcher = get_batcher()
                return batcher.fetch(provider, formatted)
            except Exception:
                return _direct_fetch()
        return _direct_fetch()

    from src.utils.retry import call_with_retry
    try:
        raw = call_with_retry(_fetch_with_batch)
        if limiter is not None:
            try:
                limiter.record_success()
            except Exception:
                pass
    except Exception as e:
        # Record rate limit errors for cooldown tracking
        if limiter is not None:
            try:
                msg = str(e).lower()
                if 'too many requests' in msg or 'rate limit' in msg or '429' in msg:
                    limiter.record_rate_limit_error()
            except Exception:
                pass
        raise
    if cache_ttl > 0:
        try:
            quote_cache.put(raw, cache_ttl)
        except Exception:
            pass
    try:
        provider._last_quotes_synthetic = False
    except Exception:
        pass
    return raw

__all__ = ['fetch_real_quotes']
