from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

# Modular sub-configs for retrieval forecaster. Backward compatible: legacy fields
# in RetrievalConfig are mapped into these structs.

@dataclass
class PruningConfig:
    min_days: int = 3
    min_future: int = 30
    max_days_scan: int | None = None
    min_hist_rows: int | None = None
    max_time_gap_ratio: float | None = None

@dataclass
class RegimeConfig:
    distance_metric: str = "l2"  # l2|cosine|recent_l2
    recent_gamma: float = 0.9
    weight_mode: str | None = None  # None|inv_dist
    regime_tolerance: float | None = None
    regime_penalty: float = 1.25

@dataclass
class AnnConfig:
    use_ann: bool = False
    ann_space: str = "cosine"
    ann_max_candidates: int | None = None
    ann_dim: int | None = None

@dataclass
class RetrievalConfig:
    root: Path
    expiry_tag: str = "this_week"
    offset: str = "0"
    window: int = 60
    k: int = 15
    # Legacy flat fields retained for backward compatibility (will populate sub-configs)
    min_days: int = 3
    min_future: int = 30
    max_days_scan: int | None = None
    min_hist_rows: int | None = None
    max_time_gap_ratio: float | None = None
    distance_metric: str = "l2"
    recent_gamma: float = 0.9
    weight_mode: str | None = None
    regime_tolerance: float | None = None
    regime_penalty: float = 1.25
    use_ann: bool = False
    ann_space: str = "cosine"
    ann_max_candidates: int | None = None
    ann_dim: int | None = None

    # New modular configs (optional injection)
    pruning: PruningConfig | None = None
    regime: RegimeConfig | None = None
    ann: AnnConfig | None = None

    # Arbitrary extras for forward compatibility
    extras: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
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
