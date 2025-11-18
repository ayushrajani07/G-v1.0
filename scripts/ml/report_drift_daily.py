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


def _emit_textfile_metrics(out: Dict[str, Any], textfile_dir: str) -> str:
    """Emit Prometheus textfile metrics for node_exporter textfile collector.

    Metrics emitted:
      g6_drift_daily_severity_count{index="NIFTY",severity="critical"} <value>
      g6_drift_daily_baseline_age_days{index="NIFTY"} <age>
      g6_drift_daily_eval_last_ms{index="NIFTY"} <timestamp_ms>
      g6_drift_daily_top_feature_psi{index="NIFTY",feature="ce_iv",rank="1"} <psi>
    """
    import os
    lines = []
    ts = int(datetime.now(timezone.utc).timestamp())
    for idx_summary in out.get('per_index', []):
        index = idx_summary['index']
        for sev, val in idx_summary['counts'].items():
            lines.append(f'g6_drift_daily_severity_count{{index="{index}",severity="{sev}"}} {val}')
        age = idx_summary.get('baseline_age_days')
        if age is not None:
            lines.append(f'g6_drift_daily_baseline_age_days{{index="{index}"}} {age}')
        eval_ms = idx_summary.get('eval_last_ms')
        if eval_ms is not None:
            lines.append(f'g6_drift_daily_eval_last_ms{{index="{index}"}} {eval_ms}')
        top = idx_summary.get('top_critical') or []
        for rank, feat in enumerate(top, start=1):
            f_name = feat.get('feature')
            psi = feat.get('psi')
            if f_name is not None and psi is not None:
                lines.append(f'g6_drift_daily_top_feature_psi{{index="{index}",feature="{f_name}",rank="{rank}"}} {psi}')
    # Aggregate counts
    for sev, val in out.get('aggregate_counts', {}).items():
        lines.append(f'g6_drift_daily_severity_count_aggregate{{severity="{sev}"}} {val}')
    lines.append(f'g6_drift_daily_generation_timestamp {ts}')
    os.makedirs(textfile_dir, exist_ok=True)
    filepath = os.path.join(textfile_dir, 'drift_daily.prom')
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    return filepath

def main():
    ap = argparse.ArgumentParser(description='Daily drift summary reporter')
    ap.add_argument('--indices', help='Comma-separated indices', default=None)
    ap.add_argument('--output', help='Output JSON file path', required=True)
    ap.add_argument('--pretty', action='store_true', help='Pretty-print JSON')
    ap.add_argument('--textfile-dir', help='Optional directory to emit Prometheus textfile metrics', default=None)
    ap.add_argument('--retain-days', type=int, default=None, help='Delete daily_*.json older than N days in reports/drift')
    ap.add_argument('--trend-days', type=int, default=None, help='Build trend.json from last N days of daily_*.json')
    ap.add_argument('--trend-output', default='reports/drift/trend.json', help='Path to write severity trend JSON')
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
    textfile_path = None
    if args.textfile_dir:
        try:
            textfile_path = _emit_textfile_metrics(out, args.textfile_dir)
        except Exception as e:
            print(f'Textfile emission failed: {e}')
    print(args.output)
    if textfile_path:
        print(textfile_path)
    # Retention & trend generation
    import glob, os
    from datetime import timedelta
    drift_dir = os.path.dirname(args.output) or '.'
    if args.retain_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(args.retain_days))
        removed = []
        for p in glob.glob(os.path.join(drift_dir, 'daily_*.json')):
            try:
                with open(p,'r',encoding='utf-8') as f:
                    d = json.load(f)
                ts = d.get('generated_at')
                dt = datetime.fromisoformat(str(ts).replace('Z','+00:00')) if ts else None
                if dt and dt < cutoff:
                    os.remove(p)
                    removed.append(os.path.basename(p))
            except Exception:
                continue
        if removed:
            print('pruned:', ','.join(removed))
    if args.trend_days is not None:
        series = []
        per_index_series: Dict[str, list] = {}
        files = sorted(glob.glob(os.path.join(drift_dir, 'daily_*.json')))
        # Use last N files by generated_at
        items = []
        for p in files:
            try:
                d = json.load(open(p,'r',encoding='utf-8'))
                ts = d.get('generated_at')
                dt = datetime.fromisoformat(str(ts).replace('Z','+00:00')) if ts else None
                if dt:
                    items.append((dt, d))
            except Exception:
                continue
        items.sort(key=lambda x: x[0])
        if args.trend_days > 0:
            items = items[-int(args.trend_days):]
        for dt, d in items:
            gen_at = d.get('generated_at')
            series.append({'generated_at': gen_at, 'aggregate_counts': d.get('aggregate_counts', {})})
            # Build per-index series element
            for pi in d.get('per_index', []):
                idx = pi.get('index')
                if not idx:
                    continue
                per_index_series.setdefault(idx, []).append({
                    'generated_at': gen_at,
                    'counts': pi.get('counts', {}),
                })
        os.makedirs(os.path.dirname(args.trend_output) or '.', exist_ok=True)
        with open(args.trend_output, 'w', encoding='utf-8') as tf:
            json.dump({'series': series, 'per_index_series': per_index_series, 'count': len(series)}, tf, indent=2)
        print(args.trend_output)

if __name__ == '__main__':
    main()
