from __future__ import annotations
"""Expiry Coverage Plugin: surfaces missing logical expiry advisories.

Leverages CSV expiry handler state if accessible; falls back to log scan (future enhancement).
"""
import re, os, datetime
from typing import List, Dict, Any
from ...advisor.core import AdvisorContext, AdvisorPlugin, PluginResult, Metric, Finding, Remedy

LOG_PATHS = ["logs/collector.log", "logs/system.log"]  # heuristic
EXPIRY_PATTERN = re.compile(r"CSV_EXPIRY_ADVISORY index=(?P<index>[A-Z0-9_]+) seen=\[(?P<seen>[^]]*)] missing=\[(?P<missing>[^]]*)]")

class ExpiryPlugin(AdvisorPlugin):
    name = "EXPIRY"

    def collect_and_evaluate(self, ctx: AdvisorContext) -> PluginResult:
        findings: List[Finding] = []
        metrics: List[Metric] = []
        remedies: List[Remedy] = []
        # Simple implementation: scan recent lines of log files for today's advisories
        today = datetime.date.today().isoformat()
        for p in LOG_PATHS:
            if not os.path.exists(p):
                continue
            try:
                with open(p, 'r', encoding='utf-8', errors='replace') as f:
                    for line in f.readlines()[-200:]:  # tail sample
                        if today not in line:
                            continue
                        m = EXPIRY_PATTERN.search(line)
                        if not m:
                            continue
                        idx = m.group('index')
                        if idx not in ctx.indices:
                            continue
                        missing_raw = m.group('missing').strip()
                        missing = [x.strip() for x in missing_raw.split(',') if x.strip()]
                        seen_raw = m.group('seen').strip()
                        seen = [x.strip() for x in seen_raw.split(',') if x.strip()]
                        severity = 'warn' if missing else 'info'
                        findings.append(Finding(code='expiry_missing_tags', plugin=self.name, severity=severity, summary=f"Missing expiries for {idx}: {missing}", evidence={'seen': seen, 'missing': missing}, confidence=0.6, index=idx))
                        metrics.append(Metric(name='expiry_missing_count', value=float(len(missing)), labels={'index': idx}, source='log_scan', ts=ctx.now))
            except Exception:
                pass
        # Remedy suggestion
        if any(f.code == 'expiry_missing_tags' for f in findings):
            remedies.append(Remedy(code='expiry_investigate_ingestion', steps=["Check collector config for expected expiries", "Verify provider feed completeness"], automated=False, preconditions=['missing_expiries'], priority=40, references=['ML_README.md#Expiry-handling']))
        return PluginResult(metrics=metrics, findings=findings, remedies=remedies, plugin_health={'indices': ctx.indices})
