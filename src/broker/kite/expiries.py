"""Expiry discovery and resolution helpers (Phase 1 extraction).

These functions are thin extractions from the original kite_provider module to
reduce size and prepare for further modularization. Behavior must remain
IDENTICAL to pre-refactor semantics.
"""
from __future__ import annotations

import datetime as _dt
import logging
try:
    from src.utils.expiry_dates import select_expiry_for_index, normalize_rule
except Exception:  # pragma: no cover
    select_expiry_for_index = None  # type: ignore
    normalize_rule = lambda r: (r or '').strip().lower().replace('-', '_')  # type: ignore
try:
    from src.utils.exceptions import ResolveExpiryError as RE  # type: ignore
except Exception:  # pragma: no cover
    class RE(Exception): ...  # type: ignore
try:
    from src.utils.index_registry import get_index_meta  # for weekly_dow policy
except Exception:  # pragma: no cover
    get_index_meta = None  # type: ignore

logger = logging.getLogger(__name__)

# The provider instance passed in is expected to offer:
#   - get_expiry_dates(self, index_symbol: str) -> list[date]
#     (For real provider this will still be the large method until Phase 2/3)
# During Phase 1 we only extract the resolution logic; the heavy discovery
# function stays in place so resolve_expiry can delegate here.


def resolve_expiry_rule(provider, index_symbol: str, expiry_rule: str):
    """Resolve an expiry rule into a concrete date using provider candidates.

    Delegates rule mapping to the universal selector in src.utils.expiry_dates.
    On error, returns today's date (defensive parity with original).
    """
    try:
        # Build candidate list (dates only)
        raw = list(provider.get_expiry_dates(index_symbol) or [])
        candidates: list[_dt.date] = []
        for x in raw:
            if isinstance(x, _dt.datetime):
                candidates.append(x.date())
            elif isinstance(x, _dt.date):
                candidates.append(x)
            else:
                try:
                    candidates.append(_dt.date.fromisoformat(str(x)))
                except Exception:
                    continue
        candidates = sorted(set(candidates))
        if not candidates:
            # Fallback candidate fabrication when provider supplies none.
            # Policy: generate a small set of weekly occurrences and monthly anchors so
            # selection rules (this_week/next_week/this_month/next_month) can resolve.
            today = _dt.date.today()
            # Determine weekly DOW via registry (default to Thursday for NSE indices, Friday for SENSEX)
            wd = 3
            try:
                if get_index_meta is not None:
                    wd = int(get_index_meta(index_symbol).weekly_dow)
                else:
                    idxu = (index_symbol or '').upper()
                    wd = 3 if idxu != 'SENSEX' else 4
            except Exception:
                wd = 3
            # Next 8 occurrences of that weekday (including today if matches)
            weekly: list[_dt.date] = []
            d = today
            for _ in range(120):  # scan up to ~4 months worst case; break early
                if d.weekday() == wd and d >= today:
                    weekly.append(d)
                    if len(weekly) >= 8:
                        break
                d = d + _dt.timedelta(days=1)
            # Monthly anchors: index-specific policy (Tue for NIFTY/BANKNIFTY/FINNIFTY, Thu for SENSEX)
            def _last_weekday_of_month(y: int, m: int, w: int) -> _dt.date:
                if m == 12:
                    ny, nm = y + 1, 1
                else:
                    ny, nm = y, m + 1
                first_next = _dt.date(ny, nm, 1)
                last_current = first_next - _dt.timedelta(days=1)
                delta = (last_current.weekday() - w) % 7
                return last_current - _dt.timedelta(days=delta)
            idxu = (index_symbol or '').upper()
            if idxu in {"NIFTY", "BANKNIFTY", "FINNIFTY"}:
                monthly_wd = 1  # Tuesday (requested policy)
            elif idxu in {"MIDCPNIFTY", "SENSEX"}:
                monthly_wd = 3  # Thursday (unchanged)
            else:
                monthly_wd = 3
            this_m = _last_weekday_of_month(today.year, today.month, monthly_wd)
            if this_m >= today:
                monthly = [this_m]
            else:
                monthly = []
            # Always include next month's anchor
            nm_year = today.year + (1 if today.month == 12 else 0)
            nm_month = 1 if today.month == 12 else (today.month + 1)
            next_m = _last_weekday_of_month(nm_year, nm_month, monthly_wd)
            monthly.append(next_m)
            candidates = sorted(set(weekly + monthly))
        rule_norm = normalize_rule(expiry_rule)
        # Direct ISO passthrough when present in candidates
        if len(rule_norm) == 10 and rule_norm[4] == '-' and rule_norm[7] == '-':
            try:
                direct = _dt.date.fromisoformat(rule_norm)
                if direct in candidates:
                    chosen = direct
                else:
                    chosen = candidates[0]
            except Exception:
                chosen = candidates[0]
        else:
            if select_expiry_for_index is None:
                raise RE("universal selector unavailable")
            try:
                chosen = select_expiry_for_index(index_symbol, candidates, rule_norm)
            except Exception:
                # As a last resort for weekly rules when selection fails (no weekly candidates
                # or insufficient count), fabricate upcoming weekly occurrences based on the
                # configured weekly DOW for this index, not the last candidate's weekday.
                if 'week' in rule_norm:
                    try:
                        wd = 3
                        if get_index_meta is not None:
                            wd = int(get_index_meta(index_symbol).weekly_dow)
                    except Exception:
                        wd = 3
                    today = _dt.date.today()
                    # Append up to the next two occurrences of wd
                    d = max(today, candidates[-1] if candidates else today)
                    # Ensure we start from tomorrow if d already equals today to avoid duplicates
                    d = d + _dt.timedelta(days=1)
                    added = 0
                    for _ in range(28):
                        if d.weekday() == wd and d >= today:
                            candidates.append(d)
                            added += 1
                            if added >= 2:
                                break
                        d = d + _dt.timedelta(days=1)
                    candidates = sorted(set(candidates))
                # retry selection after augmentation (may still raise)
                chosen = select_expiry_for_index(index_symbol, candidates, rule_norm)
        logger.debug("Resolved '%s' for %s -> %s", expiry_rule, index_symbol, chosen)
        return chosen
    except Exception:  # pragma: no cover - defensive catch identical to legacy fallback
        raise RE(f"Failed to resolve expiry for {index_symbol} rule={expiry_rule}")
