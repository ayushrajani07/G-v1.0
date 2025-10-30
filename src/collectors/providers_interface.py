#!/usr/bin/env python3
"""
Providers Interface for G6 Options Trading Platform.
Serves as a facade for the various data providers.
"""

import datetime
import logging
import os
import time as _time

from src.metrics.generated import (
    m_api_calls_total_labels,
    m_api_response_latency_ms,
    m_expiry_resolve_fail_total_labels,
    m_index_zero_price_fallback_total_labels,
    m_quote_avg_price_fallback_total_labels,
    m_quote_enriched_total_labels,
    m_quote_missing_volume_oi_total_labels,
)

try:
    from src.broker.kite_provider import is_concise_logging as _is_concise_logging  # type: ignore
except Exception:  # pragma: no cover
    def _is_concise_logging():  # type: ignore
        return os.environ.get('G6_CONCISE_LOGS', '1').lower() not in ('0','false','no','off')
try:  # Prometheus client optional during some tests
    from prometheus_client import Counter as _C
    from prometheus_client import Histogram as _H
except Exception:  # pragma: no cover
    class _Dummy:  # noqa: D401
        def __init__(self,*a,**k): pass
        def labels(self,*a,**k): return self
        def inc(self,*a,**k): pass
        def observe(self,*a,**k): pass
    _C=_H=_Dummy

# Module imports (moved from late imports)
from src.utils.exceptions import ResolveExpiryError
from src.utils.env_flags import is_truthy_env
from src.broker.kite.tracing import trace
from src.metrics.emitter import metric_batcher

# Add this before launching the subprocess

logger = logging.getLogger(__name__)

# Global concise mode detection delegated to provider helper
_CONCISE = _is_concise_logging()

def _safe_inc(lbl, amount=1):  # helper to tolerate label None or unexpected metric type
    try:
        if lbl:
            lbl.inc(amount)  # type: ignore[attr-defined]
    except Exception:
        pass

class Providers:
    """Interface for all data providers."""

    def __init__(self, primary_provider=None, secondary_provider=None):
        """
        Initialize providers interface.
        
        Args:
            primary_provider: Primary data provider (e.g., KiteProvider)
            secondary_provider: Secondary provider for fallback
        """
        self.primary_provider = primary_provider
        self.secondary_provider = secondary_provider
        self.logger = logger

        # Log which providers are being used
        provider_names = []
        if primary_provider:
            provider_class = primary_provider.__class__.__name__
            provider_names.append(provider_class)
        if secondary_provider:
            provider_class = secondary_provider.__class__.__name__
            provider_names.append(provider_class)
        # Downgrade to DEBUG; startup banner covers provider summary
        self.logger.debug("Providers initialized with: %s", ', '.join(provider_names))
        # Early metrics init so counters/gauges appear even before first enrichment
        # Deprecated metrics init removed (spec-driven metrics register lazily when first used)

    def close(self):
        """Close all providers."""
        if self.primary_provider:
            self.primary_provider.close()
        if self.secondary_provider:
            self.secondary_provider.close()

    def get_index_data(self, index_symbol):
        """
        Get index price and OHLC data.
        
        Args:
            index_symbol: Index symbol (e.g., 'NIFTY')
        
        Returns:
            Tuple of (price, ohlc_data)
        """
        try:
            # Format for Quote API
            if index_symbol == "NIFTY":
                instruments = [("NSE", "NIFTY 50")]
                self.logger.debug("INDEX_PATH mapping=NIFTY use_quote_endpoint")
            elif index_symbol == "BANKNIFTY":
                instruments = [("NSE", "NIFTY BANK")]
                self.logger.debug("INDEX_PATH mapping=BANKNIFTY use_quote_endpoint")
            elif index_symbol == "FINNIFTY":
                instruments = [("NSE", "NIFTY FIN SERVICE")]
                self.logger.debug("INDEX_PATH mapping=FINNIFTY use_quote_endpoint")
            elif index_symbol == "MIDCPNIFTY":
                instruments = [("NSE", "NIFTY MIDCAP SELECT")]
                self.logger.debug("INDEX_PATH mapping=MIDCPNIFTY use_quote_endpoint")
            elif index_symbol == "SENSEX":
                instruments = [("BSE", "SENSEX")]
                self.logger.debug("INDEX_PATH mapping=SENSEX use_quote_endpoint")
            else:
                instruments = [("NSE", index_symbol)]
                self.logger.debug("INDEX_PATH mapping=GENERIC symbol=%s", index_symbol)

            # Get quote from primary provider (includes OHLC) if available
            quotes = {}
            if self.primary_provider and hasattr(self.primary_provider, 'get_quote'):
                try:
                    self.logger.debug("INDEX_PATH attempt=get_quote provider=%s", type(self.primary_provider).__name__)
                    quotes = self.primary_provider.get_quote(instruments)  # type: ignore
                except Exception as qe:
                    self.logger.warning("get_quote failed, will fallback to LTP: %s", qe)
            else:
                # Avoid noisy error spam; debug is sufficient because we can fallback to LTP
                if not self.primary_provider:
                    self.logger.error("Primary provider not initialized")
                    return 0, {}
                self.logger.debug("Primary provider missing get_quote, using LTP fallback")

            # Extract price and OHLC
            for key, quote in quotes.items():
                price = quote.get('last_price', 0)
                ohlc = quote.get('ohlc', {})
                if price == 0:
                    # Instrumentation: unexpected zero (mock provider should give >0)
                    try:
                        self.logger.warning(
                            "get_index_data instrumentation: zero price from quote key=%s provider=%s", key, type(self.primary_provider).__name__
                        )
                    except Exception:
                        pass
                    # Synthetic fallback price injection (single pass) to keep pipeline moving
                    synth_map = {
                        'NIFTY': 24800.0,
                        'BANKNIFTY': 54000.0,
                        'FINNIFTY': 26000.0,
                        'MIDCPNIFTY': 12000.0,
                        'SENSEX': 81000.0,
                    }
                    if index_symbol in synth_map:
                        price = synth_map[index_symbol]
                        if isinstance(ohlc, dict) and not ohlc:
                            # Provide minimal OHLC so downstream doesn't misinterpret emptiness as data absence
                            base = price
                            ohlc = {'open': base, 'high': base * 1.001, 'low': base * 0.999, 'close': base}
                        self.logger.debug("Injected synthetic index price for %s: %s", index_symbol, price)
                        lbl = m_index_zero_price_fallback_total_labels(index_symbol, 'quote')
                        _safe_inc(lbl)

                if _CONCISE:
                    self.logger.debug("Index data for %s: Price=%s, OHLC=%s", index_symbol, price, ohlc)
                else:
                    self.logger.info("Index data for %s: Price=%s, OHLC=%s", index_symbol, price, ohlc)
                return price, ohlc

            # Fall back to LTP if quote doesn't have OHLC
            if not self.primary_provider or not hasattr(self.primary_provider, 'get_ltp'):
                self.logger.error("Primary provider not initialized or missing get_ltp for fallback")
                return 0, {}
            self.logger.debug("INDEX_PATH attempt=get_ltp provider=%s", type(self.primary_provider).__name__)
            ltp_data = {}
            try:
                ltp_data = self.primary_provider.get_ltp(instruments)  # type: ignore
            except Exception as le:
                self.logger.error("get_ltp fallback failed: %s", le)
                return 0, {}

            for key, data in ltp_data.items():
                price = data.get('last_price', 0)
                if price == 0:
                    try:
                        self.logger.warning("get_index_data instrumentation: zero price from LTP key=%s provider=%s", key, type(self.primary_provider).__name__)
                    except Exception:
                        pass
                    synth_map = {
                        'NIFTY': 24800.0,
                        'BANKNIFTY': 54000.0,
                        'FINNIFTY': 26000.0,
                        'MIDCPNIFTY': 12000.0,
                        'SENSEX': 81000.0,
                    }
                    if index_symbol in synth_map:
                        price = synth_map[index_symbol]
                        self.logger.debug("Injected synthetic LTP for %s: %s", index_symbol, price)
                        lbl = m_index_zero_price_fallback_total_labels(index_symbol, 'ltp')
                        _safe_inc(lbl)
                if _CONCISE:
                    self.logger.debug("LTP for %s: %s", index_symbol, price)
                else:
                    self.logger.info("LTP for %s: %s", index_symbol, price)
                return price, {}

            self.logger.error("No index data returned for %s", index_symbol)
            return 0, {}

        except Exception as e:
            self.logger.error("Error getting index data: %s", e)
            try:
                self.logger.warning("get_index_data instrumentation: exception path provider=%s index=%s err=%s", type(getattr(self, 'primary_provider', None)).__name__, index_symbol, e)
            except Exception:
                pass
            return 0, {}

    def get_ltp(self, index_symbol):
        """
        Get last traded price for an index.
        
        Args:
            index_symbol: Index symbol (e.g., 'NIFTY')
        
        Returns:
            Float: Last traded price
        """
        try:
            # Get index price and OHLC
            price, _ = self.get_index_data(index_symbol)

            # Calculate ATM strike based on index
            if index_symbol in ["BANKNIFTY", "SENSEX"]:
                # Round to nearest 100
                atm_strike = round(float(price) / 100) * 100
            else:
                # Round to nearest 50
                atm_strike = round(float(price) / 50) * 50

            if _CONCISE:
                self.logger.debug("LTP for %s: %s", index_symbol, price)
                self.logger.debug("ATM strike for %s: %s", index_symbol, atm_strike)
            else:
                self.logger.info("LTP for %s: %s", index_symbol, price)
                self.logger.info("ATM strike for %s: %s", index_symbol, atm_strike)

            return atm_strike

        except Exception as e:
            self.logger.error("Error getting LTP: %s", e)
            return 20000 if index_symbol == "BANKNIFTY" else 22000

    def get_atm_strike(self, index_symbol: str):
        """Return an approximate ATM strike for the index.

        Reuses get_ltp rounding logic (already produces the rounded strike).
        Provided for analytics compatibility (OptionChainAnalytics expects this).
        """
        try:
            return self.get_ltp(index_symbol)
        except Exception as e:  # pragma: no cover
            self.logger.error("Error computing ATM strike: %s", e)
            return 0

    # ---- Compatibility aliases expected by analytics modules ----
    def option_instruments(self, index_symbol, expiry_date, strikes):  # noqa: D401
        """Alias to get_option_instruments / option instruments provider API.

        Prefer primary provider's native method when available, else fall back to
        internal resolution chain via get_option_instruments().
        """
        try:
            if self.primary_provider and hasattr(self.primary_provider, 'option_instruments'):
                return self.primary_provider.option_instruments(index_symbol, expiry_date, strikes)  # type: ignore
            return self.get_option_instruments(index_symbol, expiry_date, strikes)
        except Exception as e:  # pragma: no cover
            self.logger.error("option_instruments alias failure: %s", e)
            return []

    def resolve_expiry(self, index_symbol, expiry_rule):
        """Resolve an expiry date for an index using provider facilities.

        Behavior:
        - If the primary provider exposes a native resolve_expiry, delegate to it.
        - Otherwise, fall back to candidate-based selection by fetching a list of
          expiry candidates from the provider (e.g., get_expiry_dates) and apply
          the universal selection logic (rule semantics handled centrally).
        - If the rule looks like an ISO date (YYYY-MM-DD), pass it through directly
          when possible.
        """
        # Lazy import to avoid circulars at module import time
        try:
            from src.utils.expiry_dates import select_expiry_for_index  # type: ignore
        except Exception as _e:  # pragma: no cover
            self.logger.error("Failed to import universal expiry selector: %s", _e)
            raise ResolveExpiryError("Expiry selector unavailable")

        try:
            # 1) Native resolver on provider, if available
            if self.primary_provider and hasattr(self.primary_provider, 'resolve_expiry'):
                return self.primary_provider.resolve_expiry(index_symbol, expiry_rule)  # type: ignore[attr-defined]

            # 2) ISO passthrough: allow direct date input
            try:
                import datetime as _dt
                if isinstance(expiry_rule, str) and len(expiry_rule) == 10 and expiry_rule[4] == '-' and expiry_rule[7] == '-':
                    # validate parse
                    return _dt.date.fromisoformat(expiry_rule)
            except Exception:
                pass

            # 3) Candidate list fallback (e.g., get_expiry_dates from provider stubs)
            candidates = []
            try:
                if self.primary_provider and hasattr(self.primary_provider, 'get_expiry_dates'):
                    candidates = list(self.primary_provider.get_expiry_dates(index_symbol))  # type: ignore[attr-defined]
            except Exception:
                candidates = []

            if candidates:
                return select_expiry_for_index(index_symbol, candidates, expiry_rule)

            # No path succeeded
            lbl = m_expiry_resolve_fail_total_labels(index_symbol, str(expiry_rule).lower(), 'no_candidates')
            _safe_inc(lbl)
            raise ResolveExpiryError("No resolver or candidate list available on primary provider")

        except ResolveExpiryError:
            raise
        except Exception as e:  # pragma: no cover - defensive
            self.logger.error("Error resolving expiry (universal): %s", e)
            lbl = m_expiry_resolve_fail_total_labels(index_symbol, str(expiry_rule).lower(), 'exception')
            _safe_inc(lbl)
            raise ResolveExpiryError(f"Failed to resolve expiry for {index_symbol} using rule '{expiry_rule}': {e}")

    def get_option_instruments(self, index_symbol, expiry_date, strikes):
        """
        Get option instruments for specific expiry and strikes.
        
        Args:
            index_symbol: Index symbol (e.g., 'NIFTY')
            expiry_date: Expiry date
            strikes: List of strike prices
        
        Returns:
            List of option instruments
        """
        try:
            # Try get_option_instruments first
            if hasattr(self.primary_provider, 'get_option_instruments'):
                if not self.primary_provider or not hasattr(self.primary_provider, 'get_option_instruments'):
                    self.logger.error("Primary provider missing get_option_instruments")
                    return []
                instruments = self.primary_provider.get_option_instruments(index_symbol, expiry_date, strikes)  # type: ignore
                if instruments:
                    return instruments

            # Fallback to option_instruments if available
            if hasattr(self.primary_provider, 'option_instruments'):
                if not self.primary_provider or not hasattr(self.primary_provider, 'option_instruments'):
                    self.logger.error("Primary provider missing option_instruments")
                    return []
                instruments = self.primary_provider.option_instruments(index_symbol, expiry_date, strikes)  # type: ignore
                if instruments:
                    return instruments

            self.logger.error("Error getting option instruments from primary provider")

            # Emergency fallback - return empty list
            return []

        except Exception as e:
            self.logger.error("Error getting option instruments: %s", e)
            return []

    def get_quote(self, instruments):
        """
        Get quotes for a list of instruments.
        
        Args:
            instruments: List of (exchange, symbol) tuples
        
        Returns:
            Dict of quotes keyed by "exchange:symbol"
        """
        try:
            if hasattr(self.primary_provider, 'get_quote'):
                if not self.primary_provider or not hasattr(self.primary_provider, 'get_quote'):
                    self.logger.error("Primary provider missing get_quote for index quotes")
                    return {}
                return self.primary_provider.get_quote(instruments)  # type: ignore
            return {}
        except Exception as e:
            self.logger.error("Error getting quotes: %s", e)
            return {}

    def enrich_with_quotes(self, instruments):
        """
        Enrich option instruments with quotes data.
        
        Args:
            instruments: List of option instruments
        
        Returns:
            Dict of enriched instruments keyed by symbol
        """
        try:
            quote_instruments = []
            for instrument in instruments:
                symbol = instrument.get('tradingsymbol', '')
                exchange = instrument.get('exchange', 'NFO')
                if symbol:
                    quote_instruments.append((exchange, symbol))
            try:  # centralized trace
                trace('quote_request', count=len(quote_instruments), sample=quote_instruments[:6])
            except Exception:
                pass
            if not self.primary_provider or not hasattr(self.primary_provider, 'get_quote'):
                self.logger.error("Primary provider missing get_quote for option quotes")
                return {}
            q_start = _time.time()
            quotes = self.primary_provider.get_quote(quote_instruments)  # type: ignore
            try:
                lat_ms = max((_time.time()-q_start)*1000.0,0.0)
                hist = m_api_response_latency_ms()
                if hist:
                    try:
                        hist.observe(lat_ms)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                lbl = m_api_calls_total_labels('get_quote','success')
                _safe_inc(lbl)
            except Exception:
                pass
            try:
                sample_keys = list(quotes.keys())[:6]
                trace('quote_response', received=len(quotes), sample_keys=sample_keys)
            except Exception:
                pass
            enriched_data = {}
            enriched_count = 0
            missing_volume_oi = 0
            avg_price_fallback = 0
            for instrument in instruments:
                symbol = instrument.get('tradingsymbol', '')
                exchange = instrument.get('exchange', 'NFO')
                key = f"{exchange}:{symbol}"
                enriched = instrument.copy()
                if key in quotes:
                    quote = quotes[key]
                    enriched['last_price'] = quote.get('last_price', 0)
                    enriched['volume'] = quote.get('volume', 0)
                    enriched['oi'] = quote.get('oi', 0)
                    enriched['avg_price'] = quote.get('average_price', 0)
                    enriched['avg_price_fallback_used'] = False
                    if (not enriched['avg_price'] or enriched['avg_price'] == 0) and 'ohlc' in quote:
                        ohlc = quote.get('ohlc', {}) or {}
                        try:
                            high = float(ohlc.get('high') or 0)
                            low = float(ohlc.get('low') or 0)
                            last_p = float(quote.get('last_price') or 0)
                            if high > 0 and low > 0:
                                fallback = 0.0
                                fallback = (high + low + 2 * last_p) / 4.0 if last_p > 0 else (high + low) / 2.0
                                if fallback > 0:
                                    enriched['avg_price'] = fallback
                                    enriched['avg_price_fallback_used'] = True
                                    avg_price_fallback += 1  # fixed indentation bug so counter increments
                        except Exception:
                            pass
                    if 'depth' in quote:
                        enriched['depth'] = quote.get('depth')
                    enriched_count += 1
                    if (not enriched.get('volume') and not enriched.get('oi')):
                        missing_volume_oi += 1
                enriched_data[symbol] = enriched
            try:
                if enriched_count:
                    prov = _active_provider_name(self)
                    # Prefer batching if enabled
                    try:
                        metric_batcher.inc(m_quote_enriched_total_labels, enriched_count, prov)
                        if missing_volume_oi:
                            metric_batcher.inc(m_quote_missing_volume_oi_total_labels, missing_volume_oi, prov)
                        if avg_price_fallback:
                            metric_batcher.inc(m_quote_avg_price_fallback_total_labels, avg_price_fallback, prov)
                    except Exception:
                        le = m_quote_enriched_total_labels(prov); _safe_inc(le, enriched_count)
                        if missing_volume_oi:
                            lm = m_quote_missing_volume_oi_total_labels(prov); _safe_inc(lm, missing_volume_oi)
                        if avg_price_fallback:
                            lf = m_quote_avg_price_fallback_total_labels(prov); _safe_inc(lf, avg_price_fallback)
                    if os.environ.get('G6_PROVIDER_METRICS_DEBUG'):
                        self.logger.debug(
                            "[prov-metrics] enriched_count=%s missing_vol_oi=%s avg_price_fb=%s provider=%s", enriched_count, missing_volume_oi, avg_price_fallback, prov
                        )
            except Exception:
                pass
            return enriched_data
        except Exception as e:
            import traceback
            tb = traceback.format_exc(limit=2)
            self.logger.error("Error enriching instruments with quotes: %s tb=%s", e, tb.strip().replace('\n', ' | '))
            basic_data = {}
            for instrument in instruments:
                symbol = instrument.get('tradingsymbol', '')
                if symbol:
                    basic_data[symbol] = instrument
            return basic_data


# ---------------------------------------------------------------------------
# Backward compatibility shim
# Historical test code imports ProvidersInterface; retain alias to Providers.
# ---------------------------------------------------------------------------
class ProvidersInterface(Providers):  # pragma: no cover - thin alias
    """Backward-compatible alias of Providers.

    Older tests or modules may still import ProvidersInterface. The primary
    implementation class was renamed to Providers; functionality is identical.
    """
    pass

__all__ = [
    'Providers',
    'ProvidersInterface',
]

# ------------------ Metrics Helpers (provider instrumentation) ------------------
# ------------------ Metrics Helpers (provider instrumentation) ------------------
def _active_provider_name(providers) -> str:  # noqa: D401
    try:
        if getattr(providers, 'primary_provider', None):
            return type(providers.primary_provider).__name__
    except Exception:
        pass
    return 'unknown'

def _ensure_provider_metrics():
    """Deprecated no-op retained for backward compatibility with older imports."""
    return

def _record_api_call(endpoint: str, result: str):  # deprecated compatibility shim
    lbl = m_api_calls_total_labels(endpoint, result)
    _safe_inc(lbl)
