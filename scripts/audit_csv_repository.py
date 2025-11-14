from __future__ import annotations

import csv
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

# Reuse the same timestamp parser used by the API
try:
    from src.web.dashboard.core.csv_io import parse_time_epoch_ms
except Exception:
    # Fallback: minimal parser (UTC naive) if import path differs
    from datetime import datetime, timezone, timedelta
    def parse_time_epoch_ms(s: str) -> int | None:
        raw = (s or '').strip()
        if not raw:
            return None
        # Try ISO first
        try:
            dt = datetime.fromisoformat(raw.replace(' ', 'T'))
        except Exception:
            dt = None
        if dt is None:
            for fmt in (
                '%d-%m-%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M:%S', '%m/%d/%Y %H:%M:%S',
                '%d-%m-%Y %H:%M', '%Y-%m-%d %H:%M', '%d/%m/%Y %H:%M', '%m/%d/%Y %H:%M',
                '%d/%m/%Y %I:%M', '%m/%d/%Y %I:%M',
            ):
                try:
                    dt = datetime.strptime(raw, fmt)
                    break
                except Exception:
                    continue
        if dt is None:
            # Numeric epoch detection (quality-of-life)
            if raw.isdigit():
                try:
                    n = int(raw)
                    if len(raw) <= 10:  # seconds
                        return n * 1000
                    return n  # assume ms
                except Exception:
                    return None
            return None
        if dt.tzinfo is None:
            # Assume IST like the main loader
            ist = timezone(timedelta(hours=5, minutes=30))
            dt = dt.replace(tzinfo=ist)
        return int(dt.timestamp() * 1000)


@dataclass
class Issue:
    kind: str
    detail: str
    row_index: int | None = None


@dataclass
class FileReport:
    path: str
    rows: int = 0
    parsed_ts: int = 0
    parse_fail: int = 0
    out_of_order: int = 0
    duplicate_ts: int = 0
    negative_values: int = 0  # across tp, avg_tp, ce, pe
    min_ts: int | None = None
    max_ts: int | None = None
    min_tp: float | None = None
    max_tp: float | None = None
    issues: list[Issue] = field(default_factory=list)

    def add_issue(self, kind: str, detail: str, row_index: int | None = None, limit: int = 10) -> None:
        if len(self.issues) < limit:
            self.issues.append(Issue(kind, detail, row_index))


def iter_csv_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    # Common layout: data/g6_data/INDEX/expiry_tag/offset/YYYY-MM-DD.csv
    for p in root.rglob('*.csv'):
        if p.is_file():
            yield p


def scan_file(p: Path, sample_issue_limit: int = 10, allow_two_per_minute: bool = False, slop_ms: int = 900) -> FileReport:
    rep = FileReport(path=str(p))
    last_ts: int | None = None
    seen: set[int] = set()
    # For allowance: track counts per-minute per allowed bucket (0sec, 30sec)
    per_minute_counts: dict[int, dict[int, int]] = {}
    duplicates_excess = 0
    unexpected_second = 0

    try:
        with p.open('r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            have_timestamp = 'timestamp' in (reader.fieldnames or [])
            if not have_timestamp:
                rep.add_issue('missing_column', 'timestamp column not found')
                return rep
            cols_num = [c for c in ('tp','avg_tp','ce','pe') if c in (reader.fieldnames or [])]
            for i, r in enumerate(reader):
                rep.rows += 1
                ts = parse_time_epoch_ms(str(r.get('timestamp', '')).strip())
                if ts is None:
                    rep.parse_fail += 1
                    rep.add_issue('parse_failure', f"unparsed timestamp: {r.get('timestamp')}", i, limit=sample_issue_limit)
                else:
                    rep.parsed_ts += 1
                    rep.min_ts = ts if rep.min_ts is None else min(rep.min_ts, ts)
                    rep.max_ts = ts if rep.max_ts is None else max(rep.max_ts, ts)
                    # out of order
                    if last_ts is not None and ts < last_ts:
                        rep.out_of_order += 1
                        rep.add_issue('out_of_order', f'{ts} < {last_ts}', i, limit=sample_issue_limit)
                    # duplicates / allowance logic
                    if allow_two_per_minute:
                        # bucket to minute start
                        minute_start = ts - (ts % 60000)
                        # find which bucket (0 or 30) within slop
                        offs = ts - minute_start
                        bucket = None
                        if abs(offs - 0) <= slop_ms:
                            bucket = 0
                        elif abs(offs - 30000) <= slop_ms:
                            bucket = 30
                        else:
                            # unexpected second inside this minute
                            unexpected_second += 1
                            rep.add_issue('unexpected_second', f't={ts} (offset {offs}ms)', i, limit=sample_issue_limit)
                        if bucket is not None:
                            mm = per_minute_counts.setdefault(minute_start, {})
                            c = mm.get(bucket, 0) + 1
                            mm[bucket] = c
                            # Allow at most one entry per allowed bucket within minute
                            if c > 1:
                                duplicates_excess += 1
                                rep.add_issue('duplicate_excess', f'minute {minute_start}, bucket :{bucket:02d}, count={c}', i, limit=sample_issue_limit)
                    else:
                        # plain duplicate detection on exact ts
                        if ts in seen:
                            rep.duplicate_ts += 1
                        else:
                            seen.add(ts)
                    last_ts = ts
                # negatives
                for col in cols_num:
                    v = r.get(col)
                    if v is None or str(v).strip() == '':
                        continue
                    try:
                        fv = float(str(v))
                        if fv < 0:
                            rep.negative_values += 1
                            rep.add_issue('negative_value', f'{col}={fv}', i, limit=sample_issue_limit)
                        if col in ('tp','avg_tp'):
                            rep.min_tp = fv if rep.min_tp is None else min(rep.min_tp, fv)
                            rep.max_tp = fv if rep.max_tp is None else max(rep.max_tp, fv)
                    except Exception:
                        rep.add_issue('non_numeric', f'{col}={v}', i, limit=sample_issue_limit)
    except Exception as e:
        rep.add_issue('read_error', str(e))
    # Post-process allowance counts
    if allow_two_per_minute:
        rep.duplicate_ts = duplicates_excess
        # surface unexpected second count as issues length (already captured), and also add numeric hint
        if unexpected_second:
            rep.add_issue('unexpected_second_summary', f'count={unexpected_second}', None, limit=sample_issue_limit)
    return rep


def main(argv: list[str]) -> int:
    import argparse
    parser = argparse.ArgumentParser(description='Audit CSV repository for ordering and timestamp issues')
    parser.add_argument('--root', default=str(Path('data') / 'g6_data'), help='Root folder of live CSVs')
    parser.add_argument('--report-json', default=str(Path('reports') / 'csv_audit_report.json'))
    parser.add_argument('--report-csv', default=str(Path('reports') / 'csv_audit_summary.csv'))
    parser.add_argument('--allow-two-per-minute', action='store_true', help='Allow up to two records per minute at :00 and :30 (± slop)')
    parser.add_argument('--slop-ms', type=int, default=900, help='Timing tolerance for :00 / :30 buckets when allowance enabled')
    parser.add_argument('--sample-limit', type=int, default=10, help='Max issues to store per file')
    args = parser.parse_args(argv)

    root = Path(args.root)
    out_json = Path(args.report_json)
    out_csv = Path(args.report_csv)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    files = list(iter_csv_files(root))
    summary = {
        'root': str(root),
        'files_total': len(files),
        'files_with_issues': 0,
        'files_out_of_order': 0,
        'files_with_parse_failures': 0,
        'files_with_duplicates': 0,
        'files_with_unexpected_seconds': 0,
        'files_with_negatives': 0,
    }

    reports: list[FileReport] = []
    for p in files:
        rep = scan_file(p, sample_issue_limit=args.sample_limit, allow_two_per_minute=args.allow_two_per_minute, slop_ms=args.slop_ms)
        reports.append(rep)
        has_issue = any([
            rep.parse_fail, rep.out_of_order, rep.duplicate_ts, rep.negative_values,
        ]) or any(iss.kind in ('missing_column','read_error') for iss in rep.issues)
        if has_issue:
            summary['files_with_issues'] += 1
        if rep.out_of_order:
            summary['files_out_of_order'] += 1
        if rep.parse_fail:
            summary['files_with_parse_failures'] += 1
        if rep.duplicate_ts:
            summary['files_with_duplicates'] += 1
        if any(iss.kind == 'unexpected_second' for iss in rep.issues):
            summary['files_with_unexpected_seconds'] += 1
        if rep.negative_values:
            summary['files_with_negatives'] += 1

    # Write JSON report (detailed)
    with out_json.open('w', encoding='utf-8') as jf:
        payload: dict[str, Any] = {
            'summary': summary,
            'files': [
                {
                    **{k: v for k, v in asdict(rep).items() if k != 'issues'},
                    'issues': [asdict(it) for it in rep.issues],
                }
                for rep in reports
            ],
        }
        json.dump(payload, jf, indent=2)

    # Write CSV summary (one row per file)
    with out_csv.open('w', newline='', encoding='utf-8') as cf:
        w = csv.writer(cf)
        w.writerow([
            'path','rows','parsed_ts','parse_fail','out_of_order','duplicate_ts','negative_values','min_ts','max_ts','min_tp','max_tp','issue_count'
        ])
        for rep in reports:
            w.writerow([
                rep.path, rep.rows, rep.parsed_ts, rep.parse_fail, rep.out_of_order, rep.duplicate_ts,
                rep.negative_values, rep.min_ts or '', rep.max_ts or '', rep.min_tp or '', rep.max_tp or '', len(rep.issues)
            ])

    print(json.dumps(summary, indent=2))
    print(f"\nDetailed report: {out_json}")
    print(f"Summary CSV   : {out_csv}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
