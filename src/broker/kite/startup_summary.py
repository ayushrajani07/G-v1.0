"""Startup summary emission extracted (A7 Step 5).

Provides `emit_startup_summary(provider)` which mirrors the previously inline
logic in `KiteProvider.__init__` (structured log, dispatcher registration,
optional JSON and human variants). Kept separate to allow reuse and easier
testing without importing full provider facade.
"""
from __future__ import annotations

import logging
import sys
from typing import Any, Protocol

# Optional imports for structured logging (moved to module top)
try:
    from src.observability.startup_summaries import register_or_note_summary
except ImportError:
    register_or_note_summary = None  # type: ignore

try:
    from src.utils.env_flags import is_truthy_env
except ImportError:
    is_truthy_env = None  # type: ignore

try:
    from src.utils.summary_json import emit_summary_json
except ImportError:
    emit_summary_json = None  # type: ignore

try:
    from src.utils.human_log import emit_human_summary
except ImportError:
    emit_human_summary = None  # type: ignore

# Use the original provider module logger name so sitecustomize whitelist allows output.
logger = logging.getLogger('src.broker.kite_provider')


class _SettingsLike(Protocol):
    """Minimal settings protocol used by startup summary.

    Only attributes accessed unconditionally are declared. Others are feature-
    gated behind hasattr/getattr with defaults and remain optional.
    """

    concise: object | None
    kite_throttle_ms: object | None


class _ProviderLike(Protocol):
    _settings: _SettingsLike
    kite: object | None

def emit_startup_summary(provider: _ProviderLike) -> None:
    # Enhanced idempotent guard: suppress only if sentinel present both locally AND mirrored
    if '_KITE_PROVIDER_SUMMARY_EMITTED' in globals():
        try:  # pragma: no cover
            kp_mod = sys.modules.get('src.broker.kite_provider')
            # Help the type-checker: treat the module as Any for dynamic attribute access
            kp_any: Any = kp_mod
            if kp_mod is not None and bool(getattr(kp_any, '_KITE_PROVIDER_SUMMARY_EMITTED', False)):
                return
            # If provider module sentinel was cleared (common in integration test reset), allow re-emission
        except Exception:
            return
    globals()['_KITE_PROVIDER_SUMMARY_EMITTED'] = True
    # Mirror sentinel into kite_provider module (historical location tests clear)
    try:  # pragma: no cover
        kp_mod = sys.modules.get('src.broker.kite_provider')
        if kp_mod is not None:
            try:
                setattr(kp_mod, '_KITE_PROVIDER_SUMMARY_EMITTED', True)
            except Exception:
                pass
    except Exception:
        pass
    try:
        s = provider._settings  # noqa: SLF001 - intentional internal access for summary snapshot
        concise: int = int(bool(getattr(s, 'concise', True)))
        throttle_ms: int = int(getattr(s, 'kite_throttle_ms', 0) or 0)
        exp_fabrication: int = int(bool(getattr(s, 'allow_expiry_fabrication', True))) if hasattr(s, 'allow_expiry_fabrication') else 1
        cache_ttl: Any = getattr(s, 'instruments_cache_ttl', None)
        retry_on_empty: int = int(bool(getattr(s, 'retry_on_empty', True))) if hasattr(s, 'retry_on_empty') else 1
        logger.info(
            "provider.kite.summary concise=%s throttle_ms=%s expiry_fabrication=%s cache_ttl=%s retry_on_empty=%s has_client=%s",
            concise, throttle_ms, exp_fabrication, cache_ttl, retry_on_empty, int(provider.kite is not None)
        )
        # Dispatcher registration
        try:  # pragma: no cover
            if register_or_note_summary is not None:
                register_or_note_summary('provider.kite', emitted=True)
        except Exception:
            pass
        # JSON variant
        try:  # pragma: no cover
            if is_truthy_env is not None and is_truthy_env('G6_PROVIDER_SUMMARY_JSON'):
                if emit_summary_json is not None:
                    emit_summary_json(
                    'provider.kite',
                    [
                        ('concise', concise),
                        ('throttle_ms', throttle_ms),
                        ('expiry_fabrication', exp_fabrication),
                        ('cache_ttl', cache_ttl),
                        ('retry_on_empty', retry_on_empty),
                        ('has_client', int(provider.kite is not None)),
                    ],
                    logger_override=logger
                )
        except Exception:
            pass
        # Human variant
        try:  # pragma: no cover
            if is_truthy_env is not None and is_truthy_env('G6_PROVIDER_SUMMARY_HUMAN'):
                if emit_human_summary is not None:
                    emit_human_summary(
                        'Kite Provider Summary',
                        [
                            ('concise', concise),
                            ('throttle_ms', throttle_ms),
                            ('expiry_fabrication', exp_fabrication),
                            ('cache_ttl', cache_ttl),
                            ('retry_on_empty', retry_on_empty),
                            ('has_client', int(provider.kite is not None)),
                        ],
                        logger
                    )
        except Exception:
            pass
    except Exception:  # pragma: no cover
        pass

def _reset_provider_summary_state() -> None:  # test-only helper (mirrors startup summaries reset pattern)
    try:
        if '_KITE_PROVIDER_SUMMARY_EMITTED' in globals():
            del globals()['_KITE_PROVIDER_SUMMARY_EMITTED']
    except Exception:
        pass
    try:  # also clear mirrored sentinel on kite_provider
        kp_mod = sys.modules.get('src.broker.kite_provider')
        if kp_mod is not None and hasattr(kp_mod, '_KITE_PROVIDER_SUMMARY_EMITTED'):
            delattr(kp_mod, '_KITE_PROVIDER_SUMMARY_EMITTED')
    except Exception:
        pass

__all__ = ['emit_startup_summary','_reset_provider_summary_state']
