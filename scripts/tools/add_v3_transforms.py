import json
from pathlib import Path


def iter_panels(node):
    if isinstance(node, dict):
        if 'targets' in node:
            yield node
        for k in ('panels', 'rows'):
            if k in node and isinstance(node[k], list):
                for ch in node[k]:
                    yield from iter_panels(ch)
    elif isinstance(node, list):
        for ch in node:
            yield from iter_panels(ch)


def ensure_transformations(panel):
    tx = panel.setdefault('transformations', [])

    # Helper to find transform by id
    def find_tx(tid):
        for t in tx:
            if t.get('id') == tid:
                return t
        return None

    # 1) Convert Field Type: time_str -> time
    conv = find_tx('convertFieldType')
    if not conv:
        conv = {'id': 'convertFieldType', 'options': {'conversions': []}}
        tx.append(conv)
    conv_opts = conv.setdefault('options', {})
    convs = conv_opts.setdefault('conversions', [])
    # Replace or insert conversion for time_str
    found = False
    for c in convs:
        if c.get('targetField') == 'time_str':
            c['destinationType'] = 'time'
            found = True
            break
    if not found:
        convs.append({'targetField': 'time_str', 'destinationType': 'time'})

    # 2) Prepare Time Series: timeField=time_str
    prep = find_tx('prepareTimeSeries')
    if not prep:
        prep = {'id': 'prepareTimeSeries', 'options': {}}
        tx.append(prep)
    prep_opts = prep.setdefault('options', {})
    prep_opts['timeField'] = 'time_str'


def main():
    root = Path(__file__).resolve().parents[2]
    dash = root / 'grafana' / 'dashboards' / 'generated' / 'analytics_infinity_v3.json'
    if not dash.exists():
        raise SystemExit(f"Missing dashboard: {dash}")
    raw = dash.read_text(encoding='utf-8')
    obj = json.loads(raw)

    touched = 0
    for panel in iter_panels(obj.get('panels', [])):
        # only panels with Infinity targets
        tgs = panel.get('targets', [])
        if any(isinstance(t, dict) and isinstance(t.get('datasource'), dict) and t['datasource'].get('type') == 'yesoreyeram-infinity-datasource' for t in tgs):
            ensure_transformations(panel)
            touched += 1

    if touched == 0:
        print('No panels with Infinity targets found. Nothing to do.')
        return

    # Backup and write
    backup = dash.with_suffix('.pre_tx.json')
    backup.write_text(raw, encoding='utf-8')
    dash.write_text(json.dumps(obj, indent=2), encoding='utf-8')
    print(f'Patched {touched} panels with transforms. Backup: {backup}')


if __name__ == '__main__':
    main()
