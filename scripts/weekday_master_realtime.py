#!/usr/bin/env python3
"""weekday_master_realtime.py
Real-time weekday master builder - runs continuously during market hours.

This script:
1. Monitors for new CSV data being written to data/g6_data/
2. Updates weekday masters in real-time as data arrives
3. Ensures masters are always up-to-date during trading hours
4. Emits metrics for monitoring

Usage:
    python scripts/weekday_master_realtime.py
    python scripts/weekday_master_realtime.py --interval 60  # update every 60 seconds
    python scripts/weekday_master_realtime.py --market-hours-only  # only run during market hours
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, time as dt_time
from pathlib import Path
from typing import Any

from zoneinfo import ZoneInfo

# Ensure repository root is on sys.path
try:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
except Exception:
    pass

from external.G6_.archived.scripts.weekday_overlay import (  # type: ignore[import-not-found]
    INDEX_DEFAULT,
    _normalize_indices,
    update_weekday_master,
)
from src.metrics import get_metrics_singleton
from src.utils.overlay_calendar import is_trading_day
from src.utils.timeutils import get_market_session_bounds

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def is_market_hours(now: datetime, open_time: dt_time, close_time: dt_time) -> bool:
    """Check if current time is within market hours."""
    current_time = now.time()
    return open_time <= current_time <= close_time


def load_config(config_path: str | None) -> dict[str, Any]:
    """Load platform configuration."""
    if not config_path or not Path(config_path).exists():
        return {}
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to load config %s: %s", config_path, e)
        return {}


def run_realtime_builder(
    base_dir: str,
    output_dir: str,
    indices: list[str],
    alpha: float,
    interval: int,
    market_hours_only: bool,
    market_open: str | None,
    market_close: str | None,
) -> None:
    """Run the real-time weekday master builder."""
    
    logger.info("=" * 60)
    logger.info("REAL-TIME WEEKDAY MASTER BUILDER STARTING")
    logger.info("=" * 60)
    logger.info("Base directory:   %s", base_dir)
    logger.info("Output directory: %s", output_dir)
    logger.info("Indices:          %s", ', '.join(indices))
    logger.info("Alpha (EMA):      %s", alpha)
    logger.info("Update interval:  %ss", interval)
    logger.info("Market hours only: %s", market_hours_only)
    logger.info("=" * 60)
    
    # Ensure output directory exists
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Metrics
    metrics = get_metrics_singleton()
    if metrics:
        logger.info("Metrics enabled - will emit to Prometheus")
    
    # Timezone
    tz = ZoneInfo("Asia/Kolkata")
    
    update_count = 0
    last_update_date: date | None = None
    issues: list[dict] = []
    
    try:
        while True:
            now = datetime.now(tz)
            today = now.date()
            
            # Check if it's a trading day
            if not is_trading_day(today):
                if market_hours_only:
                    logger.info("Non-trading day (%s) - sleeping %ss", today, interval)
                    time.sleep(interval)
                    continue
                else:
                    logger.warning("Non-trading day (%s) but processing anyway", today)
            
            # Get market hours for today
            try:
                start_dt, end_dt = get_market_session_bounds(today)
                open_time = start_dt.time()
                close_time = end_dt.time()
            except Exception:
                # Fallback to default Indian market hours
                open_time = dt_time(9, 15, 30)
                close_time = dt_time(15, 30, 0)
            
            # Check if we're in market hours
            in_market_hours = is_market_hours(now, open_time, close_time)
            
            if market_hours_only and not in_market_hours:
                logger.info(
                    "Outside market hours (%s - %s) - sleeping %ss", open_time, close_time, interval
                    f"- sleeping {interval}s"
                )
                time.sleep(interval)
                continue
            
            # New day detection - clear issues list
            if last_update_date != today:
                logger.info("New trading day: %s", today)
                issues.clear()
                last_update_date = today
            
            # Run update for all indices
            logger.info("[%s] Updating weekday masters...", now)
            cycle_start = time.time()
            cycle_updates = 0
            
            for idx in indices:
                try:
                    idx_issues: list[dict] = []
                    updated = update_weekday_master(
                        base_dir=base_dir,
                        out_root=output_dir,
                        index=idx,
                        trade_date=today,
                        alpha=alpha,
                        issues=idx_issues,
                        backup=False,  # Don't create backups in real-time mode
                        market_open=str(open_time),
                        market_close=str(close_time),
                    )
                    cycle_updates += updated
                    
                    if updated > 0:
                        logger.info("  %s: updated %s timestamp(s)", idx, updated)
                    
                    # Track issues
                    if idx_issues:
                        issues.extend(idx_issues)
                        if metrics:
                            for issue in idx_issues:
                                try:
                                    itype = issue.get('type', 'unknown')
                                    metrics.data_errors_labeled.labels(  # type: ignore
                                        index=idx,
                                        component='weekday_realtime',
                                        error_type=str(itype)
                                    ).inc()
                                except Exception:
                                    pass
                
                except Exception as e:
                    logger.error("  %s: ERROR - %s", idx, e)
                    if metrics:
                        try:
                            metrics.data_errors_labeled.labels(  # type: ignore
                                index=idx,
                                component='weekday_realtime',
                                error_type='exception'
                            ).inc()
                        except Exception:
                            pass
            
            cycle_duration = time.time() - cycle_start
            update_count += cycle_updates
            
            # Log summary
            if cycle_updates > 0:
                logger.info(
                    "✓ Cycle complete: %s updates in %ss (total: %s)", cycle_updates, cycle_duration, update_count
                    f"(total: {update_count})"
                )
            else:
                logger.debug(
                    "Cycle complete: no new data (%ss)", cycle_duration
                )
            
            # Emit metrics
            if metrics:
                try:
                    metrics.overlay_quality_last_report_unixtime.set(time.time())  # type: ignore
                    metrics.overlay_quality_last_run_total_issues.set(len(issues))  # type: ignore
                except Exception:
                    pass
            
            # Sleep until next interval
            time.sleep(interval)
    
    except KeyboardInterrupt:
        logger.info("\n" + "=" * 60)
        logger.info("SHUTTING DOWN (Ctrl+C received)")
        logger.info("Total updates: %s", update_count)
        logger.info("Total issues:  %s", len(issues))
        logger.info("=" * 60)
    
    except Exception as e:
        logger.error("FATAL ERROR: %s", e, exc_info=True)
        raise


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Real-time weekday master builder - continuously updates masters during market hours",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with defaults (60s interval, all indices)
  python scripts/weekday_master_realtime.py

  # Update every 30 seconds
  python scripts/weekday_master_realtime.py --interval 30

  # Only run during market hours (stops updating after market close)
  python scripts/weekday_master_realtime.py --market-hours-only

  # Specific indices only
  python scripts/weekday_master_realtime.py --index NIFTY --index BANKNIFTY

  # Custom directories
  python scripts/weekday_master_realtime.py --base-dir data/g6_data --output-dir data/weekday_master
        """
    )
    
    ap.add_argument(
        '--base-dir',
        default='data/g6_data',
        help='Root of per-offset CSV data (CsvSink output)',
    )
    ap.add_argument(
        '--output-dir',
        default='data/weekday_master',
        help='Root directory for weekday master overlays',
    )
    ap.add_argument(
        '--index',
        action='append',
        help='Index symbol (repeatable). If omitted and --all not used, defaults to all indices.',
    )
    ap.add_argument(
        '--all',
        action='store_true',
        help='Process all default indices (default behavior if no --index specified)',
    )
    ap.add_argument(
        '--config',
        help='Path to platform config JSON (to auto-discover directories and alpha)',
    )
    ap.add_argument(
        '--alpha',
        type=float,
        help='EMA smoothing factor α (0<α<=1). Default: 0.5',
    )
    ap.add_argument(
        '--interval',
        type=int,
        default=60,
        help='Update interval in seconds (default: 60)',
    )
    ap.add_argument(
        '--market-hours-only',
        action='store_true',
        help='Only update during market hours (9:15 AM - 3:30 PM IST)',
    )
    ap.add_argument(
        '--market-open',
        help='Override market open time (HH:MM:SS)',
    )
    ap.add_argument(
        '--market-close',
        help='Override market close time (HH:MM:SS)',
    )
    ap.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging (DEBUG level)',
    )
    
    args = ap.parse_args()
    
    # Configure logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Load config if provided
    cfg = load_config(args.config)
    
    # Resolve base directory
    base_dir = args.base_dir
    if args.base_dir == 'data/g6_data' and cfg:
        base_dir = cfg.get('storage', {}).get('csv_dir', base_dir)
    
    # Resolve output directory
    output_dir = args.output_dir
    overlay_cfg = cfg.get('overlays', {}).get('weekday', {})
    if args.output_dir == 'data/weekday_master' and overlay_cfg.get('output_dir'):
        output_dir = overlay_cfg['output_dir']
    
    # Resolve alpha
    alpha = args.alpha if args.alpha is not None else overlay_cfg.get('alpha', 0.5)
    if not (0 < alpha <= 1):
        logger.error("Alpha must be in range (0, 1]")
        return 1
    
    # Resolve indices
    indices = _normalize_indices(args.index if not args.all else INDEX_DEFAULT)
    
    # Validate interval
    if args.interval < 1:
        logger.error("Interval must be at least 1 second")
        return 1
    
    # Run the builder
    try:
        run_realtime_builder(
            base_dir=base_dir,
            output_dir=output_dir,
            indices=indices,
            alpha=alpha,
            interval=args.interval,
            market_hours_only=args.market_hours_only,
            market_open=args.market_open,
            market_close=args.market_close,
        )
        return 0
    except Exception as e:
        logger.error("Failed to run real-time builder: %s", e)
        return 1


if __name__ == '__main__':
    sys.exit(main())
