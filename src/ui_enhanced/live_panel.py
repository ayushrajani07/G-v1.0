"""Placeholder enhanced live panel builder.
Provides richer formatting if enabled, otherwise falls back gracefully.
This is intentionally lightweight until full implementation is supplied.
"""
from __future__ import annotations

from typing import Any

from .color import colorize, status_color

BOX_TOP = "+" + "-"*78 + "+"
BOX_BOTTOM = BOX_TOP

def build_live_panel(*, cycle: int, cycle_time: float, success_rate: float | None,
                     options_processed: int, per_min: float | None, api_success: float | None,
                     api_latency_ms: float | None, memory_mb: float | None, cpu_pct: float | None,
                     indices: dict[str, dict[str, Any]] | None = None, concise: bool = True,
                     market_data: dict[str, Any] | None = None, system_alerts: list[str] | None = None) -> str:
    def fmt(v):
        if v is None:
            return 'NA'
        if isinstance(v, float):
            return f"{v:.2f}"
        return str(v)

    # Derive status key with clearer ternary and wrap line length
    _sr = success_rate or 0
    status_key = 'healthy' if _sr >= 95 else ('warn' if _sr >= 80 else 'error')
    status_col, status_bold = status_color(status_key)
    header = colorize(f" G6 Cycle {cycle} ", status_col, bold=status_bold)
    lines = [BOX_TOP, f"|{header:<78}|"]
    # Wrap long info rows
    row1 = (
        f"| CycleTime: {fmt(cycle_time)}s  "
        f"Success: {fmt(success_rate)}%  "
        f"Options: {options_processed}  "
        f"Rate/min: {fmt(per_min)}{' ' * 8}|"
    )
    lines.append(row1)
    row2 = (
        f"| API Success: {fmt(api_success)}%  "
        f"Latency: {fmt(api_latency_ms)}ms  "
        f"CPU: {fmt(cpu_pct)}%  "
        f"Mem: {fmt(memory_mb)}MB{' ' * 4}|"
    )
    lines.append(row2)
    if indices:
        for name, data in indices.items():
            opt = data.get('options')
            atm = data.get('atm')
            idx_row = (
                f"| {name:<10} "
                f"opt={fmt(opt):<6} "
                f"atm={fmt(atm):<8} "
                f"status={data.get('status','?'):<10}"
                f"{' ' * 27}|"
            )
            lines.append(idx_row)
    if system_alerts:
        lines.extend([f"| ALERT: {a[:68]:<68}|" for a in system_alerts[:3]])
    lines.append(BOX_BOTTOM)
    return '\n'.join(lines)

__all__ = ['build_live_panel']
