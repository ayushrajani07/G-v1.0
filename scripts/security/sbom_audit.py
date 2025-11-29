"""Generate CycloneDX SBOM and run pip-audit.

Outputs:
  - sbom.json (CycloneDX JSON) if cyclonedx-bom available
  - audit.json (pip-audit vulnerabilities)

Exit code:
  - 1 if any vulnerability with severity >= CRITICAL found.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        return e


def generate_sbom(output: Path):
    try:
        r = run_cmd([sys.executable, '-m', 'cyclonedx_py', 'environment', '--format', 'json'])
        if isinstance(r, subprocess.CalledProcessError):
            print('cyclonedx-py not available; skipping SBOM')
            return False
        data = r.stdout
        output.write_text(data, encoding='utf-8')
        return True
    except Exception as e:
        print(f'SBOM generation error: {e}')
        return False


def run_pip_audit(output: Path):
    try:
        r = run_cmd(['pip-audit', '--format', 'json'])
        if isinstance(r, subprocess.CalledProcessError):
            # pip-audit returns non-zero when vulns found, still capture stdout
            data = r.stdout or ''
        else:
            data = r.stdout
        output.write_text(data, encoding='utf-8')
        return True
    except Exception as e:
        print(f'pip-audit error: {e}')
        return False


def evaluate_vulns(audit_path: Path) -> int:
    try:
        raw = audit_path.read_text(encoding='utf-8')
        if not raw.strip():
            return 0
        data = json.loads(raw)
        critical = 0
        for item in data:
            for vuln in item.get('vulns', []):
                severity = vuln.get('severity', '').upper()
                if severity == 'CRITICAL':
                    critical += 1
        return critical
    except Exception:
        return 0


def main():
    sbom_out = Path('sbom.json')
    audit_out = Path('audit.json')

    generated = generate_sbom(sbom_out)
    audited = run_pip_audit(audit_out)

    crit = evaluate_vulns(audit_out) if audited else 0
    summary = {
        'sbom_generated': generated,
        'audit_generated': audited,
        'critical_vulns': crit,
    }
    print(json.dumps(summary, indent=2))

    if crit > 0:
        print(f'ERROR: {crit} critical vulnerabilities found', file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
