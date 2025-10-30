"""alerts_core.py — Aggregated alert generation from collector cycle outcomes.

Phase 9 extraction: centralized alert taxonomy with per-category counts and severity.
Phase 10 enhancements: configurable thresholds & extended taxonomy (liquidity, stale, spread).
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from src.config.env_config import EnvConfig

logger = logging.getLogger(__name__)


@dataclass
class AlertSummary:
    total: int
    categories: dict[str, int]
    index_triggers: dict[str, list[str]]
    severities: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            'alerts_total': self.total,
            'alerts': dict(self.categories),
            'alerts_index_triggers': {k: v[:] for k, v in self.index_triggers.items()},
            'alerts_severity': dict(self.severities),
        }


def derive_severity_map(categories: Mapping[str, int]) -> dict[str, str]:
    """Return a mapping category -> severity (info|warning|critical).

    Default heuristic (W4-03):
      * index_failure, index_empty => critical
      * expiry_empty, low_both_coverage, stale_quote, wide_spread => warning
      * low_strike_coverage, low_field_coverage => warning (strike) / info (field)
      * liquidity_low => info
      * synthetic_quotes_used (legacy) => info

    Override via env G6_ALERT_SEVERITY_MAP supplying JSON object {category: severity}.
    Unknown severities ignored (must be one of info|warning|critical).
    """
    default: dict[str, str] = {}
    for cat in categories.keys():
        if cat in ('index_failure', 'index_empty'):
            default[cat] = 'critical'
        elif cat in ('expiry_empty', 'low_both_coverage', 'stale_quote', 'wide_spread'):
            default[cat] = 'warning'
        elif cat in ('low_strike_coverage',):
            default[cat] = 'warning'
        elif cat in ('low_field_coverage', 'liquidity_low', 'synthetic_quotes_used'):
            default[cat] = 'info'
        else:
            # extended / future categories default to warning as a conservative middle
            default[cat] = 'warning'
    raw = EnvConfig.get_str('G6_ALERT_SEVERITY_MAP', '')
    if raw:
        try:
            override = json.loads(raw)
            if isinstance(override, dict):
                for k, v in override.items():
                    if k in default and isinstance(v, str) and v.lower() in ('info','warning','critical'):
                        default[k] = v.lower()
        except Exception:
            pass
    return default


def _env_float(name: str, default: float) -> float:
    try:
        val = EnvConfig.get_float(name, default)
        return val
    except Exception:
        return default


def aggregate_alerts(indices_struct: list[dict[str, Any]], *, strike_cov_min: float | None = None, field_cov_min: float | None = None) -> AlertSummary:
    strike_min = strike_cov_min if strike_cov_min is not None else _env_float('G6_ALERT_STRIKE_COV_MIN', 0.6)
    field_min = field_cov_min if field_cov_min is not None else _env_float('G6_ALERT_FIELD_COV_MIN', 0.5)

    counts: dict[str, int] = {
        'index_failure': 0,
        'index_empty': 0,
        'expiry_empty': 0,
        'low_strike_coverage': 0,
        'low_field_coverage': 0,
        'low_both_coverage': 0,
        'synthetic_quotes_used': 0,  # legacy key retained constant (removed logic)
        # Phase 10 taxonomy expansion (optional; gated by env thresholds)
        'liquidity_low': 0,
        'stale_quote': 0,
        'wide_spread': 0,
    }
    triggers: dict[str, set[str]] = {k: set() for k in counts.keys()}

    for idx in indices_struct:
        index_symbol = idx.get('index') or 'UNKNOWN'
        failures = int(idx.get('failures') or 0)
        status = (idx.get('status') or '').upper()
        expiries = idx.get('expiries') or []

        if failures > 0:
            counts['index_failure'] += 1
            triggers['index_failure'].add(index_symbol)
        if status == 'EMPTY':
            counts['index_empty'] += 1
            triggers['index_empty'].add(index_symbol)
        # Thresholds for new taxonomy (env or defaults)
        try:
            liq_min_ratio = EnvConfig.get_float('G6_ALERT_LIQUIDITY_MIN_RATIO', 0.05)  # volume/oi or volume/notional heuristic
        except Exception:
            liq_min_ratio = 0.05
        try:
            stale_age_s = EnvConfig.get_float('G6_ALERT_QUOTE_STALE_AGE_S', 45.0)  # seconds since last trade/quote
        except Exception:
            stale_age_s = 45.0
        try:
            spread_pct_max = EnvConfig.get_float('G6_ALERT_WIDE_SPREAD_PCT', 5.0)  # percent
        except Exception:
            spread_pct_max = 5.0
        enable_extended = EnvConfig.get_bool('G6_ALERT_TAXONOMY_EXTENDED', False)

        for exp in expiries:
            if not isinstance(exp, dict):
                continue
            exp_status = (exp.get('status') or '').upper()
            if exp_status == 'EMPTY':
                counts['expiry_empty'] += 1
                triggers['expiry_empty'].add(index_symbol)
            s_cov = exp.get('strike_coverage')
            f_cov = exp.get('field_coverage')
            low_strike = isinstance(s_cov, (int, float)) and s_cov < strike_min
            low_field = isinstance(f_cov, (int, float)) and f_cov < field_min
            if low_strike:
                counts['low_strike_coverage'] += 1
                triggers['low_strike_coverage'].add(index_symbol)
            if low_field:
                counts['low_field_coverage'] += 1
                triggers['low_field_coverage'].add(index_symbol)
            if low_strike and low_field:
                counts['low_both_coverage'] += 1
                triggers['low_both_coverage'].add(index_symbol)
            # synthetic quotes flag ignored (legacy removed)
            # Extended taxonomy evaluation (per-expiry aggregate heuristics)
            if enable_extended:
                try:
                    meta = exp  # expiry record may carry aggregate fields
                    # liquidity_low: check ratio of avg volume to option_count heuristic
                    avg_vol = meta.get('avg_volume') or meta.get('avg_traded_volume')
                    opt_cnt = meta.get('options') or 0
                    if isinstance(avg_vol, (int,float)) and opt_cnt and opt_cnt>0:
                        ratio = (avg_vol / opt_cnt) if opt_cnt else 0
                        if ratio < liq_min_ratio:
                            counts['liquidity_low'] += 1
                            triggers['liquidity_low'].add(index_symbol)
                    # stale_quote: if last_quote_age_s field present and exceeds threshold
                    age_s = meta.get('last_quote_age_s') or meta.get('max_quote_age_s')
                    if isinstance(age_s, (int,float)) and age_s > stale_age_s:
                        counts['stale_quote'] += 1
                        triggers['stale_quote'].add(index_symbol)
                    # wide_spread: check avg_spread_pct field
                    spread_pct = meta.get('avg_spread_pct') or meta.get('mean_spread_pct')
                    if isinstance(spread_pct, (int,float)) and spread_pct > spread_pct_max:
                        counts['wide_spread'] += 1
                        triggers['wide_spread'].add(index_symbol)
                except Exception:
                    pass

    total = sum(counts.values())
    severities = derive_severity_map(counts)
    return AlertSummary(total=total, categories=counts, index_triggers={k: sorted(v) for k, v in triggers.items() if v}, severities=severities)
