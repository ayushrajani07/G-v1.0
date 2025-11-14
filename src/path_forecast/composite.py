from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple
import time
import os
from dataclasses import dataclass
from pathlib import Path
from collections import OrderedDict

from .interfaces import PathForecaster
from .retrieval import RetrievalPathForecaster, RetrievalConfig
from .query_builder import parse_today_tp as _parse_today_tp
from .common import safe_int as _safe_int
from .params import (
    sanitize_horizon as _p_horizon,
    sanitize_window as _p_window,
    sanitize_k as _p_k,
    sanitize_min_days as _p_min_days,
    sanitize_bucket_ms as _p_bucket,
    sanitize_max_days_scan as _p_max_days_scan,
)
from .cache import get_day_tp as _cache_get_day_tp
from .metrics import push_composite_metrics as _push_comp_metrics
from .params import (
    sanitize_min_hist_rows as _p_min_hist_rows,
    sanitize_regime_tolerance as _p_reg_tol,
)


def _median(values: List[float]) -> float:
    if not values:
        return float('nan')
    vs = sorted(values)
    n = len(vs)
    mid = n // 2
    if n % 2 == 1:
        return vs[mid]
    return 0.5 * (vs[mid - 1] + vs[mid])


@dataclass
class CompositeConfig:
    root: Path
    expiry_tag: str = "this_week"
    offset: str = "0"
    window: int = 60
    k: int = 15
    min_days: int = 3
    # Optional performance knob mirroring retrieval
    max_days_scan: int | None = None
    # Pruning hooks (mirrors RetrievalConfig). Off by default when None.
    min_hist_rows: int | None = None
    max_time_gap_ratio: float | None = None
    # Phase C knobs (mirrors RetrievalConfig for pass-through)
    distance_metric: str = "l2"  # l2|cosine|recent_l2
    recent_gamma: float = 0.9
    weight_mode: str | None = None  # None|inv_dist
    regime_tolerance: float | None = None
    regime_penalty: float = 1.25
    # Phase D ANN shortlist pass-through (optional)
    use_ann: bool = False
    ann_space: str = "cosine"  # cosine|l2
    ann_max_candidates: int | None = None


class CompositePathForecaster(PathForecaster):
    """Blend a historical-median prior with retrieval quantiles.

    Steps:
    1) Compute a prior median path over future horizon by taking the per-step
       median across historical day files aligned to today's current index.
    2) Run RetrievalPathForecaster to get quantile paths and meta.
    3) Center retrieval quantiles around a blended median m = α * retr_median + (1-α) * prior_median.
       Implement by shifting the retrieval q10/q90 by delta = m - retr_median.
    α is a simple gate based on how many candidates are available relative to
    the threshold: α = clip(candidates / (candidates + threshold), 0.3, 0.9).
    """

    def __init__(self, cfg: CompositeConfig) -> None:
        self.cfg = cfg
        self.last_meta: Dict[str, Any] = {}
        # note: prior median cache promoted to module-level shared LRU

    def _list_day_files(self, index: str) -> List[Path]:
        base = self.cfg.root / index / self.cfg.expiry_tag / self.cfg.offset
        if not base.exists() and self.cfg.offset.startswith('+'):
            base = self.cfg.root / index / self.cfg.expiry_tag / self.cfg.offset[1:]
        if not base.exists():
            return []
        files = sorted([p for p in base.glob('*.csv') if p.is_file()])
        # Sanitize max_days_scan (0 disables)
        max_scan = _p_max_days_scan(getattr(self.cfg, 'max_days_scan', 0))
        if max_scan > 0 and len(files) > max_scan:
            files = files[-max_scan:]
        return files

    def _load_tp_series(self, p: Path, index: str) -> List[float]:
        # Use cache helper only; it returns [] on missing/unreadable
        dstr = p.stem  # YYYY-MM-DD
        return _cache_get_day_tp(self.cfg.root, index, self.cfg.expiry_tag, self.cfg.offset, dstr)

    def _prior_median(self, index: str, now_pos: int, horizon: int) -> List[float]:
        files = self._list_day_files(index)
        futures_by_day: List[List[float]] = []
        pruned_days = 0
        # Sanitize pruning knobs (reuse retrieval bounds)
        min_hist_rows_s = _p_min_hist_rows(getattr(self.cfg, 'min_hist_rows', 0))
        max_time_gap_ratio_s = _p_reg_tol(getattr(self.cfg, 'max_time_gap_ratio', None))  # ratio 0-1
        for p in files:
            tp = self._load_tp_series(p, index)
            n_hist = len(tp)
            # pruning checks
            if min_hist_rows_s > 0 and n_hist < min_hist_rows_s:
                pruned_days += 1
                continue
            if n_hist < now_pos + horizon or now_pos <= 0:
                pruned_days += 1
                continue
            if max_time_gap_ratio_s is not None:
                ratio_hist = float(now_pos) / float(max(1, n_hist))
                ratio_today = 1.0  # now_pos relative to itself
                if not (0.3 <= ratio_hist <= 0.95) or abs(ratio_today - ratio_hist) > float(max_time_gap_ratio_s):
                    pruned_days += 1
                    continue
            futures_by_day.append(tp[now_pos: now_pos + horizon])
        H = horizon
        prior: List[float] = []
        for i in range(H):
            col: List[float] = []
            for seg in futures_by_day:
                if i < len(seg):
                    col.append(seg[i])
            prior.append(_median(col))
        self.last_meta = {
            "prior_days": len(futures_by_day),
            "pruned_days": pruned_days,
            "retained_days": len(futures_by_day),
            "prior_min_hist_rows_sanitized": min_hist_rows_s,
            "prior_max_time_gap_ratio_sanitized": float(max_time_gap_ratio_s) if max_time_gap_ratio_s is not None else None,
        }
        return prior

    def forecast_path(
        self,
        recent_window: Sequence[Sequence[float]],
        *,
        context: Dict[str, Any],
        quantiles: Sequence[float] = (0.1, 0.5, 0.9),
        horizon_minutes: int = 60,
        bucket_ms: int = 60_000,
    ) -> Tuple[Sequence[int], Dict[float, Sequence[float]]]:
        t_total_start = time.perf_counter()
        idx = str(context.get('index') or 'NIFTY').strip().upper()
        now_ms = int(context.get('now_ms') or 0)
        live_rows = context.get('live_rows') or []

        # Determine current position (how many samples today so far)
        todays_tp, warns = _parse_today_tp([], live_rows)
        # Note: we don't expose warnings here, but we could mirror into last_meta in future
        now_pos = len(todays_tp)
        H = _p_horizon(horizon_minutes)

        # Prior median across historical days aligned to now_pos (shared LRU caching)
        day_sig: Tuple[str, ...] = tuple(str(p) for p in self._list_day_files(idx))
        root_sig = None
        try:
            root_sig = str(self.cfg.root.resolve())
        except Exception:
            root_sig = str(self.cfg.root)
        cache_key = (root_sig, idx, self.cfg.expiry_tag, self.cfg.offset, now_pos, H, day_sig)
        prior: List[float]
        if cache_key in _PRIOR_CACHE:
            _PRIOR_CACHE.move_to_end(cache_key)
            prior = list(_PRIOR_CACHE[cache_key])
            self.last_meta["prior_cache_hit"] = 1
        else:
            prior = self._prior_median(idx, now_pos, H)
            _PRIOR_CACHE[cache_key] = list(prior)
            _PRIOR_CACHE.move_to_end(cache_key)
            # trim LRU if needed
            max_entries = _get_prior_cache_max()
            while len(_PRIOR_CACHE) > max_entries:
                _PRIOR_CACHE.popitem(last=False)
            self.last_meta["prior_cache_hit"] = 0

        # Retrieval quantiles
        rcfg = RetrievalConfig(
            root=self.cfg.root, expiry_tag=self.cfg.expiry_tag, offset=self.cfg.offset,
            window=self.cfg.window, k=self.cfg.k, min_days=self.cfg.min_days,
            max_days_scan=self.cfg.max_days_scan,
            min_hist_rows=self.cfg.min_hist_rows,
            max_time_gap_ratio=self.cfg.max_time_gap_ratio,
            distance_metric=self.cfg.distance_metric,
            recent_gamma=self.cfg.recent_gamma,
            weight_mode=self.cfg.weight_mode,
            regime_tolerance=self.cfg.regime_tolerance,
            regime_penalty=self.cfg.regime_penalty,
            use_ann=self.cfg.use_ann,
            ann_space=self.cfg.ann_space,
            ann_max_candidates=self.cfg.ann_max_candidates,
        )
        retr = RetrievalPathForecaster(rcfg)
        # Build simple [[tp], ...] recent window for retrieval consumption from todays_tp
        take = max(60, _p_window(getattr(self.cfg, 'window', 60)))
        sel = todays_tp[-take:]
        rw: List[List[float]] = [[float(v)] for v in sel]
        # Sanitize bucket size before passing downstream
        _bucket = _p_bucket(bucket_ms)
        times, rq = retr.forecast_path(
            rw,
            context={"index": idx, "now_ms": now_ms, "live_rows": live_rows},
            quantiles=quantiles,
            horizon_minutes=H,
            bucket_ms=_bucket,
        )
        meta = getattr(retr, 'last_meta', {}) or {}
        cands = int(meta.get('candidates_total') or 0)
        # Use sanitized k/min_days for fallback threshold if retrieval didn't provide
        k_sanitized = _p_k(getattr(self.cfg, 'k', 15))
        min_days_s = _p_min_days(getattr(self.cfg, 'min_days', 3))
        thresh = int(meta.get('threshold_needed') or max(1, min(min_days_s, k_sanitized // 2)))
        # Gate: more candidates -> more trust in retrieval
        alpha_raw = cands / float(cands + thresh) if (cands + thresh) > 0 else 0.5
        # Clamp alpha using clamp helper for consistency
        try:
            from .common import clamp as _clamp
            alpha = _clamp(alpha_raw, 0.3, 0.9)
        except Exception:
            alpha = max(0.3, min(0.9, alpha_raw))

        # Blend: center retrieval quantiles around blended median
        qlist = list(quantiles)
        # Determine retrieval median path (closest to 0.5)
        qmid = min(qlist, key=lambda q: abs(q - 0.5))
        retr_med = list(rq.get(qmid, tuple(float('nan') for _ in range(H))))
        blended_med: List[float] = []
        for i in range(H):
            pm = float(prior[i]) if i < len(prior) else float('nan')
            rm = float(retr_med[i]) if i < len(retr_med) else float('nan')
            if pm != pm:  # nan check
                blended_med.append(rm)
            elif rm != rm:
                blended_med.append(pm)
            else:
                blended_med.append(alpha * rm + (1.0 - alpha) * pm)

        out: Dict[float, Sequence[float]] = {}
        for q in qlist:
            if abs(q - qmid) < 1e-9:
                out[q] = tuple(blended_med)
            else:
                base = list(rq.get(q, retr_med))
                shifted: List[float] = []
                for i in range(H):
                    rm = float(retr_med[i]) if i < len(retr_med) else float('nan')
                    bq = float(base[i]) if i < len(base) else float('nan')
                    if rm != rm or bq != bq:
                        shifted.append(bq)
                    else:
                        shifted.append(bq + (blended_med[i] - rm))
                out[q] = tuple(shifted)

        # Profiling timings (optional)
        if os.environ.get('ENABLE_PATH_FORECAST_PROFILING','').strip() != '':
            try:
                self.last_meta['total_ms'] = int((time.perf_counter() - t_total_start) * 1000)
            except Exception:
                pass

        self.last_meta.update({
            "alpha": alpha,
            "candidates_total": cands,
            "threshold_needed": thresh,
            "k_used": meta.get("k_used", self.cfg.k),
            "window_used": meta.get("window_used", self.cfg.window),
            # Sanitized values for observability
            "horizon_sanitized": H,
            "bucket_ms_sanitized": _bucket,
            "k_sanitized": k_sanitized,
            "min_days_sanitized": min_days_s,
            # Mirror key retrieval diagnostics for consistency in hybrid mode
            "pruned_days": meta.get("pruned_days"),
            "retained_days": meta.get("retained_days"),
            "distance_metric": meta.get("distance_metric"),
            "weight_mode": meta.get("weight_mode"),
            "regime_penalized": meta.get("regime_penalized"),
            "ann_enabled": meta.get("ann_enabled"),
            "ann_total_windows": meta.get("ann_total_windows"),
            "ann_shortlisted": meta.get("ann_shortlisted"),
            "ann_build_ms": meta.get("ann_build_ms"),
            "ann_index_mem_bytes": meta.get("ann_index_mem_bytes"),
            "ann_prune_ratio": meta.get("ann_prune_ratio"),
        })
        # Prometheus metrics push (best-effort, env guarded inside helper)
        try:
            _push_comp_metrics(self.last_meta)
        except Exception:
            pass

        return times, out

# Module-level shared LRU for prior medians
# Key: (root_resolved, index, expiry_tag, offset, now_pos, horizon, day_files_signature)
_PRIOR_CACHE: "OrderedDict[Tuple[str,str,str,str,int,int,Tuple[str,...]], List[float]]" = OrderedDict()

def _get_prior_cache_max() -> int:
    try:
        v = int(os.environ.get('PRIOR_MEDIAN_CACHE_MAX', '256'))
        return max(16, min(4096, v))
    except Exception:
        return 256
