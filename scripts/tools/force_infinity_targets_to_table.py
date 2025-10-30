import json
from pathlib import Path

def iter_panels(node):
    if isinstance(node, dict):
        if 'targets' in node:
            yield node
        for key in ('panels', 'rows'):
            if isinstance(node.get(key), list):
                for child in node[key]:
                    yield from iter_panels(child)
    elif isinstance(node, list):
        for child in node:
            yield from iter_panels(child)


def main():
    root = Path(__file__).resolve().parents[2]
    dash = root / 'grafana' / 'dashboards' / 'generated' / 'analytics_infinity_v3.json'
    if not dash.exists():
        raise SystemExit(f"Not found: {dash}")
    raw = dash.read_text(encoding='utf-8')
    obj = json.loads(raw)

    patched = 0
    for panel in iter_panels(obj.get('panels', [])):
        for t in panel.get('targets', []):
            if not isinstance(t, dict):
                continue
            ds = t.get('datasource') or {}
            if isinstance(ds, dict) and ds.get('type') == 'yesoreyeram-infinity-datasource':
                # Normalize to table + inferred columns
                t['format'] = 'table'
                t['columns'] = []
                # Ensure root_is_array under snake_case key used in file
                jo = t.setdefault('json_options', {})
                if not isinstance(jo, dict):
                    jo = {}
                    t['json_options'] = jo
                jo['root_is_array'] = True
                patched += 1
    if patched == 0:
        print('No Infinity targets found to patch.')
        return
    backup = dash.with_suffix('.pre_table.json')
    backup.write_text(raw, encoding='utf-8')
    dash.write_text(json.dumps(obj, indent=2), encoding='utf-8')
    print(f'Patched {patched} Infinity targets to format=table (backup: {backup.name})')


if __name__ == '__main__':
    main()
