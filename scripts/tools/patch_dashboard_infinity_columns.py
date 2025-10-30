import json
from pathlib import Path


def iter_panels(p):
    if isinstance(p, dict):
        # Yield this panel
        if 'targets' in p and isinstance(p['targets'], list):
            yield p
        # Recurse into nested panels (rows)
        if 'panels' in p and isinstance(p['panels'], list):
            for child in p['panels']:
                yield from iter_panels(child)
    elif isinstance(p, list):
        for item in p:
            yield from iter_panels(item)


def main():
    root = Path(__file__).resolve().parents[2]
    dash_path = root / 'grafana' / 'dashboards' / 'generated' / 'analytics_infinity_v3.json'
    if not dash_path.exists():
        raise SystemExit(f"Dashboard file not found: {dash_path}")

    raw = dash_path.read_text(encoding='utf-8')
    data = json.loads(raw)

    changes = 0
    for panel in iter_panels(data.get('panels', [])):
        for tgt in panel.get('targets', []):
            # Patch any Infinity targets and also sanitize columns for others just in case
            ds = tgt.get('datasource') or {}
            if 'columns' in tgt and isinstance(tgt['columns'], list) and len(tgt['columns']) > 0:
                tgt['columns'] = []
                changes += 1
            if isinstance(ds, dict) and ds.get('type') == 'yesoreyeram-infinity-datasource':
                # Normalize options keys if present
                if 'json_options' in tgt and isinstance(tgt['json_options'], dict):
                    opts = tgt['json_options']
                    tgt.setdefault('jsonOptions', {})
                    tgt['jsonOptions'].update(opts)
                if 'url_options' in tgt and isinstance(tgt['url_options'], dict):
                    uo = tgt['url_options']
                    tgt.setdefault('urlOptions', {})
                    tgt['urlOptions'].update(uo)

    if changes == 0:
        print('No Infinity targets with non-empty columns found. No changes made.')
        return

    # Backup
    backup = dash_path.with_suffix('.bak.json')
    backup.write_text(raw, encoding='utf-8')

    # Write updated dashboard
    dash_path.write_text(json.dumps(data, indent=2), encoding='utf-8')
    print(f'Updated {dash_path} | targets patched: {changes} | backup: {backup.name}')


if __name__ == '__main__':
    main()
