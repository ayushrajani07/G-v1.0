from __future__ import annotations
"""Correlation Plugin: Emits composite findings when multiple plugin signals align.

Current rule: For an index, if ANN effectiveness is low (crit) AND path coverage gap is present (warn/crit),
raise a composite risk finding and metric.
"""
from typing import List, Dict, Any
from ...advisor.core import AdvisorContext, AdvisorPlugin, PluginResult, Metric, Finding, Remedy

class CorrelationPlugin(AdvisorPlugin):
    name = "CORRELATION"

    def collect_and_evaluate(self, ctx: AdvisorContext) -> PluginResult:
        findings: List[Finding] = []
        metrics: List[Metric] = []
        remedies: List[Remedy] = []

        prior: List[Finding] = ctx.cache.get('findings', []) or []
        by_index: Dict[str, Dict[str, int]] = {}
        for f in prior:
            idx = f.index or 'ALL'
            d = by_index.setdefault(idx, {})
            d[f.code] = max(d.get(f.code, 0), 1)

        for idx in ctx.indices:
            codes = by_index.get(idx, {})
            if codes.get('ann_effectiveness_low', 0) and (codes.get('path_coverage_gap', 0) or codes.get('path_forecast_fallback_mode', 0)):
                findings.append(Finding(code='advisor_composite_ann_path_risk', plugin=self.name, severity='crit', summary='ANN effectiveness low with Path coverage/fallback issues', evidence={'components': ['ann_effectiveness_low','path_coverage_gap|fallback']}, confidence=0.85, index=idx))
                metrics.append(Metric(name='advisor_composite_risk', value=1.0, labels={'index': idx, 'type': 'ann_path'}, source='correlation', ts=ctx.now))
                remedies.append(Remedy(code='composite_escalate_rollback', steps=['Rollback recent ANN tuning impacting retrieval','Recalibrate path bands','Verify retrieval corpus and exporter health'], automated=False, preconditions=['ann_low_effectiveness','path_gap'], priority=95, references=['ANN_RUNBOOK.md','ML_README.md#Path-forecast-calibration']))

        return PluginResult(metrics=metrics, findings=findings, remedies=remedies, plugin_health={'rules': 1})
