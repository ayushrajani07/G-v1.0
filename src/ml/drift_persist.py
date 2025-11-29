"""Persistence utilities for drift attribution time series (Phase 12).

Stores per (index,horizon) attribution snapshots as CSV under
`data/drift_attribution/INDEX_<horizon>.csv` with headers automatically added.
Append-only; caller ensures pruning/rotation if desired.
"""
from __future__ import annotations
import csv, time
from pathlib import Path
from typing import Dict, Any

_BASE_DIR = Path(__file__).resolve().parent.parent.parent / 'data' / 'drift_attribution'

_HEADERS = [
    'timestamp_iso','timestamp','index','horizon','tail_ratio','trend_ratio','burn_rate','weight_divergence','regime_class','retrain_signal','improve_target_pct','tail_ratio_vs_target_gap'
]

def _ensure_dir() -> None:
    _BASE_DIR.mkdir(parents=True, exist_ok=True)

def persist_attribution(attr: Dict[str, Any]) -> Path:
    """Persist an attribution snapshot. Returns path used."""
    _ensure_dir()
    index = attr.get('index','UNK')
    horizon = attr.get('horizon',0)
    path = _BASE_DIR / f"{index}_{horizon}.csv"
    new_file = not path.exists()
    with path.open('a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(_HEADERS)
        ts = float(attr.get('timestamp', time.time()))
        row = [
            _iso(ts), ts, index, horizon,
            attr.get('tail_ratio',0.0), attr.get('trend_ratio',0.0), attr.get('burn_rate',0.0),
            attr.get('weight_divergence',0.0), attr.get('regime_class',0.0), attr.get('retrain_signal',0.0),
            attr.get('improve_target_pct',0.0), attr.get('tail_ratio_vs_target_gap',0.0)
        ]
        writer.writerow(row)
    return path

def _iso(ts: float) -> str:
    import datetime
    return datetime.datetime.utcfromtimestamp(ts).isoformat()+"Z"
