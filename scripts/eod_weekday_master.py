#!/usr/bin/env python3
"""eod_weekday_master.py
End-of-Day automation script for weekday master updates.

This script:
1. Runs at end of trading day (after market close)
2. Updates weekday masters for today's data
3. Generates comprehensive quality reports
4. Emits metrics for monitoring
5. Can be scheduled via Task Scheduler or cron

Usage:
    # Update today's data (default)
    python scripts/eod_weekday_master.py

    # Update specific date
    python scripts/eod_weekday_master.py --date 2025-01-20

    # Dry run (show what would be done)
    python scripts/eod_weekday_master.py --dry-run

    # Force update even if non-trading day
    python scripts/eod_weekday_master.py --force

    # Verbose logging
    python scripts/eod_weekday_master.py --verbose
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta
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
    WEEKDAY_NAMES,
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


def check_prerequisites(base_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Check system prerequisites and return status."""
    status = {
        'base_dir_exists': base_dir.exists(),
        'output_dir_exists': output_dir.exists(),
        'csv_files_count': 0,
        'indices_found': [],
        'errors': []
    }
    
    if not status['base_dir_exists']:
        status['errors'].append(f"Base directory not found: {base_dir}")
        return status
    
    # Count CSV files and find indices
    try:
        for idx_dir in base_dir.iterdir():
            if idx_dir.is_dir() and idx_dir.name in INDEX_DEFAULT:
                status['indices_found'].append(idx_dir.name)
                for expiry_dir in idx_dir.iterdir():
                    if expiry_dir.is_dir() and expiry_dir.name != 'overview':
                        for offset_dir in expiry_dir.iterdir():
                            if offset_dir.is_dir():
                                csv_count = len(list(offset_dir.glob('*.csv')))
                                status['csv_files_count'] += csv_count
    except Exception as e:
        status['errors'].append(f"Error scanning base directory: {e}")
    
    return status


def generate_eod_report(
    trade_date: date,
    indices: list[str],
    updates_by_index: dict[str, int],
    issues: list[dict],
    duration_seconds: float,
    output_dir: Path,
) -> Path:
    """Generate comprehensive EOD report."""
    
    weekday_name = WEEKDAY_NAMES[trade_date.weekday()]
    report_dir = output_dir / '_eod_reports'
    report_dir.mkdir(parents=True, exist_ok=True)
    
    report_path = report_dir / f"{trade_date:%Y-%m-%d}_{weekday_name.upper()}_eod.json"
    
    # Calculate statistics
    total_updates = sum(updates_by_index.values())
    indices_with_data = [idx for idx, count in updates_by_index.items() if count > 0]
    indices_without_data = [idx for idx, count in updates_by_index.items() if count == 0]
    
    # Categorize issues
    critical_issues = [i for i in issues if i.get('type') in {
        'missing_index_root', 'parse_master_error', 'read_error'
    }]
    warning_issues = [i for i in issues if i.get('type') not in {
        'missing_index_root', 'parse_master_error', 'read_error'
    }]
    
    report = {
        'date': str(trade_date),
        'weekday': weekday_name,
        'timestamp': datetime.now(ZoneInfo('Asia/Kolkata')).isoformat(),
        'summary': {
            'total_indices_processed': len(indices),
            'indices_with_data': len(indices_with_data),
            'indices_without_data': len(indices_without_data),
            'total_timestamp_updates': total_updates,
            'duration_seconds': round(duration_seconds, 2),
            'updates_per_second': round(total_updates / max(1, duration_seconds), 2),
        },
        'updates_by_index': updates_by_index,
        'indices_with_data': indices_with_data,
        'indices_without_data': indices_without_data,
        'issues': {
            'total': len(issues),
            'critical': len(critical_issues),
            'warnings': len(warning_issues),
            'by_type': {},
            'details': issues[:100],  # Limit to first 100 for readability
        },
        'status': 'success' if total_updates > 0 and len(critical_issues) == 0 else 'partial' if total_updates > 0 else 'failed'
    }
    
    # Count issues by type
    for issue in issues:
        itype = issue.get('type', 'unknown')
        report['issues']['by_type'][itype] = report['issues']['by_type'].get(itype, 0) + 1
    
    # Write report
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    return report_path


def emit_metrics(
    trade_date: date,
    indices: list[str],
    updates_by_index: dict[str, int],
    issues: list[dict],
    duration_seconds: float,
) -> None:
    """Emit Prometheus metrics for monitoring."""
    try:
        metrics = get_metrics_singleton()
        if not metrics:
            return
        
        # Set EOD run timestamp
        try:
            metrics.overlay_quality_last_report_unixtime.set(time.time())  # type: ignore
        except Exception:
            pass
        
        # Set total issues
        try:
            metrics.overlay_quality_last_run_total_issues.set(len(issues))  # type: ignore
        except Exception:
            pass
        
        # Per-index metrics
        for idx in indices:
            updates = updates_by_index.get(idx, 0)
            idx_issues = [i for i in issues if i.get('index') == idx]
            
            try:
                metrics.overlay_quality_last_run_issues.labels(index=idx).set(len(idx_issues))  # type: ignore
            except Exception:
                pass
            
            # Count critical issues
            critical = len([i for i in idx_issues if i.get('type') in {
                'missing_index_root', 'parse_master_error', 'read_error'
            }])
            try:
                metrics.overlay_quality_last_run_critical.labels(index=idx).set(critical)  # type: ignore
            except Exception:
                pass
            
            # Emit per-issue-type counters
            for issue in idx_issues:
                itype = issue.get('type', 'unknown')
                try:
                    metrics.data_errors_labeled.labels(  # type: ignore
                        index=idx,
                        component='eod_weekday',
                        error_type=str(itype)
                    ).inc()
                except Exception:
                    pass
        
        # EOD-specific metrics
        try:
            # Duration gauge
            if hasattr(metrics, 'eod_weekday_duration_seconds'):
                metrics.eod_weekday_duration_seconds.set(duration_seconds)  # type: ignore
            
            # Success indicator
            if hasattr(metrics, 'eod_weekday_last_success_unixtime'):
                if sum(updates_by_index.values()) > 0:
                    metrics.eod_weekday_last_success_unixtime.set(time.time())  # type: ignore
        except Exception:
            pass
    
    except Exception as e:
        logger.debug("Failed to emit metrics: %s", e)


def run_eod_update(
    trade_date: date,
    base_dir: str,
    output_dir: str,
    indices: list[str],
    alpha: float,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run EOD update for given date."""
    
    logger.info("=" * 60)
    logger.info("END-OF-DAY WEEKDAY MASTER UPDATE")
    logger.info("=" * 60)
    logger.info("Date:       %s", trade_date)
    logger.info("Indices:    %s", ', '.join(indices))
    logger.info("Base dir:   %s", base_dir)
    logger.info("Output dir: %s", output_dir)
    logger.info("Alpha:      %s", alpha)
    logger.info("Dry run:    %s", dry_run)
    logger.info("=" * 60)
    
    # Check prerequisites
    logger.info("Checking prerequisites...")
    prereq = check_prerequisites(Path(base_dir), Path(output_dir))
    
    if prereq['errors']:
        for error in prereq['errors']:
            logger.error(error)
        return {
            'success': False,
            'error': 'Prerequisites check failed',
            'details': prereq
        }
    
    logger.info("✓ Base directory exists: %s", base_dir)
    logger.info("✓ Found %s CSV files", prereq['csv_files_count'])
    logger.info("✓ Found %s indices: %s", len(prereq['indices_found']), ', '.join(prereq['indices_found']))
    
    if dry_run:
        logger.info("")
        logger.info("DRY RUN - No changes will be made")
        logger.info("=" * 60)
        return {
            'success': True,
            'dry_run': True,
            'prerequisites': prereq
        }
    
    # Get market hours
    try:
        start_dt, end_dt = get_market_session_bounds(trade_date)
        market_open = start_dt.strftime('%H:%M:%S')
        market_close = end_dt.strftime('%H:%M:%S')
    except Exception:
        market_open, market_close = '09:15:30', '15:30:00'
    
    logger.info("Market hours: %s - %s", market_open, market_close)
    logger.info("")
    
    # Run updates
    start_time = time.time()
    updates_by_index: dict[str, int] = {}
    all_issues: list[dict] = []
    
    for idx in indices:
        logger.info("Processing %s...", idx)
        idx_issues: list[dict] = []
        
        try:
            updated = update_weekday_master(
                base_dir=base_dir,
                out_root=output_dir,
                index=idx,
                trade_date=trade_date,
                alpha=alpha,
                issues=idx_issues,
                backup=False,
                market_open=market_open,
                market_close=market_close,
            )
            
            updates_by_index[idx] = updated
            all_issues.extend(idx_issues)
            
            if updated > 0:
                logger.info("  ✓ %s: %s timestamps updated", idx, updated)
            else:
                logger.warning("  ⚠ %s: No data found", idx)
            
            if idx_issues:
                logger.warning("  ⚠ %s: %s issues encountered", idx, len(idx_issues))
        
        except Exception as e:
            logger.error("  ✗ %s: ERROR - %s", idx, e)
            updates_by_index[idx] = 0
            all_issues.append({
                'type': 'processing_exception',
                'index': idx,
                'error': str(e),
                'date': str(trade_date)
            })
    
    duration = time.time() - start_time
    total_updates = sum(updates_by_index.values())
    
    # Generate EOD report
    logger.info("")
    logger.info("Generating EOD report...")
    report_path = generate_eod_report(
        trade_date,
        indices,
        updates_by_index,
        all_issues,
        duration,
        Path(output_dir)
    )
    logger.info("✓ EOD report: %s", report_path)
    
    # Emit metrics
    emit_metrics(trade_date, indices, updates_by_index, all_issues, duration)
    
    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("EOD UPDATE COMPLETE")
    logger.info("=" * 60)
    logger.info("Total updates:     %s", total_updates)
    logger.info("Indices with data: %s/%s", len([v for v in updates_by_index.values() if v > 0]), len(indices))
    logger.info("Total issues:      %s", len(all_issues))
    logger.info("Duration:          %ss", duration)
    logger.info("Report:            %s", report_path)
    logger.info("=" * 60)
    
    return {
        'success': total_updates > 0,
        'trade_date': str(trade_date),
        'total_updates': total_updates,
        'updates_by_index': updates_by_index,
        'issues': all_issues,
        'duration_seconds': duration,
        'report_path': str(report_path)
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="End-of-Day weekday master updater with quality reporting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Update today (default)
  python scripts/eod_weekday_master.py

  # Update specific date
  python scripts/eod_weekday_master.py --date 2025-01-20

  # Dry run (check what would be done)
  python scripts/eod_weekday_master.py --dry-run

  # Force update on non-trading day
  python scripts/eod_weekday_master.py --force

  # Verbose logging
  python scripts/eod_weekday_master.py --verbose

  # Specific indices only
  python scripts/eod_weekday_master.py --index NIFTY --index BANKNIFTY

Scheduling:
  Windows Task Scheduler:
    - Run at 16:00 (4:00 PM) IST daily
    - Command: python scripts/eod_weekday_master.py
    - Working directory: <repo_root>

  Linux cron:
    0 16 * * 1-5 cd /path/to/repo && python scripts/eod_weekday_master.py
        """
    )
    
    ap.add_argument(
        '--date',
        help='Trade date (YYYY-MM-DD). Default: today',
    )
    ap.add_argument(
        '--base-dir',
        default='data/g6_data',
        help='Root of per-offset CSV data',
    )
    ap.add_argument(
        '--output-dir',
        default='data/weekday_master',
        help='Root directory for weekday master overlays',
    )
    ap.add_argument(
        '--index',
        action='append',
        help='Index symbol (repeatable). Default: all indices',
    )
    ap.add_argument(
        '--alpha',
        type=float,
        default=0.5,
        help='EMA smoothing factor (0<α<=1). Default: 0.5',
    )
    ap.add_argument(
        '--force',
        action='store_true',
        help='Force update even on non-trading days',
    )
    ap.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes',
    )
    ap.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging',
    )
    
    args = ap.parse_args()
    
    # Configure logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Parse date
    try:
        trade_date = datetime.strptime(args.date, '%Y-%m-%d').date() if args.date else date.today()
    except ValueError as e:
        logger.error("Invalid date format: %s", e)
        return 1
    
    # Check if trading day
    if not is_trading_day(trade_date) and not args.force:
        logger.warning("%s is not a trading day", trade_date)
        logger.warning("Use --force to update anyway")
        return 0
    
    # Validate alpha
    if not (0 < args.alpha <= 1):
        logger.error("Alpha must be in range (0, 1]")
        return 1
    
    # Resolve indices
    indices = _normalize_indices(args.index) if args.index else INDEX_DEFAULT
    
    # Run EOD update
    try:
        result = run_eod_update(
            trade_date=trade_date,
            base_dir=args.base_dir,
            output_dir=args.output_dir,
            indices=indices,
            alpha=args.alpha,
            dry_run=args.dry_run,
        )
        
        if result['success'] or result.get('dry_run'):
            return 0
        else:
            logger.error("EOD update failed - no data processed")
            return 1
    
    except Exception as e:
        logger.error("EOD update failed: %s", e, exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
