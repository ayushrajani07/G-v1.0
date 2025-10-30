"""Expiry resolver placeholder (Phase 4 A7).

Future responsibilities:
- Extract expiries from instrument universe
- Fabricate synthetic expiries under defined conditions
- Rule resolution (delegating to existing expiries logic initially)

Current stub supplies empty lists to avoid implying completeness.
"""
from __future__ import annotations

import datetime as _dt
import logging
import time
from collections.abc import Callable, Iterable
from typing import Any

from .logging_events import emit_event

logger = logging.getLogger(__name__)

class ExpiryResolver:
    """Thin wrapper around broker/provider discovery of expiry candidates.

    Design goals:
    - Prefer a single candidate fetch path (provider.get_expiry_dates via a callable)
    - Maintain backward compatibility: fall back to instrument scraping when needed
    - Keep a small cache with TTL to avoid repeatedly asking the broker
    - Preserve legacy fabrication behavior for tests when instruments exist but
      no expiries are extractable
    """

    def __init__(self) -> None:
        self._cache: dict[str, list[_dt.date]] = {}
        self._cache_meta: dict[str, float] = {}
        self._last_log_ts: float = 0.0

    def _allow_log(self, interval: float = 5.0) -> bool:
        now = time.time()
        if (now - self._last_log_ts) > interval:
            self._last_log_ts = now
            return True
        return False

    def list_expiries(self, index_symbol: str) -> list[_dt.date]:
        return list(self._cache.get(index_symbol, []))

    # --- core extraction logic (Phase 4 A16) ------------------------------
    def extract(
        self,
        index_symbol: str,
        instruments: Iterable[dict[str, Any]],
        atm_strike: int | float | None = None,
        strike_window: float = 500,
        today: _dt.date | None = None,
    ) -> list[_dt.date]:
        today = today or _dt.date.today()
        out: set[_dt.date] = set()
        for inst in instruments:
            if not isinstance(inst, dict):
                continue
            seg = str(inst.get("segment", ""))
            if not seg.endswith("-OPT"):
                continue
            tsym = str(inst.get("tradingsymbol", ""))
            if index_symbol not in tsym:
                continue
            if atm_strike is not None:
                try:
                    diff = abs(float(inst.get("strike", 0) or 0) - float(atm_strike))
                    if diff > strike_window:
                        continue
                except Exception:
                    continue
            exp = inst.get("expiry")
            if isinstance(exp, _dt.date):
                if exp >= today:
                    out.add(exp)
            elif isinstance(exp, str):
                try:
                    dtp = _dt.datetime.strptime(exp[:10], "%Y-%m-%d").date()
                    if dtp >= today:
                        out.add(dtp)
                except Exception:
                    pass
        return sorted(out)

    def fabricate(self, today: _dt.date | None = None) -> list[_dt.date]:
        """Fabricate two near-term weekly-like expiries.

        Notes:
        - This fabrication is used only for legacy compatibility with tests and
          guarded resolve paths where instruments exist but no expiries were
          extractable. It does not leak into the universal expiry selection.
        - We pick the next two Thursdays relative to the provided 'today'.
        """
        t = today or _dt.date.today()
        # Thursday is weekday=3 (Mon=0)
        delta = (3 - t.weekday()) % 7
        first = t if delta == 0 else (t + _dt.timedelta(days=delta))
        second = first + _dt.timedelta(days=7)
        return [first, second]

    def resolve(
        self,
        index_symbol: str,
        fetch_instruments: Callable[[], list[dict[str, Any]]],
        atm_provider: Callable[[str], int] | None = None,
        ttl: float = 600.0,
        now_func: Callable[[], float] | None = None,
        *,
        fetch_expiry_dates: Callable[[], list[_dt.date]] | None = None,
    ) -> list[_dt.date]:
        now = (now_func or time.time)()
        # Derive a deterministic 'today' from the provided clock when available
        try:
            today_dt = _dt.datetime.utcfromtimestamp(float(now)).date()
        except Exception:
            today_dt = _dt.date.today()
        cached = self._cache.get(index_symbol)
        meta = self._cache_meta.get(index_symbol, 0.0)
        if cached and (now - meta) < ttl:
            return list(cached)
        # Preferred path: ask provider for expiry candidates directly when available
        if fetch_expiry_dates is not None:
            try:
                candidates = list(fetch_expiry_dates())
            except Exception:
                candidates = []
            if candidates:
                self._cache[index_symbol] = candidates
                self._cache_meta[index_symbol] = now
                return list(candidates)

        # Fallback path: derive candidates by scraping instruments (legacy compatibility)
        instruments = []
        try:
            instruments = fetch_instruments()
        except Exception:
            instruments = []
        atm = None
        if atm_provider is not None:
            try:
                atm = atm_provider(index_symbol)
            except Exception:
                atm = None
        extracted = self.extract(index_symbol, instruments, atm_strike=atm, today=today_dt)
        if not extracted:
            if instruments:
                if self._allow_log():
                    logger.warning("expiry.no_extracted_candidates index=%s", index_symbol)
                # Legacy compatibility: fabricate when instruments exist but no expiries extracted
                fabricated = self.fabricate(today=today_dt)
                try:
                    emit_event(logger, 'provider.expiries.fabricated', index=index_symbol, count=len(fabricated))
                except Exception:
                    pass
                self._cache[index_symbol] = fabricated
                self._cache_meta[index_symbol] = now
                return list(fabricated)
            else:
                if self._allow_log():
                    logger.warning("expiry.no_instruments index=%s", index_symbol)
        self._cache[index_symbol] = extracted
        self._cache_meta[index_symbol] = now
        return list(extracted)

    def fabricate_if_needed(self, index_symbol: str) -> list[_dt.date]:
        # Later: replicate fabrication heuristic from legacy provider
        return self.list_expiries(index_symbol)

    def weekly(self, index_symbol: str) -> list[_dt.date]:
        expiries = self.list_expiries(index_symbol)
        return expiries[:2]

    def monthly(self, index_symbol: str) -> list[_dt.date]:
        expiries = self.list_expiries(index_symbol)
        by_month: dict[tuple[int,int], list[_dt.date]] = {}
        for d in expiries:
            by_month.setdefault((d.year, d.month), []).append(d)
        out: list[_dt.date] = []
        for _, vals in sorted(by_month.items()):
            out.append(max(vals))
        return out
