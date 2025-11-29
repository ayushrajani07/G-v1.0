"""Automated retrain trigger workflow (Phase 12).

Checks drift attribution endpoint for retrain_signal and writes flag file when
threshold sustained. Intended for cron/CI invocation.

Usage (PowerShell):
  python -m src.ml.retrain_trigger --index NIFTY --horizon 60 --url http://localhost:9210 --critical 2.5 --warning 2.0
"""
from __future__ import annotations
import argparse, json, time, sys
from pathlib import Path
import urllib.request

FLAG_DIR = Path('data') / 'retrain_flags'
FLAG_DIR.mkdir(parents=True, exist_ok=True)

def fetch_components(base_url: str, index: str, horizon: int) -> dict:
    url = f"{base_url.rstrip('/')}/api/ml/ensemble/drift_attribution?index={index}&horizon={horizon}"
    with urllib.request.urlopen(url, timeout=10) as r:  # nosec
        return json.loads(r.read().decode('utf-8'))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--index', required=True)
    ap.add_argument('--horizon', type=int, default=60)
    ap.add_argument('--url', required=True)
    ap.add_argument('--critical', type=float, default=2.5)
    ap.add_argument('--warning', type=float, default=2.0)
    ap.add_argument('--samples', type=int, default=3, help='Consecutive samples required')
    ap.add_argument('--interval', type=float, default=30, help='Seconds between samples')
    args = ap.parse_args()

    samples = []
    for _ in range(args.samples):
        try:
            comp = fetch_components(args.url, args.index.upper(), args.horizon)
            samples.append(comp.get('retrain_signal', 0.0))
        except Exception:
            samples.append(0.0)
        if len(samples) < args.samples:
            time.sleep(args.interval)

    avg_signal = sum(samples) / max(len(samples),1)
    status = 'none'
    if avg_signal >= args.critical:
        status = 'critical'
    elif avg_signal >= args.warning:
        status = 'warning'

    flag_path = FLAG_DIR / f"retrain_{args.index.upper()}_{args.horizon}.json"
    if status != 'none':
        payload = {
            'index': args.index.upper(),
            'horizon': args.horizon,
            'average_signal': avg_signal,
            'samples': samples,
            'status': status,
            'timestamp': time.time()
        }
        flag_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        print(json.dumps({'triggered': True, 'status': status, 'flag_file': str(flag_path)}))
    else:
        print(json.dumps({'triggered': False, 'status': status, 'average_signal': avg_signal}))

if __name__ == '__main__':
    main()
