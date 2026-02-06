from __future__ import annotations

from typing import Optional

from src.path_forecast.common import effective_window_since_open as _effective_window_since_open

from ._helpers import _load_profiles


def _apply_profile_overrides(
    profile: Optional[str],
    window: int,
    k: int,
    mode: str,
    distance_metric: Optional[str],
    weight_mode: Optional[str],
    recent_gamma: Optional[float],
    regime_tolerance: Optional[float],
    regime_penalty: Optional[float],
    ref_now_ms: int,
    use_ann: Optional[bool] = None,
    ann_space: Optional[str] = None,
    ann_max_candidates: Optional[int] = None,
) -> tuple[
    int,
    int,
    str,
    float,
    Optional[str],
    Optional[str],
    Optional[float],
    Optional[float],
    Optional[float],
    Optional[bool],
    Optional[str],
    Optional[int],
    dict,
]:
    """Return (window_eff, k_eff, mode_eff, fb_band_pct, dist_eff, weight_eff, recent_gamma_eff, regime_tol_eff, regime_penalty_eff, ann_use_eff, ann_space_eff, ann_max_cand_eff, profile_diag)."""

    # Effective window: 0 => since open (09:15 IST)
    window_eff = _effective_window_since_open(ref_now_ms, int(window))
    k_eff = int(k)
    mode_eff = str(mode).lower()
    fb_band_pct = 0.05
    dist_eff = distance_metric
    weight_eff = weight_mode
    recent_gamma_eff = recent_gamma
    regime_tol_eff = regime_tolerance
    regime_penalty_eff = regime_penalty
    ann_use_eff = use_ann
    ann_space_eff = ann_space
    ann_max_cand_eff = ann_max_candidates
    pdiag: dict[str, object] = {}
    abs_floor_override: Optional[float] = None
    try:
        if profile:
            profiles = _load_profiles()
            pf = profiles.get(profile.lower())
            if pf:
                pdiag["profile"] = profile.lower()
                try:
                    window_eff = int(pf.get("window", window_eff))
                except (TypeError, ValueError):
                    pass
                try:
                    k_eff = int(pf.get("k", k_eff))
                except (TypeError, ValueError):
                    pass
                try:
                    fb_band_pct = float(pf.get("fallback_band_pct", fb_band_pct))
                except (TypeError, ValueError):
                    pass
                try:
                    fm = pf.get("force_mode")
                    if isinstance(fm, str) and fm.strip():
                        mode_eff = fm.strip().lower()
                except (AttributeError, TypeError):
                    pass
                # Phase C overrides only when query param not supplied
                if dist_eff is None and pf.get("distance_metric"):
                    dist_eff = str(pf.get("distance_metric"))
                if weight_eff is None and pf.get("weight_mode") is not None:
                    weight_eff = (pf.get("weight_mode") if pf.get("weight_mode") not in ("", None) else None)
                _rg = pf.get("recent_gamma")
                if recent_gamma_eff is None and isinstance(_rg, (int, float, str)) and _rg not in (None, ""):
                    try:
                        recent_gamma_eff = float(_rg)
                    except (TypeError, ValueError):
                        recent_gamma_eff = None
                _rt = pf.get("regime_tolerance")
                if regime_tol_eff is None and isinstance(_rt, (int, float, str)) and _rt not in (None, ""):
                    try:
                        regime_tol_eff = float(_rt)
                    except (TypeError, ValueError):
                        regime_tol_eff = None
                _rp = pf.get("regime_penalty")
                if regime_penalty_eff is None and isinstance(_rp, (int, float, str)) and _rp not in (None, ""):
                    try:
                        regime_penalty_eff = float(_rp)
                    except (TypeError, ValueError):
                        regime_penalty_eff = None
                # Phase D ANN overrides (only when query param not supplied)
                if ann_use_eff is None and pf.get("use_ann") is not None:
                    try:
                        ann_use_eff = bool(pf.get("use_ann"))
                    except (TypeError, ValueError):
                        ann_use_eff = None
                if ann_space_eff is None and isinstance(pf.get("ann_space"), str) and pf.get("ann_space"):
                    ann_space_eff = str(pf.get("ann_space")).lower()
                _amc = pf.get("ann_max_candidates") if pf else None
                if ann_max_cand_eff is None and isinstance(_amc, (int, float, str)) and _amc not in (None, ""):
                    try:
                        ann_max_cand_eff = int(_amc)
                    except (TypeError, ValueError):
                        ann_max_cand_eff = None
                # Profile-specific absolute ribbon floor (half-width) override
                _af = pf.get("abs_floor")
                if isinstance(_af, (int, float, str)) and str(_af).strip() not in ("", "none", "null"):
                    try:
                        afv = float(_af)
                        if afv >= 0:
                            abs_floor_override = afv
                    except (TypeError, ValueError):
                        pass
                # echo effective knobs for diagnostics
                pdiag.update(
                    {
                        "profile_window": window_eff,
                        "profile_k": k_eff,
                        "profile_fallback_band_pct": fb_band_pct,
                        "profile_force_mode": mode_eff,
                        "profile_distance_metric": dist_eff,
                        "profile_weight_mode": weight_eff,
                        "profile_recent_gamma": recent_gamma_eff,
                        "profile_regime_tolerance": regime_tol_eff,
                        "profile_regime_penalty": regime_penalty_eff,
                        "profile_use_ann": ann_use_eff,
                        "profile_ann_space": ann_space_eff,
                        "profile_ann_max_candidates": ann_max_cand_eff,
                        "profile_abs_floor": abs_floor_override,
                    }
                )
    except (AttributeError, KeyError, TypeError, ValueError):
        pass
    if abs_floor_override is not None:
        pdiag["ribbon_abs_floor_override"] = abs_floor_override
    return (
        window_eff,
        k_eff,
        mode_eff,
        fb_band_pct,
        dist_eff,
        weight_eff,
        recent_gamma_eff,
        regime_tol_eff,
        regime_penalty_eff,
        ann_use_eff,
        ann_space_eff,
        ann_max_cand_eff,
        pdiag,
    )
