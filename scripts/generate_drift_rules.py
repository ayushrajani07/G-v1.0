import yaml
from pathlib import Path

CONFIG = {
    "metrics": [
        "g6_forecast_norm_error_drift_ratio",
        "g6_forecast_coverage_drift_delta_pct"
    ],
    "quantiles": [0.90, 0.95, 0.99],
    "horizon_avgs": ["15m", "1h"],
    "long_quantile_window": "6h"
}

def build_rules(cfg):
    rules = []
    # Horizon averages
    for m in cfg["metrics"]:
        for win in cfg["horizon_avgs"]:
            # Use avg_over_time over window then avg by horizon
            rules.append({
                "record": f"{m}:horizon_avg_{win}",
                "expr": f"avg(avg_over_time({m}[{win}])) by (horizon)"
            })
    # Quantiles
    for m in cfg["metrics"]:
        for q in cfg["quantiles"]:
            qs = f"{q:.2f}"  # retain trailing zero to match committed rules formatting (e.g. 0.90)
            pct = int(q*100)
            rules.append({
                "record": f"{m}:quantile{pct}_{cfg['long_quantile_window']}",
                "expr": f"quantile_over_time({qs}, {m}[{cfg['long_quantile_window']}])"
            })
    return rules

def main():
    fragment = {
        "groups": [
            {
                "name": "ml_drift_dynamic_generated.rules",
                "interval": "60s",
                "rules": build_rules(CONFIG)
            }
        ]
    }
    out_path = Path("prometheus_drift_rules_generated_fragment.yml")
    with out_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(fragment, f, sort_keys=False)
    print(f"Wrote drift rules fragment to {out_path}")

if __name__ == "__main__":
    main()
