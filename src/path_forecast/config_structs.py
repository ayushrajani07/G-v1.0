from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, model_validator

# Modular sub-configs for retrieval forecaster. Backward compatible: legacy fields
# in RetrievalConfig are mapped into these structs.

class PruningConfig(BaseModel):
    min_days: int = 3
    min_future: int = 30
    max_days_scan: Optional[int] = None
    min_hist_rows: Optional[int] = None
    max_time_gap_ratio: Optional[float] = None

class RegimeConfig(BaseModel):
    distance_metric: str = "l2"  # l2|cosine|recent_l2
    recent_gamma: float = 0.9
    weight_mode: Optional[str] = None  # None|inv_dist
    regime_tolerance: Optional[float] = None
    regime_penalty: float = 1.25

class AnnConfig(BaseModel):
    use_ann: bool = False
    ann_space: str = "cosine"
    ann_max_candidates: Optional[int] = None
    ann_dim: Optional[int] = None

class RetrievalConfig(BaseModel):
    root: Path
    expiry_tag: str = "this_week"
    offset: str = "0"
    window: int = 60
    k: int = 15
    
    # Legacy flat fields retained for backward compatibility (will populate sub-configs)
    min_days: int = 3
    min_future: int = 30
    max_days_scan: Optional[int] = None
    min_hist_rows: Optional[int] = None
    max_time_gap_ratio: Optional[float] = None
    distance_metric: str = "l2"
    recent_gamma: float = 0.9
    weight_mode: Optional[str] = None
    regime_tolerance: Optional[float] = None
    regime_penalty: float = 1.25
    use_ann: bool = False
    ann_space: str = "cosine"
    ann_max_candidates: Optional[int] = None
    ann_dim: Optional[int] = None

    # New modular configs (optional injection)
    pruning: Optional[PruningConfig] = None
    regime: Optional[RegimeConfig] = None
    ann: Optional[AnnConfig] = None

    # Arbitrary extras for forward compatibility
    extras: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def populate_subconfigs(self) -> "RetrievalConfig":
        # If modular configs not provided, build them from legacy values.
        if self.pruning is None:
            self.pruning = PruningConfig(
                min_days=self.min_days,
                min_future=self.min_future,
                max_days_scan=self.max_days_scan,
                min_hist_rows=self.min_hist_rows,
                max_time_gap_ratio=self.max_time_gap_ratio,
            )
        if self.regime is None:
            self.regime = RegimeConfig(
                distance_metric=self.distance_metric,
                recent_gamma=self.recent_gamma,
                weight_mode=self.weight_mode,
                regime_tolerance=self.regime_tolerance,
                regime_penalty=self.regime_penalty,
            )
        if self.ann is None:
            self.ann = AnnConfig(
                use_ann=self.use_ann,
                ann_space=self.ann_space,
                ann_max_candidates=self.ann_max_candidates,
                ann_dim=self.ann_dim,
            )
        return self

    @classmethod
    def from_modular(
        cls,
        *,
        root: Path,
        expiry_tag: str = "this_week",
        offset: str = "0",
        window: int = 60,
        k: int = 15,
        pruning: PruningConfig | None = None,
        regime: RegimeConfig | None = None,
        ann: AnnConfig | None = None,
        **extras: Any,
    ) -> "RetrievalConfig":
        cfg = cls(root=root, expiry_tag=expiry_tag, offset=offset, window=window, k=k,
                  pruning=pruning, regime=regime, ann=ann)
        if extras:
            cfg.extras.update(extras)
        return cfg

    def legacy_dict(self) -> Dict[str, Any]:
        """Return a flat legacy-compatible dict of core parameters for scripts expecting old shape."""
        return {
            "expiry_tag": self.expiry_tag,
            "offset": self.offset,
            "window": self.window,
            "k": self.k,
            "min_days": self.pruning.min_days if self.pruning else self.min_days,
            "min_future": self.pruning.min_future if self.pruning else self.min_future,
            "max_days_scan": self.pruning.max_days_scan if self.pruning else self.max_days_scan,
            "min_hist_rows": self.pruning.min_hist_rows if self.pruning else self.min_hist_rows,
            "max_time_gap_ratio": self.pruning.max_time_gap_ratio if self.pruning else self.max_time_gap_ratio,
            "distance_metric": self.regime.distance_metric if self.regime else self.distance_metric,
            "recent_gamma": self.regime.recent_gamma if self.regime else self.recent_gamma,
            "weight_mode": self.regime.weight_mode if self.regime else self.weight_mode,
            "regime_tolerance": self.regime.regime_tolerance if self.regime else self.regime_tolerance,
            "regime_penalty": self.regime.regime_penalty if self.regime else self.regime_penalty,
            "use_ann": self.ann.use_ann if self.ann else self.use_ann,
            "ann_space": self.ann.ann_space if self.ann else self.ann_space,
            "ann_max_candidates": self.ann.ann_max_candidates if self.ann else self.ann_max_candidates,
            "ann_dim": self.ann.ann_dim if self.ann else self.ann_dim,
        }

class EnsembleConfig(BaseModel):
    """Configuration for ensemble forecaster.
    
    Component configs:
    - baseline: Structural TP formula
    - gbrt: GBRT quantile regression on residuals
    - retrieval: K-NN historical retrieval
    - conformal: Conformal prediction bands
    """
    # Component enable/disable flags
    baseline_enabled: bool = True
    gbrt_enabled: bool = True
    retrieval_enabled: bool = True
    conformal_enabled: bool = True
    
    # Baseline configuration
    baseline_k: float = 1.0
    
    # GBRT configuration
    gbrt_model_path: Optional[Path] = None
    gbrt_feature_config: Optional[Dict[str, Any]] = None
    
    # Retrieval configuration (passed to RetrievalPathForecaster)
    retrieval_root: Optional[Path] = None
    retrieval_expiry_tag: str = "this_week"
    retrieval_offset: str = "0"
    retrieval_window: int = 60
    retrieval_k: int = 20
    retrieval_min_days: int = 3
    retrieval_distance_metric: str = "l2"
    retrieval_weight_mode: Optional[str] = None
    retrieval_use_ann: bool = False
    
    # Conformal configuration
    conformal_target_coverage: float = 0.8
    conformal_window: int = 600
    conformal_min_radius: float = 0.0
    
    # Weighting strategy
    weighting_strategy: str = "confidence_adaptive"  # confidence_adaptive | static | dynamic
    
    # Weights for high confidence (>= threshold)
    weights_high_conf_gbrt: float = 0.8
    weights_high_conf_retrieval: float = 0.2
    
    # Weights for low confidence (< threshold)
    weights_low_conf_gbrt: float = 0.5
    weights_low_conf_retrieval: float = 0.5
    
    # Confidence threshold for weight transition
    confidence_threshold: float = 0.7
    
    # Fallback settings
    min_candidates_threshold: int = 5
    
    # Diagnostics
    enable_profiling: bool = False
