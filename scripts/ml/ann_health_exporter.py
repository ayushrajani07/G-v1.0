#!/usr/bin/env python
"""ANN Health Prometheus Exporter

Periodically runs a narrow ANN health slice (retrieval k=10 windows 60,120) and exposes
live vs baseline metrics as Prometheus gauges. Designed for lightweight continuous
monitoring instead of manual ad-hoc runs.

Metrics exposed (example keys):
  ann_health_speedup{index="NIFTY",window="60"}
  ann_health_prune_ratio{index="NIFTY",window="60"}
  ann_health_q50_mad{index="NIFTY",window="60"}
  ann_health_rows{index="NIFTY",window="60"}
  ann_health_regression_total
  ann_health_last_run_timestamp_seconds

Baseline deltas:
  ann_health_speedup_delta{...} = live_speedup - baseline_speedup
  ann_health_prune_ratio_delta{...}
  ann_health_q50_mad_delta{...}

Exit code is never used; runs indefinitely until interrupted.

Usage:
  python scripts/ml/ann_health_exporter.py --index NIFTY --tag this_week --offset 0 \
    --days-back 3 --baseline baselines/ann_daily_baseline.json --port 9308 --interval 300

"""
from __future__ import annotations
import argparse, json, os, sys, time, datetime, subprocess
from src.error_handling import safe_write_json, safe_read_json, get_error_handler, ErrorCategory, ErrorSeverity  # type: ignore
from pathlib import Path

# Standardized sleep helper using centralized backoff if available
try:
    from src.utils.backoff import sleep_ms as _sleep_ms  # type: ignore
except Exception:  # pragma: no cover
    _sleep_ms = None  # type: ignore

def _sleep_s(_sec: float) -> None:
    try:
        ms = int(float(_sec) * 1000)
        if _sleep_ms:
            _sleep_ms(ms)
        else:
            time.sleep(float(_sec))
    except Exception:
        time.sleep(float(_sec))

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS = REPO_ROOT / 'scripts' / 'ml' / 'ann_harness_large.py'

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--index', required=True)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--offset', default='0')
    ap.add_argument('--days-back', type=int, default=3, help='How many days to include ending today')
    ap.add_argument('--baseline', required=True, help='Baseline JSON file')
    ap.add_argument('--port', type=int, default=9308)
    ap.add_argument('--interval', type=int, default=300, help='Seconds between health evaluations')
    ap.add_argument('--min-rows', type=int, default=5)
    ap.add_argument('--speedup-min-drop', type=float, default=0.05)
    ap.add_argument('--mad-max', type=float, default=0.05)
    ap.add_argument('--prune-max', type=float, default=0.90)
    ap.add_argument('--windows', default='60,120')
    ap.add_argument('--horizon', default='60')
    ap.add_argument('--python', default=sys.executable)
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--once', action='store_true', help='Run a single evaluation and exit instead of looping')
    ap.add_argument('--refresh-baseline-if-ok', action='store_true', help='When no regressions and min-rows satisfied, refresh baseline values from live run')
    return ap.parse_args()

def run_slice(ns, start, end) -> Path:
    out_root = REPO_ROOT / 'results' / 'ann_health_exporter_tmp'
    cmd = [
        ns.python, str(HARNESS),
        '--indices', ns.index,
        '--tags', ns.tag,
        '--offsets', ns.offset,
        '--start', start,
        '--end', end,
        '--windows', ns.windows,
        '--horizons', ns.horizon,
        '--k', '10',
        '--modes', 'retrieval',
        '--ann-max-candidates', '20',
        '--metrics-minimal',
        '--out-root', str(out_root)
    ]
    env = os.environ.copy(); env['PYTHONPATH'] = str(REPO_ROOT)
    if ns.verbose:
        print('[exec]', ' '.join(cmd))
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, text=True)
    if res.returncode != 0:
        raise RuntimeError('slice run failed')
    return out_root / 'combined' / 'ann_ranking.csv'

def read_ranking(path: Path):
    import csv
    out = {}
    if not path.exists():
        return out
    with path.open('r', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            if row.get('mode') != 'retrieval':
                continue
            w = str(row.get('window'))
            k = str(row.get('k'))
            if k != '10':
                continue
            key = f'retrieval_{w}_k{k}'
            try:
                d = {
                    'speedup_avg': float(row.get('speedup_avg') or 0.0),
                    'prune_ratio_avg': float(row.get('prune_ratio_avg') or 0.0),
                    'q50_mad_avg': float(row.get('q50_mad_avg') or 0.0),
                    'rows': int(row.get('rows') or 0)
                }
                # Optional extended metrics if present in ranking CSV
                v_eff_adj = row.get('effectiveness_score_adjusted') if 'effectiveness_score_adjusted' in row else None
                if v_eff_adj not in (None, ''):
                    try:
                        d['effectiveness_score_adjusted'] = float(str(v_eff_adj))
                    except Exception:
                        pass
                v_eff = row.get('effectiveness_score') if 'effectiveness_score' in row else None
                if v_eff not in (None, ''):
                    try:
                        d['effectiveness_score'] = float(str(v_eff))
                    except Exception:
                        pass
                v_guard = row.get('ann_guard_trigger_rate') if 'ann_guard_trigger_rate' in row else None
                if v_guard not in (None, ''):
                    try:
                        d['ann_guard_trigger_rate'] = float(str(v_guard))
                    except Exception:
                        pass
                out[key] = d
            except Exception:
                continue
    return out

def main():
    ns = parse_args()
    try:
        from prometheus_client import start_http_server, Gauge
    except ImportError:
        print('[error] prometheus_client not installed. pip install prometheus-client')
        sys.exit(1)

    speedup_g = Gauge('ann_health_speedup', 'ANN retrieval speedup', ['index','window'])
    prune_g = Gauge('ann_health_prune_ratio', 'ANN retrieval prune ratio', ['index','window'])
    mad_g = Gauge('ann_health_q50_mad', 'ANN retrieval q50 MAD', ['index','window'])
    rows_g = Gauge('ann_health_rows', 'Sample rows contributing to metrics', ['index','window'])
    speedup_delta_g = Gauge('ann_health_speedup_delta', 'Live - baseline speedup', ['index','window'])
    prune_delta_g = Gauge('ann_health_prune_ratio_delta', 'Live - baseline prune ratio', ['index','window'])
    mad_delta_g = Gauge('ann_health_q50_mad_delta', 'Live - baseline MAD', ['index','window'])
    regression_total_g = Gauge('ann_health_regression_total', 'Number of regression conditions detected')
    eff_adj_g = Gauge('ann_health_effectiveness_adjusted', 'Adjusted effectiveness score (fallback raw effectiveness if adjusted unavailable)', ['index','window'])
    guard_rate_g = Gauge('ann_health_guard_trigger_rate', 'Guard trigger rate for ANN (0-1)', ['index','window'])
    ts_g = Gauge('ann_health_last_run_timestamp_seconds', 'Unix timestamp of last health evaluation')

    baseline_path = Path(ns.baseline)
    if not baseline_path.exists():
        print('[error] baseline missing:', baseline_path)
        sys.exit(1)
    # Support both flat (single-index) and nested (multi-index) baseline formats.
    # Flat example (backward-compatible):
    # {
    #   "retrieval_60_k10": {"speedup_avg": 0.9, "prune_ratio_avg": 0.83, "q50_mad_avg": 0.0},
    #   "retrieval_120_k10": {...}
    # }
    # Nested example (multi-index):
    # {
    #   "NIFTY": {"retrieval_60_k10": {...}, "retrieval_120_k10": {...}},
    #   "BANKNIFTY": {"retrieval_60_k10": {...}, "retrieval_120_k10": {...}}
    # }
    baseline_doc = safe_read_json(baseline_path, default={}, function_name='ann_health_baseline_read')
    if isinstance(baseline_doc, dict) and baseline_doc and all(isinstance(v, dict) for v in baseline_doc.values()) and any(
        k.startswith('retrieval_') for k in baseline_doc.keys()
    ):
        # Flat structure detected
        baseline_view = baseline_doc
        is_nested = False
    else:
        # Attempt nested by index
        baseline_view = {}
        is_nested = True
        try:
            idx_branch = baseline_doc.get(ns.index, {}) if isinstance(baseline_doc, dict) else {}
            if isinstance(idx_branch, dict):
                baseline_view = idx_branch
            else:
                baseline_view = {}
        except Exception:
            baseline_view = {}

    start_http_server(ns.port)
    print(f'[exporter] listening on :{ns.port}')

    while True:
        end_date = datetime.date.today()
        start_date = end_date - datetime.timedelta(days=max(ns.days_back-1,0))
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')
        regression_count = 0
        try:
            ranking_csv = run_slice(ns, start_str, end_str)
            live = read_ranking(ranking_csv)
            for bkey, bvals in baseline_view.items():
                # expected key sample: retrieval_60_k10
                parts = bkey.split('_')
                if len(parts) != 3:
                    continue
                _, window, k = parts
                index = ns.index
                lvals = live.get(bkey, {})
                sp = lvals.get('speedup_avg', 0.0)
                pr = lvals.get('prune_ratio_avg', 1.0)
                md = lvals.get('q50_mad_avg', 0.0)
                rows = lvals.get('rows', 0)
                eff_adj = lvals.get('effectiveness_score_adjusted') or lvals.get('effectiveness_score') or 0.0
                guard_rate = lvals.get('ann_guard_trigger_rate') or 0.0
                speedup_g.labels(index=index, window=window).set(sp)
                prune_g.labels(index=index, window=window).set(pr)
                mad_g.labels(index=index, window=window).set(md)
                rows_g.labels(index=index, window=window).set(rows)
                speedup_delta_g.labels(index=index, window=window).set(sp - (bvals.get('speedup_avg') or 0.0))
                prune_delta_g.labels(index=index, window=window).set(pr - (bvals.get('prune_ratio_avg') or 0.0))
                mad_delta_g.labels(index=index, window=window).set(md - (bvals.get('q50_mad_avg') or 0.0))
                eff_adj_g.labels(index=index, window=window).set(eff_adj)
                guard_rate_g.labels(index=index, window=window).set(guard_rate)
                # Regression logic respecting min_rows
                if rows >= ns.min_rows:
                    if ((bvals.get('speedup_avg') or 0.0) - sp) > ns.speedup_min_drop:
                        regression_count += 1
                    if md > ns.mad_max:
                        regression_count += 1
                    if pr > ns.prune_max:
                        regression_count += 1
            regression_total_g.set(regression_count)
            ts_g.set(time.time())
            if ns.verbose:
                print(f'[exporter] run complete regressions={regression_count} start={start_str} end={end_str}')

            # Optional baseline refresh when healthy
            if ns.refresh_baseline_if_ok and regression_count == 0:
                # Refresh only keys present in baseline when we have sufficient rows
                updated = False
                # Work on a copy of the per-index view
                refreshed_view = dict(baseline_view)
                for bkey in list(refreshed_view.keys()):
                    lvals = live.get(bkey)
                    if not lvals:
                        continue
                    if lvals.get('rows', 0) < ns.min_rows:
                        continue
                    refreshed_view[bkey]['speedup_avg'] = float(lvals.get('speedup_avg') or 0.0)
                    refreshed_view[bkey]['prune_ratio_avg'] = float(lvals.get('prune_ratio_avg') or 0.0)
                    refreshed_view[bkey]['q50_mad_avg'] = float(lvals.get('q50_mad_avg') or 0.0)
                    updated = True
                if updated:
                    # Reconstruct document depending on baseline format
                    new_doc = None
                    if is_nested:
                        new_doc = dict(baseline_doc)
                        # Only update this index branch; preserve other indices
                        if not isinstance(new_doc.get(ns.index, {}), dict):
                            new_doc[ns.index] = {}
                        new_doc[ns.index] = refreshed_view
                    else:
                        new_doc = refreshed_view
                    # Atomic refresh with safe write + error recording for replace failure
                    tmp_path = baseline_path.with_suffix('.tmp')
                    ok = safe_write_json(tmp_path, new_doc, function_name='ann_health_baseline_write_tmp')
                    if ok:
                        try:
                            tmp_path.replace(baseline_path)
                        except Exception as _rep_err:  # pragma: no cover - rare failure
                            get_error_handler().handle_error(
                                _rep_err,
                                category=ErrorCategory.FILE_IO,
                                severity=ErrorSeverity.LOW,
                                component='ann_health_exporter',
                                function_name='ann_health_baseline_atomic_replace',
                                message='baseline_replace_failed',
                                context={'tmp_path': str(tmp_path), 'baseline_path': str(baseline_path)}
                            )
                        else:
                            if ns.verbose:
                                print(f'[exporter] baseline refreshed: {baseline_path}')
        except Exception as e:
            print('[warn] exporter evaluation failed:', e)
        if ns.once:
            # Exit after first evaluation (used for verification / tests)
            break
    _sleep_s(ns.interval)

if __name__ == '__main__':
    main()
