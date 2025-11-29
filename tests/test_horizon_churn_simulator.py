import json
from scripts.load.horizon_churn_simulator import simulate_churn


def test_churn_growth_under_threshold():
    indices = ["NIFTY", "BANKNIFTY"]
    baseline = [15, 30, 60]
    candidates = [5, 10, 15, 30, 45, 60, 90]
    summary = simulate_churn(indices, baseline, candidates, cycles=40, seed=42)
    assert summary['max_growth_pct'] <= 15.0, json.dumps(summary, indent=2)
