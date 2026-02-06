"""Universal Advisor Prometheus Exporter.

Runs the advisor engine periodically (default every 60s) and exposes a small
set of gauges for Prometheus to scrape:

  advisor_health_score{index="NIFTY"} 92
  advisor_overall_level{index="NIFTY",level="ok"} 1  (one-hot style)
  advisor_flag{index="NIFTY",code="ann_speedup_drop"} 1 (active finding flags)

Design notes:
* We call the engine directly instead of hitting the FastAPI endpoint to avoid
  network overhead and dependency on the web server.
* Engine now computes per-index health_score & level (summary.per_index). We
  export those directly; aggregate overall remains for dashboards/alerts.
* Flags are exported using a generic advisor_flag gauge with code label to keep
  cardinality manageable (codes are few / bounded by findings set).

Usage (local):
  python scripts/advisor/universal_advisor_exporter.py --port 9322 --indices NIFTY,BANKNIFTY,SENSEX

Prometheus scrape job example (added separately in prometheus.yml):
  - job_name: 'advisor_health'
    static_configs:
      - targets: ['127.0.0.1:9322']
        labels:
          job: 'advisor_health'
          instance: 'advisor-universal'

"""
from __future__ import annotations
import argparse, time, threading, signal, sys
from prometheus_client import start_http_server, Gauge, CollectorRegistry
from typing import List

from src.advisor.core import AdvisorContext, build_default_engine

# --- Prometheus Metrics ---
registry = CollectorRegistry()

g_health_score = Gauge('advisor_health_score','Advisor health score (0-100)', ['index'], registry=registry)

g_overall_level = Gauge('advisor_overall_level','Advisor overall level one-hot (set to 1 for the current level)', ['index','level'], registry=registry)

g_flag = Gauge(
    'advisor_flag',
    'Advisor active finding flags (value 1 while active)',
    ['index','code'], registry=registry
)
g_composite_risk = Gauge(
  'advisor_composite_risk',
  'Composite risk indicator (1 when composite correlation active)',
  ['index','type'], registry=registry
)

shutdown = False

def run_cycle(indices: List[str], windows: List[int], horizons: List[int], params: dict):
    ctx = AdvisorContext(indices=indices, horizons=horizons, windows=windows, now=time.time(), params=params)
    engine = build_default_engine(ctx)
    report = engine.run(ctx)
    summary = report['summary']
    flags = report.get('flags', {})
    per_index = summary.get('per_index', {})

    # Export metrics per index if available; fall back to overall for any missing.
    overall_health = int(summary.get('health_score', 0))
    overall_level = summary.get('overall_level', 'unknown')
    for idx in indices:
        h = int(per_index.get(idx, {}).get('health_score', overall_health))
        lvl = str(per_index.get(idx, {}).get('level', overall_level))
        g_health_score.labels(index=idx).set(h)
        for l in ('ok','warn','crit','unknown'):
            g_overall_level.labels(index=idx, level=l).set(1 if l == lvl else 0)
        for code, active in flags.items():
            if active:
                g_flag.labels(index=idx, code=code).set(1)
    # Export composite risk metrics if engine emitted any (they appear in metrics list)
    for m in report.get('metrics', []):
      if m.get('name') == 'advisor_composite_risk':
        labels = m.get('labels', {})
        g_composite_risk.labels(
          index=labels.get('index', 'UNKNOWN'),
          type=labels.get('type', 'generic'),
        ).set(float(m.get('value', 1)))

def loop(indices: List[str], interval: int, windows: List[int], horizons: List[int], params: dict):
    while not shutdown:
        start_ts = time.time()
        try:
            run_cycle(indices, windows, horizons, params)
        except Exception as e:
            # Exporter errors are logged to stderr; we don't raise to keep loop alive.
            print(f"[advisor_exporter] cycle error: {e}", file=sys.stderr)
        dur = time.time() - start_ts
        sleep_for = max(1, interval - dur)
        time.sleep(sleep_for)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=9322)
    parser.add_argument('--indices', type=str, default='NIFTY')
    parser.add_argument('--windows', type=str, default='60,120')
    parser.add_argument('--horizons', type=str, default='60')
    parser.add_argument('--interval', type=int, default=60)
    parser.add_argument('--use-prometheus', action='store_true', help='Query Prometheus instead of scraping exporters (pass --prometheus-url)')
    parser.add_argument('--prometheus-url', type=str, default=None)
    parser.add_argument('--ann-ports', type=str, default='9308,9309,9310')
    args = parser.parse_args()

    idxs = [s.strip().upper() for s in args.indices.split(',') if s.strip()]
    ws = [int(x) for x in args.windows.split(',') if x.strip()]
    hs = [int(x) for x in args.horizons.split(',') if x.strip()]

    params = {
        'prometheus': (args.prometheus_url if args.use_prometheus else None),
        'ann_ports': args.ann_ports,
        # path plugin defaults (mirroring API route)
        'path_horizon': 60,
        'path_window_minutes': 180,
        'path_expiry_tag': 'this_month',
        'path_offset': '0',
        'path_bucket_ms': 60000,
    }

    start_http_server(args.port, registry=registry)
    print(f"[advisor_exporter] started on :{args.port} for indices={idxs} interval={args.interval}s")

    def handle_sig(signum, frame):
        global shutdown
        shutdown = True
        print('[advisor_exporter] shutdown signal received')

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, handle_sig)

    loop(idxs, args.interval, ws, hs, params)

if __name__ == '__main__':
    main()
