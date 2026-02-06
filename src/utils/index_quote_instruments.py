"""Canonical mapping of index symbols to quote/ltp instrument identifiers.

Kite quote/LTP calls for indices typically use a tuple (exchange, tradingsymbol)
like ('NSE', 'NIFTY 50') rather than the root symbol ('NIFTY').

Other modules should import from here instead of duplicating literals.
"""

from __future__ import annotations

from typing import Final


INDEX_QUOTE_INSTRUMENT: Final[dict[str, tuple[str, str]]] = {
    "NIFTY": ("NSE", "NIFTY 50"),
    "BANKNIFTY": ("NSE", "NIFTY BANK"),
    "FINNIFTY": ("NSE", "NIFTY FIN SERVICE"),
    "MIDCPNIFTY": ("NSE", "NIFTY MIDCAP SELECT"),
    "SENSEX": ("BSE", "SENSEX"),
}


def get_index_quote_instrument(index_symbol: str) -> tuple[str, str]:
    s = (index_symbol or "").strip().upper()
    return INDEX_QUOTE_INSTRUMENT.get(s, ("NSE", s or "NSE"))


__all__ = ["INDEX_QUOTE_INSTRUMENT", "get_index_quote_instrument"]
