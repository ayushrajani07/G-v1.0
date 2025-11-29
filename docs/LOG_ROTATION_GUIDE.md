# Debug Log Rotation Guide

**Effective Date:** November 21, 2025  
**Feature:** Automatic daily log rotation for debug logs

---

## Overview

Debug logs now **automatically rotate daily at midnight**, eliminating the need for manual log management and preventing a single log file from growing indefinitely.

## How It Works

### Automatic Rotation Schedule

- **Rotation Time:** Midnight (00:00) local time
- **Frequency:** Daily
- **Retention:** Last 7 days (configurable)
- **Naming Convention:** `debug.log.YYYY-MM-DD`

### File Naming Pattern

```
logs/
├── debug.log              ← Current day (active)
├── debug.log.2025-11-21   ← Yesterday
├── debug.log.2025-11-20   ← 2 days ago
├── debug.log.2025-11-19   ← 3 days ago
├── debug.log.2025-11-18   ← 4 days ago
├── debug.log.2025-11-17   ← 5 days ago
├── debug.log.2025-11-16   ← 6 days ago
└── debug.log.2025-11-15   ← 7 days ago (deleted tomorrow)
```

## Benefits

1. **Automatic Management:** No manual intervention required
2. **Predictable Sizes:** Each day starts with a fresh log
3. **Easy Analysis:** Logs organized by date
4. **Space Control:** Old logs automatically cleaned up
5. **Performance:** Smaller files = faster searches

## Configuration

### Current Settings

```python
# File: src/utils/logging_utils.py
TimedRotatingFileHandler(
    debug_file,
    when='midnight',      # Rotate at midnight
    interval=1,           # Every 1 day
    backupCount=7,        # Keep last 7 days
    encoding='utf-8',
    utc=False             # Use local time
)
```

### Customization Options

#### Change Retention Period

Edit `src/utils/logging_utils.py` line ~138:

```python
# Keep 14 days instead of 7
backupCount=14

# Keep 30 days
backupCount=30

# Keep only 3 days (for disk space savings)
backupCount=3
```

#### Change Rotation Frequency

```python
# Rotate every hour (for high-volume testing)
when='H', interval=1

# Rotate every week
when='W0'  # W0=Monday, W6=Sunday

# Rotate every midnight (default)
when='midnight', interval=1
```

#### Use UTC Time

```python
utc=True  # Rotate at midnight UTC instead of local time
```

## Usage Examples

### View All Debug Logs

```powershell
# List all debug log files with sizes
Get-ChildItem "logs\debug.log*" | 
    Select-Object Name, 
        @{Name="SizeMB";Expression={[math]::Round($_.Length/1MB, 2)}},
        LastWriteTime |
    Sort-Object LastWriteTime -Descending

# Total disk usage
$totalMB = (Get-ChildItem "logs\debug.log*" | 
    Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host "Total debug logs: $([math]::Round($totalMB, 2)) MB"
```

### Search Across Multiple Days

```powershell
# Search today's log
Select-String -Path "logs\debug.log" -Pattern "ERROR"

# Search yesterday's log
Select-String -Path "logs\debug.log.2025-11-20" -Pattern "ERROR"

# Search all debug logs (last 7 days)
Get-ChildItem "logs\debug.log*" | 
    Select-String -Pattern "ERROR" |
    Select-Object Filename, LineNumber, Line
```

### Archive Old Logs

```powershell
# Compress logs older than 3 days
$cutoffDate = (Get-Date).AddDays(-3)
Get-ChildItem "logs\debug.log.20*" | 
    Where-Object { $_.LastWriteTime -lt $cutoffDate } |
    Compress-Archive -DestinationPath "logs\archive\debug_archive_$(Get-Date -Format 'yyyyMMdd').zip" -Update

# Delete original files after compression (optional)
Get-ChildItem "logs\debug.log.20*" | 
    Where-Object { $_.LastWriteTime -lt $cutoffDate } |
    Remove-Item
```

### Force Immediate Rotation (Testing)

```powershell
# Manually trigger rotation (for testing)
# This renames the current log file
Move-Item "logs\debug.log" "logs\debug.log.$(Get-Date -Format 'yyyy-MM-dd-HHmmss')"

# Next log write will create a new debug.log
```

## Monitoring

### Check Rotation Status

```powershell
# View current log file age
$currentLog = Get-Item "logs\debug.log" -ErrorAction SilentlyContinue
if ($currentLog) {
    $age = (Get-Date) - $currentLog.CreationTime
    Write-Host "Current log age: $($age.TotalHours.ToString('F1')) hours"
    Write-Host "Size: $([math]::Round($currentLog.Length/1MB, 2)) MB"
} else {
    Write-Host "No current debug.log (will be created on next log write)"
}

# Count rotated files
$rotatedCount = (Get-ChildItem "logs\debug.log.20*" -ErrorAction SilentlyContinue).Count
Write-Host "Rotated log files: $rotatedCount"
```

### Verify Rotation Worked

```powershell
# Check if rotation happened overnight
$today = Get-Date -Format "yyyy-MM-dd"
$yesterday = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd")

if (Test-Path "logs\debug.log.$yesterday") {
    Write-Host "✓ Rotation successful - yesterday's log exists"
} else {
    Write-Host "✗ No rotated log from yesterday (check if system was running)"
}
```

## Troubleshooting

### Rotation Not Happening

**Symptoms:** `debug.log` keeps growing, no dated files created

**Causes & Solutions:**

1. **System Not Running at Midnight**
   - Rotation only happens if the application is running when midnight occurs
   - Solution: Ensure the platform runs continuously, or logs will rotate on next startup

2. **Permissions Issue**
   - Handler can't create new files
   - Solution: Check write permissions on `logs/` directory

3. **Handler Not Initialized**
   - Old code still using basic FileHandler
   - Solution: Verify `setup_development()` or `setup_logging()` is called

### Old Logs Not Deleted

**Symptoms:** More than 7 dated log files exist

**Causes & Solutions:**

1. **Manual Files Mixed In**
   - Manually created files don't follow cleanup rules
   - Solution: Use consistent naming pattern `debug.log.YYYY-MM-DD`

2. **BackupCount Too High**
   - Check if `backupCount` was increased
   - Solution: Adjust `backupCount` in `logging_utils.py`

### Missing Log Files

**Symptoms:** Expected dated files don't exist

**Causes:**

1. Application wasn't running on those dates
2. Logs were manually deleted
3. Rotation hadn't started yet on those dates

## Performance Impact

**Before Daily Rotation:**
- Single 350 MB log file
- Slow to open/search
- Risk of running out of disk space

**After Daily Rotation:**
- Maximum ~50 MB per file (typical daily growth)
- Fast to open/search individual files
- Automatic space management

**Typical Disk Usage:**
```
7 days × 50 MB/day = ~350 MB total
(Same space, but organized and auto-managed)
```

## Integration with Existing Tools

### Grafana Loki (Future)

Daily rotation makes it easier to ingest logs into Loki:

```yaml
# Loki scrape config (future enhancement)
scrape_configs:
  - job_name: g6_debug
    static_configs:
      - targets:
          - localhost
        labels:
          job: g6_debug
          __path__: /path/to/logs/debug.log*
```

### Log Aggregation

Tools like `logstash` or `filebeat` can now process complete day-files:

```yaml
# Filebeat config example
filebeat.inputs:
  - type: log
    paths:
      - /path/to/logs/debug.log*
    fields:
      app: g6
      log_type: debug
```

## Migration Notes

### For Existing Deployments

**No action required.** The change is backward compatible:

1. Existing `debug.log` will continue to be used
2. At next midnight, it will be renamed to `debug.log.YYYY-MM-DD`
3. A new `debug.log` will start
4. After 7 days, the oldest rotated file will be deleted

### For Large Existing Log Files

If you have a very large existing `debug.log` (e.g., 350+ MB):

**Option 1: Let it rotate naturally**
```powershell
# Just wait - it will rotate tonight at midnight
# The large file will become debug.log.YYYY-MM-DD
```

**Option 2: Manual rotation now**
```powershell
# Rotate immediately
Move-Item "logs\debug.log" "logs\debug.log.$(Get-Date -Format 'yyyy-MM-dd')"

# Or compress it first
Compress-Archive -Path "logs\debug.log" -DestinationPath "logs\archive\debug_large.zip"
Remove-Item "logs\debug.log"
```

## FAQ

**Q: What happens if the application restarts before midnight?**  
A: The current `debug.log` continues to be used. Rotation only happens at midnight.

**Q: Can I change the rotation time from midnight?**  
A: Yes, modify the `when` parameter. See "Customization Options" above.

**Q: Will this affect production logs (ops.jsonl)?**  
A: No, this only affects debug logs. Ops logs use a different handler (not currently rotated).

**Q: What if I want to keep logs longer than 7 days?**  
A: Increase `backupCount` in `logging_utils.py` or manually archive old logs before they're deleted.

**Q: Can I disable rotation and go back to a single file?**  
A: Yes, edit `logging_utils.py` and replace `TimedRotatingFileHandler` with the original `FileHandler`.

**Q: Does rotation cause log loss?**  
A: No, logs are renamed (not deleted) during rotation. No data is lost.

---

## Summary

Daily log rotation provides:
- ✅ Automatic log management
- ✅ Predictable file sizes
- ✅ Easy date-based analysis
- ✅ Automatic cleanup
- ✅ Better performance
- ✅ Zero manual intervention

**Next Steps:**
- Monitor rotation over the next week
- Adjust `backupCount` if needed
- Consider implementing ops log rotation
- Set up automated compression for long-term archival
