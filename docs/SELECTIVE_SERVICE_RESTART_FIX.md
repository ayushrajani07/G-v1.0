# Selective Service Restart - obs_start_clean.ps1 Fix

**Date:** October 28, 2025  
**Issue:** Script was killing ALL Python processes, affecting unrelated applications  
**Solution:** Modified to selectively kill only observability stack services

## Problem

The original `obs_start_clean.ps1` script used:

```powershell
# BEFORE (Problematic)
$pythonProcs = Get-Process python -ErrorAction SilentlyContinue
if ($pythonProcs) {
    $pythonProcs | Stop-Process -Force -ErrorAction SilentlyContinue
}
```

**Impact:**
- ❌ Killed ALL Python processes on the system
- ❌ Disrupted unrelated Python applications (IDEs, scripts, notebooks)
- ❌ Could terminate long-running data processing tasks
- ❌ Affected VS Code Python extensions, Jupyter servers, etc.

## Solution

Modified to target only the Web API process on the specific port:

```powershell
# AFTER (Selective)
$webApiProcs = Get-NetTCPConnection -LocalPort $WebPort -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -eq 'python' }
} | Select-Object -Unique
if ($webApiProcs) {
    $webApiProcs | Stop-Process -Force -ErrorAction SilentlyContinue
}
```

**Benefits:**
- ✅ Only kills the Web API (uvicorn) listening on port 9500
- ✅ Leaves other Python processes untouched
- ✅ Safe for concurrent Python development
- ✅ Still stops Grafana and Prometheus as intended

## How It Works

### Port-Based Process Discovery

1. **Find process by port:**
   ```powershell
   Get-NetTCPConnection -LocalPort $WebPort -State Listen
   ```
   Returns TCP connections listening on the specified port (9500)

2. **Get the owning process:**
   ```powershell
   Get-Process -Id $_.OwningProcess
   ```
   Retrieves the actual process using that port

3. **Filter for Python:**
   ```powershell
   Where-Object { $_.ProcessName -eq 'python' }
   ```
   Ensures we only stop Python processes (additional safety)

4. **Unique selection:**
   ```powershell
   Select-Object -Unique
   ```
   Removes duplicates if multiple connections exist

### Service Targets

The script now selectively stops:

| Service | Selection Method | Port/Process |
|---------|-----------------|--------------|
| **Web API** | Port-based (9500) | Python (uvicorn) |
| **Grafana** | Process name | grafana-server, grafana |
| **Prometheus** | Process name | prometheus |

## Usage

No changes to script invocation:

```powershell
# Standard usage
.\scripts\obs_start_clean.ps1

# With custom ports
.\scripts\obs_start_clean.ps1 -GrafanaPort 3002 -WebPort 9500 -PrometheusPort 9091

# Open browser after start
.\scripts\obs_start_clean.ps1 -OpenBrowser
```

## Safety Features

1. **Error handling:** All stop operations wrapped in try-catch
2. **Silent failures:** Uses `-ErrorAction SilentlyContinue`
3. **Process verification:** Checks process name after port discovery
4. **Unique filtering:** Prevents duplicate stop attempts
5. **Status reporting:** Shows what was stopped

## Example Output

**Before (killed everything):**
```
Stopping any existing processes...
  Stopped 8 Python process(es)     ← ALL Python processes
  Stopped 1 Grafana process(es)
  Stopped 1 Prometheus process(es)
```

**After (selective):**
```
Stopping observability stack services...
  Stopped Web API (uvicorn on port 9500)    ← Only port 9500
  Stopped Grafana server
  Stopped Prometheus
  Total stopped: 3 process(es)
```

## Other Python Processes Preserved

Examples of Python processes that will **NOT** be killed:

- ✅ VS Code Python Language Server
- ✅ Jupyter Notebook/Lab servers
- ✅ PyCharm debugger
- ✅ Other FastAPI/Flask apps on different ports
- ✅ Data processing scripts
- ✅ Python REPL sessions
- ✅ pytest running tests

## Fallback Behavior

If no process is listening on port 9500:
- No Web API processes are stopped
- Script continues normally
- New Web API starts on the specified port

## Testing

Verify selective stopping:

```powershell
# Start a dummy Python server on another port
Start-Process python -ArgumentList "-m", "http.server", "8000" -WindowStyle Hidden

# Run obs_start_clean.ps1
.\scripts\obs_start_clean.ps1

# Check if dummy server still running
Get-Process python | Where-Object { (Get-NetTCPConnection -OwningProcess $_.Id -ErrorAction SilentlyContinue).LocalPort -eq 8000 }
# Should return the process (not killed)
```

## Related Scripts

Other scripts that already use selective stopping:
- `auto_stack.ps1` - Never killed all Python processes ✓
- `stop_stack.ps1` - Uses port-based termination ✓

## Migration Notes

No action required for users. The script behavior is backward-compatible:
- Same command-line interface
- Same success/failure exit codes
- Same log output format
- Only **more selective** in what it stops

---

**Status:** ✅ Implemented  
**Risk:** Low - more selective = safer  
**Impact:** Prevents disruption of other Python applications  
**Rollback:** Git revert to previous version if needed
