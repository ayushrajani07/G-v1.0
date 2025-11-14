from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.metrics.spec import METRIC_SPECS, GROUPED_METRIC_SPECS  # type: ignore


def card_hint(n: int) -> str:
    return ['low', 'low-moderate', 'moderate', 'high'][n] if 0 <= n < 4 else 'very_high'


def build_example(name: str, mtype: str, labels: list[str]) -> str:
    if mtype == 'Counter':
        return f'rate({name}[5m])'
    if mtype == 'Gauge':
        return f'avg by ({labels[0]}) ({name})' if labels else f'avg({name})'
    if mtype == 'Summary':
        return f'quantile(0.9, {name}_sum / {name}_count)'
    if mtype == 'Histogram':
        return f'rate({name}_bucket[5m])'
    return name


def gen_expected() -> str:
    all_specs = list(METRIC_SPECS) + list(GROUPED_METRIC_SPECS)
    rows = []
    for spec in all_specs:
        mtype = getattr(spec.kind, '__name__', str(spec.kind))
        labs = list(spec.labels) if spec.labels else []
        gobj = getattr(spec, 'group', None)
        grp = getattr(gobj, 'value', '') if gobj else ''
        rows.append({
            'attr': spec.attr,
            'name': spec.name,
            'type': mtype,
            'group': grp,
            'labels': ','.join(labs),
            'card': card_hint(len(labs)),
            'example': build_example(spec.name, mtype, labs),
            'desc': spec.doc.strip(),
            'conditional': 'Y' if spec.predicate else 'N',
        })
    rows.sort(key=lambda r: (r['group'] or '~', r['name']))
    GROUP_GATING_ENVS = {
        'analytics_vol_surface': ['G6_ENABLE_METRIC_GROUPS','G6_VOL_SURFACE','G6_VOL_SURFACE_PER_EXPIRY'],
        'analytics_risk_agg': ['G6_ENABLE_METRIC_GROUPS','G6_RISK_AGG'],
        'adaptive_controller': ['G6_ENABLE_METRIC_GROUPS','G6_ADAPTIVE_CONTROLLER'],
        'panel_diff': ['G6_ENABLE_METRIC_GROUPS'],
        'panels_integrity': ['G6_ENABLE_METRIC_GROUPS'],
        'greeks': ['G6_ENABLE_METRIC_GROUPS'],
        'sse_ingest': ['G6_ENABLE_METRIC_GROUPS','G6_SSE_INGEST'],
    }
    grp_lines = []
    for grp in sorted({r['group'] for r in rows if r['group'] }):
        envs = GROUP_GATING_ENVS.get(grp, [])
        grp_lines.append(f'- **{grp}**: {", ".join(envs) if envs else "(none)"}')
    header = (
        '# G6 Metrics Catalog\n\n'
        'Auto-generated from declarative specification (`spec.py`). Do not edit manually.\n\n'
        'Generated: (normalized)\n\n'
        '## Group Gating Environment Variables\n\n' + '\n'.join(grp_lines) + '\n\n'
    )
    col_names = ['Attr','Prom Name','Type','Group','Labels','Cardinality','Example Query','Description','Conditional']
    lines = [' | '.join(col_names), ' | '.join(['---']*len(col_names))]
    for r in rows:
        desc = r['desc'].replace('|','\\|')
        exq = r['example'].replace('|','\\|')
        lines.append(f"{r['attr']} | {r['name']} | {r['type']} | {r['group']} | {r['labels']} | {r['card']} | {exq} | {desc} | {r['conditional']}")
    return header + '\n'.join(lines) + '\n'


def main() -> int:
    committed = (ROOT / 'docs' / 'METRICS_CATALOG.md').read_text(encoding='utf-8')
    # normalize Generated line
    comm_lines = []
    for line in committed.splitlines():
        comm_lines.append('Generated: (normalized)' if line.startswith('Generated: ') else line)
    committed_norm = '\n'.join(comm_lines) + ('\n' if not committed.endswith('\n') else '')
    expected = gen_expected()
    print('LEN committed_norm, expected:', len(committed_norm), len(expected))
    if committed_norm == expected:
        print('MATCH')
        return 0
    a = committed_norm.splitlines()
    b = expected.splitlines()
    # find first diff
    for i, (x, y) in enumerate(zip(a, b), start=1):
        if x != y:
            print('First diff at line', i)
            print('Committed:', x)
            print('Expected :', y)
            break
    print('Tail committed:', a[-3:])
    print('Tail expected :', b[-3:])
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
