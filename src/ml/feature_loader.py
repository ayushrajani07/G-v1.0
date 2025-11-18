from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Any


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    csv_col: str
    importance: int = 100
    transform: str = "identity"  # identity|log1p|abs|ratio|diff
    src1: Optional[str] = None    # for ratio/diff, name of first source column
    src2: Optional[str] = None    # for ratio/diff, name of second source column


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
                src1=spec.get("src1"),
                src2=spec.get("src2"),
            )
        return out or _default_map()
    except Exception:
        return _default_map()


def feature_names_sorted_by_importance(mapper: Optional[Dict[str, FeatureSpec]] = None) -> List[str]:
    m = mapper or load_feature_map()
    return [k for k, _ in sorted(m.items(), key=lambda kv: kv[1].importance)]


def _compute_from_row(spec: FeatureSpec, row: Dict[str, Any]) -> Optional[float]:
    try:
        if spec.transform in ("ratio", "diff"):
            s1 = spec.src1 or spec.csv_col
            s2 = spec.src2 or spec.csv_col
            v1_raw = row.get(s1)
            v2_raw = row.get(s2)
            if v1_raw is None or v2_raw is None:
                return None
            v1 = float(v1_raw)
            v2 = float(v2_raw)
            if spec.transform == "ratio":
                denom = v2 if abs(v2) > 1e-12 else (1e-12 if v2 >= 0 else -1e-12)
                return v1 / denom
            else:  # diff
                return v1 - v2
        # single-input transforms use csv_col
        raw = row.get(spec.csv_col)
        if raw is None:
            return None
        v = float(raw)
        return _transform_value(spec.transform, v)
    except Exception:
        return None


def apply_transform(mapper: Dict[str, FeatureSpec], feature: str, value: float) -> float:
    spec = mapper.get(feature)
    if not spec:
        return value
    return _transform_value(spec.transform, value)
