"""Dynamic ML quality targets loader.

Allows overriding forecast quality improvement and stability targets via:
1. Environment variables
   - ML_QUALITY_MAE_P95_IMPROVE_PCT
   - ML_QUALITY_WEIGHT_STDDEV_MAX
   - ML_QUALITY_REGIME_ALERT_MINUTES
   - ML_QUALITY_RESIDUAL_COVERAGE_TOL_PCT
   - ML_QUALITY_HORIZONS (comma separated)
   - ML_QUALITY_RESIDUAL_DEPTH
   - ML_QUALITY_TARGETS_FILE (path to JSON file)
2. JSON file (schema below) referenced by ML_QUALITY_TARGETS_FILE.

Example JSON schema:
{
  "mae_p95_improve_pct": 10,
  "weight_stddev_max": 0.15,
  "regime_alert_minutes": 5,
  "residual_coverage_tol_pct": 2,
  "horizons": [15,30,60],
  "residual_depth": 360
}

Precedence: JSON file values -> environment variable overrides -> defaults.
Provides a .reload() method to pick up changes at runtime.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Any

_DEFAULTS = {
    'mae_p95_improve_pct': 10.0,
    'weight_stddev_max': 0.15,
    'regime_alert_minutes': 5,
    'residual_coverage_tol_pct': 2.0,
    'horizons': [15, 30, 60],
    'residual_depth': 360,
}

_ENV_MAP = {
    'mae_p95_improve_pct': 'ML_QUALITY_MAE_P95_IMPROVE_PCT',
    'weight_stddev_max': 'ML_QUALITY_WEIGHT_STDDEV_MAX',
    'regime_alert_minutes': 'ML_QUALITY_REGIME_ALERT_MINUTES',
    'residual_coverage_tol_pct': 'ML_QUALITY_RESIDUAL_COVERAGE_TOL_PCT',
    'horizons': 'ML_QUALITY_HORIZONS',
    'residual_depth': 'ML_QUALITY_RESIDUAL_DEPTH',
    'targets_file': 'ML_QUALITY_TARGETS_FILE',
}

@dataclass
class QualityTargets:
    mae_p95_improve_pct: float = _DEFAULTS['mae_p95_improve_pct']
    weight_stddev_max: float = _DEFAULTS['weight_stddev_max']
    regime_alert_minutes: int = _DEFAULTS['regime_alert_minutes']
    residual_coverage_tol_pct: float = _DEFAULTS['residual_coverage_tol_pct']
    horizons: List[int] = field(default_factory=lambda: list(_DEFAULTS['horizons']))
    residual_depth: int = _DEFAULTS['residual_depth']
    source: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

class QualityTargetsLoader:
    def __init__(self):
        self._targets = QualityTargets()
        self.reload()

    def _read_file(self, path: Path) -> Dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                return {}
            return data
        except Exception:
            return {}

    def reload(self) -> QualityTargets:
        file_path = os.environ.get(_ENV_MAP['targets_file'])
        file_data: Dict[str, Any] = {}
        if file_path:
            p = Path(file_path)
            if p.exists():
                file_data = self._read_file(p)
        # start with file values or defaults
        merged: Dict[str, Any] = {**_DEFAULTS, **file_data}
        # env overrides
        for key, env_name in _ENV_MAP.items():
            if key == 'targets_file':
                continue
            raw = os.environ.get(env_name)
            if raw is None:
                continue
            if key == 'horizons':
                try:
                    merged[key] = [int(x) for x in raw.split(',') if x.strip()]
                except Exception:
                    pass
            else:
                try:
                    if key.endswith('_minutes') or key in ('residual_depth',):
                        merged[key] = int(raw)
                    else:
                        merged[key] = float(raw)
                except ValueError:
                    pass
        qt = QualityTargets(
            mae_p95_improve_pct=float(merged['mae_p95_improve_pct']),
            weight_stddev_max=float(merged['weight_stddev_max']),
            regime_alert_minutes=int(merged['regime_alert_minutes']),
            residual_coverage_tol_pct=float(merged['residual_coverage_tol_pct']),
            horizons=list(merged['horizons']),
            residual_depth=int(merged['residual_depth']),
            source={
                'file_path': file_path if file_path else None,
                'file_values': file_data,
                'env_overrides': {k: os.environ.get(v) for k, v in _ENV_MAP.items() if k != 'targets_file' and os.environ.get(v) is not None},
            }
        )
        self._targets = qt
        return qt

    def get(self) -> QualityTargets:
        return self._targets

# Global loader
_loader: QualityTargetsLoader | None = None

def get_quality_targets(reload: bool = False) -> QualityTargets:
    global _loader
    if _loader is None:
        _loader = QualityTargetsLoader()
    elif reload:
        _loader.reload()
    return _loader.get()
