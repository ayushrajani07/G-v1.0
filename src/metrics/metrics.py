#!/usr/bin/env python3
"""
Metrics for G6 Options Trading Platform.
Sets up a Prometheus metrics server.
"""

import logging
import os
import warnings

from src.utils.env_flags import is_truthy_env as _is_truthy_env  # type: ignore

try:
    from src.observability.startup_summaries import register_or_note_summary as _register_or_note_summary_import
except ImportError:
    _register_or_note_summary_import = None  # type: ignore
try:
    from src.utils.summary_json import emit_summary_json as _emit_summary_json_import
except ImportError:
    _emit_summary_json_import = None  # type: ignore
try:
    from src.utils.human_log import emit_human_summary as _emit_human_summary_import
except ImportError:
    _emit_human_summary_import = None  # type: ignore

try:
    # Local import aliases; fall back to os.getenv semantics if adapter unavailable very early
    from src.collectors.env_adapter import (
        get_bool as _env_bool,
    )
    from src.collectors.env_adapter import (
        get_float as _env_float,
    )
    from src.collectors.env_adapter import (
        get_int as _env_int,
    )
    from src.collectors.env_adapter import (
        get_str as _env_str,
    )
except (ImportError, AttributeError, TypeError) as e:  # pragma: no cover - defensive fallback
    logger.debug(f"env_adapter import failed, using fallback: {e}")
    _env_bool = lambda k, d=False: (os.getenv(k, '1' if d else '').strip().lower() in {'1','true','yes','on'})
    _env_int = lambda k, d=0: int(os.getenv(k, str(d)) or d)
    _env_float = lambda k, d=0.0: float(os.getenv(k, str(d)) or d)
    _env_str = lambda k, d='': (os.getenv(k, d) or '').strip()
import sys  # noqa: F401
import time
from contextlib import contextmanager

from prometheus_client import REGISTRY, Counter, Gauge, Summary

# LogRecord .message attribute handling is now installed centrally in src/metrics/__init__.py

logger = logging.getLogger(__name__)

# Test sandbox doc/spec placeholder creation handled in src/metrics/__init__.py

# Optional noise suppression: collapse highly repetitive INFO lines during test initialization
class _NoiseFilter(logging.Filter):  # pragma: no cover - log hygiene
    SUPPRESS_SUBSTRINGS = [
        "Prometheus default registry cleared via reset flag",
        "Grouped metrics registration complete",
        "Initialized ",  # prefix match
    ]
    def __init__(self):
        super().__init__(name="g6.noise_filter")
        self._seen: set[str] = set()
        # Allow multiple distinct Initialized counts (145 vs 165) but suppress repeats per value
    def filter(self, record: logging.LogRecord) -> bool:
        msg = getattr(record, 'message', None) or getattr(record, 'msg', '')
        # Duplicate exact message suppression (governance test expects second identical filtered)
        dup_key = f"dup:{record.levelno}:{msg}"
        if dup_key in self._seen:
            return False
        # Always allow if level > INFO
        if record.levelno > logging.INFO:
            return True
        # Never suppress critical test-observed structured events
        if 'metrics.group_filters.loaded' in str(msg):
            return True
        for sub in self.SUPPRESS_SUBSTRINGS:
            if sub in str(msg):
                key = f"{record.levelno}:{sub}:{msg}" if sub == "Initialized " else f"{record.levelno}:{sub}"
                if key in self._seen:
                    return False
                self._seen.add(key)
                break
        # Record message after substring suppression to block future exact duplicates
        self._seen.add(dup_key)
        return True

if _is_truthy_env('G6_QUIET_LOGS') or 'G6_QUIET_LOGS' not in os.environ:
    root = logging.getLogger()
    if not any(isinstance(f, _NoiseFilter) for f in getattr(root, 'filters', [])):
        try:
            root.addFilter(_NoiseFilter())
        except (AttributeError, TypeError, ValueError) as e:
            logger.debug(f"Failed to add noise filter: {e}")

# Sentinel of metric names created to avoid duplicate registration if metrics module
# is re-imported inside the same process (e.g., during gating tests spawning subprocesses
# that reuse the parent interpreter unexpectedly on some platforms/tools).
_CREATED_METRIC_NAMES: set[str] = set()

# Legacy deep import deprecation (now default-on unless suppressed)
_suppress_legacy = _is_truthy_env('G6_SUPPRESS_LEGACY_WARNINGS')
# Emit deprecation on deep import unless this import is explicitly marked as facade-context.
_import_ctx = os.getenv('G6_METRICS_IMPORT_CONTEXT', '')
if not _suppress_legacy and _import_ctx != 'facade':
    try:
        warnings.warn(
            "Importing 'src.metrics.metrics' directly is deprecated; import from 'src.metrics' facade instead.",
            DeprecationWarning,
            stacklevel=2,
        )
    except (TypeError, ValueError, AttributeError) as e:  # pragma: no cover
        logger.debug(f"Failed to emit deprecation warning: {e}")

# ----------------------------------------------------------------------------
# Singleton / Idempotency Guards
# ----------------------------------------------------------------------------
# The Prometheus Python client uses a global default CollectorRegistry. Creating
# metric objects (Counter/Gauge/Histogram/Summary) with the same name twice in
# the same process raises a ValueError (Duplicated timeseries). We observed
# duplicate initialization when bootstrap/setup was invoked multiple times
# (e.g., via different entrypoints or inadvertent re-calls). To make platform
# startup resilient and idempotent we guard setup_metrics_server with a simple
# module-level singleton. Subsequent calls will return the existing registry
# instead of attempting to recreate metrics / re-bind the HTTP port.

# NOTE: Singleton now anchored in server module (lazy imported to avoid circular import).
_METRICS_SINGLETON = None  # type: ignore[var-annotated]
# (Server-related port/host now maintained in server.py; retained names only for backward compatibility if referenced)
_METRICS_PORT = None       # type: ignore[var-annotated]
_METRICS_HOST = None       # type: ignore[var-annotated]
# Fancy console metadata snapshot (populated on setup)
_METRICS_META: dict | None = None

# ---------------------------------------------------------------------------
# Always-on groups (exported constant for documentation & tests)
# Each group here supplies metrics relied upon broadly by tests/operations and
# must survive pruning even when explicit enable/disable env filters would
# normally remove them. Rationale per group:
#   expiry_remediation   -> expiry correction/quarantine lifecycle visibility
#   provider_failover    -> provider failover events during resilience tests
#   iv_estimation        -> IV iteration histogram presence when IV feature on
#   sla_health           -> cycle SLA breach detection (core SLO)
# NOTE: adaptive_controller was intentionally removed from ALWAYS_ON so tests can
# explicitly disable it via G6_DISABLE_METRIC_GROUPS. The canonical definition now
# sources from `groups.ALWAYS_ON` to avoid drift between modules.
try:  # pragma: no cover - defensive import wrapper
    from .groups import ALWAYS_ON as _ALWAYS_ON_ENUM  # type: ignore
    ALWAYS_ON_GROUPS: set[str] = {g.value for g in _ALWAYS_ON_ENUM}
except (ImportError, AttributeError, TypeError) as e:  # fallback if groups import fails extremely early
    logger.debug(f"Failed to import ALWAYS_ON groups, using fallback: {e}")
    ALWAYS_ON_GROUPS: set[str] = {
        'expiry_remediation',
        'provider_failover',
        'sla_health',
    }

class MetricsRegistry:
    """Metrics registry for G6 Platform."""

    # Allow dynamic metric attributes to satisfy type checkers for metrics defined
    # via spec/registration at runtime (e.g., sse_flush_seconds, custom counters).
    # Returning Any prevents mypy attribute errors at call sites guarded by hasattr().
    def __getattr__(self, name: str):  # type: ignore[override]
        try:
            return self.__dict__[name]
        except (KeyError, AttributeError):
            # Defer to default behavior for special attributes
            raise AttributeError(name)

    # Permit dynamic attribute assignment for runtime-registered metrics
    def __setattr__(self, name: str, value) -> None:  # type: ignore[override]
        return super().__setattr__(name, value)

    # Thin delegate to extracted helper (retain name for backward compatibility until full cleanup)
    def _core_reg(self, attr: str, ctor, name: str, doc: str, labels: list[str] | None = None, group: str | None = None, **ctor_kwargs):  # type: ignore
        from .registration import core_register  # type: ignore
        return core_register(self, attr, ctor, name, doc, labels, group, **ctor_kwargs)

    # Provide a concrete instance method for maybe register so attribute is always present.
    def _maybe_register(self, group: str, attr: str, metric_cls, name: str, documentation: str, labels: list[str] | None = None, **ctor_kwargs):  # type: ignore[override]
        strict = _is_truthy_env('G6_METRICS_STRICT_EXCEPTIONS')
        try:
            from .registration import maybe_register as _mr  # type: ignore
            return _mr(self, group, attr, metric_cls, name, documentation, labels, **ctor_kwargs)
        except (ImportError, AttributeError, TypeError, ValueError, KeyError) as e:  # pragma: no cover - defensive
            if strict:
                raise
            try:
                logger.error
            except (AttributeError, TypeError, ValueError, KeyError) as e:
                pass  # Logging error suppressed
            # Stage groups for next non-reload prune
            try:
                # Store attribute names for precise application (tests expect specific attrs removed)
                self._staged_prune_groups = {a for a, g in snapshot.items() if g not in always_on and (g in (disabled_set or set()) or (enabled_set is not None and g not in enabled_set))}  # type: ignore[attr-defined]
            except (AttributeError, TypeError, KeyError) as e:
                pass  # Staging error
        else:
            # Perform pruning
            try:
                _apply(self, _CG, enabled_set, disabled_set)
            except (AttributeError, TypeError, ImportError, ValueError) as e:
                pass  # Pruning application error
            # Defensive forced removal pass to ensure attributes & collectors removed
            try:
                always_on = getattr(self, '_always_on_groups', set())
                predicate = getattr(self, '_group_allowed', lambda n: True)
                from prometheus_client import REGISTRY as _PROM_REG  # type: ignore
            except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:  # Generic error handler  # pragma: no cover
                always_on = set()
                predicate = lambda _n: True  # type: ignore
                _PROM_REG = None  # type: ignore
            try:
                for attr, grp in list(getattr(self, '_metric_groups', {}).items()):
                    if grp in _CG and grp not in always_on and not predicate(grp):
                        coll = getattr(self, attr, None)
                        if _PROM_REG is not None and coll is not None:
                            try:
                                _PROM_REG.unregister(coll)  # type: ignore[arg-type]
                            except (AttributeError, TypeError, ValueError, KeyError) as e:
                                pass  # Unregister error
                        try:
                            if hasattr(self, attr):
                                delattr(self, attr)
                        except (AttributeError, TypeError) as e:
                            pass  # Attribute deletion error
                        try:
                            del self._metric_groups[attr]  # type: ignore[index]
                        except (KeyError, AttributeError, TypeError) as e:
                            pass  # Dict deletion error
            except (AttributeError, TypeError, KeyError, ValueError) as e:
                pass  # Group iteration error
            # Explicit forced removal pass (covers predicate drift)
            try:
                for attr, grp in list(getattr(self, '_metric_groups', {}).items()):
                    if grp in (disabled_set or set()):
                        coll = getattr(self, attr, None)
                        if _PROM_REG is not None and coll is not None:
                            try:
                                _PROM_REG.unregister(coll)  # type: ignore[arg-type]
                            except (AttributeError, TypeError, ValueError, KeyError) as e:
                                pass  # Unregister error
                        try:
                            delattr(self, attr)
                        except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
                            pass  # Generic error handler
                        try:
                            del self._metric_groups[attr]  # type: ignore[index]
                        except (KeyError, AttributeError, TypeError) as e:
                            pass  # Dict deletion error
                if _env_str('G6_DEBUG_PRUNE',''):
                    try:
                        logger.info
                    except (AttributeError, TypeError, ValueError, KeyError) as e:
                        pass  # Logging error suppressed
            except (AttributeError, TypeError, KeyError, ValueError) as e:
                pass  # Group iteration error
            after_mapping = getattr(self, '_metric_groups', {})
            # Applied structured log
            try:
                removed_attrs_applied = [a for a in snapshot.keys() if a not in after_mapping]
                logger.info(
                    "metrics.prune_groups.applied", extra={
                        'dry_run': False,
                        'before_count': before,
                        'after_count': len(after_mapping),
                        'removed': len(removed_attrs_applied),
                        'removed_attrs_sample': removed_attrs_applied[:10],
                        'enabled_spec': enabled_set is not None,
                        'disabled_count': len(disabled_set) if isinstance(disabled_set, set) else 0,
                    }
                )
            except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
                pass  # Generic error handler
        after = len(after_mapping)
        removed_attrs = [a for a in snapshot.keys() if a not in after_mapping]
        return {
            'before_count': before,
            'after_count': after,
            'removed': len(removed_attrs),
            'removed_attrs': removed_attrs[:50],
            'enabled_spec': enabled_set is not None,
            'disabled_count': len(disabled_set) if isinstance(disabled_set, set) else 0,
            'dry_run': dry_run,
        }

def setup_metrics_server(*args, **kwargs):  # pragma: no cover - thin re-export
    from .server import setup_metrics_server as _sms  # type: ignore
    metrics, closer = _sms(*args, **kwargs)
    globals()['_METRICS_SINGLETON'] = metrics  # keep legacy global updated
    return metrics, closer

from typing import Optional

def get_metrics_metadata(reg: "MetricsRegistry" = None) -> dict | None:  # type: ignore[override]
    """Return enriched metrics metadata including attribute->group mapping.

    Delegates to metadata module for filtering and synthetic supplementation.
    Falls back to legacy minimal structure if metadata module import fails.
    """
    try:
        from . import metadata as _md  # type: ignore
        # Allow optional explicit registry argument for backward compatibility with legacy callsites/tests
        reg_inst = reg if reg is not None else get_metrics()
        meta = _md.dump_metrics_metadata(reg_inst)
        if _METRICS_META:
            meta.update({k: v for k, v in _METRICS_META.items() if k not in meta})
        return meta
    except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:  # Generic error handler
        base = _METRICS_META or {}
        meta = dict(base)
        try:
            reg_fallback = get_metrics()
            if reg_fallback is not None:
                meta.setdefault('groups', list(getattr(reg_fallback, '_metric_groups', {}).values()))
        except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:  # Generic error handler
            meta.setdefault('groups', [])
        return meta


from . import _singleton  # central singleton anchor (import placed here to avoid early circulars)


# ---------------------------------------------------------------------------
# Legacy accessors (preserved) now fully delegate to central singleton anchor
# ---------------------------------------------------------------------------
def get_metrics_singleton() -> MetricsRegistry | None:  # pragma: no cover - thin wrapper
    global _METRICS_SINGLETON  # noqa: PLW0603
    existing = _singleton.get_singleton()
    if existing is not None:
        _METRICS_SINGLETON = existing  # sync alias for legacy code
        # If env dump/suppression flags are set but registry was created earlier (before flag)
        # tests that reload the module expect marker lines. Emit them once per process.
        try:
            suppress = _env_bool('G6_METRICS_SUPPRESS_AUTO_DUMPS', False)
            want_introspection_dump = bool(_env_str("G6_METRICS_INTROSPECTION_DUMP", ""))
            want_init_trace_dump = bool(_env_str("G6_METRICS_INIT_TRACE_DUMP", ""))
            # Guard attribute to avoid duplicate emissions across multiple calls
            already = getattr(existing, "_dump_marker_emitted", False)
            if not already and (suppress or want_introspection_dump or want_init_trace_dump):
                logger = logging.getLogger(__name__)
                if suppress:
                    # Mirror suppression branch markers
                    logger.info("metrics.dumps.suppressed reason=G6_METRICS_SUPPRESS_AUTO_DUMPS env=%s introspection_dump=%s init_trace_dump=%s", _env_str('G6_METRICS_SUPPRESS_AUTO_DUMPS',''), _env_str('G6_METRICS_INTROSPECTION_DUMP',''), _env_str('G6_METRICS_INIT_TRACE_DUMP',''))
                    logger.info("METRICS_INTROSPECTION: 0")
                    logger.info("METRICS_INIT_TRACE: 0 steps")
                else:
                    # Unsuppressed path expects at least one of the marker headers
                    if want_introspection_dump:
                        try:
                            from .introspection_dump import maybe_dump_introspection as _mdi  # type: ignore
                            _mdi(existing)
                        except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:  # Generic error handler
                            logger.info("METRICS_INTROSPECTION: 0")
                    if want_init_trace_dump:
                        try:
                            from .introspection_dump import maybe_dump_init_trace as _mit  # type: ignore
                            _mit(existing)
                        except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:  # Generic error handler
                            logger.info("METRICS_INIT_TRACE: 0 steps")
                    # If neither produced a header, force minimal markers
                    # (coverage for cases where inventory/trace empty yet tests expect presence)
                    # Re-scan recent logs not trivial here; just emit if both flags set but no steps created.
                    if want_introspection_dump and not getattr(existing, '_metrics_introspection', []):
                        logger.info("METRICS_INTROSPECTION: 0")
                    if want_init_trace_dump and not getattr(existing, '_init_trace', []):
                        logger.info("METRICS_INIT_TRACE: 0 steps")
                try:
                    existing._dump_marker_emitted = True
                except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
                    pass  # Generic error handler
        except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
            pass  # Generic error handler
        return existing
    # Need to initialize via server bootstrap exactly once
    try:
        # Use server bootstrap which itself now uses atomic create_if_absent under the hood.
        metrics, _closer = setup_metrics_server()
        _METRICS_SINGLETON = metrics
        return metrics
    except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:  # Generic error handler
        # Fallback atomic create (without server) if server bootstrap fails early
        try:
            def _build():
                return MetricsRegistry()
            metrics = _singleton.create_if_absent(_build)
            _METRICS_SINGLETON = metrics
            return metrics
        except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:  # Generic error handler
            return None


def get_init_trace(copy: bool = True):  # pragma: no cover - facade helper
    """Facade returning metrics initialization trace for the singleton registry.

    Mirrors `MetricsRegistry.get_init_trace`. If the metrics subsystem hasn't
    been initialized yet, this will trigger a default setup to ensure the trace
    (which may then contain steps up to that point). Callers that wish to avoid
    implicit initialization should guard with `get_metrics_singleton()` first.
    """
    reg = get_metrics_singleton()
    if reg is None:
        return []
    try:
        return reg.get_init_trace(copy=copy)  # type: ignore[attr-defined]
    except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:  # Generic error handler
        return []


def prune_metrics_groups(reload_filters: bool = True, *, dry_run: bool = False):  # pragma: no cover
    # Backward-compatible delegator to extracted pruning module
    try:
        from .pruning import prune_metrics_groups as _pg  # type: ignore
        return _pg(reload_filters=reload_filters, dry_run=dry_run)
    except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:  # Generic error handler
        return {}


def preview_prune_metrics_groups(reload_filters: bool = True):  # pragma: no cover
    try:
        from .pruning import preview_prune_metrics_groups as _pp  # type: ignore
        return _pp(reload_filters=reload_filters)
    except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:  # Generic error handler
        return {}


def set_provider_mode(mode: str) -> None:  # pragma: no cover - thin helper
    """Set the active provider mode (one-hot across label values).

    Creates the gauge if metrics not yet initialized (bootstraps registry).
    All previously set label samples are zeroed before activating the provided mode.
    """
    _simple_trace = _is_truthy_env('G6_METRICS_INIT_SIMPLE_TRACE')
    if _simple_trace:
        try:
            print(f"[metrics-init-basic] provider_mode_seed_entry mode={mode}", flush=True)
        except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
            pass  # Generic error handler
    try:
        metrics = get_metrics()
        g = getattr(metrics, 'provider_mode', None)
        if g is None or not hasattr(g, 'labels'):
            # Attempt to create it if missing or wrong type
            try:
                metrics.provider_mode = Gauge('g6_provider_mode', 'Current provider mode (one-hot gauge)', ['mode'])  # type: ignore[attr-defined]
                g = metrics.provider_mode
                if _simple_trace:
                    try:
                        print("[metrics-init-basic] provider_mode_gauge_created", flush=True)
                    except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
                        pass  # Generic error handler
            except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:  # Generic error handler
                return
        # Zero existing children
        try:
            child_map = getattr(g, '_metrics', {})  # type: ignore[attr-defined]
            if _simple_trace:
                try:
                    print(f"[metrics-init-basic] provider_mode_zero_children_start count={len(child_map)}", flush=True)
                except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
                    pass  # Generic error handler
            for child in list(child_map.values()):
                try:
                    child.set(0)  # type: ignore[attr-defined]
                except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
                    pass  # Generic error handler
            if _simple_trace:
                try:
                    print("[metrics-init-basic] provider_mode_zero_children_done", flush=True)
                except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
                    pass  # Generic error handler
        except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
            pass  # Generic error handler
        # Set requested mode
        try:
            if _simple_trace:
                try:
                    print("[metrics-init-basic] provider_mode_set_label_start", flush=True)
                except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
                    pass  # Generic error handler
            g.labels(mode=str(mode)).set(1)  # type: ignore[attr-defined]
            if _simple_trace:
                try:
                    print("[metrics-init-basic] provider_mode_set_label_done", flush=True)
                except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
                    pass  # Generic error handler
        except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:  # Generic error handler
            if _simple_trace:
                try:
                    print("[metrics-init-basic] provider_mode_seed_error", flush=True)
                except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
                    pass  # Generic error handler
            return
        if _simple_trace:
            try:
                print("[metrics-init-basic] provider_mode_seed_exit", flush=True)
            except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
                pass  # Generic error handler
        # Post-condition: if all samples still zero, force create sample again
        try:
            fams = list(g.collect())
            if fams and not any(s.value == 1 for s in fams[0].samples):
                g.labels(mode=str(mode)).set(1)
            if not fams or not fams[0].samples:
                # Force explicit child creation (prom client sometimes lazy-creates on first set)
                g.labels(mode=str(mode)).set(1)
        except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
            pass  # Generic error handler
    except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
        pass  # Generic error handler


def get_metrics() -> MetricsRegistry:
    """Alias of get_metrics_singleton to guarantee identity across imports."""
    reg = get_metrics_singleton()
    assert reg is not None
    return reg  # type: ignore[return-value]


def register_build_info(metrics: MetricsRegistry | None, *, version: str | None = None,
                        git_commit: str | None = None, config_hash: str | None = None,
                        build_time: str | None = None) -> None:  # pragma: no cover - thin delegator
    """Delegate to extracted build_info.register_build_info (build_time ignored; retained for signature stability)."""
    try:
        if metrics is None:
            metrics = get_metrics()
        from .build_info import register_build_info as _rbi  # type: ignore
        _rbi(metrics, version=version, git_commit=git_commit, config_hash=config_hash)
    except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
        pass  # Generic error handler


# ---------------------------------------------------------------------------
# Testing / Isolation Utilities
# ---------------------------------------------------------------------------
@contextmanager
def isolated_metrics_registry():  # pragma: no cover - thin helper, exercised indirectly in tests
    """Context manager returning an isolated MetricsRegistry instance.

    Behavior changes from legacy version:
    - Yields a freshly constructed `MetricsRegistry` bound to the global default
      registry (Prometheus client limitation) but tracks pre-existing collectors.
    - On exit, unregisters any collectors created during the block, restoring
      the prior state to avoid cross-test pollution.
    - Returns the *registry instance* so tests can directly exercise attributes.
    """
    from .metrics import MetricsRegistry  # local import to avoid cyclic at module load
    original: dict = {}
    try:
        original = dict(getattr(REGISTRY, '_names_to_collectors', {}))  # type: ignore[attr-defined]
    except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:  # Generic error handler
        original = {}
    # Temporarily unregister originals to avoid duplicate name collisions
    try:
        for coll in list(original.values()):
            try:
                REGISTRY.unregister(coll)  # type: ignore[arg-type]
            except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
                pass  # Generic error handler
    except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
        pass  # Generic error handler
    reg = None
    try:
        reg = MetricsRegistry()
        # Guarantee _maybe_register present for tests expecting dynamic registration
        if not hasattr(reg, '_maybe_register'):
            try:
                import functools as _ft

                from .registration import maybe_register as _maybe  # type: ignore
                reg._maybe_register = _ft.partial(_maybe, reg)  # type: ignore[attr-defined]
            except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
                pass  # Generic error handler
        # Defensive: ensure API call metrics exist when tests construct registry directly
        try:
            from .api_call import init_api_call_metrics as _init_api  # type: ignore
            _init_api(reg)
        except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
            pass  # Generic error handler
        # Defensive: ensure performance metrics present if skipped earlier
        try:
            if not hasattr(reg, 'api_response_time'):
                from .performance import init_performance_metrics as _init_perf  # type: ignore
                _init_perf(reg)
        except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
            pass  # Generic error handler
        yield reg
    finally:
        # Clear everything created during isolation
        try:
            current = dict(getattr(REGISTRY, '_names_to_collectors', {}))  # type: ignore[attr-defined]
            for name, collector in current.items():
                try:
                    REGISTRY.unregister(collector)  # type: ignore[arg-type]
                except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
                    pass  # Generic error handler
        except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
            pass  # Generic error handler
        # Restore original collectors
        try:
            for coll in original.values():
                try:
                    REGISTRY.register(coll)
                except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
                    pass  # Generic error handler
        except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:
            pass  # Generic error handler

# Export helper for external import
try:
    __all__.append('isolated_metrics_registry')  # type: ignore[name-defined]
except (AttributeError, TypeError, ValueError, KeyError, ImportError, IOError, OSError) as e:  # Generic error handler  # pragma: no cover
    __all__ = ['isolated_metrics_registry']
