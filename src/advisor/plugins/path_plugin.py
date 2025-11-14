from __future__ import annotations
"""Path Forecast Plugin: wraps existing path advisor logic into plugin findings.

Instead of duplicating logic, we import and invoke the existing FastAPI handler
function directly in-process to obtain summary/alerts.
"""
from typing import List, Dict, Any, cast
from ...advisor.core import AdvisorContext, AdvisorPlugin, PluginResult, Metric, Finding, Remedy

# Import API function
try:
    from src.web.dashboard.routes.path_forecast import api_ml_path_advisor  # async handler
except Exception:  # pragma: no cover
    api_ml_path_advisor = None  # type: ignore

class PathPlugin(AdvisorPlugin):
    name = "PATH"

    def collect_and_evaluate(self, ctx: AdvisorContext) -> PluginResult:
        findings: List[Finding] = []
        metrics: List[Metric] = []
        remedies: List[Remedy] = []
        # We will query only one horizon/window combo per index for brevity (can be extended)
        horizon = int(ctx.params.get('path_horizon', 60))
        window_minutes = int(ctx.params.get('path_window_minutes', 180))
        expiry_tag = str(ctx.params.get('path_expiry_tag', 'this_month'))
        offset = str(ctx.params.get('path_offset', '0'))
        bucket_ms = int(ctx.params.get('path_bucket_ms', 60000))

        for idx in ctx.indices:
            try:
                if api_ml_path_advisor is None:
                    raise RuntimeError('path advisor route not importable')
                # Call async route function directly
                import anyio  # type: ignore
                async def _call():
                    handler = cast(Any, api_ml_path_advisor)
                    return await handler(index=idx, horizon=horizon, window_minutes=window_minutes, expiry_tag=expiry_tag, offset=offset, bucket_ms=bucket_ms, date_str=None, gap_warn=0.05, gap_crit=0.10, min_samples_warn=30, min_samples_crit=10)
                resp = anyio.run(_call)
                data: Dict[str, Any] = resp.body  # type: ignore
                # FastAPI JSONResponse exposes .body as bytes
                if isinstance(data, (bytes, bytearray)):
                    import json
                    data = json.loads(data.decode('utf-8', errors='replace'))
                summary = data.get('summary') or {}
                alerts = data.get('alerts') or []
                # metrics snapshot
                cov = summary.get('coverage')
                samples = summary.get('samples')
                band_scale = summary.get('band_scale')
                if isinstance(cov, (int, float)):
                    metrics.append(Metric(name='path_coverage', value=float(cov), labels={'index': idx}, source='path_advisor', ts=ctx.now))
                if isinstance(samples, (int, float)):
                    metrics.append(Metric(name='path_samples', value=float(samples), labels={'index': idx}, source='path_advisor', ts=ctx.now))
                if isinstance(band_scale, (int, float)):
                    metrics.append(Metric(name='path_band_scale', value=float(band_scale), labels={'index': idx}, source='path_advisor', ts=ctx.now))
                # map alerts to findings
                for a in alerts:
                    level = str(a.get('level') or 'warn')
                    code = f"path_{a.get('code')}"
                    sev = 'crit' if level == 'crit' else ('warn' if level == 'warn' else 'info')
                    findings.append(Finding(code=code, plugin=self.name, severity=sev, summary=str(a.get('message') or code), evidence=a.get('metrics') or {}, confidence=0.7, index=idx))
                # propose remedies from alert categories
                codes = {f.code for f in findings}
                if 'path_coverage_gap' in codes:
                    remedies.append(Remedy(code='path_recalibrate_bands', steps=["POST /api/ml/path_calibrate with current target", "Verify coverage improves over next 30-60m"], automated=True, preconditions=["coverage_gap"], priority=60, references=["ML_README.md#Path-forecast-calibration"]))
                if 'path_low_samples' in codes:
                    remedies.append(Remedy(code='path_wait_or_widen_window', steps=["Increase window_minutes for diagnostics", "Ensure archiver running"], automated=False, preconditions=["low_samples"], priority=30, references=["ML_README.md#Path-forecast-observability"]))
                if 'path_forecast_fallback_mode' in codes:
                    remedies.append(Remedy(code='path_restore_retrieval_pipeline', steps=["Check retrieval corpus availability", "Inspect composite/hybrid fallback causes"], automated=False, preconditions=["fallback_mode"], priority=80, references=["ML_README.md#Troubleshooting"]))
            except Exception as e:
                findings.append(Finding(code='path_plugin_error', plugin=self.name, severity='warn', summary=f'Path plugin error: {e}', evidence={}, confidence=0.3, index=idx))
        return PluginResult(metrics=metrics, findings=findings, remedies=remedies, plugin_health={'indices': ctx.indices})
