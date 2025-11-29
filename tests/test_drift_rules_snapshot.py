import re
from pathlib import Path
import yaml

RECORDING = Path("prometheus_recording_rules_generated.yml")
ALERTS = Path("prometheus_alerts_drift.yml")

REQUIRED_RECORDS = [
    "g6_forecast_norm_error_drift_ratio:quantile90_6h",
    "g6_forecast_norm_error_drift_ratio:quantile95_6h",
    "g6_forecast_norm_error_drift_ratio:quantile99_6h",
    "g6_forecast_coverage_drift_delta_pct:quantile90_6h",
    "g6_forecast_coverage_drift_delta_pct:quantile95_6h",
    "g6_forecast_coverage_drift_delta_pct:quantile99_6h",
    "g6_forecast_norm_error_drift_ratio:adaptive_threshold",
    "g6_forecast_coverage_drift_delta_pct:adaptive_threshold",
    "g6_forecast_norm_error_drift_ratio:cardinality",
    "g6_forecast_coverage_drift_delta_pct:cardinality",
]

REQUIRED_ALERTS = [
    "MLAdaptiveNormErrorDriftInfo",
    "MLAdaptiveNormErrorDriftCritical",
    "MLAdaptiveCoverageDriftCritical",
    "MLAdaptiveNormErrorDriftAdaptive",
    "MLAdaptiveCoverageDriftAdaptive",
]

def load_yaml(path: Path):
    with path.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def test_recording_rules_snapshot():
    data = load_yaml(RECORDING)
    records = set()
    for g in data.get('groups', []):
        for r in g.get('rules', []):
            rec = r.get('record')
            if rec:
                records.add(rec)
    missing = [r for r in REQUIRED_RECORDS if r not in records]
    assert not missing, f"Missing recording rules: {missing}"


def test_alerts_snapshot():
    text = ALERTS.read_text(encoding='utf-8')
    missing = [a for a in REQUIRED_ALERTS if f"alert: {a}" not in text]
    assert not missing, f"Missing alerts: {missing}"


def test_no_duplicate_quantile_rules():
    data = load_yaml(RECORDING)
    quantile_pattern = re.compile(r":quantile(90|95|99)_6h$")
    seen = {}
    for g in data.get('groups', []):
        for r in g.get('rules', []):
            rec = r.get('record')
            if rec and quantile_pattern.search(rec):
                assert rec not in seen, f"Duplicate quantile rule {rec}"
                seen[rec] = True


def test_adaptive_threshold_formula_present():
    data = load_yaml(RECORDING)
    adaptive = {r.get('record'): r.get('expr') for g in data.get('groups', []) for r in g.get('rules', []) if r.get('record', '').endswith(':adaptive_threshold')}
    assert adaptive, "No adaptive threshold rules found"
    for rec, expr in adaptive.items():
        assert 'quantile95_6h' in expr, f"Adaptive threshold {rec} missing base quantile reference"
        assert 'cardinality' in expr, f"Adaptive threshold {rec} missing cardinality scaling reference"
