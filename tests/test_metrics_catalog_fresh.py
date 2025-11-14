import os
from pathlib import Path

# Ensure repo root on sys.path for src imports
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.metrics.spec import METRIC_SPECS, GROUPED_METRIC_SPECS  # type: ignore


def _cardinality_hint(label_count: int) -> str:
    if label_count == 0:
        return 'low'
    if label_count == 1:
        return 'low-moderate'
    if label_count == 2:
        return 'moderate'
    if label_count == 3:
        return 'high'
    return 'very_high'


def _build_example_query(name: str, metric_type: str, labels: list[str]) -> str:
    if metric_type == 'Counter':
        return f'rate({name}[5m])'
    if metric_type == 'Gauge':
        if labels:
            return f'avg by ({labels[0]}) ({name})'
        return f'avg({name})'
    if metric_type == 'Summary':
        return f'quantile(0.9, {name}_sum / {name}_count)'
    if metric_type == 'Histogram':
        return f'rate({name}_bucket[5m])'
    return name


def _generate_expected_content() -> str:
    # Import the same gating env mapping as the generator, but provide a local fallback if not importable
    GROUP_GATING_ENVS = {
        'analytics_vol_surface': ['G6_ENABLE_METRIC_GROUPS','G6_VOL_SURFACE','G6_VOL_SURFACE_PER_EXPIRY'],
        'analytics_risk_agg': ['G6_ENABLE_METRIC_GROUPS','G6_RISK_AGG'],
        'adaptive_controller': ['G6_ENABLE_METRIC_GROUPS','G6_ADAPTIVE_CONTROLLER'],
        'panel_diff': ['G6_ENABLE_METRIC_GROUPS'],
        'panels_integrity': ['G6_ENABLE_METRIC_GROUPS'],
        'greeks': ['G6_ENABLE_METRIC_GROUPS'],
        'sse_ingest': ['G6_ENABLE_METRIC_GROUPS','G6_SSE_INGEST'],
    }
    all_specs = list(METRIC_SPECS) + list(GROUPED_METRIC_SPECS)
    rows = []
    for spec in all_specs:
        metric_type = getattr(spec.kind, '__name__', str(spec.kind))
        lab_list = list(spec.labels) if spec.labels else []
        group_obj = getattr(spec, 'group', None)
        group = getattr(group_obj, 'value', '') if group_obj else ''
        rows.append({
            'attr': spec.attr,
            'name': spec.name,
            'type': metric_type,
            'group': group,
            'labels': ','.join(lab_list),
            'card': _cardinality_hint(len(lab_list)),
            'example': _build_example_query(spec.name, metric_type, lab_list),
            'desc': spec.doc.strip(),
            'conditional': 'Y' if spec.predicate else 'N',
        })
    rows.sort(key=lambda r: (r['group'] or '~', r['name']))
    group_section_lines = []
    for grp in sorted({r['group'] for r in rows if r['group'] }):
        envs = GROUP_GATING_ENVS.get(grp, [])
        group_section_lines.append(f'- **{grp}**: {", ".join(envs) if envs else "(none)"}')
    # Normalize Generated line to a constant so comparison is stable
    header = (
        '# G6 Metrics Catalog\n\n'
        'Auto-generated from declarative specification (`spec.py`). Do not edit manually.\n\n'
        'Generated: (normalized)\n\n'
        '## Group Gating Environment Variables\n\n' + '\n'.join(group_section_lines) + '\n\n'
    )
    col_names = ['Attr','Prom Name','Type','Group','Labels','Cardinality','Example Query','Description','Conditional']
    lines = [' | '.join(col_names), ' | '.join(['---'] * len(col_names))]
    for r in rows:
        desc = r['desc'].replace('|','\\|')
        example = r['example'].replace('|','\\|')
        lines.append(
            f"{r['attr']} | {r['name']} | {r['type']} | {r['group']} | {r['labels']} | {r['card']} | "
            f"{example} | {desc} | {r['conditional']}"
        )
    return header + '\n'.join(lines) + '\n'


def _normalize_generated_line(s: str) -> str:
    out_lines = []
    for line in s.splitlines():
        if line.startswith('Generated: '):
            out_lines.append('Generated: (normalized)')
        else:
            out_lines.append(line)
    # Always ensure a single trailing newline. Using splitlines() on Windows CRLF
    # can drop the terminal newline when rejoining, even if the original string
    # ended with CRLF. For cross-platform stability, normalize to a single '\n'
    # between lines and a single trailing '\n' at EOF.
    return '\n'.join(out_lines) + '\n'


def test_metrics_catalog_fresh():
    catalog_path = ROOT / 'docs' / 'METRICS_CATALOG.md'
    assert catalog_path.exists(), 'METRICS_CATALOG.md missing; generate it first.'
    committed = catalog_path.read_text(encoding='utf-8')
    # Normalize the dynamic Generated line
    committed_norm = _normalize_generated_line(committed)
    expected = _generate_expected_content()
    assert committed_norm == expected, 'METRICS_CATALOG.md is stale; re-run scripts/gen_metrics_catalog.py and commit changes.'
