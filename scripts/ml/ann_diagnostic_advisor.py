#!/usr/bin/env python
"""ANN Diagnostic Advisor (Initial Skeleton)

Aggregates live ANN health metrics from Prometheus and compares against baseline
thresholds to produce a structured recommendation report per index.

Contract (v0):
Inputs:
  --indices NIFTY,BANKNIFTY,SENSEX   Comma-separated list of indices
  --baseline baselines/ann_daily_baseline.json  Path to nested baseline JSON
  --prometheus http://127.0.0.1:9090            Prometheus base URL (optional; if omitted attempts direct metric endpoint scraping via --ports)
  --ports 9308,9309,9310                        Exporter ports (fallback live scrape when Prometheus not reachable)
  --windows 60,120                              Retrieval windows to assess
  --min-rows 5                                  Minimum rows gating for regressions
  --speedup-drop-threshold 0.05                 Speedup drop (baseline - live > threshold) triggers concern
  --mad-max 0.05                                MAD above this triggers concern
  --prune-max 0.90                              Prune ratio above this triggers concern
  --effectiveness-min 0.02                      Adjusted effectiveness below triggers concern (if present)
  --refresh-suggestion-margin 0.02              If baseline differs from live by less than margin and all healthy -> suggest baseline refresh
Outputs:
  JSON (printed to stdout) schema:
  {
     "generated_at": ISO8601,
     "indices": {
        "NIFTY": {
           "windows": {
              "60": {"speedup": 0.90, "baseline_speedup": 0.93, "speedup_drop": 0.03, ...,
                      "flags": ["speedup_drop"], "recommendations": ["retune_ann"], "rows": 15},
              "120": {...}
           },
           "aggregate": {"regression_flags": [...], "actions": ["retune_ann"], "healthy": false}
        },
        ...
     }
  }

Future versions:
 - Incorporate multi-window burn-rate analysis (5m vs 1h deltas via recording rules)
 - Composite health score
 - Advisor playbook mapping (link to ANN_RUNBOOK.md sections)

"""
from __future__ import annotations
import argparse, json, os, sys, time, datetime, re
from pathlib import Path
from typing import Dict, Any, List

try:
    import requests  # type: ignore
except ImportError:
    requests = None  # Fallback; we will error if Prometheus querying is requested.

REPO_ROOT = Path(__file__).resolve().parents[2]

PROM_QUERIES_TEMPLATE = {
    'speedup': 'ann_health_speedup{index="{index}",window="{window}"}',
    'prune_ratio': 'ann_health_prune_ratio{index="{index}",window="{window}"}',
    'mad': 'ann_health_q50_mad{index="{index}",window="{window}"}',
    'rows': 'ann_health_rows{index="{index}",window="{window}"}',
    'effectiveness': 'ann_health_effectiveness_adjusted{index="{index}",window="{window}"}',
    'guard_rate': 'ann_health_guard_trigger_rate{index="{index}",window="{window}"}',
}

METRIC_LINE_REGEX = re.compile(r'^(?P<name>ann_health_[a-z_]+)\{([^}]*)index="(?P<index>[A-Z0-9_]+)",window="(?P<window>[0-9]+)"[^}]*\}\s+(?P<value>[-+]?[0-9]*\.?[0-9]+)$')


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--indices', default='NIFTY,BANKNIFTY,SENSEX')
    ap.add_argument('--baseline', default=str(REPO_ROOT / 'baselines' / 'ann_daily_baseline.json'))
    ap.add_argument('--prometheus', help='Prometheus base URL (e.g., http://127.0.0.1:9090)')
    ap.add_argument('--ports', default='9308,9309,9310', help='Exporter ports when scraping directly (comma-separated)')
    ap.add_argument('--windows', default='60,120')
    ap.add_argument('--min-rows', type=int, default=5)
    ap.add_argument('--speedup-drop-threshold', type=float, default=0.05)
    ap.add_argument('--mad-max', type=float, default=0.05)
    ap.add_argument('--prune-max', type=float, default=0.90)
    ap.add_argument('--effectiveness-min', type=float, default=0.02)
    ap.add_argument('--refresh-suggestion-margin', type=float, default=0.02)
    ap.add_argument('--output', help='Optional file path to write JSON (default stdout)')
    ap.add_argument('--verbose', action='store_true')
    return ap.parse_args()


def load_baseline(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f'baseline not found: {path}')
    doc = json.loads(path.read_text(encoding='utf-8'))
    # Normalize flat -> nested under NIFTY
    if any(k.startswith('retrieval_') for k in doc.keys()):
        doc = {'NIFTY': doc}
    return doc


def query_prometheus(base: str, prom_query: str) -> float:
    if not requests:
        raise RuntimeError('requests not installed; cannot query Prometheus')
    url = f'{base.rstrip('/')}/api/v1/query'
    try:
        r = requests.get(url, params={'query': prom_query}, timeout=5)
        r.raise_for_status()
        data = r.json()
        if data.get('status') != 'success':
            return float('nan')
        result = data.get('data', {}).get('result', [])
        if not result:
            return float('nan')
        # Take first value
        val = result[0].get('value', [None, None])[1]
        return float(val)
    except Exception:
        return float('nan')


def scrape_exporter(port: int) -> Dict[str, float]:
    # Scrape metrics text exposition
    import urllib.request
    out: Dict[str, float] = {}
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/') as resp:  # default root in start_http_server
            for raw in resp.read().decode('utf-8').splitlines():
                m = METRIC_LINE_REGEX.match(raw)
                if not m:
                    continue
                name = m.group('name')
                index = m.group('index')
                window = m.group('window')
                value = float(m.group('value'))
                key = f'{name}|{index}|{window}'
                out[key] = value
    except Exception:
        pass
    return out


def collect_live(ns) -> Dict[str, Dict[str, Dict[str, float]]]:
    indices = [i.strip() for i in ns.indices.split(',') if i.strip()]
    windows = [w.strip() for w in ns.windows.split(',') if w.strip()]
    live: Dict[str, Dict[str, Dict[str, float]]] = {idx: {w: {} for w in windows} for idx in indices}
    if ns.prometheus:
        for idx in indices:
            for w in windows:
                for alias, tmpl in PROM_QUERIES_TEMPLATE.items():
                    q = tmpl.format(index=idx, window=w)
                    live[idx][w][alias] = query_prometheus(ns.prometheus, q)
    else:
        # scrape exporter ports
        ports = [p.strip() for p in ns.ports.split(',') if p.strip()]
        for p in ports:
            metrics_map = scrape_exporter(int(p))
            for key, value in metrics_map.items():
                # key format: metric|INDEX|WINDOW
                try:
                    _, idx, w = key.split('|')
                except ValueError:
                    continue
                if idx in live and w in live[idx]:
                    metric_name = key.split('|')[0].replace('ann_health_', '')
                    live[idx][w][metric_name] = value
    return live


def evaluate(ns, baseline: Dict[str, Any], live: Dict[str, Dict[str, Dict[str, float]]]) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        'generated_at': datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z'),
        'indices': {}
    }
    for idx, windows_map in live.items():
        baseline_branch = baseline.get(idx, {}) if isinstance(baseline, dict) else {}
        idx_entry = {'windows': {}, 'aggregate': {'regression_flags': [], 'actions': [], 'healthy': True}}
        for w, metrics in windows_map.items():
            key = f'retrieval_{w}_k10'
            bvals = baseline_branch.get(key, {})
            speedup_live = metrics.get('speedup', float('nan'))
            prune_live = metrics.get('prune_ratio', float('nan'))
            mad_live = metrics.get('q50_mad', float('nan'))
            rows_live = metrics.get('rows', 0)
            eff_live = metrics.get('effectiveness_adjusted', metrics.get('effectiveness', float('nan')))
            flags: List[str] = []
            recs: List[str] = []
            baseline_speedup = bvals.get('speedup_avg', 0.0)
            speedup_drop = baseline_speedup - speedup_live if speedup_live == speedup_live else float('nan')
            # Regression gating
            if rows_live >= ns.min_rows:
                if speedup_drop > ns.speedup_drop_threshold:
                    flags.append('speedup_drop')
                if mad_live > ns.mad_max:
                    flags.append('mad_high')
                if prune_live > ns.prune_max:
                    flags.append('prune_high')
                if eff_live == eff_live and eff_live < ns.effectiveness_min:
                    flags.append('effectiveness_low')
            else:
                flags.append('insufficient_rows')
            # Recommendations mapping
            if 'insufficient_rows' in flags and len(flags) == 1:
                recs.append('collect_more_data')
            if any(f in flags for f in ['speedup_drop','mad_high','prune_high']) and 'insufficient_rows' not in flags:
                recs.append('investigate_ann')
            if 'effectiveness_low' in flags:
                recs.append('retune_or_guard_adjust')
            # Baseline refresh suggestion
            if not flags or all(f not in ['speedup_drop','mad_high','prune_high','effectiveness_low'] for f in flags if f != 'insufficient_rows'):
                if rows_live >= ns.min_rows and abs(speedup_drop) < ns.refresh_suggestion_margin:
                    recs.append('optional_baseline_refresh')
            window_entry = {
                'speedup': speedup_live,
                'baseline_speedup': baseline_speedup,
                'speedup_drop': speedup_drop,
                'prune_ratio': prune_live,
                'q50_mad': mad_live,
                'rows': rows_live,
                'effectiveness_adjusted': eff_live,
                'flags': flags,
                'recommendations': recs
            }
            idx_entry['windows'][w] = window_entry
            idx_entry['aggregate']['regression_flags'].extend([f for f in flags if f != 'insufficient_rows'])
            if any(f in flags for f in ['speedup_drop','mad_high','prune_high','effectiveness_low']):
                idx_entry['aggregate']['healthy'] = False
            for r in recs:
                if r not in idx_entry['aggregate']['actions']:
                    idx_entry['aggregate']['actions'].append(r)
        report['indices'][idx] = idx_entry
    return report


def main():
    ns = parse_args()
    baseline = load_baseline(Path(ns.baseline))
    live = collect_live(ns)
    report = evaluate(ns, baseline, live)
    text = json.dumps(report, indent=2)
    if ns.output:
        Path(ns.output).write_text(text, encoding='utf-8')
        if ns.verbose:
            print('[advisor] wrote report to', ns.output)
    else:
        print(text)

if __name__ == '__main__':
    main()
