import sys
import yaml
from pathlib import Path

RECORDING_FILE = Path("prometheus_recording_rules_generated.yml")
FRAGMENT_FILE = Path("prometheus_drift_rules_generated_fragment.yml")


def load_rules(path: Path):
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    records = {}
    if not data or "groups" not in data:
        return records
    for g in data["groups"]:
        for r in g.get("rules", []):
            rec = r.get("record")
            expr = r.get("expr")
            if rec and expr:
                records[rec] = expr.strip()
    return records


def main():
    if not FRAGMENT_FILE.exists():
        print("Fragment file missing. Did generator run?", file=sys.stderr)
        sys.exit(1)
    if not RECORDING_FILE.exists():
        print("Recording rules file missing.", file=sys.stderr)
        sys.exit(1)

    fragment_rules = load_rules(FRAGMENT_FILE)
    recording_rules = load_rules(RECORDING_FILE)

    missing = []
    drift = []
    for rec, expr in fragment_rules.items():
        if rec not in recording_rules:
            missing.append(rec)
        else:
            if recording_rules[rec] != expr:
                drift.append((rec, expr, recording_rules[rec]))

    if missing or drift:
        print("Integrity check FAILED", file=sys.stderr)
        if missing:
            print("Missing records:")
            for m in missing:
                print(f"  - {m}")
        if drift:
            print("Drifted expressions:")
            for rec, expected, actual in drift:
                print(f"  - {rec}\n    expected: {expected}\n    actual:   {actual}")
        sys.exit(1)

    print("Drift rules integrity OK (fragment matches recording file).")


if __name__ == "__main__":
    main()
