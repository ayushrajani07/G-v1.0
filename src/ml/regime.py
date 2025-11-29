"""Regime stability audit helpers.

A lightweight heuristic combining residual trend, weight volatility and
component divergence to derive a stability score and classification.

Score definition (0..1):
  base = 1 - clamp(residual_trend - 1, 0, 0.5) * 0.9
  volatility_penalty = clamp(weight_volatility_gbrt + weight_volatility_retrieval - 0.3, 0, 0.4)
  divergence_bonus = clamp(divergence - 0.15, 0, 0.15)
  score = clamp(base - volatility_penalty + divergence_bonus, 0, 1)

Classification:
  score >= 0.75 -> stable
  0.5 <= score < 0.75 -> transition
  score < 0.5 -> volatile

Metrics (optional, guarded by ENABLE_ML_QUALITY_METRICS):
  g6_ml_regime_stability (score) labeled by index,horizon
  g6_ml_regime_state (enum: 0 volatile,1 transition,2 stable)

Consumers: weighting engine may use `compute_regime_stability` output.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Dict
import logging
import os

_LOG = logging.getLogger("ml.regime")

try:
    from prometheus_client import Gauge  # type: ignore
except Exception:  # pragma: no cover
    Gauge = None  # type: ignore

_G_REGIME_STABILITY = None
_G_REGIME_STATE = None

_STATE_MAP = {"volatile": 0, "transition": 1, "stable": 2}

@dataclass
class RegimeAudit:
    index: str
    horizon: int
    residual_trend: float
    weight_volatility_gbrt: float
    weight_volatility_retrieval: float
    divergence: float
    score: float
    classification: Literal['stable','transition','volatile']


def _init_metrics():
    global _G_REGIME_STABILITY, _G_REGIME_STATE
    if _G_REGIME_STABILITY is not None or Gauge is None:
        return
    if os.environ.get("ENABLE_ML_QUALITY_METRICS", "").strip() == "":
        return
    try:
        _G_REGIME_STABILITY = Gauge(
            "g6_ml_regime_stability",
            "Regime stability composite score (0..1)",
            labelnames=["index","horizon"],
        )
        _G_REGIME_STATE = Gauge(
            "g6_ml_regime_state",
            "Regime state enum (0 volatile,1 transition,2 stable)",
            labelnames=["index","horizon"],
        )
    except Exception as e:  # pragma: no cover
        _LOG.debug(f"Failed to init regime metrics: {e}")


def compute_regime_stability(residual_trend: float, weight_volatility_gbrt: float, weight_volatility_retrieval: float, divergence: float) -> tuple[float,str]:
    # Normalize inputs
    rt = float(residual_trend)
    wv_g = float(weight_volatility_gbrt)
    wv_r = float(weight_volatility_retrieval)
    div = float(divergence)
    # Base penalizes residual trend above 1 (up to 1.5 -> max penalty)
    base = 1 - min(max(rt - 1, 0.0), 0.5) * 0.9
    volatility_penalty = min(max(wv_g + wv_r - 0.3, 0.0), 0.4)
    divergence_bonus = min(max(div - 0.15, 0.0), 0.15)
    score = max(min(base - volatility_penalty + divergence_bonus, 1.0), 0.0)
    if score >= 0.75:
        cls = 'stable'
    elif score >= 0.5:
        cls = 'transition'
    else:
        cls = 'volatile'
    return score, cls


def audit_regime(index: str, horizon: int, residual_trend: float, weight_volatility_gbrt: float, weight_volatility_retrieval: float, divergence: float) -> RegimeAudit:
    score, cls = compute_regime_stability(residual_trend, weight_volatility_gbrt, weight_volatility_retrieval, divergence)
    _init_metrics()
    if _G_REGIME_STABILITY is not None:
        try:
            _G_REGIME_STABILITY.labels(index=index.upper(), horizon=int(horizon)).set(score)
            _G_REGIME_STATE.labels(index=index.upper(), horizon=int(horizon)).set(_STATE_MAP[cls])
        except Exception as e:  # pragma: no cover
            _LOG.debug(f"Failed to push regime metrics: {e}")
    return RegimeAudit(
        index=index.upper(),
        horizon=int(horizon),
        residual_trend=residual_trend,
        weight_volatility_gbrt=weight_volatility_gbrt,
        weight_volatility_retrieval=weight_volatility_retrieval,
        divergence=divergence,
        score=score,
        classification=cls,
    )
