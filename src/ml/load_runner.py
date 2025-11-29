"""Phase 11: Multi-index load test runner.

Runs defined scenarios from load_scenarios.json using Flask test client.
Collects latency distribution and error counts; prints JSON summary.

Usage (PowerShell):
  python -m src.ml.load_runner --scenario baseline_dual_index_light
  python -m src.ml.load_runner --all

Environment:
  LOAD_SCENARIOS_FILE (optional) path override.
"""
from __future__ import annotations
import json, time, statistics, threading, argparse, os
from pathlib import Path
from typing import List, Dict, Any
from collections import defaultdict, deque

from src.web.api.ml_ensemble import create_app

_DEFAULT_FILE = Path(__file__).parent / 'load_scenarios.json'

class Scenario:
    def __init__(self, name: str, indices: List[str], horizons: List[int], concurrency: int, duration_seconds: int):
        self.name = name
        self.indices = indices
        self.horizons = horizons
        self.concurrency = concurrency
        self.duration_seconds = duration_seconds

def _load_scenarios(path: Path) -> List[Scenario]:
    data = json.loads(path.read_text(encoding='utf-8'))
    out = []
    for s in data.get('scenarios', []):
        try:
            out.append(Scenario(
                name=s['name'],
                indices=list(s['indices']),
                horizons=[int(h) for h in s['horizons']],
                concurrency=int(s['concurrency']),
                duration_seconds=int(s['duration_seconds'])
            ))
        except Exception:
            continue
    return out

class LoadStats:
    def __init__(self):
        self.latencies: Dict[str, List[float]] = defaultdict(list)  # scenario -> ms list
        self.errors: Dict[str, int] = defaultdict(int)
        self.counts: Dict[str, int] = defaultdict(int)

    def record(self, scenario: str, latency_ms: float, ok: bool):
        self.latencies[scenario].append(latency_ms)
        self.counts[scenario] += 1
        if not ok:
            self.errors[scenario] += 1

    def summary(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for scen, arr in self.latencies.items():
            arr_sorted = sorted(arr)
            def pct(p: float) -> float:
                if not arr_sorted:
                    return 0.0
                idx = int(p * (len(arr_sorted) - 1))
                return arr_sorted[idx]
            out[scen] = {
                'requests': self.counts[scen],
                'errors': self.errors[scen],
                'error_rate_pct': round(100 * self.errors[scen] / max(self.counts[scen], 1), 3),
                'avg_ms': round(statistics.mean(arr_sorted), 2) if arr_sorted else 0.0,
                'p90_ms': round(pct(0.90), 2),
                'p95_ms': round(pct(0.95), 2),
                'p99_ms': round(pct(0.99), 2),
                'max_ms': round(max(arr_sorted), 2) if arr_sorted else 0.0,
            }
        return out

_stats = LoadStats()

def _worker(app, scenario: Scenario, stop_time: float):
    client = app.test_client()
    indices_cycle = deque(scenario.indices)
    horizons_cycle = deque(scenario.horizons)
    while time.time() < stop_time:
        idx = indices_cycle[0]
        hz = horizons_cycle[0]
        indices_cycle.rotate(-1)
        horizons_cycle.rotate(-1)
        t0 = time.time()
        try:
            resp = client.get(f'/api/ml/ensemble/forecast?index={idx}&horizon={hz}')
            ok = resp.status_code == 200
        except Exception:
            ok = False
        latency_ms = (time.time() - t0) * 1000
        _stats.record(scenario.name, latency_ms, ok)

def run_scenario(scenario: Scenario) -> Dict[str, Any]:
    app = create_app()
    stop_time = time.time() + scenario.duration_seconds
    threads = []
    for _ in range(scenario.concurrency):
        th = threading.Thread(target=_worker, args=(app, scenario, stop_time), daemon=True)
        threads.append(th)
        th.start()
    for th in threads:
        th.join()
    return _stats.summary()[scenario.name]

def main():
    parser = argparse.ArgumentParser(description='Phase 11 load runner')
    parser.add_argument('--scenario', help='Scenario name to run')
    parser.add_argument('--all', action='store_true', help='Run all scenarios')
    parser.add_argument('--file', help='Scenarios file override')
    args = parser.parse_args()
    file_path = Path(args.file) if args.file else Path(os.environ.get('LOAD_SCENARIOS_FILE', _DEFAULT_FILE))
    scenarios = _load_scenarios(file_path)
    if not scenarios:
        print(json.dumps({'error': 'no_scenarios_loaded', 'file': str(file_path)}))
        return
    selected: List[Scenario]
    if args.all:
        selected = scenarios
    elif args.scenario:
        selected = [s for s in scenarios if s.name == args.scenario]
        if not selected:
            print(json.dumps({'error': 'scenario_not_found', 'name': args.scenario}))
            return
    else:
        print(json.dumps({'error': 'no_selection', 'available': [s.name for s in scenarios]}))
        return
    results: Dict[str, Any] = {}
    start = time.time()
    for scen in selected:
        results[scen.name] = run_scenario(scen)
    total_sec = round(time.time() - start, 2)
    print(json.dumps({'duration_total_s': total_sec, 'scenarios': results}, indent=2))

if __name__ == '__main__':
    main()
