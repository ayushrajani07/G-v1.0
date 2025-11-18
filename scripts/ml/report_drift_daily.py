#!/usr/bin/env python
"""Daily Drift Summary Reporter

Generates a JSON summary of current drift severity distribution, top critical features, and baseline ages.
Intended for ops automation (cron run near end-of-day). Output can feed dashboards or textfile collector.

Usage:
  python scripts/ml/report_drift_daily.py --indices NIFTY,BANKNIFTY --output reports/drift/daily.json
  python scripts/ml/report_drift_daily.py --output reports/drift/$(date +%Y-%m-%d).json

Environment Variables:
  G6_DRIFT_ENABLE            Should be 1 for metrics to exist
  G6_DRIFT_INDICES           Optional override for indices if --indices unset

Fields:
  generated_at               ISO8601 timestamp
  indices                    List of indices included
  counts                     Severity counts per index and aggregate
  top_critical               Up to top 10 critical features (psi desc) per index
  baseline_age_days          Current baseline age days per index
  eval_last_ms               Last evaluation timestamp ms per index
  notes                      Any warnings (e.g. missing metrics)
"""
from __future__ import annotations
import argparse, json, time
from datetime import datetime, timezone
from typing import Dict, Any

try:
    from src.web.dashboard import drift_metrics  # type: ignore
    from src.web.dashboard.prom_metrics import get_feature_drift_snapshot  # type: ignore
except Exception:
    drift_metrics = None  # type: ignore
    get_feature_drift_snapshot = None  # type: ignore

SEVERITY_LABELS = {0:'stable',1:'watch',2:'actionable',3:'critical'}


def collect_index_summary(index: str) -> Dict[str, Any]:
    features = []
    if get_feature_drift_snapshot:
        try:
            features = get_feature_drift_snapshot(index)
        except Exception:
            features = []
    counts = {'stable':0,'watch':0,'actionable':0,'critical':0}
    critical = []
    for rec in features:
        sev_raw = rec.get('severity')
        if isinstance(sev_raw,(int,float)) and int(sev_raw) in SEVERITY_LABELS:
            sev = SEVERITY_LABELS[int(sev_raw)]
        else:
            sev = 'stable'
        counts[sev] += 1
        if sev == 'critical':
            critical.append(rec)
    # Sort critical by psi desc
    critical.sort(key=lambda r: r.get('psi',0.0), reverse=True)
    critical = critical[:10]
    # Registry metrics (baseline age, eval timestamps)
    baseline_age = None
    eval_last_ms = None
    reg = None
    try:
        if drift_metrics:
            reg = drift_metrics.get_registry()
    except Exception:
        reg = None
    if reg is not None:
        for fam in reg.collect():
            name = getattr(fam,'name',None)
            if name == 'g6_drift_baseline_age_days':
                for s in fam.samples:
                    if s.labels.get('index') == index:
                        baseline_age = s.value
            elif name == 'g6_drift_last_eval_ms':
                for s in fam.samples:
                    if s.labels.get('index') == index:
                        eval_last_ms = s.value
    return {
        'index': index,
        'counts': counts,
        'top_critical': [
            {
                'feature': c.get('feature'),
                'psi': c.get('psi'),
                'mean_delta_zscore': c.get('mean_delta_zscore'),
                'var_ratio': c.get('var_ratio'),
            } for c in critical
        ],
        'baseline_age_days': baseline_age,
        'eval_last_ms': eval_last_ms,
    }


def main():
    ap = argparse.ArgumentParser(description='Daily drift summary reporter')
    ap.add_argument('--indices', help='Comma-separated indices', default=None)
    ap.add_argument('--output', help='Output JSON file path', required=True)
    ap.add_argument('--pretty', action='store_true', help='Pretty-print JSON')
    args = ap.parse_args()
    if args.indices:
        indices = [s.strip().upper() for s in args.indices.split(',') if s.strip()]
    else:
        import os
        indices = [s.strip().upper() for s in os.environ.get('G6_DRIFT_INDICES','NIFTY').split(',') if s.strip()]
    summaries = [collect_index_summary(i) for i in indices]
    aggregate = {'stable':0,'watch':0,'actionable':0,'critical':0}
    for s in summaries:
        for k,v in s['counts'].items():
            aggregate[k] += v
    notes = []
    if not any(s['counts']['critical'] for s in summaries):
        notes.append('no_critical_features')
    if drift_metrics is None or get_feature_drift_snapshot is None:
        notes.append('metrics_module_unavailable')
    out = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'indices': indices,
        'aggregate_counts': aggregate,
        'per_index': summaries,
        'notes': notes,
        'version': 1,
    }
    # Ensure directory
    import os
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output,'w',encoding='utf-8') as f:
        if args.pretty:
            json.dump(out,f,indent=2)
        else:
            json.dump(out,f,separators=(',',':'))
    print(args.output)

if __name__ == '__main__':
    main()
