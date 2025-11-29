"""Parquet persistence for drift attribution (Phase 13).

Optional (enabled via env ENABLE_DRIFT_PARQUET=1). Falls back silently if pandas/pyarrow not available.
Writes daily partition files under:
    data/drift_attribution_parquet/YYYYMMDD/INDEX_H.parquet
Each write performs read-modify-write (acceptable for moderate volume). Future optimization: row-group append.
"""
from __future__ import annotations
import os, datetime
from pathlib import Path
from typing import Dict, Any

_BASE_ROOT = Path(__file__).resolve().parent.parent.parent / 'data' / 'drift_attribution_parquet'

_COLUMNS_ORDER = [
    'timestamp','timestamp_iso','index','horizon','tail_ratio','trend_ratio','burn_rate','tail_burn_accel',
    'weight_divergence','regime_class','retrain_signal','improve_target_pct','tail_ratio_vs_target_gap','drift_cause'
]

def _enabled() -> bool:
    return os.environ.get('ENABLE_DRIFT_PARQUET','').strip() != ''

def persist_attribution_parquet(attr: Dict[str, Any]) -> Path | None:
    if not _enabled():
        return None
    try:
        import pandas as pd  # type: ignore
        # engine selection attempt (pyarrow or fastparquet); rely on pandas default else skip
        # Build row dict
        ts = float(attr.get('timestamp', 0.0))
        iso = attr.get('timestamp_iso') or datetime.datetime.utcfromtimestamp(ts).isoformat()+"Z"
        row = {
            'timestamp': ts,
            'timestamp_iso': iso,
            'index': attr.get('index'),
            'horizon': int(attr.get('horizon',0)),
            'tail_ratio': attr.get('tail_ratio'),
            'trend_ratio': attr.get('trend_ratio'),
            'burn_rate': attr.get('burn_rate'),
            'tail_burn_accel': attr.get('tail_burn_accel'),
            'weight_divergence': attr.get('weight_divergence'),
            'regime_class': attr.get('regime_class'),
            'retrain_signal': attr.get('retrain_signal'),
            'improve_target_pct': attr.get('improve_target_pct'),
            'tail_ratio_vs_target_gap': attr.get('tail_ratio_vs_target_gap'),
            'drift_cause': attr.get('drift_cause'),
        }
        day = datetime.datetime.utcfromtimestamp(ts).strftime('%Y%m%d')
        base = _BASE_ROOT / day
        base.mkdir(parents=True, exist_ok=True)
        path = base / f"{row['index']}_{row['horizon']}.parquet"
        df_new = pd.DataFrame([row], columns=_COLUMNS_ORDER)
        if path.exists():
            try:
                df_old = pd.read_parquet(path)
                df = pd.concat([df_old, df_new], ignore_index=True)
            except Exception:
                df = df_new
        else:
            df = df_new
        # Write (overwrite) parquet file
        try:
            df.to_parquet(path, index=False)
        except Exception:
            # Engine missing (pyarrow/fastparquet). Disable further writes by clearing env.
            os.environ.pop('ENABLE_DRIFT_PARQUET', None)
            return None
        return path
    except Exception:
        return None

__all__ = ['persist_attribution_parquet']
