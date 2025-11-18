from __future__ import annotations

import argparse
from pathlib import Path


def generate(template_path: Path, indices: list[str]) -> str:
    tmpl = template_path.read_text(encoding="utf-8")
    out_parts: list[str] = []
    for idx in indices:
        idx_u = idx.strip().upper()
        if not idx_u:
            continue
        out_parts.append(tmpl.replace("__INDEX__", idx_u))
    return "\n\n".join(out_parts) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate per-index Prometheus alert rules for ML drift")
    ap.add_argument("--template", type=Path, required=True, help="Path to per-index template YAML with __INDEX__ placeholder")
    ap.add_argument("--indices", type=str, required=True, help="Comma-separated indices, e.g., NIFTY,BANKNIFTY")
    ap.add_argument("--out", type=Path, default=Path("prometheus_alerts_drift.generated.yml"), help="Output rules file")
    args = ap.parse_args()
    indices = [s.strip() for s in args.indices.split(',') if s.strip()]
    if not indices:
        print("No indices provided")
        return 2
    content = generate(args.template, indices)
    args.out.write_text(content, encoding="utf-8")
    print(f"Wrote {args.out} for indices: {', '.join(indices)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
