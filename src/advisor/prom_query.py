from __future__ import annotations
"""Prometheus + exporter scrape helpers for ANN advisor plugins."""
import re, json
from typing import Dict, Any, List

try:
    import requests  # type: ignore
except ImportError:
    requests = None

_METRIC_RE = re.compile(r'^(?P<name>ann_health_[a-z_]+)\{([^}]*)index="(?P<index>[A-Z0-9_]+)",window="(?P<window>[0-9]+)"[^}]*\}\s+(?P<value>[-+]?[0-9]*\.?[0-9]+)$')

ANN_METRIC_KEYS = [
    'ann_health_speedup',
    'ann_health_prune_ratio',
    'ann_health_q50_mad',
    'ann_health_rows',
    'ann_health_effectiveness_adjusted',
    'ann_health_guard_trigger_rate',
    'ann_health_speedup_delta',
    'ann_health_prune_ratio_delta',
]


def query_prometheus_instant(base: str, query: str) -> float:
    if not requests:
        return float('nan')
    try:
        r = requests.get(f"{base.rstrip('/')}/api/v1/query", params={'query': query}, timeout=4)
        r.raise_for_status()
        data = r.json()
        if data.get('status') != 'success':
            return float('nan')
        res = (data.get('data') or {}).get('result') or []
        if not res:
            return float('nan')
        val = res[0].get('value', [None, None])[1]
        return float(val)
    except Exception:
        return float('nan')


def scrape_exporter_port(port: int) -> Dict[str, float]:
    import urllib.request
    out: Dict[str, float] = {}
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as resp:  # nosec B310
            for line in resp.read().decode('utf-8', errors='replace').splitlines():
                m = _METRIC_RE.match(line)
                if not m:
                    continue
                name = m.group('name')
                idx = m.group('index')
                win = m.group('window')
                val = float(m.group('value'))
                out[f"{name}|{idx}|{win}"] = val
    except Exception:
        pass
    return out


def get_ann_metrics(indices: List[str], windows: List[int], prometheus: str | None, ports: List[int]) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Return nested map: idx -> window(str) -> metric_name(short) -> value.
    metric_name(short) without prefix, e.g., speedup, prune_ratio, q50_mad.
    """
    out: Dict[str, Dict[str, Dict[str, float]]] = {i: {str(w): {} for w in windows} for i in indices}
    if prometheus:
        # Batch-like queries by substituting index/window in loop (simple for now)
        for idx in indices:
            for w in windows:
                for full in ANN_METRIC_KEYS:
                    short = full.replace('ann_health_', '')
                    q = f"{full}{{index=\"{idx}\",window=\"{w}\"}}"
                    v = query_prometheus_instant(prometheus, q)
                    if v == v:  # not NaN
                        out[idx][str(w)][short] = v
    else:
        # Try exporter scrape across ports
        merged: Dict[str, float] = {}
        for p in ports:
            merged.update(scrape_exporter_port(int(p)))
        for key, val in merged.items():
            # name|IDX|WIN
            try:
                name, idx, win = key.split('|')
            except ValueError:
                continue
            if idx not in out or win not in out[idx]:
                continue
            short = name.replace('ann_health_', '')
            out[idx][win][short] = val
    return out
