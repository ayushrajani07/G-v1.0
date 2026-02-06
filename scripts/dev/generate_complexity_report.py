#!/usr/bin/env python3
"""
Generate cyclomatic complexity report for hotspot modules using radon.
Outputs a Markdown file under reports/complexity_<YYYYMMDD_HHMMSS>.md.
"""
from __future__ import annotations

import datetime
from datetime import UTC
import os
import sys
from pathlib import Path
from typing import Iterable

try:
    from radon.complexity import cc_visit
except Exception as e:
    print("Radon not installed. Please run: pip install -r requirements-dev.txt", file=sys.stderr)
    raise

HOTSPOTS: list[str] = [
    'src/web/dashboard/routes/path_forecast/_router.py',
    'src/web/dashboard/routes/path_forecast/_json_handler.py',
    'src/storage/csv_sink.py',
    'src/web/dashboard/routes/ml.py',
    'src/collectors/unified_collectors.py',
    'src/metrics/metrics.py',
    'src/orchestrator/cycle.py',
]

ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = ROOT / 'reports'
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

def grade_to_emoji(grade: str) -> str:
    return {
        'A': '🟩', 'B': '🟨', 'C': '🟧', 'D': '🟥', 'E': '🟥', 'F': '🟥'
    }.get(grade.upper(), '⬜')

def analyze_file(path: Path):
    try:
        code = path.read_text(encoding='utf-8')
    except Exception:
        return None
    try:
        blocks = cc_visit(code)
    except Exception:
        return None
    # Compute worst grade and average score
    worst_grade = 'A'
    scores: list[float] = []
    for b in blocks:
        try:
            scores.append(b.complexity)
            if b.rank > worst_grade:
                worst_grade = b.rank
        except Exception:
            pass
    avg = sum(scores) / len(scores) if scores else 0.0
    return {
        'blocks': blocks,
        'avg': avg,
        'worst': worst_grade,
    }

def rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except Exception:
        return str(p)

def main() -> int:
    # Use timezone-aware now to avoid naive-persisted timestamp violations in tests
    timestamp = datetime.datetime.now(UTC).strftime('%Y%m%d_%H%M%S')
    out_path = REPORTS_DIR / f'complexity_{timestamp}.md'
    lines: list[str] = []
    lines.append(f"# Complexity Report\n\nGenerated: {timestamp}\n\n")
    lines.append("Targets:\n")
    for hp in HOTSPOTS:
        lines.append(f"- `{hp}`")
    lines.append("\n---\n")

    for hp in HOTSPOTS:
        file_path = ROOT / hp
        if not file_path.exists():
            lines.append(f"\n## {hp}\n\n- File not found. Skipping.\n")
            continue
        result = analyze_file(file_path)
        if not result:
            lines.append(f"\n## {hp}\n\n- Analysis failed.\n")
            continue
        worst = result['worst']
        avg = result['avg']
        emoji = grade_to_emoji(worst)
        lines.append(f"\n## {hp}  {emoji}\n")
        lines.append(f"- Worst grade: `{worst}`\n- Average CC: `{avg:.2f}`\n")
        blocks = result['blocks']
        # Sort by complexity desc
        blocks_sorted = sorted(blocks, key=lambda b: getattr(b, 'complexity', 0), reverse=True)
        lines.append("\n### Top 10 most complex blocks\n")
        lines.append("\n| Rank | Function/Method | CC | Line |\n|---:|---|---:|---:|\n")
        for i, b in enumerate(blocks_sorted[:10], start=1):
            name = getattr(b, 'name', '<unknown>')
            cc = getattr(b, 'complexity', 0)
            lineno = getattr(b, 'lineno', 0)
            lines.append(f"| {i} | `{name}` | {cc} | {lineno} |\n")

    out_path.write_text("".join(lines), encoding='utf-8')
    print(f"Complexity report written: {rel(out_path)}")
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
