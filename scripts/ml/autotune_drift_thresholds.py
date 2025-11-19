#!/usr/bin/env python
"""Auto-tuning scaffolding for drift threshold percentiles.

Goal: Adjust warn/crit percentiles (and coverage lower percentiles) to achieve
stable target violation rates without overreacting to transient volatility.

Strategy (initial):
1. Collect recent calibration artifacts (JSON) from metrics/drift_baselines.
2. For each horizon metric set, derive empirical violation rate proxies:
   - Using latest aggregate thresholds vs historical raw metric distributions.
3. Define target bands (configurable):
   warn_violation_target_range = (0.05, 0.12)
   crit_violation_target_range = (0.01, 0.04)
4. Nudge percentiles by step (e.g. 0.01) toward direction that reduces deviation
   only if sample size >= min_samples and stability report status == 'stable'.
5. Provide a dry-run backtest scoring summary.

Exports a function `auto_tune_percentiles(context)` returning a dict:
{
  'warn_pctl_new': float,
  'crit_pctl_new': float,
  'coverage_warn_low_pctl_new': float,
  'coverage_crit_low_pctl_new': float,
  'adjustments': [ { 'key': 'warn_pctl', 'old': 0.85, 'new': 0.86, 'reason': 'violation_rate_low' }, ... ],
  'score_before': {...},
  'score_after': {...},
  'stable': bool,
}

Initial placeholders implemented; violation rate estimation uses synthetic heuristics
until real violation logs integrated.
"""
from __future__ import annotations

import os, json, statistics
from typing import Any, Dict, List, Sequence, Tuple
from dataclasses import dataclass

DEFAULT_TARGETS = {
    'warn_rate_min': 0.05,
    'warn_rate_max': 0.12,
    'crit_rate_min': 0.01,
    'crit_rate_max': 0.04,
}

@dataclass
class PercentileSet:
    warn_pctl: float
    crit_pctl: float
    coverage_warn_low_pctl: float
    coverage_crit_low_pctl: float

@dataclass
class ArtifactSnapshot:
    file: str
    aggregate: Dict[str, Any]

# Heuristic keys expected in aggregate
WARN_KEYS = ['mae_warn','norm_warn']
CRIT_KEYS = ['mae_crit','norm_crit']
COVERAGE_WARN_KEYS = ['coverage_drop_warn']
COVERAGE_CRIT_KEYS = ['coverage_drop_crit']

MIN_SAMPLE_ARTIFACTS = 5
PCTL_STEP = 0.01
SAMPLE_LOG_DIR = 'metrics/drift_samples'  # expected directory of per-sample JSON logs (optional)

# Sample log schema (expected best-effort):
# {
#   "horizon": 15,
#   "mae_values": [ ... ],
#   "norm_error_values": [ ... ],
#   "coverage_drop_values": [ ... ]
# }

def _backtest_penalty(artifacts: List[ArtifactSnapshot], pctls: PercentileSet) -> float:
    """Placeholder backtest scoring: aggregate deviation of heuristic violation rates.
    Real implementation would replay historical samples vs candidate thresholds.
    """
    rates = _estimate_violation_rates(artifacts, pctls)
    score = _score(rates, DEFAULT_TARGETS)
    return score['total_penalty']

def _load_artifacts(dir_path: str) -> List[ArtifactSnapshot]:
    out: List[ArtifactSnapshot] = []
    if not os.path.isdir(dir_path):
        return out
    for name in sorted(os.listdir(dir_path), reverse=True):
        if not name.startswith('calibrated_thresholds_') or not name.endswith('.json'):
            continue
        path = os.path.join(dir_path, name)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            agg = data.get('aggregate') or {}
            out.append(ArtifactSnapshot(file=path, aggregate=agg))
            if len(out) >= 50:  # cap lookback
                break
        except Exception:
            continue
    return out

def _load_sample_logs(dir_path: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not os.path.isdir(dir_path):
        return out
    for name in sorted(os.listdir(dir_path), reverse=True):
        if not name.endswith('.json'):
            continue
        path = os.path.join(dir_path, name)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                js = json.load(f)
            if isinstance(js, dict):
                out.append(js)
            if len(out) >= 200:  # cap samples
                break
        except Exception:
            continue
    return out

def _fraction_exceed(values: Sequence[float], threshold: float, invert: bool = False) -> float:
    if not values:
        return 0.0
    if invert:  # coverage drop thresholds are negative; treat exceed as value <= threshold
        cnt = sum(1 for v in values if v <= threshold)
    else:
        cnt = sum(1 for v in values if v >= threshold)
    return round(cnt / len(values), 6)

def _estimate_violation_rates(artifacts: List[ArtifactSnapshot], pctls: PercentileSet) -> Dict[str, float]:
    """Estimate violation rates using real sample logs if available, else fallback heuristic.

    Real path: fraction of per-sample metric values exceeding threshold.
    Fallback: ratio using aggregate means (legacy heuristic).
    """
    rates: Dict[str, float] = {}
    samples = _load_sample_logs(SAMPLE_LOG_DIR)
    if samples:
        mae_vals: List[float] = []
        norm_vals: List[float] = []
        cov_vals: List[float] = []
        for row in samples:
            for k in ('mae_values','mae'):  # tolerate variant keys
                v = row.get(k)
                if isinstance(v, list):
                    mae_vals.extend(float(x) for x in v if isinstance(x,(int,float)))
            for k in ('norm_error_values','norm_errors','norm'):  # variant
                v = row.get(k)
                if isinstance(v, list):
                    norm_vals.extend(float(x) for x in v if isinstance(x,(int,float)))
            for k in ('coverage_drop_values','coverage_values'):
                v = row.get(k)
                if isinstance(v, list):
                    cov_vals.extend(float(x) for x in v if isinstance(x,(int,float)))
        if mae_vals:
            rates['warn_violation_rate'] = _fraction_exceed(mae_vals, pctls.warn_pctl)
            rates['crit_violation_rate'] = _fraction_exceed(mae_vals, pctls.crit_pctl)
        if norm_vals:
            # Combine with mae if present; keep higher violation rate representation
            r_warn_norm = _fraction_exceed(norm_vals, pctls.warn_pctl)
            r_crit_norm = _fraction_exceed(norm_vals, pctls.crit_pctl)
            rates['warn_violation_rate'] = max(rates.get('warn_violation_rate',0.0), r_warn_norm)
            rates['crit_violation_rate'] = max(rates.get('crit_violation_rate',0.0), r_crit_norm)
        if cov_vals:
            rates['coverage_warn_violation_rate'] = _fraction_exceed(cov_vals, pctls.coverage_warn_low_pctl, invert=True)
            rates['coverage_crit_violation_rate'] = _fraction_exceed(cov_vals, pctls.coverage_crit_low_pctl, invert=True)
        return rates
    # Fallback heuristic (aggregates only)
    if not artifacts:
        return rates
    dist: Dict[str, List[float]] = {k: [] for k in WARN_KEYS + CRIT_KEYS + COVERAGE_WARN_KEYS + COVERAGE_CRIT_KEYS}
    for snap in artifacts:
        agg = snap.aggregate
        for key in dist.keys():
            v = agg.get(key)
            if isinstance(v, (int,float)):
                dist[key].append(float(v))
    def _heuristic_rate(mean_val: float, threshold: float) -> float:
        if threshold <= 0 or mean_val <= 0:
            return 0.0
        raw = (mean_val - threshold)/max(mean_val, threshold)
        return max(0.0, min(1.0, raw))
    warn_key = next((k for k in WARN_KEYS if dist[k]), None)
    crit_key = next((k for k in CRIT_KEYS if dist[k]), None)
    cov_warn_key = next((k for k in COVERAGE_WARN_KEYS if dist[k]), None)
    cov_crit_key = next((k for k in COVERAGE_CRIT_KEYS if dist[k]), None)
    if warn_key:
        mean_warn = statistics.fmean(dist[warn_key])
        rates['warn_violation_rate'] = _heuristic_rate(mean_warn, pctls.warn_pctl)
    if crit_key:
        mean_crit = statistics.fmean(dist[crit_key])
        rates['crit_violation_rate'] = _heuristic_rate(mean_crit, pctls.crit_pctl)
    if cov_warn_key:
        mean_covw = statistics.fmean(dist[cov_warn_key])
        rates['coverage_warn_violation_rate'] = _heuristic_rate(abs(mean_covw), abs(pctls.coverage_warn_low_pctl))
    if cov_crit_key:
        mean_covc = statistics.fmean(dist[cov_crit_key])
        rates['coverage_crit_violation_rate'] = _heuristic_rate(abs(mean_covc), abs(pctls.coverage_crit_low_pctl))
    return rates

def _estimate_violation_rates_by_horizon(pctls: PercentileSet) -> Dict[int, Dict[str, float]]:
    """Compute violation rates grouped by horizon using sample logs.
    Returns mapping: horizon -> {warn_violation_rate, crit_violation_rate, coverage_warn_violation_rate, coverage_crit_violation_rate}
    If no sample logs, returns empty dict.
    """
    samples = _load_sample_logs(SAMPLE_LOG_DIR)
    if not samples:
        return {}
    buckets: Dict[int, Dict[str, List[float]]] = {}
    for row in samples:
        h = int(row.get('horizon') or 0)
        if h not in buckets:
            buckets[h] = {'mae': [], 'norm': [], 'cov': []}
        for k in ('mae_values','mae'):
            v = row.get(k)
            if isinstance(v, list):
                buckets[h]['mae'].extend(float(x) for x in v if isinstance(x,(int,float)))
        for k in ('norm_error_values','norm_errors','norm'):
            v = row.get(k)
            if isinstance(v, list):
                buckets[h]['norm'].extend(float(x) for x in v if isinstance(x,(int,float)))
        for k in ('coverage_drop_values','coverage_values'):
            v = row.get(k)
            if isinstance(v, list):
                buckets[h]['cov'].extend(float(x) for x in v if isinstance(x,(int,float)))
    out: Dict[int, Dict[str, float]] = {}
    for h, d in buckets.items():
        mae = d['mae']; norm = d['norm']; cov = d['cov']
        if not (mae or norm or cov):
            continue
        warn = 0.0; crit = 0.0
        if mae:
            warn = max(warn, _fraction_exceed(mae, pctls.warn_pctl))
            crit = max(crit, _fraction_exceed(mae, pctls.crit_pctl))
        if norm:
            warn = max(warn, _fraction_exceed(norm, pctls.warn_pctl))
            crit = max(crit, _fraction_exceed(norm, pctls.crit_pctl))
        covw = _fraction_exceed(cov, pctls.coverage_warn_low_pctl, invert=True) if cov else 0.0
        covc = _fraction_exceed(cov, pctls.coverage_crit_low_pctl, invert=True) if cov else 0.0
        out[h] = {
            'warn_violation_rate': warn,
            'crit_violation_rate': crit,
            'coverage_warn_violation_rate': covw,
            'coverage_crit_violation_rate': covc,
        }
    return out

def _adaptive_step(base_step: float, rate: float | None, lo: float, hi: float) -> float:
    """Scale step size based on distance from target band.
    - within band: 0
    - up to 2pp away: 1x step; 2–5pp: 2x; >5pp: 3x (pp in absolute terms)
    """
    if rate is None:
        return base_step
    if lo <= rate <= hi:
        return 0.0
    dist = 0.0
    if rate < lo:
        dist = lo - rate
    elif rate > hi:
        dist = rate - hi
    if dist > 0.05:
        return base_step * 3.0
    if dist > 0.02:
        return base_step * 2.0
    return base_step

def _score(rates: Dict[str,float], targets: Dict[str,float]) -> Dict[str, Any]:
    score: Dict[str, Any] = {'components': {}, 'total_penalty': 0.0}
    def _component(rate: float, lo: float, hi: float) -> float:
        if rate < lo:
            return lo - rate
        if rate > hi:
            return rate - hi
        return 0.0
    w_pen = _component(rates.get('warn_violation_rate',0.0), targets['warn_rate_min'], targets['warn_rate_max'])
    c_pen = _component(rates.get('crit_violation_rate',0.0), targets['crit_rate_min'], targets['crit_rate_max'])
    score['components'] = {'warn_penalty': w_pen, 'crit_penalty': c_pen}
    score['total_penalty'] = w_pen + c_pen
    return score

def auto_tune_percentiles(
    artifact_dir: str,
    current: PercentileSet,
    targets: Dict[str,float] | None = None,
    min_artifacts: int = MIN_SAMPLE_ARTIFACTS,
    step: float = PCTL_STEP,
    epsilon: float = 0.005,
    produce_canary: bool = True,
) -> Dict[str, Any]:
    t = targets or DEFAULT_TARGETS
    artifacts = _load_artifacts(artifact_dir)
    if len(artifacts) < min_artifacts:
        return {'stable': False, 'reason': 'insufficient_artifacts', 'count': len(artifacts)}
    rates_before = _estimate_violation_rates(artifacts, current)
    score_before = _score(rates_before, t)
    new = PercentileSet(
        warn_pctl=current.warn_pctl,
        crit_pctl=current.crit_pctl,
        coverage_warn_low_pctl=current.coverage_warn_low_pctl,
        coverage_crit_low_pctl=current.coverage_crit_low_pctl,
    )
    adjustments = []
    # Nudge warn with adaptive step
    w_rate = rates_before.get('warn_violation_rate')
    w_step = _adaptive_step(step, w_rate, t['warn_rate_min'], t['warn_rate_max'])
    if w_step > 0:
        if w_rate is not None and w_rate < t['warn_rate_min'] and new.warn_pctl < 0.90:
            old = new.warn_pctl; new.warn_pctl = round(min(0.90, new.warn_pctl + w_step),4)
            adjustments.append({'key':'warn_pctl','old':old,'new':new.warn_pctl,'reason':'violation_rate_low','adaptive_step':w_step})
        elif w_rate is not None and w_rate > t['warn_rate_max'] and new.warn_pctl > 0.80:
            old = new.warn_pctl; new.warn_pctl = round(max(0.80, new.warn_pctl - w_step),4)
            adjustments.append({'key':'warn_pctl','old':old,'new':new.warn_pctl,'reason':'violation_rate_high','adaptive_step':w_step})
    # Nudge crit with adaptive step
    c_rate = rates_before.get('crit_violation_rate')
    c_step = _adaptive_step(step, c_rate, t['crit_rate_min'], t['crit_rate_max'])
    if c_step > 0:
        if c_rate is not None and c_rate < t['crit_rate_min'] and new.crit_pctl < 0.97:
            old = new.crit_pctl; new.crit_pctl = round(min(0.97, new.crit_pctl + c_step),4)
            adjustments.append({'key':'crit_pctl','old':old,'new':new.crit_pctl,'reason':'violation_rate_low','adaptive_step':c_step})
        elif c_rate is not None and c_rate > t['crit_rate_max'] and new.crit_pctl > 0.92:
            old = new.crit_pctl; new.crit_pctl = round(max(0.92, new.crit_pctl - c_step),4)
            adjustments.append({'key':'crit_pctl','old':old,'new':new.crit_pctl,'reason':'violation_rate_high','adaptive_step':c_step})
    # Coverage nudge placeholder (future real logic)
    rates_after = _estimate_violation_rates(artifacts, new)
    score_after = _score(rates_after, t)
    backtest_before = _backtest_penalty(artifacts, current)
    backtest_after = _backtest_penalty(artifacts, new)
    penalty_improvement = score_before['total_penalty'] - score_after['total_penalty']
    converged = penalty_improvement < epsilon
    if converged:
        # Revert adjustments if improvement negligible
        new = current
        if adjustments:
            adjustments.append({'key':'_converged','old': score_before['total_penalty'], 'new': score_after['total_penalty'], 'reason':'penalty_improvement<epsilon'})
    # Canary percentile alternative (exploratory)
    canary = None
    if produce_canary and not converged:
        canary_set = PercentileSet(
            warn_pctl=min(0.90, new.warn_pctl + step),
            crit_pctl=max(0.92, new.crit_pctl - step),
            coverage_warn_low_pctl=new.coverage_warn_low_pctl,
            coverage_crit_low_pctl=new.coverage_crit_low_pctl,
        )
        can_rates = _estimate_violation_rates(artifacts, canary_set)
        can_score = _score(can_rates, t)
        can_backtest = _backtest_penalty(artifacts, canary_set)
        ph = _estimate_violation_rates_by_horizon(canary_set)
        canary = {
            'warn_pctl': canary_set.warn_pctl,
            'crit_pctl': canary_set.crit_pctl,
            'score': can_score,
            'backtest_penalty': can_backtest,
            'rates': can_rates,
            'per_horizon': ph,
        }
    return {
        'stable': True,
        'warn_pctl_new': new.warn_pctl,
        'crit_pctl_new': new.crit_pctl,
        'coverage_warn_low_pctl_new': new.coverage_warn_low_pctl,
        'coverage_crit_low_pctl_new': new.coverage_crit_low_pctl,
        'adjustments': adjustments,
        'score_before': score_before,
        'score_after': score_after,
        'rates_before': rates_before,
        'rates_after': rates_after,
        'artifact_count': len(artifacts),
        'backtest_before': backtest_before,
        'backtest_after': backtest_after,
        'penalty_improvement': penalty_improvement,
        'epsilon': epsilon,
        'converged': converged,
        'canary': canary,
        'per_horizon': _estimate_violation_rates_by_horizon(new),
    }

if __name__ == '__main__':  # pragma: no cover
    import argparse
    ap = argparse.ArgumentParser(description='Dry-run auto-tune percentiles')
    ap.add_argument('--artifact-dir', default='metrics/drift_baselines')
    ap.add_argument('--warn-pctl', type=float, default=0.85)
    ap.add_argument('--crit-pctl', type=float, default=0.95)
    ap.add_argument('--coverage-warn-low-pctl', type=float, default=0.15)
    ap.add_argument('--coverage-crit-low-pctl', type=float, default=0.05)
    args = ap.parse_args()
    current = PercentileSet(args.warn_pctl, args.crit_pctl, args.coverage_warn_low_pctl, args.coverage_crit_low_pctl)
    res = auto_tune_percentiles(args.artifact_dir, current)
    print(json.dumps(res, indent=2, sort_keys=True))
