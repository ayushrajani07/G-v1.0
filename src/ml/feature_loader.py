from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    csv_col: str
    importance: int = 100
    transform: str = "identity"  # identity|log1p|abs


def _default_map() -> Dict[str, FeatureSpec]:
    base: List[FeatureSpec] = [
        FeatureSpec("tp", "tp", 10, "identity"),
        FeatureSpec("ce_iv", "ce_iv", 20, "identity"),
        FeatureSpec("pe_iv", "pe_iv", 21, "identity"),
        FeatureSpec("ce_gamma", "ce_gamma", 30, "identity"),
        FeatureSpec("pe_gamma", "pe_gamma", 31, "identity"),
        FeatureSpec("ce_vega", "ce_vega", 32, "identity"),
        FeatureSpec("pe_vega", "pe_vega", 33, "identity"),
        FeatureSpec("ce_theta", "ce_theta", 34, "identity"),
        FeatureSpec("pe_theta", "pe_theta", 35, "identity"),
        FeatureSpec("ce_vol", "ce_vol", 40, "identity"),
        FeatureSpec("pe_vol", "pe_vol", 41, "identity"),
        FeatureSpec("ce_oi", "ce_oi", 50, "identity"),
        FeatureSpec("pe_oi", "pe_oi", 51, "identity"),
    ]
    return {f.name: f for f in base}


def _transform_value(kind: str, val: float) -> float:
    if kind == "identity":
        return val
    if kind == "log1p":
        import math
        return math.log1p(max(val, -0.999999999))
    if kind == "abs":
        return abs(val)
    return val


def load_feature_map() -> Dict[str, FeatureSpec]:
    path = os.environ.get("G6_DRIFT_FEATURE_MAP_JSON", "").strip()
    if not path:
        return _default_map()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        out: Dict[str, FeatureSpec] = {}
        for name, spec in raw.items():
            out[name] = FeatureSpec(
                name=name,
                csv_col=spec.get("csv_col", name),
                importance=int(spec.get("importance", 100)),
                transform=str(spec.get("transform", "identity")),
            )
        return out or _default_map()
    except Exception:
        return _default_map()


def feature_names_sorted_by_importance(mapper: Optional[Dict[str, FeatureSpec]] = None) -> List[str]:
    m = mapper or load_feature_map()
    return [k for k, _ in sorted(m.items(), key=lambda kv: kv[1].importance)]


def apply_transform(mapper: Dict[str, FeatureSpec], feature: str, value: float) -> float:
    spec = mapper.get(feature)
    if not spec:
        return value
    return _transform_value(spec.transform, value)
