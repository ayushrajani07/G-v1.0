import yaml
from pathlib import Path
import sys

RECORDING = Path("prometheus_recording_rules_generated.yml")
FRAGMENT = Path("prometheus_drift_rules_generated_fragment.yml")


def load_groups(path: Path):
    if not path.exists():
        return []
    with path.open('r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    return data.get('groups', [])


def main():
    if not FRAGMENT.exists():
        print("Fragment missing; run generate_drift_rules.py first", file=sys.stderr)
        sys.exit(1)
    if not RECORDING.exists():
        print("Recording rules file missing", file=sys.stderr)
        sys.exit(1)

    frag_groups = load_groups(FRAGMENT)
    rec_groups = load_groups(RECORDING)

    # Build index of existing record names
    existing = set()
    for g in rec_groups:
        for r in g.get('rules', []):
            rec = r.get('record')
            if rec:
                existing.add(rec)

    added = []
    for g in frag_groups:
        for r in g.get('rules', []):
            rec = r.get('record')
            if rec and rec not in existing:
                # Append rule to first group (or create if none)
                if not rec_groups:
                    rec_groups.append({'name': 'merged.rules', 'interval': g.get('interval', '60s'), 'rules': []})
                rec_groups[0]['rules'].append(r)
                added.append(rec)

    if added:
        with RECORDING.open('w', encoding='utf-8') as f:
            yaml.safe_dump({'groups': rec_groups}, f, sort_keys=False)
        print(f"Added {len(added)} new drift rules: {', '.join(added)}")
    else:
        print("No new drift rules to add (already synchronized)")

if __name__ == '__main__':
    main()
