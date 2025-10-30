#!/usr/bin/env python3
"""weekday_master_batch.py
Batch weekday master generator - processes all historical data collected until today.

This script:
1. Scans all CSV files in data/g6_data/ from earliest to latest date
2. Generates weekday masters for all available trading days
3. Can process specific date ranges or all available data
4. Useful for initial setup or regenerating all masters

Usage:
    # Generate masters from ALL collected data until today
    python scripts/weekday_master_batch.py --all

    # Generate masters for specific date range
    python scripts/weekday_master_batch.py --start 2025-01-01 --end 2025-01-31

    # Generate masters for last N days
    python scripts/weekday_master_batch.py --days 30

    # Specific indices only
    python scripts/weekday_master_batch.py --all --index NIFTY --index BANKNIFTY
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# Ensure repository root is on sys.path
try:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
except Exception:
    pass

# Import from local scripts directory
try:
    from scripts.weekday_overlay import (
        _normalize_indices,
        update_weekday_master,
    )
    INDEX_DEFAULT = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]
except ImportError:
    # Fallback to archived version
    from external.G6_.archived.scripts.weekday_overlay import (  # type: ignore[import-not-found]
        INDEX_DEFAULT,
        _normalize_indices,
        update_weekday_master,
    )
from src.utils.overlay_calendar import is_trading_day
from src.utils.overlay_quality import write_quality_report

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def find_available_dates(base_dir: Path, indices: list[str]) -> list[date]:
    """Scan base_dir to find all dates with CSV data for any index."""
    dates_found: set[date] = set()
    
    for idx in indices:
        idx_dir = base_dir / idx
        if not idx_dir.exists():
            continue
        
        # Scan all expiry_tag directories
        for expiry_dir in idx_dir.iterdir():
            if not expiry_dir.is_dir() or expiry_dir.name == 'overview':
                continue
            
            # Scan all offset directories
            for offset_dir in expiry_dir.iterdir():
                if not offset_dir.is_dir():
                    continue
                
                # Find all YYYY-MM-DD.csv files
                for csv_file in offset_dir.glob("*.csv"):
                    date_str = csv_file.stem  # filename without .csv
                    try:
                        d = datetime.strptime(date_str, '%Y-%m-%d').date()
                        dates_found.add(d)
                    except ValueError:
                        continue
    
    return sorted(dates_found)


def process_batch(
    base_dir: str,
    output_dir: str,
    indices: list[str],
    dates: list[date],
    alpha: float,
    backup: bool = False,
) -> dict[str, Any]:
    """Process a batch of dates and return statistics."""
    
    logger.info("=" * 60)
    logger.info("BATCH WEEKDAY MASTER GENERATION")
    logger.info("=" * 60)
    logger.info("Base directory:   %s", base_dir)
    logger.info("Output directory: %s", output_dir)
    logger.info("Indices:          %s", ', '.join(indices))
    logger.info("Date range:       %s to %s", dates[0], dates[-1])
    logger.info("Total dates:      %s", len(dates))
    logger.info("Alpha (EMA):      %s", alpha)
    logger.info("Backup files:     %s", backup)
    logger.info("=" * 60)
    
    # Ensure output directory exists
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Statistics
    stats = {
        'total_dates_processed': 0,
        'total_dates_skipped': 0,
        'total_updates': 0,
        'dates_with_data': [],
        'dates_without_data': [],
        'issues_by_date': {},
        'issues_by_index': {},
    }
    
    for idx, trade_date in enumerate(dates, 1):
        # Check if trading day
        is_trading = is_trading_day(trade_date)
        weekday_name = trade_date.strftime('%A')
        
        logger.info("")
        logger.info("[%s/%s] Processing %s (%s) %s", idx, len(dates), trade_date, weekday_name, '✓ Trading' if is_trading else '✗ Non-trading')
        
        if not is_trading:
            logger.info("  Skipping non-trading day")
            stats['total_dates_skipped'] += 1
            stats['dates_without_data'].append(str(trade_date))
            continue
        
        date_updates = 0
        date_issues: list[dict] = []
        
        for idx_name in indices:
            try:
                updated = update_weekday_master(
                    base_dir=base_dir,
                    out_root=output_dir,
                    index=idx_name,
                    trade_date=trade_date,
                    alpha=alpha,
                    issues=date_issues,
                    backup=backup,
                )
                
                if updated > 0:
                    logger.info("  %s: %s updates", idx_name, updated)
                    date_updates += updated
                else:
                    logger.debug("  %s: no data", idx_name)
            
            except Exception as e:
                logger.error("  %s: ERROR - %s", idx_name, e)
                date_issues.append({
                    'type': 'processing_error',
                    'index': idx_name,
                    'date': str(trade_date),
                    'error': str(e)
                })
        
        # Update statistics
        stats['total_dates_processed'] += 1
        stats['total_updates'] += date_updates
        
        if date_updates > 0:
            stats['dates_with_data'].append(str(trade_date))
        else:
            stats['dates_without_data'].append(str(trade_date))
        
        if date_issues:
            stats['issues_by_date'][str(trade_date)] = date_issues
            for issue in date_issues:
                idx_name = issue.get('index', 'unknown')
                if idx_name not in stats['issues_by_index']:
                    stats['issues_by_index'][idx_name] = []
                stats['issues_by_index'][idx_name].append(issue)
        
        # Write quality report for this date
        try:
            summary = {
                'indices': indices,
                'base_dir': base_dir,
                'output_dir': output_dir,
                'alpha': alpha,
                'total_updates': date_updates,
                'issues': date_issues,
            }
            report_path = write_quality_report(output_dir, trade_date, weekday_name, summary)
            logger.debug("  Quality report: %s", report_path)
        except Exception as e:
            logger.warning("  Failed to write quality report: %s", e)
    
    return stats


def print_summary(stats: dict[str, Any]) -> None:
    """Print batch processing summary."""
    logger.info("")
    logger.info("=" * 60)
    logger.info("BATCH PROCESSING COMPLETE")
    logger.info("=" * 60)
    logger.info("Total dates processed:    %s", stats['total_dates_processed'])
    logger.info("Dates with data:          %s", len(stats['dates_with_data']))
    logger.info("Dates without data:       %s", len(stats['dates_without_data']))
    logger.info("Dates skipped:            %s", stats['total_dates_skipped'])
    logger.info("Total timestamp updates:  %s", stats['total_updates'])
    logger.info("Total issues:             %s", sum((len(v) for v in stats['issues_by_date'].values())))
    
    if stats['issues_by_index']:
        logger.info("")
        logger.info("Issues by index:")
        for idx, issues in stats['issues_by_index'].items():
            logger.info("  %s: %s issues", idx, len(issues))
    
    if stats['dates_with_data']:
        logger.info("")
        logger.info("Date range with data: %s to %s", stats['dates_with_data'][0], stats['dates_with_data'][-1])
    
    logger.info("=" * 60)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Batch weekday master generator - processes all historical data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate from ALL collected data
  python scripts/weekday_master_batch.py --all

  # Generate for last 30 days
  python scripts/weekday_master_batch.py --days 30

  # Generate for specific date range
  python scripts/weekday_master_batch.py --start 2025-01-01 --end 2025-01-31

  # Specific indices only
  python scripts/weekday_master_batch.py --all --index NIFTY --index BANKNIFTY

  # With backup files (creates .bak files before overwriting)
  python scripts/weekday_master_batch.py --all --backup
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
        help='Index symbol (repeatable). If omitted, processes all default indices.',
    )
    ap.add_argument(
        '--all',
        action='store_true',
        help='Process ALL dates found in base-dir',
    )
    ap.add_argument(
        '--days',
        type=int,
        help='Process last N days (from today backwards)',
    )
    ap.add_argument(
        '--start',
        help='Start date (YYYY-MM-DD) for date range processing',
    )
    ap.add_argument(
        '--end',
        help='End date (YYYY-MM-DD) for date range processing (default: today)',
    )
    ap.add_argument(
        '--alpha',
        type=float,
        default=0.5,
        help='EMA smoothing factor α (0<α<=1). Default: 0.5',
    )
    ap.add_argument(
        '--backup',
        action='store_true',
        help='Create backup files (.bak) before overwriting existing masters',
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
    
    # Validate alpha
    if not (0 < args.alpha <= 1):
        logger.error("Alpha must be in range (0, 1]")
        return 1
    
    # Resolve indices
    indices = _normalize_indices(args.index) if args.index else INDEX_DEFAULT
    
    base_path = Path(args.base_dir)
    if not base_path.exists():
        logger.error("Base directory does not exist: %s", args.base_dir)
        return 1
    
    # Determine date range
    dates_to_process: list[date] = []
    
    if args.all:
        logger.info("Scanning for all available dates...")
        dates_to_process = find_available_dates(base_path, indices)
        if not dates_to_process:
            logger.error("No CSV data found in base directory")
            return 1
        logger.info("Found data for %s dates", len(dates_to_process))
    
    elif args.days:
        end_date = date.today()
        start_date = end_date - timedelta(days=args.days)
        logger.info("Processing last %s days: %s to %s", args.days, start_date, end_date)
        
        # Find available dates in this range
        all_dates = find_available_dates(base_path, indices)
        dates_to_process = [d for d in all_dates if start_date <= d <= end_date]
        
        if not dates_to_process:
            logger.error("No data found for last %s days", args.days)
            return 1
    
    elif args.start or args.end:
        try:
            start_date = datetime.strptime(args.start, '%Y-%m-%d').date() if args.start else date(2020, 1, 1)
            end_date = datetime.strptime(args.end, '%Y-%m-%d').date() if args.end else date.today()
        except ValueError as e:
            logger.error("Invalid date format: %s", e)
            return 1
        
        if start_date > end_date:
            logger.error("Start date must be before or equal to end date")
            return 1
        
        logger.info("Processing date range: %s to %s", start_date, end_date)
        
        # Find available dates in this range
        all_dates = find_available_dates(base_path, indices)
        dates_to_process = [d for d in all_dates if start_date <= d <= end_date]
        
        if not dates_to_process:
            logger.error("No data found in date range %s to %s", start_date, end_date)
            return 1
    
    else:
        logger.error("Must specify one of: --all, --days N, or --start/--end")
        logger.error("Use --help for usage examples")
        return 1
    
    # Process the batch
    try:
        stats = process_batch(
            base_dir=args.base_dir,
            output_dir=args.output_dir,
            indices=indices,
            dates=dates_to_process,
            alpha=args.alpha,
            backup=args.backup,
        )
        
        # Print summary
        print_summary(stats)
        
        return 0
    
    except Exception as e:
        logger.error("Batch processing failed: %s", e, exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
