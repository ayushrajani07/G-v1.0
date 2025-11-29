import os
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path("scripts/monitor/prom_rule_latency_profiler.py")


def test_latency_profiler_skips_without_endpoint():
    # Ensure PROMETHEUS_URL not set
    prom_env = dict(os.environ)
    prom_env.pop("PROMETHEUS_URL", None)
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, env=prom_env)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data.get("status") == "skipped"
    assert "PROMETHEUS_URL" in data.get("reason", "")
