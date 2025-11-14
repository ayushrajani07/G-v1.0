from __future__ import annotations
import json
from pathlib import Path
import sys

def main(argv: list[str]) -> int:
    p = Path(argv[0]) if argv else Path('reports/csv_audit_report_allow2.json')
    with p.open('r', encoding='utf-8') as f:
        data = json.load(f)
    files = data.get('files', [])
    cats = {
        'out_of_order': [],
        'duplicate_excess_or_dup': [],
        'unexpected_second': [],
        'missing_column': [],
        'read_error': [],
    }
    for fobj in files:
        path = fobj['path']
        issues = fobj.get('issues', [])
        if fobj.get('out_of_order', 0) > 0:
            cats['out_of_order'].append((path, [i for i in issues if i['kind']=='out_of_order'][:3], fobj['out_of_order']))
        if fobj.get('duplicate_ts', 0) > 0:
            cats['duplicate_excess_or_dup'].append((path, [i for i in issues if i['kind'] in ('duplicate_excess','duplicate_ts')][:3], fobj['duplicate_ts']))
        if any(i['kind']=='unexpected_second' for i in issues):
            us = [i for i in issues if i['kind']=='unexpected_second']
            cats['unexpected_second'].append((path, us[:3], len(us)))
        if any(i['kind']=='missing_column' for i in issues):
            cats['missing_column'].append((path, [i for i in issues if i['kind']=='missing_column'][:1], 1))
        if any(i['kind']=='read_error' for i in issues):
            cats['read_error'].append((path, [i for i in issues if i['kind']=='read_error'][:1], 1))

    summary = {
        k: data.get('summary', {}).get(k)
        for k in (
            'files_total','files_with_issues','files_out_of_order','files_with_duplicates','files_with_unexpected_seconds'
        )
    }
    print('SUMMARY:', summary)
    for key in ['out_of_order','duplicate_excess_or_dup','unexpected_second','missing_column','read_error']:
        arr = cats[key]
        print(f"\nCATEGORY: {key} (files={len(arr)})")
        for path, sample, count in arr[:5]:
            print('-', path)
            print('  count:', count)
            for s in sample:
                print('   ', s)
    return 0

if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
