"""Static analysis of Prometheus rule cost.

Outputs:
- total rule count
- recording vs alert rule counts
- average expression length
- cardinality guard heuristic (number of distinct metric bases * horizon labels)
- counts of adaptive / quantile rules
Optionally queries a live Prometheus endpoint for current series cardinality
if PROMETHEUS_URL env var is set.
"""
from __future__ import annotations
import os
import re
import sys
import json
from pathlib import Path
import yaml
import urllib.request

RECORDING_FILES = [
    Path("prometheus_recording_rules_generated.yml"),
    Path("prometheus_recording_rules_dynamic_drift.yml"),
    Path("prometheus_recording_rules_ttl.yml"),
]
ALERT_FILES = [
    Path("prometheus_alerts_drift.yml"),
    Path("prometheus_alerts_ml_drift.yml"),
    Path("prometheus_alerts_chain.yml"),
]

QUANTILE_RE = re.compile(r":quantile(90|95|99)_")
ADAPTIVE_RE = re.compile(r":adaptive_threshold$")
CARDINALITY_RE = re.compile(r":cardinality$")


def load_yaml(path: Path):
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def extract_rules(doc: dict) -> list[dict]:
    rules = []
    for g in doc.get("groups", []):
        for r in g.get("rules", []):
            rules.append(r)
    return rules


def count_horizon_labels(metric: str) -> int:
    # heuristic: horizon labels appear as {horizon="..."} substrings
    return metric.count("horizon=")


def fetch_series_count(prom_url: str) -> int | None:
    try:
        with urllib.request.urlopen(f"{prom_url.rstrip('/')}/api/v1/series?match[]=g6_forecast_norm_error_drift_ratio") as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") == "success":
            return len(data.get("data", []))
    except Exception:
        return None
    return None


def main():
    recs = []
    alerts = []
    for f in RECORDING_FILES:
        doc = load_yaml(f)
        if doc:
            recs.extend(extract_rules(doc))
    for f in ALERT_FILES:
        text = f.read_text(encoding="utf-8") if f.exists() else ""
        alerts.extend([l.strip() for l in text.splitlines() if l.strip().startswith("- alert:")])

    expr_lengths = [len(r.get("expr", "")) for r in recs if r.get("expr")]
    quantile_rules = [r for r in recs if QUANTILE_RE.search(r.get("record", ""))]
    adaptive_rules = [r for r in recs if ADAPTIVE_RE.search(r.get("record", ""))]
    cardinality_rules = [r for r in recs if CARDINALITY_RE.search(r.get("record", ""))]

    metric_bases = set()
    for r in recs:
        rec_name = r.get("record", "")
        if ":" in rec_name:
            metric_bases.add(rec_name.split(":")[0])

    prom_url = os.environ.get("PROMETHEUS_URL")
    live_series = fetch_series_count(prom_url) if prom_url else None

    report = {
        "recording_rule_count": len(recs),
        "alert_rule_count": len(alerts),
        "avg_expression_length": round(sum(expr_lengths)/len(expr_lengths), 2) if expr_lengths else 0,
        "quantile_rule_count": len(quantile_rules),
        "adaptive_rule_count": len(adaptive_rules),
        "cardinality_rule_count": len(cardinality_rules),
        "metric_base_count": len(metric_bases),
        "live_series_count_norm_error_drift_ratio": live_series,
        "heuristic_note": "live_series_count requires PROMETHEUS_URL env var; heuristic cardinality uses series API for single metric"
    }

    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
