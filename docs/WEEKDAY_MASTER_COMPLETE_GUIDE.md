# Weekday Master System - Complete User Guide

## Overview

The **Weekday Master System** maintains aggregated intraday statistics for each index across multiple weekdays. This guide covers all three complementary approaches to ensure reliable, accurate weekday master files.

### The Three-System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  WEEKDAY MASTER ECOSYSTEM                    │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  1. BATCH GENERATOR (Initial Setup)                          │
│     └─> Processes ALL historical CSV data                    │
│         • One-time use or full rebuilds                       │
│         • Scans entire data/g6_data directory                 │
│         • Generates complete weekday masters from scratch     │
│                                                               │
│  2. REAL-TIME BUILDER (Market Hours)                          │
│     └─> Continuous updates during trading                    │
│         • Runs 9:15 AM - 3:30 PM IST (market hours)          │
│         • Updates every 60 seconds                            │
│         • Live monitoring with Prometheus metrics             │
│                                                               │
│  3. EOD UPDATER (After Market Close)                          │
│     └─> Final validation and reporting                       │
│         • Runs automatically at 4:00 PM (Task Scheduler)     │
│         • Comprehensive quality reports                       │
│         • Prerequisites validation                            │
│         • Error detection and metrics                         │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## System 1: Batch Generator

**Script:** `scripts/weekday_master_batch.py` (394 lines)  
**Purpose:** Initial setup and historical data processing  
**Use When:** First-time setup, full rebuilds, or processing historical data

### Key Features

- **Automatic Date Discovery**: Scans `data/g6_data` to find all available dates
- **Multiple Processing Modes**:
  - `--all`: Process all available historical data
  - `--days N`: Process last N days
  - `--start/--end`: Process specific date range
- **Progress Tracking**: Real-time updates with completion percentage
- **Comprehensive Summary**: Statistics per index and overall metrics

### Quick Start

```powershell
# Process ALL historical data (recommended for initial setup)
python scripts/weekday_master_batch.py --all

# Process last 30 days
python scripts/weekday_master_batch.py --days 30

# Process specific date range
python scripts/weekday_master_batch.py --start 2025-10-01 --end 2025-10-24

# Dry run to see what would be processed
python scripts/weekday_master_batch.py --all --dry-run
```

### VS Code Tasks

- **"Weekday Master: Batch Generate (all data)"** - Process all historical dates
- **"Weekday Master: Batch Generate (last 30 days)"** - Quick recent history update

### When to Use

✅ **DO USE** for:
- Initial project setup
- Rebuilding weekday masters from scratch
- Recovering from data corruption
- Processing historical data collected while system was offline

❌ **DON'T USE** for:
- Daily updates (use EOD system instead)
- Live updates during trading (use Real-time system instead)

### Output

Creates/updates files in `data/weekday_master/`:
```
NIFTY_MONDAY.csv
NIFTY_TUESDAY.csv
...
BANKNIFTY_MONDAY.csv
...
```

### Example Output

```
╔════════════════════════════════════════════════════════════════╗
║          Weekday Master Batch Generator - Summary              ║
╠════════════════════════════════════════════════════════════════╣
║ Processed 45 dates in 12.34 seconds (3.65 dates/sec)          ║
╠════════════════════════════════════════════════════════════════╣
║ Index          │ Dates  │ Updates │ Avg per Date │ Skipped    ║
╠════════════════════════════════════════════════════════════════╣
║ NIFTY          │   45   │   180   │    4.00      │     0      ║
║ BANKNIFTY      │   45   │   180   │    4.00      │     0      ║
║ FINNIFTY       │   42   │   168   │    4.00      │     3      ║
║ SENSEX         │   38   │   152   │    4.00      │     7      ║
╚════════════════════════════════════════════════════════════════╝
```

---

## System 2: Real-Time Builder

**Script:** `scripts/weekday_master_realtime.py` (258 lines)  
**Purpose:** Continuous updates during market hours  
**Use When:** Live trading hours to ensure masters stay current

### Key Features

- **Market Hours Awareness**: Automatically runs only during 9:15 AM - 3:30 PM IST
- **Configurable Update Interval**: Default 60 seconds (adjustable)
- **Prometheus Metrics**: Real-time monitoring via metrics
- **Graceful Shutdown**: Ctrl+C to stop cleanly
- **Prerequisites Validation**: Checks directories and data availability

### Quick Start

```powershell
# Start real-time builder (market hours only, 60s interval)
python scripts/weekday_master_realtime.py --market-hours-only --interval 60

# Run continuously (even outside market hours)
python scripts/weekday_master_realtime.py --interval 60

# Custom interval (30 seconds)
python scripts/weekday_master_realtime.py --market-hours-only --interval 30
```

### PowerShell Wrapper

```powershell
# Easy launcher with defaults
.\scripts\start_weekday_master_realtime.ps1 -MarketHoursOnly -Interval 60
```

### VS Code Tasks

- **"Weekday Master: Start Real-time Builder (market hours)"** - Auto-stops outside market hours
- **"Weekday Master: Start Real-time Builder (continuous)"** - Runs 24/7

### Workflow

```
1. Start before market open (e.g., 9:00 AM)
   └─> Waits until 9:15 AM to begin updates

2. During market hours (9:15 AM - 3:30 PM)
   └─> Updates every 60 seconds
   └─> Emits metrics to Prometheus (port 8000)
   └─> Shows live progress in console

3. After market close (3:30 PM)
   └─> Automatically stops (if --market-hours-only)
   └─> Wait for EOD system to run final update
```

### Prometheus Metrics

Exposed on `http://localhost:8000/metrics`:

```
# Number of updates processed
weekday_master_updates_total{index="NIFTY"}

# Last update timestamp (Unix epoch)
weekday_master_last_update_timestamp{index="NIFTY"}

# Processing duration in seconds
weekday_master_processing_duration_seconds
```

### Example Output

```
[2025-10-25 09:30:15] ✓ Updated NIFTY (FRIDAY): 185 rows
[2025-10-25 09:30:15] ✓ Updated BANKNIFTY (FRIDAY): 185 rows
[2025-10-25 09:30:15] ✓ Updated FINNIFTY (FRIDAY): 185 rows
[2025-10-25 09:30:15] ⚠ Skipped SENSEX: no data available

Cycle completed in 0.87s | Next update in 60s
```

### When to Use

✅ **DO USE** for:
- Live trading days
- Ensuring weekday masters stay current
- Testing with live data
- Monitoring data collection in real-time

❌ **DON'T USE** for:
- Initial historical data loading (use Batch instead)
- Automated daily updates (use EOD instead)

---

## System 3: EOD Updater ✨

**Script:** `scripts/eod_weekday_master.py` (385 lines)  
**Purpose:** Automated after-market updates with comprehensive quality reporting  
**Use When:** Daily automated execution at market close

### Key Features

- **Prerequisites Validation**: Checks directories, CSV data availability, detects indices
- **Comprehensive EOD Reports**: JSON files with full statistics and issue categorization
- **Quality Reports**: Technical reports from overlay quality system
- **Prometheus Metrics**: Freshness, issues, duration monitoring
- **Dry-Run Mode**: Test without making changes
- **Force Mode**: Run even if prerequisites fail
- **Automatic Logging**: All output saved to `logs/eod_weekday_YYYY-MM-DD.log`

### Quick Start (Manual)

```powershell
# Update today's data with comprehensive reporting
.\scripts\eod_weekday_master.ps1

# Test without making changes
.\scripts\eod_weekday_master.ps1 -DryRun

# Update specific date
.\scripts\eod_weekday_master.ps1 -Date "2025-10-24"

# Force run even with missing data
.\scripts\eod_weekday_master.ps1 -Force

# Direct Python invocation
python scripts/eod_weekday_master.py --date 2025-10-24 --dry-run
```

### Automated Scheduling

**Setup once, runs daily:**

```powershell
# Setup Windows Task Scheduler (4:00 PM weekdays)
.\scripts\setup_eod_schedule.ps1

# Check if scheduled task is active
.\scripts\setup_eod_schedule.ps1 -ShowStatus

# Change execution time to 5:00 PM
.\scripts\setup_eod_schedule.ps1 -Time "17:00"

# Remove scheduled task
.\scripts\setup_eod_schedule.ps1 -Uninstall
```

**Task Details:**
- **Name**: G6_EOD_Weekday_Master
- **Schedule**: Monday-Friday at 4:00 PM (after market close at 3:30 PM)
- **Log Files**: `logs/eod_weekday_YYYY-MM-DD.log`
- **Reports**: `data/weekday_master/_eod_reports/YYYY-MM-DD_WEEKDAY_eod.json`

### VS Code Tasks

- **"EOD: Weekday Master Update (today)"** - Run EOD update for today
- **"EOD: Weekday Master Update (dry-run)"** - Test run without changes
- **"EOD: Setup Scheduled Task"** - Configure Task Scheduler
- **"EOD: Show Schedule Status"** - Check if automation is active

### EOD Report Structure

**File:** `data/weekday_master/_eod_reports/2025-10-24_FRIDAY_eod.json`

```json
{
  "date": "2025-10-24",
  "weekday": "FRIDAY",
  "timestamp": "2025-10-24T16:00:15+05:30",
  "summary": {
    "total_updates": 4,
    "duration_seconds": 2.34,
    "updates_per_second": 1.71,
    "indices_with_data": ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]
  },
  "updates_by_index": {
    "NIFTY": {"rows_added": 375, "total_rows": 1875},
    "BANKNIFTY": {"rows_added": 375, "total_rows": 1875},
    "FINNIFTY": {"rows_added": 375, "total_rows": 1875},
    "SENSEX": {"rows_added": 375, "total_rows": 1875}
  },
  "issues": {
    "total": 2,
    "critical": 0,
    "warnings": 2,
    "by_type": {
      "missing_data": 0,
      "data_quality": 2,
      "processing_error": 0
    },
    "details": [
      {
        "type": "data_quality",
        "severity": "warning",
        "index": "FINNIFTY",
        "message": "Gap detected in time series: 10:45 - 11:15"
      }
    ]
  },
  "status": "success"  // or "partial" or "failed"
}
```

### Quality Reports

**File:** `data/weekday_master/_quality/overlay_quality_2025-10-24.json`

Technical quality metrics from `src.utils.overlay_quality`:
- Time coverage analysis
- Data gaps detection
- Row count statistics
- Validation status

### Prometheus Metrics

```
# Time since last successful EOD update (seconds)
eod_weekday_master_last_success_age_seconds

# Number of issues found in last run
eod_weekday_master_issues_total{severity="critical"}
eod_weekday_master_issues_total{severity="warning"}

# Processing duration
eod_weekday_master_duration_seconds

# Number of indices updated
eod_weekday_master_indices_updated
```

### Prerequisites Validation

The EOD system checks:

1. **Directory Structure**:
   ```
   ✓ data/g6_data exists
   ✓ data/weekday_master exists
   ✓ data/weekday_master/_eod_reports exists
   ✓ data/weekday_master/_quality exists
   ```

2. **CSV Data Availability**:
   ```
   ✓ Found 1,234 CSV files in data/g6_data
   ✓ Detected indices: NIFTY, BANKNIFTY, FINNIFTY, SENSEX
   ✓ Today's data (2025-10-24): NIFTY, BANKNIFTY (2 indices)
   ```

3. **Date Validation**:
   ```
   ✓ Date is a weekday (FRIDAY)
   ✓ Date is not in the future
   ✓ CSV data exists for this date
   ```

### When to Use

✅ **DO USE** for:
- Daily automated execution after market close
- Final validation and cleanup
- Comprehensive quality reporting
- Scheduled reliability

❌ **DON'T USE** for:
- Live trading hours (use Real-time instead)
- Initial historical data (use Batch instead)

---

## Complete Workflow: Typical Day

### Initial Setup (First Time Only)

```powershell
# Step 1: Process all historical data
python scripts/weekday_master_batch.py --all

# Step 2: Setup automated EOD scheduling
.\scripts\setup_eod_schedule.ps1

# Step 3: Verify everything is configured
.\scripts\setup_eod_schedule.ps1 -ShowStatus
```

### Daily Workflow

#### Morning (Before Market Open - 9:00 AM)

```powershell
# Start real-time builder (optional, for live monitoring)
.\scripts\start_weekday_master_realtime.ps1 -MarketHoursOnly -Interval 60
```

**What happens:**
- Script waits until 9:15 AM (market open)
- Then updates every 60 seconds until 3:30 PM (market close)
- Automatically stops after market close

#### During Market Hours (9:15 AM - 3:30 PM)

- Real-time builder runs automatically
- Updates weekday masters every minute
- Console shows live progress
- Metrics available at `http://localhost:8000/metrics`

#### After Market Close (4:00 PM - Automated)

**Task Scheduler runs EOD system automatically:**

1. Prerequisites validation
2. Final weekday master update
3. EOD report generation
4. Quality report creation
5. Metrics emission
6. Log file saved

**Check results:**
```powershell
# View today's EOD report
cat data\weekday_master\_eod_reports\2025-10-24_FRIDAY_eod.json | ConvertFrom-Json

# View log file
cat logs\eod_weekday_2025-10-24.log

# Check quality report
cat data\weekday_master\_quality\overlay_quality_2025-10-24.json
```

---

## Directory Structure

```
g6_reorganized/
├── data/
│   ├── g6_data/                          # Source CSV files
│   │   ├── NIFTY_2025-10-24.csv
│   │   ├── BANKNIFTY_2025-10-24.csv
│   │   └── ...
│   │
│   └── weekday_master/                   # Output directory
│       ├── NIFTY_MONDAY.csv              # Aggregated weekday files
│       ├── NIFTY_TUESDAY.csv
│       ├── ...
│       ├── _eod_reports/                 # EOD comprehensive reports
│       │   ├── 2025-10-24_FRIDAY_eod.json
│       │   └── ...
│       └── _quality/                     # Technical quality reports
│           ├── overlay_quality_2025-10-24.json
│           └── ...
│
├── logs/                                 # EOD log files
│   ├── eod_weekday_2025-10-24.log
│   └── ...
│
├── scripts/
│   ├── weekday_master_batch.py           # System 1: Batch Generator
│   ├── weekday_master_realtime.py        # System 2: Real-time Builder
│   ├── eod_weekday_master.py             # System 3: EOD Updater
│   ├── eod_weekday_master.ps1            # PowerShell wrapper
│   ├── setup_eod_schedule.ps1            # Task Scheduler setup
│   ├── start_weekday_master_realtime.ps1 # Real-time launcher
│   └── weekday_overlay.py                # Core updater (called by all)
│
└── docs/
    ├── WEEKDAY_MASTER_COMPLETE_GUIDE.md  # This file
    ├── WEEKDAY_MASTER_GUIDE.md           # Batch/Real-time details
    └── EOD_WEEKDAY_MASTER_GUIDE.md       # EOD system details
```

---

## CSV Schema

### Source Files (data/g6_data/)

```csv
timestamp,close,volume,rsi,adx,stochastic,macd,signal,obv,atr,vwap,pivot,r1,s1,r2,s2,r3,s3,stochastic_k,stochastic_d,historical_volatility
09:15:30,23450.25,1234567,55.3,23.4,45.2,12.3,11.8,98765432,45.6,23448.5,23445.0,23500.0,23400.0,23550.0,23350.0,23600.0,23300.0,45.2,43.1,18.5
```

### Weekday Master Files (data/weekday_master/)

```csv
time,close_mean,volume_mean,rsi_mean,adx_mean,stochastic_mean,macd_mean,signal_mean,obv_mean,atr_mean,vwap_mean,pivot_mean,r1_mean,s1_mean,r2_mean,s2_mean,r3_mean,s3_mean,stochastic_k_mean,stochastic_d_mean,historical_volatility_mean,occurrences
09:15:30,23452.15,1245678,54.8,24.1,44.9,12.5,11.9,99123456,45.2,23450.3,23447.2,23502.1,23402.3,23552.5,23352.1,23602.8,23302.5,44.9,43.5,18.3,15
```

**Note:** `occurrences` column indicates how many historical data points contributed to each aggregated row.

---

## Monitoring & Troubleshooting

### Check System Health

```powershell
# 1. Verify directories exist
Test-Path data\g6_data
Test-Path data\weekday_master
Test-Path data\weekday_master\_eod_reports
Test-Path data\weekday_master\_quality

# 2. Check recent CSV data
Get-ChildItem data\g6_data\*_2025-10-*.csv | Select-Object Name, Length, LastWriteTime

# 3. Check weekday master files
Get-ChildItem data\weekday_master\*.csv | Select-Object Name, Length, LastWriteTime

# 4. View latest EOD report
$latest = Get-ChildItem data\weekday_master\_eod_reports\*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1
cat $latest.FullName | ConvertFrom-Json | ConvertTo-Json -Depth 10

# 5. Check Task Scheduler status
.\scripts\setup_eod_schedule.ps1 -ShowStatus
```

### Common Issues

#### Issue: "No CSV data found"

**Cause:** CSV collectors not running or data directory incorrect

**Solution:**
```powershell
# Check if collectors are running
python scripts/dev_tools.py simulate-status --status-file data/runtime_status.json

# Verify CSV files exist
Get-ChildItem data\g6_data\*.csv | Measure-Object
```

#### Issue: "EOD task not running"

**Cause:** Task Scheduler not configured or task disabled

**Solution:**
```powershell
# Check status
.\scripts\setup_eod_schedule.ps1 -ShowStatus

# Reinstall if needed
.\scripts\setup_eod_schedule.ps1 -Uninstall
.\scripts\setup_eod_schedule.ps1
```

#### Issue: "Weekday master file has no data"

**Cause:** No historical data for that weekday yet

**Solution:**
```powershell
# Check how many occurrences (CSV must have dates for that weekday)
cat data\weekday_master\NIFTY_MONDAY.csv | Select-Object -First 5

# If occurrences=0, need more historical data
python scripts/weekday_master_batch.py --days 30
```

#### Issue: "Real-time builder not updating"

**Cause:** Outside market hours or data not being collected

**Solution:**
```powershell
# Force run (ignoring market hours)
python scripts/weekday_master_realtime.py --interval 60

# Check if CSV data is being written
$latest = Get-ChildItem data\g6_data\*.csv | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$latest.LastWriteTime  # Should be recent
```

---

## Performance & Resource Usage

### Batch Generator
- **Speed**: ~3-5 dates/second
- **Memory**: ~100-200 MB
- **Disk I/O**: Moderate (reads all CSVs)
- **Duration**: 30 days ≈ 10 seconds, 365 days ≈ 2 minutes

### Real-Time Builder
- **Speed**: 0.5-2 seconds per update cycle
- **Memory**: ~50-100 MB
- **CPU**: Low (mostly idle between intervals)
- **Network**: None (local filesystem only)

### EOD Updater
- **Speed**: 1-3 seconds for single day
- **Memory**: ~50-100 MB
- **Disk I/O**: Low (single day's CSVs)
- **Duration**: Typically < 5 seconds

---

## Best Practices

### ✅ DO

1. **Setup once, automate daily:**
   - Run batch generator for historical data
   - Setup Task Scheduler for EOD automation
   - Real-time builder is optional for live monitoring

2. **Monitor EOD reports:**
   - Check `data/weekday_master/_eod_reports/` daily
   - Look for `status: "success"`
   - Review issues section for warnings

3. **Keep logs:**
   - EOD logs saved to `logs/eod_weekday_YYYY-MM-DD.log`
   - Archive old logs periodically
   - Check logs if status is "failed"

4. **Test before automation:**
   - Use `--dry-run` mode to test
   - Verify one manual run before scheduling
   - Check Task Scheduler status weekly

5. **Use real-time for development:**
   - Start real-time builder when testing
   - Monitor live metric updates
   - Verify data flows correctly

### ❌ DON'T

1. **Don't run batch generator daily** - Use EOD automation instead
2. **Don't manually edit weekday master CSVs** - Let scripts maintain them
3. **Don't delete _eod_reports or _quality folders** - Historical reporting data
4. **Don't run multiple systems simultaneously on same data** - Can cause conflicts
5. **Don't ignore "failed" status in EOD reports** - Investigate immediately

---

## Integration with Other Systems

### Prometheus Scraping

Add to `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'weekday_master_realtime'
    static_configs:
      - targets: ['localhost:8000']
    scrape_interval: 15s

  - job_name: 'weekday_master_eod'
    static_configs:
      - targets: ['localhost:8000']
    scrape_interval: 60s
```

### Grafana Dashboards

Query examples:

```promql
# Updates per hour by index
rate(weekday_master_updates_total[1h])

# Issues detected today
eod_weekday_master_issues_total{severity="critical"}

# Time since last successful EOD update
eod_weekday_master_last_success_age_seconds / 3600  # Convert to hours
```

### Status Monitoring

```python
# Check if EOD ran successfully today
import json
from pathlib import Path
from datetime import datetime

today = datetime.now().strftime("%Y-%m-%d")
weekday = datetime.now().strftime("%A").upper()
report_file = Path(f"data/weekday_master/_eod_reports/{today}_{weekday}_eod.json")

if report_file.exists():
    with open(report_file) as f:
        report = json.load(f)
        if report["status"] == "success":
            print("✓ EOD update successful")
        else:
            print("⚠ EOD update had issues:", report["issues"]["total"])
else:
    print("✗ EOD report not found - system may not have run")
```

---

## Quick Reference Card

### Commands

```powershell
# ============= BATCH GENERATOR =============
python scripts/weekday_master_batch.py --all                    # Process all history
python scripts/weekday_master_batch.py --days 30               # Last 30 days

# ============= REAL-TIME BUILDER =============
.\scripts\start_weekday_master_realtime.ps1 -MarketHoursOnly   # Market hours only
python scripts/weekday_master_realtime.py --interval 60        # Continuous

# ============= EOD UPDATER =============
.\scripts\eod_weekday_master.ps1                               # Update today
.\scripts\eod_weekday_master.ps1 -DryRun                       # Test run
.\scripts\setup_eod_schedule.ps1                               # Setup automation
.\scripts\setup_eod_schedule.ps1 -ShowStatus                   # Check status

# ============= MONITORING =============
cat data\weekday_master\_eod_reports\2025-10-24_FRIDAY_eod.json  # View EOD report
cat logs\eod_weekday_2025-10-24.log                              # View log
Get-ChildItem data\weekday_master\*.csv                          # List master files
```

### File Locations

| Purpose | Location |
|---------|----------|
| Source CSV data | `data/g6_data/INDEX_YYYY-MM-DD.csv` |
| Weekday masters | `data/weekday_master/INDEX_WEEKDAY.csv` |
| EOD reports | `data/weekday_master/_eod_reports/YYYY-MM-DD_WEEKDAY_eod.json` |
| Quality reports | `data/weekday_master/_quality/overlay_quality_YYYY-MM-DD.json` |
| Log files | `logs/eod_weekday_YYYY-MM-DD.log` |

### System Choice Decision Tree

```
Need to create weekday masters?
│
├─ First time setup? ──> Use BATCH GENERATOR
│
├─ Live trading hours? ──> Use REAL-TIME BUILDER (optional)
│
└─ Daily automation? ──> Use EOD UPDATER (recommended)
```

---

## FAQ

### Q: Do I need to run all three systems?

**A:** No. For most users:
- **Run once:** Batch generator (initial setup)
- **Run daily (automated):** EOD updater
- **Optional:** Real-time builder (for live monitoring)

### Q: What happens if I miss a day?

**A:** The next EOD run will update yesterday's data. Batch generator can also backfill:
```powershell
python scripts/weekday_master_batch.py --start 2025-10-20 --end 2025-10-24
```

### Q: Can I run EOD updater multiple times a day?

**A:** Yes, it's idempotent. Running multiple times on same date just regenerates the same weekday master rows (updates in-place).

### Q: How do I know if automation is working?

**A:** Check three things:
1. Task Scheduler status: `.\scripts\setup_eod_schedule.ps1 -ShowStatus`
2. Today's EOD report exists: `data/weekday_master/_eod_reports/YYYY-MM-DD_WEEKDAY_eod.json`
3. Log file exists: `logs/eod_weekday_YYYY-MM-DD.log`

### Q: What if CSV data is missing for a day?

**A:** System skips that index gracefully. EOD report will show:
```json
"issues": {
  "details": [
    {
      "type": "missing_data",
      "severity": "warning",
      "index": "SENSEX",
      "message": "No CSV data found for 2025-10-24"
    }
  ]
}
```

### Q: How much disk space do weekday masters use?

**A:** Minimal. Each master CSV is ~50-100 KB. For 4 indices × 5 weekdays = 20 files ≈ 2 MB total.

### Q: Can I change the EOD execution time?

**A:** Yes:
```powershell
.\scripts\setup_eod_schedule.ps1 -Time "17:00"  # 5:00 PM
.\scripts\setup_eod_schedule.ps1 -Time "16:30"  # 4:30 PM
```

### Q: What's the difference between EOD report and quality report?

**A:**
- **EOD Report** (`_eod_reports/`): High-level summary for users (status, indices updated, issues)
- **Quality Report** (`_quality/`): Technical validation details (time coverage, gaps, row counts)

### Q: Do I need Prometheus to use these systems?

**A:** No, Prometheus is optional. Systems work standalone. Metrics are bonus for monitoring.

---

## Support & Troubleshooting

### Getting Help

1. **Check documentation:**
   - This guide (complete overview)
   - `docs/WEEKDAY_MASTER_GUIDE.md` (batch/real-time details)
   - `docs/EOD_WEEKDAY_MASTER_GUIDE.md` (EOD system details)

2. **Review logs:**
   - EOD logs: `logs/eod_weekday_YYYY-MM-DD.log`
   - Console output from real-time builder

3. **Check reports:**
   - EOD reports: `data/weekday_master/_eod_reports/*.json`
   - Quality reports: `data/weekday_master/_quality/*.json`

4. **Validate prerequisites:**
   ```powershell
   python scripts/eod_weekday_master.py --dry-run
   ```

### Reporting Issues

When reporting problems, include:
- System used (batch/real-time/EOD)
- Command run
- Error message
- Log file content
- EOD report (if applicable)
- Output from: `Get-ChildItem data\g6_data\*.csv | Measure-Object`

---

## Changelog

### Version 2.0 (October 2025) - Complete System
- Added EOD updater with comprehensive reporting
- Added Task Scheduler automation
- Added PowerShell wrappers for all systems
- Added VS Code tasks integration
- Enhanced documentation

### Version 1.0 (October 2025) - Initial Release
- Batch generator for historical data
- Real-time builder for live updates
- Prometheus metrics integration
- Initial documentation

---

## Appendix A: VS Code Tasks Reference

Access via **Terminal → Run Task...**

### Batch Generator Tasks
- `Weekday Master: Batch Generate (all data)`
- `Weekday Master: Batch Generate (last 30 days)`

### Real-Time Builder Tasks
- `Weekday Master: Start Real-time Builder (market hours)`
- `Weekday Master: Start Real-time Builder (continuous)`

### EOD System Tasks
- `EOD: Weekday Master Update (today)`
- `EOD: Weekday Master Update (dry-run)`
- `EOD: Setup Scheduled Task`
- `EOD: Show Schedule Status`

---

## Appendix B: Algorithm Details

### Aggregation Logic

For each time point (e.g., 09:15:30), weekday masters store:

```python
aggregated_value = mean([
    value_from_monday_1,
    value_from_monday_2,
    value_from_monday_3,
    ...
])
```

**Example:**
```
NIFTY at 09:15:30 on Mondays:
- 2025-10-06: close = 23450.25
- 2025-10-13: close = 23480.50
- 2025-10-20: close = 23500.00

Weekday master (NIFTY_MONDAY.csv):
09:15:30, close_mean = (23450.25 + 23480.50 + 23500.00) / 3 = 23476.92, occurrences = 3
```

### Update Process

1. **Load existing master** (if exists)
2. **Read today's CSV data**
3. **For each timestamp:**
   - Calculate new mean including today's value
   - Increment occurrence count
   - Write updated row
4. **Save master** (atomic tmp → rename)

---

## Summary

You now have a complete, production-ready weekday master system:

✅ **Batch Generator** - Initial setup from all historical data  
✅ **Real-Time Builder** - Live updates during market hours  
✅ **EOD Updater** - Automated daily updates with quality reports  
✅ **Task Scheduler Integration** - Set-and-forget automation  
✅ **Comprehensive Monitoring** - Prometheus metrics, JSON reports, logs  
✅ **VS Code Integration** - Easy access via Tasks menu  

**Next Steps:**
1. Run batch generator for historical data: `python scripts/weekday_master_batch.py --all`
2. Setup EOD automation: `.\scripts\setup_eod_schedule.ps1`
3. Verify status tomorrow: `.\scripts\setup_eod_schedule.ps1 -ShowStatus`

---

*For detailed system-specific documentation, see:*
- *`docs/WEEKDAY_MASTER_GUIDE.md` - Batch/Real-time systems*
- *`docs/EOD_WEEKDAY_MASTER_GUIDE.md` - EOD automation*
