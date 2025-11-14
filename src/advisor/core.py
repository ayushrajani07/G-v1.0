"""Universal Advisor Core Engine.

Provides plugin registration, metric collection context, aggregation, scoring, and
report serialization.

Initial lightweight implementation: synchronous, single request assembly.
"""
from __future__ import annotations
import time, datetime, json
from dataclasses import dataclass, field
from typing import Dict, List, Protocol, Any, Optional

# ---- Data Models ----
@dataclass
class Metric:
    name: str
    value: float
    labels: Dict[str, str]
    source: str
    ts: float

@dataclass
class Finding:
    code: str
    plugin: str
    severity: str  # info|warn|crit
    summary: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5
    index: Optional[str] = None  # optional index specificity; if None applies to all indices

@dataclass
class Diagnosis:
    code: str
    description: str
    findings: List[str]
    confidence: float

@dataclass
class Prognosis:
    code: str
    description: str
    horizon_minutes: int
    risk_level: str  # low|medium|high
    confidence: float

@dataclass
class Remedy:
    code: str
    steps: List[str]
    automated: bool
    preconditions: List[str]
    priority: int
    references: List[str] = field(default_factory=list)

@dataclass
class PluginResult:
    metrics: List[Metric]
    findings: List[Finding]
    diagnoses: List[Diagnosis] = field(default_factory=list)
    prognoses: List[Prognosis] = field(default_factory=list)
    remedies: List[Remedy] = field(default_factory=list)
    plugin_health: Dict[str, Any] = field(default_factory=dict)  # summary numbers

@dataclass
class AdvisorContext:
    indices: List[str]
    horizons: List[int]
    windows: List[int]
    now: float
    params: Dict[str, Any]
    # shared cache for baseline / queries
    cache: Dict[str, Any] = field(default_factory=dict)

class AdvisorPlugin(Protocol):
    name: str
    def collect_and_evaluate(self, ctx: AdvisorContext) -> PluginResult: ...

# ---- Core Engine ----
class AdvisorEngine:
    def __init__(self):
        self._plugins: List[AdvisorPlugin] = []

    def register(self, plugin: AdvisorPlugin) -> None:
        self._plugins.append(plugin)

    def run(self, ctx: AdvisorContext) -> Dict[str, Any]:
        all_metrics: List[Metric] = []
        all_findings: List[Finding] = []
        all_diagnoses: List[Diagnosis] = []
        all_prognoses: List[Prognosis] = []
        all_remedies: List[Remedy] = []
        plugin_health: Dict[str, Any] = {}
        # Seed pre-existing findings (e.g., tests or external collectors)
        seeded_findings = ctx.cache.get('findings')
        if isinstance(seeded_findings, list):
            all_findings.extend(seeded_findings)
            ctx.cache['findings'] = all_findings.copy()
        for p in self._plugins:
            try:
                res = p.collect_and_evaluate(ctx)
            except Exception as e:
                # record plugin error finding
                all_findings.append(Finding(
                    code=f"plugin_error_{p.name}",
                    plugin=p.name,
                    severity="warn",
                    summary=f"Plugin {p.name} failed: {e}",
                    evidence={},
                    confidence=0.2,
                    index=None,
                ))
                continue
            all_metrics.extend(res.metrics)
            all_findings.extend(res.findings)
            all_diagnoses.extend(res.diagnoses)
            all_prognoses.extend(res.prognoses)
            all_remedies.extend(res.remedies)
            if res.plugin_health:
                plugin_health[p.name] = res.plugin_health
            # expose cumulative findings to downstream plugins for correlation logic
            ctx.cache['findings'] = all_findings.copy()

        per_index = self._compute_health_per_index(ctx.indices, all_findings)
        # Aggregate overall: worst level + average score for summary convenience
        health_scores = [v['health_score'] for v in per_index.values()] or [100]
        worst_level = 'ok'
        level_rank = {'ok':0,'warn':1,'crit':2}
        for v in per_index.values():
            if level_rank.get(v['level'],0) > level_rank.get(worst_level,0):
                worst_level = v['level']
        health_score = int(sum(health_scores)/len(health_scores))
        overall = worst_level
        flags = self._make_flags(all_findings)
        ordered_remedies = self._prioritize_remedies(all_remedies)
        from src.utils.timeutils import utc_now_z
        return {
            "generated_at": utc_now_z(),
            "summary": {
                "overall_level": overall,
                "health_score": health_score,
                "actions_ordered": [r.code for r in ordered_remedies],
                "plugin_health": plugin_health,
                "per_index": per_index,
            },
            "metrics": [m.__dict__ for m in all_metrics],
            "findings": [self._finding_to_dict(f) for f in all_findings],
            "diagnoses": [d.__dict__ for d in all_diagnoses],
            "prognoses": [p.__dict__ for p in all_prognoses],
            "remedies": [self._remedy_to_dict(r) for r in ordered_remedies],
            "flags": flags,
        }

    # ---- Helpers ----
    def _compute_health_per_index(self, indices: List[str], findings: List[Finding]) -> Dict[str, Dict[str, Any]]:
        per: Dict[str, Dict[str, Any]] = {}
        for idx in indices:
            score = 100
            level = 'ok'
            for f in findings:
                if f.index is not None and f.index != idx:
                    continue
                if f.severity == 'crit':
                    score -= 25
                    level = 'crit'
                elif f.severity == 'warn' and level != 'crit':
                    score -= 10
                    if level == 'ok':
                        level = 'warn'
            score = max(0, min(100, score))
            per[idx] = {'health_score': score, 'level': level}
        return per

    def _make_flags(self, findings: List[Finding]) -> Dict[str, int]:
        flags: Dict[str, int] = {}
        for f in findings:
            # compress code into numeric flag
            flags[f.code] = 1
        return flags

    def _prioritize_remedies(self, remedies: List[Remedy]) -> List[Remedy]:
        # Higher priority number executed first; stable sort
        return sorted(remedies, key=lambda r: (-r.priority, r.code))

    @staticmethod
    def _finding_to_dict(f: Finding) -> Dict[str, Any]:
        return {
            "code": f.code,
            "plugin": f.plugin,
            "severity": f.severity,
            "summary": f.summary,
            "evidence": f.evidence,
            "confidence": f.confidence,
            "index": f.index,
        }

    @staticmethod
    def _remedy_to_dict(r: Remedy) -> Dict[str, Any]:
        return {
            "code": r.code,
            "steps": r.steps,
            "automated": r.automated,
            "preconditions": r.preconditions,
            "priority": r.priority,
            "references": r.references,
        }

# Convenience factory

def build_default_engine(ctx: AdvisorContext) -> AdvisorEngine:
    from .plugins.ann_plugin import AnnPlugin
    from .plugins.path_plugin import PathPlugin
    from .plugins.expiry_plugin import ExpiryPlugin
    from .plugins.correlation_plugin import CorrelationPlugin
    eng = AdvisorEngine()
    eng.register(AnnPlugin())
    eng.register(PathPlugin())
    eng.register(ExpiryPlugin())
    eng.register(CorrelationPlugin())  # must come last to see prior findings
    return eng
