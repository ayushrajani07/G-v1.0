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
from typing import Any, Dict, List
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

def _estimate_violation_rates(artifacts: List[ArtifactSnapshot], pctls: PercentileSet) -> Dict[str, float]:
    """Synthetic placeholder: use dispersion of warn/crit metrics vs central tendency to approximate violation rate.

    In real path: compute actual fraction of samples exceeding thresholds.
    Here: For each metric type we derive ratio of mean to threshold to approximate aggressiveness.
    """
    rates: Dict[str, float] = {}
    if not artifacts:
        return rates
    # Collect distributions for each key
    dist: Dict[str, List[float]] = {k: [] for k in WARN_KEYS + CRIT_KEYS + COVERAGE_WARN_KEYS + COVERAGE_CRIT_KEYS}
    for snap in artifacts:
        agg = snap.aggregate
        for key in dist.keys():
            v = agg.get(key)
            if isinstance(v, (int,float)):
                dist[key].append(float(v))
    # Simple heuristic: violation_rate ≈ max(0, (mean - threshold)/max(mean, threshold)) clipped
    def _heuristic_rate(mean_val: float, threshold: float) -> float:
        if threshold <= 0 or mean_val <= 0:
            return 0.0
        raw = (mean_val - threshold)/max(mean_val, threshold)
        return max(0.0, min(1.0, raw))
    # Use first warn key for warn threshold estimation etc.
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
    # Nudge warn
    w_rate = rates_before.get('warn_violation_rate')
    if w_rate is not None:
        if w_rate < t['warn_rate_min'] and new.warn_pctl < 0.90:
            old = new.warn_pctl; new.warn_pctl = round(min(0.90, new.warn_pctl + step),4)
            adjustments.append({'key':'warn_pctl','old':old,'new':new.warn_pctl,'reason':'violation_rate_low'})
        elif w_rate > t['warn_rate_max'] and new.warn_pctl > 0.80:
            old = new.warn_pctl; new.warn_pctl = round(max(0.80, new.warn_pctl - step),4)
            adjustments.append({'key':'warn_pctl','old':old,'new':new.warn_pctl,'reason':'violation_rate_high'})
    # Nudge crit
    c_rate = rates_before.get('crit_violation_rate')
    if c_rate is not None:
        if c_rate < t['crit_rate_min'] and new.crit_pctl < 0.97:
            old = new.crit_pctl; new.crit_pctl = round(min(0.97, new.crit_pctl + step),4)
            adjustments.append({'key':'crit_pctl','old':old,'new':new.crit_pctl,'reason':'violation_rate_low'})
        elif c_rate > t['crit_rate_max'] and new.crit_pctl > 0.92:
            old = new.crit_pctl; new.crit_pctl = round(max(0.92, new.crit_pctl - step),4)
            adjustments.append({'key':'crit_pctl','old':old,'new':new.crit_pctl,'reason':'violation_rate_high'})
    # Coverage nudge placeholder (future real logic)
    rates_after = _estimate_violation_rates(artifacts, new)
    score_after = _score(rates_after, t)
    backtest_before = _backtest_penalty(artifacts, current)
    backtest_after = _backtest_penalty(artifacts, new)
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
