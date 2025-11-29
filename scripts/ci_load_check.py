"""CI load check for Phase 12.

Runs stress_high_concurrency scenario and enforces latency/error SLOs.
Fail (exit 1) if thresholds violated.
"""
from __future__ import annotations
import subprocess, json, sys

THRESHOLD_P95_MS = 1200.0
THRESHOLD_ERROR_RATE_PCT = 1.0
SCENARIO = 'stress_high_concurrency'

cmd = [sys.executable, '-m', 'src.ml.load_runner', '--scenario', SCENARIO]
try:
    out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
except subprocess.CalledProcessError as e:
    print('CI_LOAD_CHECK_FAILED: runner error')
    print(e.output)
    sys.exit(2)

try:
    data = json.loads(out.splitlines()[-1])  # last line JSON
except Exception:
    print('CI_LOAD_CHECK_FAILED: invalid JSON output')
    sys.exit(3)

scenarios = data.get('scenarios', {})
res = scenarios.get(SCENARIO)
if not res:
    print('CI_LOAD_CHECK_FAILED: scenario missing')
    sys.exit(4)

p95 = res.get('p95_ms', 0)
err_pct = res.get('error_rate_pct', 0)
print(f"LoadCheck: p95={p95}ms error_rate={err_pct}% requests={res.get('requests')} errors={res.get('errors')}")

violations = []
if p95 > THRESHOLD_P95_MS:
    violations.append(f"p95 {p95} > {THRESHOLD_P95_MS}")
if err_pct > THRESHOLD_ERROR_RATE_PCT:
    violations.append(f"error_rate {err_pct}% > {THRESHOLD_ERROR_RATE_PCT}%")

if violations:
    print('CI_LOAD_CHECK_FAILED: ' + '; '.join(violations))
    sys.exit(1)

print('CI_LOAD_CHECK_PASSED')
