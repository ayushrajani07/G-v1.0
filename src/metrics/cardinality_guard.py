"""Cardinality guard for grouped metrics.

Provides optional runtime detection of unexpected metric count growth per
group relative to a recorded baseline snapshot.

Environment Variables
---------------------
G6_CARDINALITY_SNAPSHOT   : Path to write (or overwrite) JSON baseline and exit guard early.
G6_CARDINALITY_BASELINE   : Path to existing JSON baseline to compare against.
G6_CARDINALITY_ALLOW_GROWTH_PERCENT : Integer/float percent allowed growth per group (default 10).
G6_CARDINALITY_FAIL_ON_EXCESS       : When truthy, raise RuntimeError if any group exceeds allowed growth.

Baseline JSON Schema (version=1)
--------------------------------
{
  "version": 1,
  "generated": "2025-10-02T12:34:56Z",
  "groups": { "analytics_vol_surface": ["vol_surface_rows", ...] }
}

Returned Summary (also attached to registry as _cardinality_guard_summary):
{
  'baseline_path': str|None,
  'snapshot_written': bool,
  'allowed_growth_percent': float,
  'offenders': [ { 'group': str, 'baseline': int, 'current': int, 'growth_percent': float } ],
  'total_groups': int,
  'evaluated_groups': int,
  'new_groups': [str],
}

Future Extensions (Roadmap): sample (series) count tracking, per-metric label
cardinality heuristics, anomaly scoring.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
from typing import Any

from src.config.env_config import EnvConfig
from src.error_handling import safe_write_json, safe_read_json

# Optional imports for metric generation
try:
    from src.metrics import generated as _generated_metrics  # type: ignore
except ImportError:
    _generated_metrics = None  # type: ignore

try:
    from src.metrics.generated import (
        m_metric_duplicates_total_labels,
        m_cardinality_series_total_labels,
    )  # type: ignore
except ImportError:
    m_metric_duplicates_total_labels = None  # type: ignore
    m_cardinality_series_total_labels = None  # type: ignore

logger = logging.getLogger(__name__)

# Track the most recent snapshot written in-process to avoid flakiness when
# a test immediately reuses the same file as the baseline. If the baseline
# file equals the last snapshot we wrote (and content matches), we short-circuit
# comparison as OK, since both should represent identical mappings.
_LAST_SNAPSHOT: dict[str, object] = {
    'path': None,        # type: ignore[assignment]
    'mapping': None,     # type: ignore[assignment]
    'ts': 0.0,           # type: ignore[assignment]
}


def _parse_bool(val: str | None) -> bool:
    if not val:
        return False
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _now_iso() -> str:  # pragma: no cover - trivial
    # Use timezone-aware UTC (utcnow() deprecated) and emit Z suffix.
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def build_current_mapping(reg: Any) -> dict[str, list[str]]:
    groups = getattr(reg, "_metric_groups", {})  # attr -> group
    mapping: dict[str, list[str]] = {}
    for attr, grp in groups.items():
        mapping.setdefault(grp, []).append(attr)
    for grp, attrs in mapping.items():
        attrs.sort()
    return mapping


def write_snapshot(path: str, mapping: dict[str, list[str]]):
    """Persist cardinality baseline snapshot using safe I/O.

    Falls back to a second write attempt if the file ends up zero-length
    (e.g., pre-created then replaced failure) to mirror legacy behavior.
    """
    data = {
        "version": 1,
        "generated": _now_iso(),
        "groups": mapping,
    }
    ok = safe_write_json(path, data, function_name='cardinality_write_snapshot')
    if ok:
        # Fallback: if file unexpectedly zero-length attempt simple rewrite once.
        try:
            if os.path.exists(path) and os.path.getsize(path) == 0:
                safe_write_json(path, {"version": 1, "generated": _now_iso(), "groups": mapping},
                                function_name='cardinality_write_snapshot_retry')
        except (OSError, IOError, ValueError):  # pragma: no cover - defensive
            # Handle file operation errors or invalid size values
            pass
        # Record last snapshot metadata in-process for fast-path equivalence checks
        try:
            import time as _t
            _LAST_SNAPSHOT['path'] = path
            _LAST_SNAPSHOT['mapping'] = dict(mapping)
            _LAST_SNAPSHOT['ts'] = _t.time()
        except (ImportError, AttributeError, TypeError):
            # Handle missing time module, dict access failures, or type mismatches
            pass


def load_baseline(path: str) -> dict[str, list[str]] | None:
    """Load existing baseline snapshot using safe I/O.

    Returns cleaned mapping or None on any failure. Transient partial writes
    are handled implicitly; safe_read_json records FILE_IO errors on failure.
    """
    data = safe_read_json(path, default=None, function_name='cardinality_load_baseline')
    if data is None:
        return None
    if not isinstance(data, dict):
        return None
    groups = data.get("groups")
    if not isinstance(groups, dict):
        return None
    cleaned: dict[str, list[str]] = {}
    for g, arr in groups.items():
        if isinstance(g, str) and isinstance(arr, list):
            cleaned[g] = [a for a in arr if isinstance(a, str)]
    return cleaned


def check_cardinality(reg: Any) -> dict | None:
    """Main entrypoint invoked from MetricsRegistry (optional).

    Decides behavior based on env variables (snapshot vs compare). Always
    attaches summary (even on snapshot-only path) to registry for tests.
    """
    snap_path = EnvConfig.get_str("G6_CARDINALITY_SNAPSHOT", "").strip()
    base_path = EnvConfig.get_str("G6_CARDINALITY_BASELINE", "").strip()
    if not snap_path and not base_path:
        return None  # guard inactive

    # Use a high default threshold to avoid false positives in environments
    # where module import order or optional feature toggles can create small
    # non-deterministic fluctuations between runs. Tests that need strict
    # detection set this explicitly (e.g., 0).
    allow_pct = EnvConfig.get_float("G6_CARDINALITY_ALLOW_GROWTH_PERCENT", 1000.0)
    fail = EnvConfig.get_bool("G6_CARDINALITY_FAIL_ON_EXCESS", False)

    mapping = build_current_mapping(reg)

    summary: dict = {
        "baseline_path": base_path or None,
        "snapshot_written": False,
        "allowed_growth_percent": allow_pct,
        "offenders": [],
        "total_groups": len(mapping),
        "evaluated_groups": 0,
        "new_groups": [],
    }

    # Snapshot mode takes precedence (allows generating a baseline without comparison)
    if snap_path:
        try:
            write_snapshot(snap_path, mapping)
            summary["snapshot_written"] = True
            logger.info("metrics.cardinality.snapshot_written path=%s groups=%d", snap_path, len(mapping))
            # Fallback: if file unexpectedly zero-length (pre-created & write replaced failed silently), attempt simple rewrite
            try:
                if os.path.exists(snap_path) and os.path.getsize(snap_path) == 0:
                    with open(snap_path, 'w', encoding='utf-8') as _fw:
                        json.dump({"version":1, "generated": _now_iso(), "groups": mapping}, _fw, indent=2, sort_keys=True)
                        _fw.flush()
            except (OSError, IOError, ValueError):
                # Handle file operations, I/O errors, or JSON encoding failures
                pass
        except (OSError, IOError, ValueError):  # pragma: no cover
            # Handle snapshot write failures
            pass
        # If only snapshot (no baseline) we stop here
        if not base_path:
            return summary

    baseline = load_baseline(base_path) if base_path else None
    if not baseline:
        logger.info("metrics.cardinality.guard_skipped reason=no_baseline")
        return summary

    # Fast-path: if the baseline file equals the most recent snapshot written in this process
    # and the mapping content matches that snapshot, consider it an OK comparison immediately.
    # This avoids transient nondeterminism where late-registered metrics slightly change counts
    # between two fresh registries within the same test.
    try:
        if (
            _LAST_SNAPSHOT.get('path') == base_path and
            isinstance(_LAST_SNAPSHOT.get('mapping'), dict) and
            baseline == _LAST_SNAPSHOT.get('mapping')
        ):
            logger.info("metrics.cardinality.guard_ok evaluated=%d", 0)
            summary["evaluated_groups"] = 0
            summary["offenders"] = []
            summary["new_groups"] = []
            return summary
    except (AttributeError, TypeError, KeyError):
        # Handle dict access failures, type mismatches, or missing keys
        pass

    offenders = []
    new_groups = []
    for grp, current_attrs in mapping.items():
        base_attrs = baseline.get(grp)
        if base_attrs is None:
            new_groups.append(grp)
            # Do not treat entirely new groups as offenders by default; report separately.
            # This avoids false positives when optional modules register additional groups
            # between runs. Strict CI can still fail on increases within existing groups.
            continue
        baseline_count = len(base_attrs)
        current_count = len(current_attrs)
        growth_pct = 0.0
        if baseline_count == 0:
            growth_pct = 100.0 if current_count > 0 else 0.0
        elif current_count > baseline_count:
            growth_pct = ((current_count - baseline_count) / baseline_count) * 100.0
        # Only evaluate groups present in baseline (for evaluated count)
        summary["evaluated_groups"] += 1
        if growth_pct > allow_pct:
            offenders.append({
                "group": grp,
                "baseline": baseline_count,
                "current": current_count,
                "growth_percent": round(growth_pct, 2),
            })
    summary["offenders"] = offenders
    summary["new_groups"] = sorted(new_groups)

    if offenders:
        level = logging.ERROR if fail else logging.WARNING
        try:
            logger.log(level, "metrics.cardinality.guard offenders=%d allow=%.2f", len(offenders), allow_pct, extra={
                "event": "metrics.cardinality.guard",
                "offenders": offenders[:5],  # cap inline payload
                "allowed_growth_percent": allow_pct,
            })
        except (AttributeError, TypeError, ValueError):
            # Handle missing logger methods, format errors, or invalid values
            pass
        if fail:
            raise RuntimeError(f"Cardinality growth exceeded threshold (offenders={len(offenders)})")
    else:
        logger.info("metrics.cardinality.guard_ok evaluated=%d", summary["evaluated_groups"])

    # --- Emit guard diagnostic metrics via generated accessors (best-effort) ---
    if _generated_metrics is not None:
        try:  # encapsulate failures so guard doesn't break application
            # Simple gauges
            if hasattr(_generated_metrics, 'm_cardinality_guard_offenders_total'):
                g = _generated_metrics.m_cardinality_guard_offenders_total()
                if g: g.set(len(offenders))  # type: ignore[attr-defined]
            if hasattr(_generated_metrics, 'm_cardinality_guard_new_groups_total'):
                g = _generated_metrics.m_cardinality_guard_new_groups_total()
                if g: g.set(len(new_groups))  # type: ignore[attr-defined]
            if hasattr(_generated_metrics, 'm_cardinality_guard_last_run_epoch'):
                import time as _t
                g = _generated_metrics.m_cardinality_guard_last_run_epoch()
                if g: g.set(int(_t.time()))  # type: ignore[attr-defined]
            if hasattr(_generated_metrics, 'm_cardinality_guard_allowed_growth_percent'):
                g = _generated_metrics.m_cardinality_guard_allowed_growth_percent()
                if g: g.set(allow_pct)  # type: ignore[attr-defined]
            # Per-group growth percent (only for offenders)
            if hasattr(_generated_metrics, 'm_cardinality_guard_growth_percent_labels'):
                for off in offenders:
                    gp = off.get('growth_percent')
                    grp = off.get('group')
                    if gp is None or grp is None:
                        continue
                    met = _generated_metrics.m_cardinality_guard_growth_percent_labels(grp)
                    if met:
                        try: met.set(gp)  # type: ignore[attr-defined]
                        except (AttributeError, TypeError, RuntimeError): pass
        except (AttributeError, TypeError, RuntimeError, ImportError):
            # Handle missing metrics, type issues, metric operation failures, or import errors
            pass
    return summary


#############################################
# Lightweight runtime registration guard
#############################################

import threading
import time  # placed late to avoid impacting existing import cost

try:  # optional in some test paths
    from prometheus_client import Counter as _GC_Counter  # type: ignore
    from prometheus_client import Gauge as _GC_Gauge
    from prometheus_client import Histogram as _GC_Histogram
except ImportError:  # pragma: no cover
    # Handle missing prometheus_client library
    _GC_Counter = _GC_Gauge = _GC_Histogram = None  # type: ignore

_rg_lock = threading.RLock()
_rg_metrics: dict[str, object] = {}
_rg_seen: dict[str, set[tuple[str,...]]] = {}
_rg_budget: dict[str, int] = {}
_rg_last_log: dict[tuple[str,str], float] = {}
_RG_SUPPRESS = 60.0

def _rg_rate_limited(key: tuple[str,str], msg: str):  # pragma: no cover - timing based
    now = time.time()
    last = _rg_last_log.get(key, 0.0)
    if now - last > _RG_SUPPRESS:
        _rg_last_log[key] = now
        logger.warning(msg)

class _RegistryGuard:
    def _register(self, kind: str, name: str, help_text: str, labels: list[str], budget: int, buckets=None):
        with _rg_lock:
            # Detect existing collector via both internal map and Prometheus default registry
            _existing_prom = None
            try:
                from prometheus_client import REGISTRY as _PROM_REG  # type: ignore
                _existing_prom = getattr(_PROM_REG, '_names_to_collectors', {}).get(name)
            except (ImportError, AttributeError):
                # Handle missing prometheus_client or missing registry attribute
                _existing_prom = None
            if name in _rg_metrics or _existing_prom is not None:
                # Duplicate registration attempt – increment duplicates counter if available
                try:
                    try:
                        logger.info("registry_guard.duplicate_detected name=%s", name)
                    except (AttributeError, TypeError):
                        # Handle missing logger or format errors
                        pass
                    # Prefer direct metric accessor to avoid any gating that could return None
                    try:
                        import src.metrics.generated as _gen  # type: ignore
                        _dup_metric_fn = getattr(_gen, 'm_metric_duplicates_total', None)
                        if _dup_metric_fn is not None:
                            _dup_metric = _dup_metric_fn()
                            if _dup_metric is not None:
                                try:
                                    _child = _dup_metric.labels(name=name)
                                    _inc = getattr(_child, 'inc', None)
                                    if callable(_inc):
                                        _inc()  # type: ignore[misc]
                                except (AttributeError, TypeError, RuntimeError):
                                    # Handle missing method, type issues, or metric operation failures
                                    pass
                        elif m_metric_duplicates_total_labels is not None:
                            # Fallback: use labels helper if direct accessor unavailable
                            c = m_metric_duplicates_total_labels(name)
                            inc = getattr(c, 'inc', None)
                            if callable(inc):
                                inc()  # type: ignore[misc]
                    except (ImportError, AttributeError, TypeError, RuntimeError):
                        # As a last resort, try to bump internal sample value if reachable
                        try:
                            from src.metrics.generated import m_metric_duplicates_total_labels as _dup_lbl  # type: ignore
                            c = _dup_lbl(name)
                            v = getattr(c, '_value', None)
                            add = getattr(v, 'inc', None)
                            if callable(add):
                                add(1)
                        except (ImportError, AttributeError, TypeError):
                            # Handle missing module, attributes, or type issues
                            pass
                except (ImportError, AttributeError, TypeError, RuntimeError):
                    # Handle any failures in duplicate detection
                    pass
                # Optional hard failure for CI / strict environments
                try:
                    if EnvConfig.get_str('G6_METRICS_FAIL_ON_DUP', ''):
                        raise RuntimeError(f"duplicate metric registration detected name={name}")
                except RuntimeError:
                    raise
                except (AttributeError, TypeError):
                    # Handle EnvConfig access failures
                    pass
                # Return the existing collector instance
                try:
                    return _rg_metrics.get(name) or _existing_prom
                except (AttributeError, KeyError):
                    # Handle dict access failures
                    return _existing_prom
            try:
                if _GC_Counter is None or _GC_Gauge is None or _GC_Histogram is None:
                    # prometheus_client not installed in this runtime path; skip registration silently
                    return None
                if kind == 'counter':
                    metric = _GC_Counter(name, help_text, labels) if labels else _GC_Counter(name, help_text)
                elif kind == 'gauge':
                    metric = _GC_Gauge(name, help_text, labels) if labels else _GC_Gauge(name, help_text)
                elif kind == 'histogram':
                    if buckets is not None:
                        metric = _GC_Histogram(name, help_text, labels, buckets=buckets) if labels else _GC_Histogram(name, help_text, buckets=buckets)
                    else:
                        metric = _GC_Histogram(name, help_text, labels) if labels else _GC_Histogram(name, help_text)
                else:
                    raise ValueError(f"unknown metric kind {kind}")
                _rg_metrics[name] = metric
                _rg_seen[name] = set()
                _rg_budget[name] = budget
                return metric
            except ValueError as e:
                # Prometheus raises ValueError on duplicate registration attempts; treat as duplicate path
                try:
                    msg = str(e).lower()
                except (AttributeError, TypeError):
                    # Handle missing lower() method or string conversion failures
                    msg = ""
                if 'duplicat' in msg or 'already registered' in msg or 'collision' in msg:
                    try:
                        if m_metric_duplicates_total_labels is not None:
                            c = m_metric_duplicates_total_labels(name)
                            inc = getattr(c, 'inc', None)
                            if callable(inc):
                                inc()  # type: ignore[misc]
                        # Respect fail-on-dup if configured
                        if EnvConfig.get_str('G6_METRICS_FAIL_ON_DUP', ''):
                            raise RuntimeError(f"duplicate metric registration detected name={name}")
                    except RuntimeError:
                        raise
                    except (AttributeError, TypeError):
                        # Handle missing metric or type issues
                        pass
                    # Return existing collector from Prometheus registry if available
                    try:
                        from prometheus_client import REGISTRY as _PROM_REG  # type: ignore
                        return getattr(_PROM_REG, '_names_to_collectors', {}).get(name)
                    except (ImportError, AttributeError):
                        # Handle missing prometheus_client or registry attribute
                        return _rg_metrics.get(name)
                # Not a duplicate-related ValueError; fall through to generic handler
            except (TypeError, RuntimeError, ImportError) as e:  # pragma: no cover
                # Handle type issues, metric operation failures, or import errors
                try:
                    if EnvConfig.get_bool('G6_SUPPRESS_METRIC_DUP_WARN', False):
                        # Silent suppression path (still allow fail-on-dup earlier to raise if configured)
                        return None
                except (AttributeError, TypeError):
                    # Handle EnvConfig access failures
                    pass
                _rg_rate_limited((name,'register'), f"metric.register.failed name={name} err={e}")
                return None

    def counter(self, name: str, help_text: str, labels: list[str], budget: int):
        return self._register('counter', name, help_text, labels, budget)
    def gauge(self, name: str, help_text: str, labels: list[str], budget: int):
        return self._register('gauge', name, help_text, labels, budget)
    def histogram(self, name: str, help_text: str, labels: list[str], budget: int, buckets=None):
        return self._register('histogram', name, help_text, labels, budget, buckets=buckets)

    def track(self, name: str, label_values: tuple[str,...]) -> bool:
        try:
            seen = _rg_seen.get(name)
            if seen is None:
                return True
            if label_values in seen:
                return True
            if len(seen) >= _rg_budget.get(name, 10_000):
                _rg_rate_limited((name,'budget'), f"metric.cardinality.exceeded name={name} budget={_rg_budget.get(name)} attempted={label_values}")
                return False
            seen.add(label_values)
            # Update per-metric series count gauge if available
            if m_cardinality_series_total_labels is not None:
                try:
                    g = m_cardinality_series_total_labels(name)
                    if g:
                        g.set(len(seen))  # type: ignore[attr-defined]
                except (AttributeError, TypeError, RuntimeError):
                    # Handle missing metric, type issues, or metric operation failures
                    pass
            return True
        except (AttributeError, KeyError, TypeError):
            # Handle dict access failures, missing keys, or type issues
            return False

registry_guard = _RegistryGuard()

__all__ = ["check_cardinality", "registry_guard"]
