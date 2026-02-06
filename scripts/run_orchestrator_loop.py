#!/usr/bin/env python
"""Preferred orchestration loop runner (replaces legacy unified_main entry).

Features:
    * Uses bootstrap_runtime + run_loop abstraction (unified collectors always active)
  * Honors G6_LOOP_MAX_CYCLES (or --cycles CLI mapped to env) for bounded runs
  * Optional auto snapshots enablement (--auto-snapshots) convenience
  * Clean metrics server shutdown

CLI cycles vs env precedence:
  If --cycles > 0 we set G6_LOOP_MAX_CYCLES unless already provided.

Exit Codes:
  0 success
  2 bootstrap failure
  3 unrecoverable cycle exception
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config.env_config import EnvConfig
from src.config.g6_config import get_g6_config
from src.utils.logging_utils import setup_logging
from src.orchestrator.bootstrap import bootstrap_runtime  # type: ignore
from src.orchestrator.context import RuntimeContext  # type: ignore
from src.orchestrator.cycle import run_cycle  # type: ignore
from src.orchestrator.loop import run_loop  # type: ignore
from src.orchestrator.startup_sequence import run_startup_sequence  # type: ignore

try:
    from src.collectors.helpers.cycle_tables import flush_deferred_cycle_tables  # type: ignore
except Exception:  # pragma: no cover
    def flush_deferred_cycle_tables():  # type: ignore
        pass

logger = logging.getLogger("run_orchestrator_loop")

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Orchestrator Loop Runner")
    p.add_argument("--config", default="config/g6_config.json", help="Config JSON path")
    p.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Cycle interval seconds (default: 30; override with G6_LOOP_INTERVAL_SECONDS)",
    )
    p.add_argument("--cycles", type=int, default=0, help="Number of cycles (0=unbounded)")
    p.add_argument("--auto-snapshots", action="store_true", help="Enable auto snapshots (sets env toggle)")
    p.add_argument("--parallel", action="store_true", help="Enable parallel per-index collection")
    # Output/logging presentation (maps to env)
    p.add_argument("--concise", action="store_true", help="Force concise logging mode (sets G6_CONCISE_LOGS=1)")
    p.add_argument("--verbose", action="store_true", help="Force verbose logging (sets G6_CONCISE_LOGS=0 and disables quiet mode)")
    p.add_argument("--quiet", action="store_true", help="Suppress most logs; keep cycle summaries & warnings/errors (sets G6_QUIET_MODE=1)")
    p.add_argument(
        "--human",
        action="store_true",
        help="Human-friendly output preset (single header + readable cycle table; implies --quiet unless overridden)",
    )
    p.add_argument(
        "--market-hours-only",
        action="store_true",
        help="Skip cycles when market is closed (sets G6_LOOP_MARKET_HOURS=1)",
    )
    p.add_argument(
        "--force-market-open",
        "--force-open",
        action="store_true",
        help="Bypass market-hours gating (sets G6_FORCE_MARKET_OPEN=1)",
    )
    p.add_argument(
        "--force-market-open-if-next-open-gt-minutes",
        type=float,
        default=None,
        metavar="MINUTES",
        help=(
            "Bypass market-hours gating only when the next market open is more than MINUTES away "
            "(sets G6_FORCE_MARKET_OPEN_IF_NEXT_OPEN_GT_MINUTES). Example: 120"
        ),
    )
    # Interactive market prompt is enabled by default for operator ergonomics.
    # You can disable it explicitly (useful for non-interactive runs).
    g_prompt = p.add_mutually_exclusive_group()
    g_prompt.add_argument(
        "--interactive-market-prompt",
        action="store_true",
        help="(Default) When market is closed, prompt in terminal to force-open for this run",
    )
    g_prompt.add_argument(
        "--no-interactive-market-prompt",
        action="store_true",
        help="Disable the interactive market-closed prompt",
    )
    p.add_argument("--cycle-output", choices=("pretty", "raw", "both"), default=None, help="Override cycle output mode (G6_CYCLE_OUTPUT)")
    p.add_argument("--cycle-style", choices=("legacy", "readable"), default=None, help="Override cycle style (G6_CYCLE_STYLE)")
    p.add_argument("--single-header", action="store_true", help="Emit daily header once (sets G6_SINGLE_HEADER_MODE=1)")
    p.add_argument("--compact-banners", action="store_true", help="Use compact banners (sets G6_COMPACT_BANNERS=1)")
    p.add_argument("--phase-timing", action="store_true", help="Include PHASE_TIMING line in human/quiet output")
    return p.parse_args(argv)

def _load_env_overlay() -> None:
    """Best-effort .env overlay loader.

    Prefer python-dotenv when available; otherwise parse simple KEY=VALUE lines.
    Does not overwrite existing explicit environment variables.
    """
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
        return
    except Exception:
        pass
    env_path = _PROJECT_ROOT / '.env'
    try:
        if env_path.exists():
            for line in env_path.read_text(encoding='utf-8').splitlines():
                s = line.strip()
                if not s or s.startswith('#') or '=' not in s:
                    continue
                k, v = s.split('=', 1)
                k = k.strip(); v = v.strip()
                if k and not EnvConfig.get_str(k, ''):
                    os.environ[k] = v
    except Exception:
        # non-fatal
        pass

def _maybe_auth_preflight() -> bool:
    """Ensure Kite auth token exists; trigger interactive login if missing.

    Returns True if OK to proceed (token present or acquired), False to abort.

    Safeguards:
    - Skips during tests (PYTEST_CURRENT_TEST set)
    - Can be disabled via G6_DISABLE_AUTH_PREFLIGHT=1
    - Runs when KITE_ACCESS_TOKEN missing OR API credentials are incomplete
    """
    if EnvConfig.get_bool('G6_DISABLE_AUTH_PREFLIGHT', False):
        return True
    if EnvConfig.get_str('PYTEST_CURRENT_TEST', ''):
        return True
    # Load any .env first so we detect keys if present
    _load_env_overlay()
    have_key = bool(EnvConfig.get_str('KITE_API_KEY', ''))
    have_secret = bool(EnvConfig.get_str('KITE_API_SECRET', ''))
    have_token = bool(EnvConfig.get_str('KITE_ACCESS_TOKEN', ''))
    if have_token:
        return True  # already authenticated
    # If credentials are missing or token absent, launch token manager (it will prompt and persist to .env)
    if not (have_key and have_secret):
        logger.info('Kite credentials missing; launching token manager to capture API key/secret and token...')
    else:
        logger.info('Kite token missing; launching login flow (token manager)...')
    # Invoke token manager in no-autorun mode to just acquire token
    cmd = [sys.executable, '-m', 'src.tools.token_manager', '--no-autorun']
    try:
        rc = os.spawnv(os.P_WAIT, sys.executable, cmd)  # type: ignore[arg-type]
    except Exception:
        # Fallback to subprocess if spawnv not applicable on platform
        import subprocess  # lazy
        try:
            rc = subprocess.call(cmd)
        except Exception:
            rc = 1
    if int(rc) != 0:
        logger.error('Token manager did not complete successfully (rc=%s)', rc)
        return False
    # Reload env from .env so this process sees the fresh token
    _load_env_overlay()
    # Ensure we now have both creds and token
    if not (EnvConfig.get_str('KITE_API_KEY', '') and EnvConfig.get_str('KITE_API_SECRET', '')):
        logger.error('Credentials still missing after token manager run')
        return False
    if not EnvConfig.get_str('KITE_ACCESS_TOKEN', ''):
        logger.error('Token acquisition reported success but KITE_ACCESS_TOKEN still missing in env')
        return False
    logger.info('Kite token acquired. Continuing startup...')
    return True

def ensure_env(args: argparse.Namespace) -> None:
    # Default presentation preset: match operator screenshot-style console output.
    # This script is an operator-facing runner, so we default to human-friendly,
    # compact, minimal-noise output unless the user explicitly overrides via env/flags.
    os.environ.setdefault("G6_HUMAN_MODE", "1")
    os.environ.setdefault("G6_CONCISE_LOGS", "1")
    os.environ.setdefault("G6_SINGLE_HEADER_MODE", "1")
    os.environ.setdefault("G6_COMPACT_BANNERS", "1")
    os.environ.setdefault("G6_CYCLE_OUTPUT", "pretty")
    os.environ.setdefault("G6_CYCLE_STYLE", "readable")
    os.environ.setdefault("G6_CYCLE_TABLE_COMPACT", "1")
    os.environ.setdefault("G6_CYCLE_TABLE_HEADER_ONCE", "1")
    os.environ.setdefault("G6_PHASE_TIMING_MULTILINE", "1")
    os.environ.setdefault("G6_CONSOLE_SHOW_PHASE_TIMING", "1")
    os.environ.setdefault("G6_HUMAN_SHOW_ATM", "1")
    os.environ.setdefault("G6_HUMAN_SHOW_INDEX_TABLE", "1")
    os.environ.setdefault("G6_HUMAN_HIDE_INDEX_LINES", "1")
    os.environ.setdefault("G6_HUMAN_INDEX_TABLE_MAX_ROWS", "6")
    # Re-print cycle header periodically so logs remain readable mid-scroll.
    os.environ.setdefault("G6_CYCLE_TABLE_HEADER_EVERY", "25")
    # Visual spacing between blocks (cycle row / indices table / phase timing).
    os.environ.setdefault("G6_HUMAN_SPACERS", "1")
    os.environ.setdefault("G6_HUMAN_SPACER_LINES", "1")
    # Keep operator console readable: do not print full Python tracebacks by default.
    os.environ.setdefault("G6_CONSOLE_TRACEBACKS", "0")
    # Append IST timestamp at the end of each cycle.
    os.environ.setdefault("G6_CYCLE_END_IST", "1")

    # Win-win speedup: cache option instrument resolution when strikes/expiry unchanged.
    # Safe because it only reuses results for identical (index, expiry, strikes) and only for a short TTL.
    os.environ.setdefault("G6_INSTRUMENTS_CACHE_TTL_SEC", "900")

    # Win-win speedup: cache option instruments *universe* used to build the expiry map.
    # Bounded and short TTL to avoid memory growth; does not reduce completeness.
    os.environ.setdefault("G6_UNIVERSE_CACHE_TTL_SEC", "300")
    os.environ.setdefault("G6_UNIVERSE_CACHE_MAX_ENTRIES", "8")
    os.environ.setdefault("G6_UNIVERSE_CACHE_MAX_INSTRUMENTS", "200000")

    # Cache the built expiry map too (derived from universe); avoids rebuilding when universe unchanged.
    os.environ.setdefault("G6_EXPIRY_MAP_CACHE_TTL_SEC", "300")

    # NOTE: Avoid defaults that could reduce completeness (e.g., cycle time budgets).
    os.environ.setdefault("G6_CYCLE_SHOW_IST_TS", "1")
    # Default quiet unless user explicitly chose verbose.
    if not getattr(args, 'verbose', False):
        os.environ.setdefault("G6_QUIET_MODE", "1")

    if args.auto_snapshots:
        os.environ.setdefault("G6_AUTO_SNAPSHOTS", "1")
        os.environ.setdefault("G6_SNAPSHOT_CACHE", "1")
    if args.parallel:
        os.environ.setdefault("G6_PARALLEL_INDICES", "1")
    if EnvConfig.get_str("G6_SNAPSHOT_CACHE", '') == "1" or EnvConfig.get_str("G6_CATALOG_HTTP_FORCED", '') == "1":
        os.environ.setdefault("G6_CATALOG_HTTP", "1")
    if args.cycles > 0 and not EnvConfig.get_str("G6_LOOP_MAX_CYCLES", ''):
        os.environ["G6_LOOP_MAX_CYCLES"] = str(args.cycles)

    if args.market_hours_only:
        os.environ.setdefault("G6_LOOP_MARKET_HOURS", "1")

    # Market-hours overrides
    if getattr(args, 'force_market_open', False):
        os.environ["G6_FORCE_MARKET_OPEN"] = "1"
        logger.warning("Market gate override enabled: force market open (G6_FORCE_MARKET_OPEN=1)")
    if getattr(args, 'force_market_open_if_next_open_gt_minutes', None) is not None:
        os.environ["G6_FORCE_MARKET_OPEN_IF_NEXT_OPEN_GT_MINUTES"] = str(args.force_market_open_if_next_open_gt_minutes)
        logger.warning(
            "Market gate override enabled: force market open if next open > %sm (G6_FORCE_MARKET_OPEN_IF_NEXT_OPEN_GT_MINUTES)",
            args.force_market_open_if_next_open_gt_minutes,
        )

    # Interactive prompt default: enabled unless explicitly disabled.
    if not getattr(args, 'no_interactive_market_prompt', False):
        os.environ.setdefault("G6_MARKET_GATE_INTERACTIVE_PROMPT", "1")

    # Presentation preset: human (kept for backward-compat; defaults are already applied above)
    if args.human:
        os.environ.setdefault("G6_HUMAN_MODE", "1")

    if args.phase_timing:
        os.environ["G6_SHOW_PHASE_TIMING"] = "1"
        os.environ.setdefault("G6_CONSOLE_SHOW_PHASE_TIMING", "1")
        os.environ.setdefault("G6_PHASE_TIMING_MULTILINE", "1")

    # Logging mode precedence: quiet > verbose > concise > existing env
    if args.quiet:
        os.environ["G6_CONCISE_LOGS"] = "1"
        os.environ.setdefault("G6_QUIET_MODE", "1")
    elif args.verbose:
        os.environ["G6_CONCISE_LOGS"] = "0"
        os.environ.pop("G6_QUIET_MODE", None)
    elif args.concise:
        os.environ["G6_CONCISE_LOGS"] = "1"
        os.environ.pop("G6_QUIET_MODE", None)

    # Fine-grained cycle output controls
    if args.cycle_output:
        os.environ["G6_CYCLE_OUTPUT"] = str(args.cycle_output)
    if args.cycle_style:
        os.environ["G6_CYCLE_STYLE"] = str(args.cycle_style)
    if args.single_header:
        os.environ["G6_SINGLE_HEADER_MODE"] = "1"
    if args.compact_banners:
        os.environ["G6_COMPACT_BANNERS"] = "1"

    # EnvConfig caches parsed env values; clear it after we mutate env so later
    # EnvConfig.get_* calls (e.g., banner / loop settings) reflect CLI flags.
    try:
        EnvConfig.clear_cache()
    except Exception:
        pass


def _init_logging(args: argparse.Namespace) -> None:
    """Initialize logging consistently across scripts.

    Key goals:
    - Minimal, readable terminal output by default (message-only)
    - Suppress bulky per-expiry / STRUCT / PHASE_TIMING spam in the console
      while preserving full logs for file/diagnostics.
    """
    # In verbose mode, opt out of console suppression.
    if getattr(args, 'verbose', False):
        os.environ.setdefault('G6_VERBOSE_CONSOLE', '1')
        os.environ.setdefault('G6_CONSOLE_SHOW_STRUCT_EVENTS', '1')
        os.environ.setdefault('G6_CONSOLE_SHOW_PHASE_TIMING', '1')
        os.environ.setdefault('G6_CONSOLE_SHOW_EXPIRY_DETAIL', '1')
        os.environ.setdefault('G6_CONSOLE_SHOW_INDEX_DETAIL', '1')
        os.environ.setdefault('G6_CONSOLE_SHOW_PERSIST_FLOW', '1')
        os.environ.setdefault('G6_CONSOLE_SHOW_NO_EXPIRY_WARNINGS', '1')
        os.environ.setdefault('G6_CONSOLE_SHOW_METRICS_GOVERNANCE', '1')

    # If the user didn't request phase timing, keep it hidden on console.
    if getattr(args, 'phase_timing', False):
        os.environ.setdefault('G6_CONSOLE_SHOW_PHASE_TIMING', '1')

    # Silence high-volume structured event spam at the origin for this runner
    # (can be overridden by explicitly setting env before launch).
    if not getattr(args, 'verbose', False):
        os.environ.setdefault(
            'G6_STRUCT_EVENTS_SUPPRESS',
            'instrument_prefilter_summary adaptive_summary option_match_stats strike_cluster',
        )

    try:
        EnvConfig.clear_cache()
    except Exception:
        pass

    level = EnvConfig.get_str('G6_LOG_LEVEL', 'INFO')
    log_file = EnvConfig.get_str('G6_LOG_FILE', 'logs/g6_platform.log')
    setup_logging(level=level, log_file=log_file)


def _apply_presentation_logging() -> None:
    """Deprecated: presentation is now handled by src.utils.logging_utils.setup_logging."""
    return


def build_cycle_fn():
    def _fn(ctx: RuntimeContext):  # unified collectors always active
        run_cycle(ctx)
    return _fn


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    ensure_env(args)

    _init_logging(args)

    # Auth preflight (interactive prompt if Kite token missing)
    if not _maybe_auth_preflight():
        return 2
    try:
        ctx, metrics_stop = bootstrap_runtime(args.config)
    except Exception:
        logger.exception("Bootstrap failed")
        return 2

    # Invoke ordered startup sequence (non-fatal) before loop
    try:
        run_startup_sequence(ctx)
    except Exception:
        logger.exception("Startup sequence encountered an unexpected error (continuing)")

    # Heuristic index params fallback (mirrors run_live)
    try:
        raw_cfg = ctx.config.raw if hasattr(ctx.config, 'raw') else {}
        if ctx.index_params is None:
            idx_params = raw_cfg.get('index_params') or raw_cfg.get('indices') or {}
            if isinstance(idx_params, dict) and idx_params:
                ctx.index_params = idx_params  # type: ignore[assignment]
            else:
                logger.warning("No index_params found in config; cycles may no-op")
    except Exception:
        logger.debug("Index params extraction failed", exc_info=True)

    if args.auto_snapshots and not EnvConfig.get_str('G6_AUTO_SNAPSHOTS', ''):
        os.environ['G6_AUTO_SNAPSHOTS'] = '1'

    cycle_fn = build_cycle_fn()
    # Interval resolution precedence:
    # 1) CLI --interval when provided
    # 2) Env/config via G6Config (G6_LOOP_INTERVAL_SECONDS)
    # 3) Final fallback to 30s
    g6_cfg = get_g6_config(refresh=True)
    if args.interval is not None:
        os.environ['G6_LOOP_INTERVAL_SECONDS'] = str(args.interval)
        try:
            EnvConfig.clear_cache()
        except Exception:
            pass
        g6_cfg = get_g6_config(refresh=True)
    effective_interval = g6_cfg.loop_interval_seconds
    try:
        if not isinstance(effective_interval, (int, float)) or float(effective_interval) <= 0:
            effective_interval = 30.0
    except Exception:
        effective_interval = 30.0
    logger.info(
        "Starting orchestrator loop interval=%.2fs parallel=%s auto_snapshots=%s max_cycles_env=%s",
        effective_interval,
        args.parallel,
        bool(EnvConfig.get_str('G6_AUTO_SNAPSHOTS', '')),
        EnvConfig.get_str('G6_LOOP_MAX_CYCLES', ''),
    )
    # SINGLE_HEADER_MODE: emit daily header once centrally (concise mode expectation)
    if EnvConfig.get_bool('G6_SINGLE_HEADER_MODE', False):
        try:
            import datetime
            # Use timezone-aware UTC date to avoid naive now() (tests forbid naive usage)
            today_str = datetime.datetime.now(datetime.UTC).strftime('%d-%b-%Y')
            if EnvConfig.get_bool('G6_COMPACT_BANNERS', False):
                logger.info("DAILY OPTIONS COLLECTION LOG %s", today_str)
            else:
                header = ("\n" + "="*70 + f"\n        DAILY OPTIONS COLLECTION LOG — {today_str}\n" + "="*70 + "\n")
                logger.info(header)
        except Exception:
            logger.debug('single_header_mode_emit_failed', exc_info=True)

    try:
        run_loop(ctx, cycle_fn=cycle_fn, interval=effective_interval)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received – exiting cleanly (code 0)")
    except Exception:
        logger.exception("Unrecoverable loop exception")
        return 3
    finally:
        # Graceful shutdown: close sinks/providers to stop any background threads (e.g., Influx retries)
        try:
            prov = getattr(ctx, 'providers', None)
            if prov and hasattr(prov, 'close'):
                try:
                    prov.close()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            _csv = getattr(ctx, 'csv_sink', None)
            if _csv is not None and hasattr(_csv, 'close'):
                try:
                    _csv.close()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            _influx = getattr(ctx, 'influx_sink', None)
            if _influx is not None and hasattr(_influx, 'close'):
                try:
                    _influx.close()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if callable(metrics_stop):  # type: ignore[call-arg]
                metrics_stop()
        except Exception:
            pass
    logger.info("Loop complete")
    # Final flush of deferred tables if enabled
    try:
        flush_deferred_cycle_tables()
    except Exception:
        logger.debug('flush_deferred_cycle_tables_failed', exc_info=True)
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
