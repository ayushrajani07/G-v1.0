"""Bootstrap helpers for initializing RuntimeContext.

This module extracts early initialization concerns from `unified_main.py` to
reduce its size and improve testability.

Current responsibilities:
  * Load config (delegates to `unified_main.load_config` for now to preserve behavior)
  * Initialize metrics server (reuse existing setup_metrics_server)
  * Populate a `RuntimeContext` instance

Future planned responsibilities (see roadmap):
  * Provider factory instantiation & failover wiring
  * Health monitor startup
  * Event bus initialization
  * CSV / Parquet sink setup abstraction
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
import os
from typing import Any

from src.config.env_config import EnvConfig
from src.config.runtime_config import get_runtime_config
from src.orchestrator.context import RuntimeContext
from src.utils.build_info import auto_register_build_info

# Common imports moved to top to eliminate late imports (Phase 3 refactoring)
from src.utils.env_flags import is_truthy_env, is_truthy as _is_truthy
from src.collector.settings import get_collector_settings
from src.config.env_lifecycle import ENV_LIFECYCLE_REGISTRY
from src.observability.startup_summaries import register_summary, register_or_note_summary
from src.utils.summary_json import emit_summary_json
from src.utils.human_log import emit_human_summary
from src.utils.market_hours import get_next_market_open, is_premarket_window
from src.orchestrator.catalog_http import start_http_server_in_thread
from src.orchestrator.components import apply_circuit_breakers, init_health, init_providers, init_storage

# Alias used in multiple locations for brevity
_is_truthy_env = is_truthy_env

logger = logging.getLogger(__name__)

# Deliberate shallow imports to avoid circular dependencies
# Use Optional[Callable] placeholders to avoid mypy redefinition/assignment errors.
setup_metrics_server: Callable[..., Any] | None = None
try:  # pragma: no cover - optional path if metrics not yet refactored
    from src.metrics import setup_metrics_server as _setup_metrics_server  # facade import
    setup_metrics_server = _setup_metrics_server
except (ImportError, AttributeError):  # pragma: no cover
    # Handle missing module or function
    setup_metrics_server = None

# Use canonical config loader (ConfigWrapper) to avoid depending on legacy unified_main.
load_config_fn: Callable[[str], Any] | None = None
try:
    from src.config.loader import load_config as _load_config
    load_config_fn = _load_config
except (ImportError, AttributeError):  # pragma: no cover
    # Handle missing module or function
    load_config_fn = None
try:
    from src.unified_main import load_config as _legacy_load_config_import
except (ImportError, AttributeError, RuntimeError):
    # Handle missing module or function
    _legacy_load_config_import = None  # type: ignore


def run_env_deprecation_scan(*, strict_mode_override: bool | None = None) -> None:
    """Scan environment for deprecated variables and emit warnings / raise if strict.

    Parameters
    ----------
    strict_mode_override : bool | None
        Force strict mode on/off (bypasses env flag) when not None.
    """
    try:
        if strict_mode_override is None:
            # Read raw env to avoid cached reads during tests where the flag is monkeypatched per-case.
            strict_mode = _is_truthy(os.environ.get('G6_ENV_DEPRECATION_STRICT'))
        else:
            strict_mode = strict_mode_override

        # Build allowlist from env var; split into items only when the env var is present.
        raw_allow = EnvConfig.get_str('G6_ENV_DEPRECATION_ALLOW', '') or ''
        allowlist = set(raw_allow.split(',')) if raw_allow else set()
        for _entry in ENV_LIFECYCLE_REGISTRY:
            if _entry.status == 'deprecated' and EnvConfig.get_str(_entry.name, ''):
                repl = f" Use {_entry.replacement} instead." if _entry.replacement else ""
                msg = f"[env-deprecated] {_entry.name} is deprecated{repl}"
                if strict_mode and _entry.name not in allowlist:
                    logger.error(msg + " (strict mode violation)")
                    raise RuntimeError(f"Deprecated env var disallowed in strict mode: {_entry.name}")
                else:
                    logger.warning(msg)
    except RuntimeError:
        # Re-raise strict violation immediately
        raise
    except (AttributeError, TypeError, KeyError, ValueError):  # pragma: no cover - non-fatal path
        # Handle config access or parsing failures
        logger.debug("Env lifecycle deprecation scan failed", exc_info=True)


def bootstrap_runtime(config_path: str,
                      *,
                      reset_metrics: bool = False,
                      custom_registry: bool = False,
                      enable_resource_sampler: bool = True) -> tuple[RuntimeContext, Any | None]:
    """Bootstrap core services and return (context, metrics).

    Parameters
    ----------
    config_path : str
        Path to JSON configuration.
    reset_metrics : bool
        Whether to reset Prometheus default registry before creating metrics.
    custom_registry : bool
        Use a custom CollectorRegistry instead of global registry.
    enable_resource_sampler : bool
        Launch resource sampler thread for utilization gauges.
    """
    if load_config_fn is None:
        # Fallback to legacy if new path unavailable
        if _legacy_load_config_import:
            load_config_fn_final = _legacy_load_config_import
        else:
            raise RuntimeError("load_config unavailable; import order issue")
    else:
        load_config_fn_final = load_config_fn
    raw_cfg = load_config_fn_final(config_path)

    metrics: Any | None = None
    # Avoid lambda assignment to comply with style; simple no-op callable
    def _no_op() -> None:
        return None
    metrics_stop: Callable[[], None] = _no_op
    if setup_metrics_server is not None:
        try:
            metrics, metrics_stop = setup_metrics_server(
                port=raw_cfg.raw.get('metrics', {}).get('port', 9108) if hasattr(raw_cfg, 'raw') else 9108,
                host=raw_cfg.raw.get('metrics', {}).get('host', '0.0.0.0') if hasattr(raw_cfg, 'raw') else '0.0.0.0',
                enable_resource_sampler=enable_resource_sampler,
                use_custom_registry=custom_registry,
                reset=reset_metrics,
            )
        except (OSError, IOError, RuntimeError, AttributeError, TypeError):
            # Handle server bind, I/O, or initialization failures
            logger.exception("Metrics server initialization failed")

    # Build runtime_config snapshot (loop/metrics env) and attach to context
    try:
        rt_cfg = get_runtime_config(refresh=True)
    except (AttributeError, TypeError, ValueError, RuntimeError):
        # Handle config retrieval failures
        rt_cfg = None
    ctx = RuntimeContext(config=raw_cfg, runtime_config=rt_cfg, metrics=metrics)
    # Emit deprecation warnings / strict enforcement
    run_env_deprecation_scan()
    # Auto register build info metric (idempotent). Allows env overrides:
    # G6_VERSION, G6_GIT_COMMIT. Config hash derived from raw config contents.
    try:
        auto_register_build_info(metrics, raw_cfg)
    except (AttributeError, TypeError, RuntimeError):  # pragma: no cover - non-fatal
        # Handle metric registration failures
        logger.debug("Auto build info registration failed", exc_info=True)

    # Component initialization (now default ON). Set G6_DISABLE_COMPONENTS=1 to skip.
    if not EnvConfig.get_bool('G6_DISABLE_COMPONENTS', False):
        try:
            providers = init_providers(raw_cfg)
            csv_sink = init_storage(raw_cfg)
            apply_circuit_breakers(raw_cfg, providers)
            health = init_health(raw_cfg, providers, csv_sink)
            ctx.providers = providers
            ctx.csv_sink = csv_sink
            ctx.health_monitor = health
        except (ImportError, AttributeError, TypeError, ValueError, RuntimeError, OSError, IOError):
            # Handle import, initialization, or I/O failures
            logger.exception("Component bootstrap (providers/storage/health) failed; proceeding with partial context")
            # If failure likely due to missing credentials and we are in premarket init window, emit guidance.
            try:
                if is_premarket_window():
                    nxt = get_next_market_open()
                    logger.warning(
                        (
                            "Premarket bootstrap partial (credentials missing?). "
                            "Will retry provider init automatically after regular open at %s "
                            "if orchestrator restarts, or set credentials earlier to enable warm caches."
                        ),
                        nxt,
                    )
            except (AttributeError, TypeError, ValueError, OSError):  # pragma: no cover
                # Handle market hours check failures
                pass
    # Start catalog HTTP server if enabled
    if is_truthy_env('G6_CATALOG_HTTP'):
        try:
            start_http_server_in_thread()
        except (OSError, IOError, RuntimeError, AttributeError):
            # Handle server start failures
            logger.exception("Catalog HTTP server failed to start")

    # One-shot orchestrator startup summary (structured + optional human block)
    try:
        if '_G6_ORCH_SUMMARY_EMITTED' not in globals():
            globals()['_G6_ORCH_SUMMARY_EMITTED'] = True
            # Derive key runtime flags / counts
            try:
                # Prefer runtime config value, fallback to raw config's loop.interval when available
                loop_interval = getattr(rt_cfg, 'loop_interval', None)
                if loop_interval is None and hasattr(raw_cfg, 'raw'):
                    loop_interval = raw_cfg.raw.get('loop', {}).get('interval', None)
            except (AttributeError, TypeError, KeyError):
                # Handle config access failures
                loop_interval = None
            # Indices count: attempt to access planned indices list in config (common key patterns)
            indices_count = None
            indices_sample = None
            try:
                raw_indices = None
                if hasattr(raw_cfg, 'raw'):
                    rc = raw_cfg.raw
                    raw_indices = rc.get('indices') or rc.get('symbols') or rc.get('index_list')
                if isinstance(raw_indices, (list, tuple)):
                    indices_count = len(raw_indices)
                    if raw_indices:
                        head = list(raw_indices)[:3]
                        indices_sample = ','.join(str(x) for x in head)
                        if indices_count > 3:
                            indices_sample += ',...'
            except (AttributeError, TypeError, KeyError, ValueError):
                # Handle config parsing or string conversion failures
                pass
            # Collector / pipeline flags
            try:
                pipeline_v2 = int(_is_truthy_env('G6_COLLECTOR_PIPELINE_V2'))
            except (ValueError, TypeError, KeyError):
                # Handle flag parsing failures
                pipeline_v2 = 0
            diff_mode = int(_is_truthy_env('G6_SSE_STRUCTURED'))
            structured_sse = diff_mode  # alias for clarity
            quiet_mode = int(_is_truthy_env('G6_QUIET_MODE'))
            salvage_enabled = int(_is_truthy_env('G6_FOREIGN_EXPIRY_SALVAGE'))
            domain_models = int(_is_truthy_env('G6_DOMAIN_MODELS'))
            egress_frozen = int(_is_truthy_env('G6_EGRESS_FROZEN'))
            # Provider client presence
            has_provider_client = 0
            try:
                providers = getattr(ctx, 'providers', None)
                if providers:
                    # heuristic: any provider with attribute 'kite' not None
                    for p in (providers if isinstance(providers, (list, tuple, set)) else [providers]):
                        if getattr(p, 'kite', None) is not None:
                            has_provider_client = 1
                            break
            except (AttributeError, TypeError):
                # Handle provider attribute access failures
                pass
            # Metrics HTTP server status
            metrics_http = 0
            try:
                if metrics is not None:
                    # Look for internal server thread / port attr heuristics
                    if hasattr(metrics, 'server') or hasattr(metrics, 'port'):
                        metrics_http = 1
            except (AttributeError, TypeError):
                # Handle metrics attribute access failures
                pass
            # Build info gauge presence heuristic
            build_info_registered = 0
            try:
                from prometheus_client import REGISTRY as _R
                for fam in _R.collect():  # pragma: no cover (iter small)
                    if getattr(fam, 'name', '') == 'g6_build_info':
                        build_info_registered = 1
                        break
            except (ImportError, AttributeError, TypeError, RuntimeError):
                # Handle registry import or collection failures
                pass
            # Overrides count from settings snapshot if already loaded
            overrides_count = 0
            try:
                _s = get_collector_settings()
                overrides_count = len(getattr(_s, 'log_level_overrides', {}) or {})
                pipeline_v2 = int(bool(getattr(_s, 'pipeline_v2_flag', False))) or pipeline_v2
                quiet_mode = int(bool(getattr(_s, 'quiet_mode', False))) or quiet_mode
                salvage_enabled = int(bool(getattr(_s, 'salvage_enabled', False))) or salvage_enabled
                domain_models = int(bool(getattr(_s, 'domain_models', False))) or domain_models
            except (AttributeError, TypeError, ValueError, RuntimeError):
                # Handle settings access or parsing failures
                pass
            start_ts = int(getattr(ctx, 'start_time', time.time()))
            # Human-readable block first (if requested) so tests capturing single call see both
            human_flag = is_truthy_env('G6_ORCH_SUMMARY_HUMAN')
            if human_flag:
                try:  # pragma: no cover
                    emit_human_summary(
                        'Orchestrator Summary',
                        [
                            ('loop_interval', loop_interval),
                            ('indices_count', indices_count),
                            ('indices_sample', indices_sample),
                            ('pipeline_v2', pipeline_v2),
                            ('diff_mode', diff_mode),
                            ('structured_sse', structured_sse),
                            ('quiet_mode', quiet_mode),
                            ('salvage_enabled', salvage_enabled),
                            ('domain_models', domain_models),
                            ('provider_client', has_provider_client),
                            ('metrics_http', metrics_http),
                            ('build_info_registered', build_info_registered),
                            ('overrides_count', overrides_count),
                            ('egress_frozen', egress_frozen),
                            ('start_timestamp', start_ts),
                        ],
                        logger
                    )
                except (AttributeError, TypeError, OSError, IOError):
                    # Handle summary emission failures
                    pass
            logger.info(
                (
                    "orchestrator.summary loop_interval=%s indices=%s pipeline_v2=%s diff_mode=%s "
                    "structured_sse=%s quiet=%s salvage=%s domain_models=%s provider_client=%s "
                    "metrics_http=%s build_info=%s overrides=%s egress_frozen=%s start_ts=%s"
                ),
                loop_interval,
                indices_count,
                pipeline_v2,
                diff_mode,
                structured_sse,
                quiet_mode,
                salvage_enabled,
                domain_models,
                has_provider_client,
                metrics_http,
                build_info_registered,
                overrides_count,
                egress_frozen,
                start_ts,
            )
            try:
                register_or_note_summary('orchestrator', emitted=True)
            except (AttributeError, TypeError, RuntimeError):
                # Handle summary registration failures
                pass
            # JSON variant
            try:
                if is_truthy_env('G6_ORCH_SUMMARY_JSON'):
                    emit_summary_json(
                            'orchestrator',
                            [
                                ('loop_interval', loop_interval),
                                ('indices_count', indices_count),
                                ('pipeline_v2', pipeline_v2),
                                ('diff_mode', diff_mode),
                                ('structured_sse', structured_sse),
                                ('quiet_mode', quiet_mode),
                                ('salvage_enabled', salvage_enabled),
                                ('domain_models', domain_models),
                                ('provider_client', has_provider_client),
                                ('metrics_http', metrics_http),
                                ('build_info_registered', build_info_registered),
                                ('overrides_count', overrides_count),
                                ('egress_frozen', egress_frozen),
                                ('start_timestamp', start_ts),
                            ],
                            logger_override=logger,
                        )
            except (AttributeError, TypeError, OSError, IOError, json.JSONEncodeError):
                # Handle JSON emission failures
                pass
    except (AttributeError, TypeError, ValueError, RuntimeError):
        # Handle summary emission wrapper failures
        pass
    # Force collector settings hydration early so its one-shot summary is emitted under captured logger
    try:
        # If sentinel was cleared by a previous test, re-hydration will emit structured + optional JSON/human summaries
        get_collector_settings(force_reload=True)
    except (AttributeError, TypeError, ValueError, RuntimeError, ImportError):
        # Handle settings hydration failures
        logger.debug("collector settings early hydration failed", exc_info=True)
    return ctx, metrics_stop

# Emit deprecated env vars presence summary (JSON optional) via dispatcher convenience
try:  # registration happens at import time (idempotent)
    def _emit_deprecated_env_summary() -> bool:
        present = []
        def _is_deprecated_present(entry) -> bool:
            try:
                return getattr(entry, 'status', '') == 'deprecated' and bool(EnvConfig.get_str(entry.name, ''))
            except (AttributeError, TypeError, KeyError):
                # Handle entry attribute or config access failures
                return False
        present = [entry.name for entry in ENV_LIFECYCLE_REGISTRY if _is_deprecated_present(entry)]
        if not present:
            # still emit a zero-count line for visibility
            logging.getLogger(__name__).info("env.deprecations.summary count=0")
            if is_truthy_env('G6_ENV_DEPRECATIONS_SUMMARY_JSON'):
                try:
                    emit_summary_json('env.deprecations', [('count', 0)], logger_override=logging.getLogger(__name__))
                except (AttributeError, TypeError, OSError, IOError, json.JSONEncodeError):
                    # Handle JSON emission failures
                    pass
            return True
        log = logging.getLogger(__name__)
        log.info("env.deprecations.summary count=%s names=%s", len(present), ','.join(present))
        if is_truthy_env('G6_ENV_DEPRECATIONS_SUMMARY_JSON'):
            try:
                emit_summary_json(
                    'env.deprecations',
                    [('count', len(present)), ('names', present)],
                    logger_override=log,
                )
            except (AttributeError, TypeError, OSError, IOError, json.JSONEncodeError):
                # Handle JSON emission failures
                pass
        return True
    # Ensure callable registered for dispatcher emission + mark not yet emitted
    register_summary('env.deprecations', _emit_deprecated_env_summary)
    register_or_note_summary('env.deprecations', emitted=False)
except (AttributeError, TypeError, RuntimeError, ImportError):
    # Handle summary registration failures
    pass

__all__ = ["bootstrap_runtime", "run_env_deprecation_scan"]
