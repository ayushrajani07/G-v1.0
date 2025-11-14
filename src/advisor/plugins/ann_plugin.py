from __future__ import annotations
"""ANN Plugin: evaluates ANN health metrics and produces findings/remedies.
"""
import json, datetime
from typing import List, Dict, Any
from ...advisor.core import AdvisorContext, AdvisorPlugin, PluginResult, Metric, Finding, Diagnosis, Prognosis, Remedy
from ..prom_query import get_ann_metrics
from pathlib import Path

class AnnPlugin(AdvisorPlugin):
    name = "ANN"

    def collect_and_evaluate(self, ctx: AdvisorContext) -> PluginResult:
        indices = ctx.indices
        windows = ctx.windows or [60, 120]
        prometheus = ctx.params.get('prometheus')
        ports = [int(p) for p in str(ctx.params.get('ann_ports','9308,9309,9310')).split(',') if p.strip()]
        metrics_map = get_ann_metrics(indices, windows, prometheus, ports)
        baseline_path = Path(ctx.params.get('baseline', 'baselines/ann_daily_baseline.json'))
        baseline_doc: Dict[str, Any] = {}
        try:
            if baseline_path.exists():
                raw = json.loads(baseline_path.read_text(encoding='utf-8'))
                if any(k.startswith('retrieval_') for k in raw.keys()):
                    raw = {'NIFTY': raw}
                baseline_doc = raw
        except Exception:
            pass

        findings: List[Finding] = []
        plug_metrics: List[Metric] = []
        remedies: List[Remedy] = []
        # thresholds
        speedup_drop_th = float(ctx.params.get('ann_speedup_drop', 0.05))
        mad_max = float(ctx.params.get('ann_mad_max', 0.05))
        prune_max = float(ctx.params.get('ann_prune_max', 0.90))
        eff_min = float(ctx.params.get('ann_eff_min', 0.02))

        for idx, win_map in metrics_map.items():
            branch = baseline_doc.get(idx, {}) if isinstance(baseline_doc, dict) else {}
            for win, vals in win_map.items():
                # record metrics
                for k, v in vals.items():
                    plug_metrics.append(Metric(name=f"ann_{k}", value=float(v), labels={"index": idx, "window": win}, source="ann_exporter", ts=ctx.now))
                base_key = f"retrieval_{win}_k10"
                baseline = branch.get(base_key, {})
                live_speedup = vals.get('speedup', float('nan'))
                baseline_speedup = baseline.get('speedup_avg', 0.0)
                speedup_drop = baseline_speedup - live_speedup if live_speedup == live_speedup else 0.0
                rows = vals.get('rows', 0)
                mad = vals.get('q50_mad', float('nan'))
                prune = vals.get('prune_ratio', float('nan'))
                eff = vals.get('effectiveness_adjusted', vals.get('effectiveness', float('nan')))
                # gating
                if rows < int(ctx.params.get('ann_min_rows', 5)):
                    findings.append(Finding(code="ann_insufficient_rows", plugin=self.name, severity="info", summary=f"Rows < gate for {idx} win {win}", evidence={"rows": rows}, confidence=0.6, index=idx))
                    continue
                if speedup_drop > speedup_drop_th:
                    findings.append(Finding(code="ann_speedup_drop", plugin=self.name, severity="warn", summary=f"Speedup drop {speedup_drop:.3f} > {speedup_drop_th}", evidence={"live": live_speedup, "baseline": baseline_speedup}, confidence=0.75, index=idx))
                if mad == mad and mad > mad_max:
                    findings.append(Finding(code="ann_mad_high", plugin=self.name, severity="warn", summary=f"MAD {mad:.3f} > {mad_max}", evidence={"mad": mad}, confidence=0.7, index=idx))
                if prune == prune and prune > prune_max:
                    findings.append(Finding(code="ann_prune_high", plugin=self.name, severity="warn", summary=f"Prune {prune:.3f} > {prune_max}", evidence={"prune": prune}, confidence=0.7, index=idx))
                if eff == eff and eff < eff_min:
                    findings.append(Finding(code="ann_effectiveness_low", plugin=self.name, severity="crit", summary=f"Effectiveness {eff:.3f} < {eff_min}", evidence={"effectiveness": eff}, confidence=0.85, index=idx))

        # Compose remedies based on findings
        codes = {f.code for f in findings}
        if 'ann_effectiveness_low' in codes and ('ann_prune_high' in codes or 'ann_speedup_drop' in codes):
            remedies.append(Remedy(
                code="ann_rollback_recent_tuning",
                steps=["Identify last tuning commit affecting ANN parameters", "Revert candidate/prune overrides", "Run exporter --once to confirm regressions cleared"],
                automated=False,
                preconditions=["effectiveness_low", "speedup_or_prune_issue"],
                priority=90,
                references=["ANN_RUNBOOK.md#8.-Rollback-Procedure"],
            ))
        if 'ann_prune_high' in codes and 'ann_effectiveness_low' not in codes:
            remedies.append(Remedy(
                code="ann_retune_prune_candidates",
                steps=["Increase ann_max_candidates by small increment", "Lower prune threshold by 0.02", "Re-evaluate ranking CSV"],
                automated=False,
                preconditions=["prune_high"],
                priority=70,
                references=["ANN_RUNBOOK.md#7.-Retuning-Guidelines"],
            ))
        if 'ann_speedup_drop' in codes and 'ann_effectiveness_low' not in codes:
            remedies.append(Remedy(
                code="ann_refresh_baseline",
                steps=["Run daily health check with --refresh-baseline-if-ok", "Commit updated baseline branch"],
                automated=False,
                preconditions=["speedup_drop"],
                priority=50,
                references=["ANN_RUNBOOK.md#6.-Baseline-Refresh-Procedure"],
            ))

        return PluginResult(metrics=plug_metrics, findings=findings, remedies=remedies, plugin_health={"indices": indices})
