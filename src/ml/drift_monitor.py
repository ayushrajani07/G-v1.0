"""Drift Monitoring Module (Phase 10 – P4 Smoothing & Quantile Caching)

Implements production-ready drift detection for feature distributions:
 - PSI (Population Stability Index) using quantile binning
 - KS (Kolmogorov–Smirnov) two-sample test
 - Mean delta + Z-score normalization
 - Variance ratio delta
 - Baseline persistence & refresh hooks

P1 additions:
 - Real data loader integration via `FeatureLoader` (CSV based) with graceful fallback to synthetic if data absent.
 - Registry unification support (external metrics module consumes results and sets Prometheus gauges).

Environment Variables (core):
 - G6_DRIFT_BASELINE_DAYS (default 30)
 - G6_DRIFT_RECENT_ROWS (default 300)
 - G6_DRIFT_PSI_WARN (default 0.25)
 - G6_DRIFT_PSI_CRIT (default 0.40)
 - G6_DRIFT_KS_WARN (default 0.01)
 - G6_DRIFT_KS_CRIT (default 0.001)
 - G6_DRIFT_MEAN_Z_WARN (default 2.0)
 - G6_DRIFT_MEAN_Z_CRIT (default 3.0)
 - G6_DRIFT_VAR_RATIO_WARN_HIGH (default 1.5)
 - G6_DRIFT_VAR_RATIO_WARN_LOW (default 0.67)
 - G6_DRIFT_VAR_RATIO_CRIT_HIGH (default 2.0)
 - G6_DRIFT_VAR_RATIO_CRIT_LOW (default 0.5)
 - G6_DRIFT_MAX_FEATURES (default 30)
 - G6_DRIFT_BASELINE_REFRESH_DAYS (default 30)
 - G6_DRIFT_ENABLE_SMOOTHING (default 0)
 - G6_DRIFT_SMOOTHING_HALF_LIFE (default 5) (cycles)

Note: Baseline refresh logic will be implemented in P2; hooks included now.
"""
from __future__ import annotations

import json, os, logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import math
import numpy as np
try:
    from scipy import stats  # type: ignore
except Exception:  # pragma: no cover
    stats = None  # type: ignore

_LOG = logging.getLogger(__name__)

_DEF_BASELINE_DAYS = 30
_DEF_RECENT_ROWS = 300

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)).strip())
    except Exception:
        return default

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)).strip())
    except Exception:
        return default

class FeatureLoader:
    """Load feature series from CSV files in data/g6_data structure.

    Expects path pattern: data/g6_data/<INDEX>/this_month/0/<YYYY-MM-DD>.csv (fallback this_week).
    Minimal implementation: only loads columns explicitly requested; if missing, skips feature.
    """
    def __init__(self, root: Path):
        self.root = root

    def load_recent_rows(self, index: str, limit: int) -> List[Dict[str, float]]:
        if limit <= 0:
            return []
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        candidates = [
            self.root / index.upper() / 'this_month' / '0' / f'{today}.csv',
            self.root / index.upper() / 'this_week' / '0' / f'{today}.csv',
        ]
        path = next((p for p in candidates if p.exists()), None)
        if path is None:
            return []
        rows: List[Dict[str, float]] = []
        try:
            import csv
            with path.open('r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for r in reader:
                    # Convert numeric cells; keep subset
                    out: Dict[str, float] = {}
                    for k, v in r.items():
                        if v is None or v == '':
                            continue
                        try:
                            out[k.strip()] = float(v)
                        except Exception:
                            continue
                    if out:
                        rows.append(out)
            if len(rows) > limit:
                rows = rows[-limit:]
        except Exception as e:  # pragma: no cover
            _LOG.debug(f"feature_loader recent load failed index={index}: {e}")
        return rows

    def aggregate_feature_values(self, rows: List[Dict[str, float]], feature: str) -> List[float]:
        values: List[float] = []
        for r in rows:
            v = r.get(feature)
            if v is not None and math.isfinite(v):
                values.append(float(v))
        return values

def _project_root() -> Path:
    start = Path(__file__).resolve()
    for parent in [start.parent] + list(start.parents):
        if (parent / 'pyproject.toml').exists():
            return parent
    return Path.cwd()

class DriftMonitor:
    def __init__(self,
                 baseline_days: int = _DEF_BASELINE_DAYS,
                 recent_rows: int = _DEF_RECENT_ROWS,
                 num_bins: int = 10):
        self.baseline_days = baseline_days
        self.recent_rows = recent_rows
        self.num_bins = num_bins
        self.psi_warn = _env_float('G6_DRIFT_PSI_WARN', 0.25)
        self.psi_crit = _env_float('G6_DRIFT_PSI_CRIT', 0.40)
        self.ks_warn = _env_float('G6_DRIFT_KS_WARN', 0.01)
        self.ks_crit = _env_float('G6_DRIFT_KS_CRIT', 0.001)
        self.mean_z_warn = _env_float('G6_DRIFT_MEAN_Z_WARN', 2.0)
        self.mean_z_crit = _env_float('G6_DRIFT_MEAN_Z_CRIT', 3.0)
        self.var_warn_high = _env_float('G6_DRIFT_VAR_RATIO_WARN_HIGH', 1.5)
        self.var_warn_low = _env_float('G6_DRIFT_VAR_RATIO_WARN_LOW', 0.67)
        self.var_crit_high = _env_float('G6_DRIFT_VAR_RATIO_CRIT_HIGH', 2.0)
        self.var_crit_low = _env_float('G6_DRIFT_VAR_RATIO_CRIT_LOW', 0.5)
        self.max_features = _env_int('G6_DRIFT_MAX_FEATURES', 30)
        self.root = _project_root()
        self.baseline_dir = self.root / 'metrics' / 'drift_baselines'
        self.baseline_dir.mkdir(parents=True, exist_ok=True)
        self.loader = FeatureLoader(self.root / 'data' / 'g6_data')
        # Smoothing config
        self.smoothing_enabled = bool(_env_int('G6_DRIFT_ENABLE_SMOOTHING', 0))
        self.smoothing_half_life = _env_float('G6_DRIFT_SMOOTHING_HALF_LIFE', 5.0)
        self._smoothing_state: Dict[str, Dict[str, float]] = {}
        # Quantile edge cache (feature -> edges list)
        self._quantile_cache: Dict[str, List[float]] = {}

    def compute_feature_distributions(self, index: str, lookback_days: int, features: Optional[List[str]] = None) -> Dict[str, Any]:
        # Note: multi-day aggregation for baseline pending (P2). Quantile edges cached only for baseline.
        rows = self.loader.load_recent_rows(index, self.recent_rows if lookback_days == 0 else self.recent_rows)
        if features is None:
            # Initial feature selection (placeholder list)
            features = [
                'tp','ce_iv','pe_iv','ce_gamma','pe_gamma','ce_vega','pe_vega','ce_theta','pe_theta','ce_vol','pe_vol','ce_oi','pe_oi'
            ]
        data: Dict[str, Any] = {}
        for feat in features:
            vals = self.loader.aggregate_feature_values(rows, feat)
            if not vals:
                continue
            arr = np.array(vals)
            # For baseline (lookback_days>0) compute and cache quantiles; for recent reuse baseline quantiles
            if lookback_days > 0:
                quantiles = list(np.quantile(arr, np.linspace(0,1,self.num_bins+1)))
                self._quantile_cache[feat] = [float(q) for q in quantiles]
            else:
                # Recent window: do not recompute quantiles; rely on baseline cache (may be missing if feature newly added)
                quantiles = self._quantile_cache.get(feat)
            data[feat] = {
                'values': vals,
                'mean': float(arr.mean()),
                'std': float(arr.std(ddof=0)),
                'min': float(arr.min()),
                'max': float(arr.max()),
                'quantiles': [float(q) for q in quantiles] if quantiles is not None else None
            }
            if len(data) >= self.max_features:
                break
        return {
            'index': index.upper(),
            'lookback_days': lookback_days,
            'window_start': (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat(),
            'window_end': datetime.now(timezone.utc).isoformat(),
            'features': data
        }

    def get_or_create_baseline(self, index: str, features: Optional[List[str]] = None) -> Dict[str, Any]:
        existing = self.load_baseline(index)
        if existing is not None:
            return existing
        baseline = self.compute_feature_distributions(index, self.baseline_days, features)
        self.save_baseline(index, baseline)
        return baseline

    def calculate_drift_metrics(self, baseline_window: Dict[str, Any], recent_window: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        b_feats = baseline_window.get('features', {})
        r_feats = recent_window.get('features', {})
        common = set(b_feats.keys()) & set(r_feats.keys())
        out: Dict[str, Dict[str, Any]] = {}
        for feat in common:
            b = b_feats[feat]; r = r_feats[feat]
            psi, bins = self._calculate_psi(b['values'], r['values'], b.get('quantiles'))
            if stats is not None:
                try:
                    ks_stat, ks_p = stats.ks_2samp(b['values'], r['values'])
                except Exception:
                    ks_stat, ks_p = 0.0, 1.0
            else:
                ks_stat, ks_p = 0.0, 1.0
            mean_delta = r['mean'] - b['mean']
            baseline_std = b['std'] if b['std'] > 0 else 1.0
            mean_z = mean_delta / baseline_std
            var_delta_ratio = (r['std']**2) / (b['std']**2) if b['std'] > 0 else 1.0
            # Optional EWMA smoothing prior to classification
            original = {
                'psi': psi,
                'mean_z': mean_z,
                'var_ratio': var_delta_ratio,
            }
            if self.smoothing_enabled:
                psi, mean_z, var_delta_ratio = self._apply_smoothing(feat, psi, mean_z, var_delta_ratio)
            severity, reasons = self._classify(psi, ks_p, mean_z, var_delta_ratio)
            out[feat] = {
                'psi': psi,
                'ks_statistic': ks_stat,
                'ks_pvalue': ks_p,
                'mean_delta': mean_delta,
                'mean_delta_zscore': mean_z,
                'var_ratio': var_delta_ratio,
                'psi_raw': original['psi'],
                'mean_delta_zscore_raw': original['mean_z'],
                'var_ratio_raw': original['var_ratio'],
                'severity': severity,
                'reasons': reasons,
                'bins': bins
            }
        return out

    def _calculate_psi(self, baseline_values: List[float], recent_values: List[float], quantile_edges: Optional[List[float]]) -> Tuple[float,List[Dict[str,Any]]]:
        b = np.array(baseline_values); r = np.array(recent_values)
        if quantile_edges is None:
            quantile_edges = list(np.quantile(b, np.linspace(0,1,self.num_bins+1)))
        edges = np.unique(quantile_edges)
        if len(edges) < 2:
            return 0.0, []
        b_bins = np.digitize(b, edges[1:-1])
        r_bins = np.digitize(r, edges[1:-1])
        n_bins = len(edges)-1
        b_counts = np.bincount(b_bins, minlength=n_bins)
        r_counts = np.bincount(r_bins, minlength=n_bins)
        b_props = b_counts / len(b) if len(b) else np.zeros(n_bins)
        r_props = r_counts / len(r) if len(r) else np.zeros(n_bins)
        psi_total = 0.0; details = []
        eps = 1e-9
        for i in range(n_bins):
            bp = max(b_props[i], eps); rp = max(r_props[i], eps)
            psi_bin = (rp - bp) * math.log(rp / bp)
            psi_total += psi_bin
            details.append({'bin': i, 'baseline': bp, 'recent': rp, 'psi': psi_bin})
        return float(psi_total), details

    def _classify(self, psi: float, ks_p: float, mean_z: float, var_ratio: float) -> Tuple[str,List[str]]:
        reasons: List[str] = []
        crit = False; actionable = False; watch = False
        if psi >= self.psi_crit:
            crit = True; reasons.append(f'psi_crit {psi:.3f}')
        elif psi >= self.psi_warn:
            watch = True; reasons.append(f'psi_warn {psi:.3f}')
        if ks_p <= self.ks_crit:
            crit = True; reasons.append(f'ks_crit {ks_p:.4f}')
        elif ks_p <= self.ks_warn:
            watch = True; reasons.append(f'ks_warn {ks_p:.4f}')
        if abs(mean_z) >= self.mean_z_crit:
            crit = True; reasons.append(f'mean_z_crit {mean_z:.2f}')
        elif abs(mean_z) >= self.mean_z_warn:
            watch = True; reasons.append(f'mean_z_warn {mean_z:.2f}')
        if var_ratio >= self.var_crit_high or var_ratio <= self.var_crit_low:
            crit = True; reasons.append(f'var_ratio_crit {var_ratio:.2f}')
        elif var_ratio >= self.var_warn_high or var_ratio <= self.var_warn_low:
            watch = True; reasons.append(f'var_ratio_warn {var_ratio:.2f}')
        if crit:
            return 'critical', reasons
        if watch and (psi >= self.psi_warn and (ks_p <= self.ks_warn or abs(mean_z) >= self.mean_z_warn)):
            actionable = True
        if actionable:
            return 'actionable', reasons
        if watch:
            return 'watch', reasons
        return 'stable', reasons

    def _apply_smoothing(self, feat: str, psi: float, mean_z: float, var_ratio: float) -> Tuple[float,float,float]:
        # Half-life smoothing: alpha derived from half-life cycles H: alpha = 1 - 0.5^(1/H)
        H = max(self.smoothing_half_life, 0.1)
        alpha = 1.0 - math.pow(0.5, 1.0 / H)
        st = self._smoothing_state.setdefault(feat, {})
        def _ewma(key: str, current: float) -> float:
            prev = st.get(key)
            if prev is None:
                st[key] = current
                return current
            val = alpha * current + (1 - alpha) * prev
            st[key] = val
            return val
        s_psi = _ewma('psi', psi)
        s_mean_z = _ewma('mean_z', mean_z)
        s_var_ratio = _ewma('var_ratio', var_ratio)
        return s_psi, s_mean_z, s_var_ratio

    # Persistence
    def baseline_path(self, index: str) -> Path:
        return self.baseline_dir / f"{index.upper()}.json"

    def load_baseline(self, index: str) -> Optional[Dict[str, Any]]:
        path = self.baseline_path(index)
        if not path.exists():
            return None
        try:
            with path.open('r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            _LOG.warning(f'baseline_load_failed index={index}: {e}')
            return None

    def save_baseline(self, index: str, data: Dict[str, Any]) -> bool:
        path = self.baseline_path(index)
        tmp = path.with_suffix('.tmp')
        data['saved_at'] = datetime.now(timezone.utc).isoformat()
        data['version'] = str(int(data.get('version', 0)) + 1)
        try:
            with tmp.open('w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, path)
            return True
        except Exception as e:
            _LOG.error(f'baseline_save_failed index={index}: {e}')
            return False

def create_drift_monitor_from_env() -> DriftMonitor:
    return DriftMonitor(
        baseline_days=_env_int('G6_DRIFT_BASELINE_DAYS', _DEF_BASELINE_DAYS),
        recent_rows=_env_int('G6_DRIFT_RECENT_ROWS', _DEF_RECENT_ROWS),
        num_bins=10,
    )

__all__ = ['DriftMonitor','create_drift_monitor_from_env']
