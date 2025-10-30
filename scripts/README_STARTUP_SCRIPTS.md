# G6 Observability Stack - Startup Scripts Guide

**Updated:** October 25, 2025  
**Context:** Following Phase 2 optimizations (5 → 2 services)

---

## Current Architecture (2 Services)

After optimization, the G6 stack now consists of only **2 services**:
1. **Grafana** (port 3002) - Visualization
2. **Web API** (port 9500) - JSON API serving live/overlay data

**Removed services:**
- ❌ Prometheus (port 9091) - Not used by dashboards
- ❌ Metrics Server (port 9108) - Deprecated
- ❌ Overlay Exporter (port 9109) - Deprecated

---

## Canonical Startup Script

### ✅ **obs_start_clean.ps1** (RECOMMENDED)

**Purpose:** Start the complete G6 observability stack (Grafana + Web API)  
**Lines:** 203 (clean, focused, well-tested)  
**Status:** Canonical version, actively maintained

**Basic usage:**
```powershell
# Start stack with default settings (requires login)
.\scripts\obs_start_clean.ps1

# Start with anonymous access (no login required)
.\scripts\obs_start_clean.ps1 -GrafanaAllowAnonymous

# Start and open browser
.\scripts\obs_start_clean.ps1 -OpenBrowser

# Custom ports
.\scripts\obs_start_clean.ps1 -GrafanaPort 3000 -WebPort 9501
```

**Parameters:**
- `-GrafanaPort` (default: 3002) - Grafana HTTP port
- `-WebPort` (default: 9500) - Web API port
- `-GrafanaDataRoot` (default: C:\GrafanaData) - Grafana data directory
- `-OpenBrowser` - Automatically open Grafana in browser after startup

**What it does:**
1. Stops any existing Grafana/Web API processes
2. Starts Web API (FastAPI on port 9500)
3. Starts Grafana (on port 3002 by default)
4. Provisions datasources (Infinity plugin for Web API)
5. Optionally opens browser

---

## Other Scripts (For Reference)

### 📦 **auto_stack.ps1** (728 lines - Complex Legacy)

**Status:** Legacy script supporting old 5-service architecture  
**Used by:** VS Code tasks (referenced for compatibility)  
**Recommendation:** Migrate tasks to `obs_start_clean.ps1` when possible

**Why it's complex:**
- Supports Prometheus (removed in Phase 2)
- Supports InfluxDB (not required for current architecture)
- 728 lines with extensive parameter handling
- Port scanning and service detection logic

**When to use:** Only if you need InfluxDB or legacy Prometheus support

---

### 🔄 **restart_stack_and_open_analytics.ps1** (361 lines)

**Purpose:** Restart Grafana only (preserves Web API/other services)  
**Status:** Specialized use case  
**Used by:** VS Code tasks for dashboard iteration

**When to use:** When iterating on Grafana dashboards without full restart

---

### ❌ **obs_start.ps1.deprecated** (416 lines - DEPRECATED)

**Status:** DEPRECATED (renamed to .deprecated in Phase 2)  
**Why deprecated:** Contains Prometheus startup logic (no longer needed)  
**Replacement:** Use `obs_start_clean.ps1` instead

**Historical context:**
- Pre-optimization version supporting all 5 services
- 416 lines with Prometheus configuration
- Superseded by cleaner 203-line version

---

## Stopping the Stack

### ✅ **obs_stop.ps1** (88 lines - RECOMMENDED)

**Purpose:** Stop all G6 observability services  
**Usage:**
```powershell
# Normal stop (graceful)
.\scripts\obs_stop.ps1

# Aggressive stop (force kill)
.\scripts\obs_stop.ps1 -Aggressive
```

**What it does:**
1. Stops Grafana processes (grafana-server, grafana)
2. Stops Web API (Python processes on port 9500)
3. Optionally stops InfluxDB (if running)
4. Reports final status

---

## VS Code Task Integration

**Current tasks reference these scripts:**
- `auto_stack.ps1` - Used in several tasks (legacy compatibility)
- `restart_stack_and_open_analytics.ps1` - Used for Grafana restart tasks
- `obs_start_clean.ps1` - Not yet widely used in tasks (should migrate)

**Recommendation:** Update `.vscode/tasks.json` to use `obs_start_clean.ps1` for consistency

---

## Migration Guide

### From auto_stack.ps1 to obs_start_clean.ps1

**Before (complex):**
```powershell
.\scripts\auto_stack.ps1 -StartPrometheus:$false -StartInflux:$false -StartGrafana:$true -GrafanaAllowAnonymous
```

**After (simple):**
```powershell
.\scripts\obs_start_clean.ps1 -GrafanaAllowAnonymous
```

**Benefit:** 72% fewer lines, clearer intent, faster execution

---

## Architecture Evolution

### Phase 1 (Pre-optimization): 5 Services
- Grafana (3002)
- Prometheus (9091) ← Removed
- Web API (9500)
- Metrics Server (9108) ← Removed
- Overlay Exporter (9109) ← Removed

### Phase 2 (Current): 2 Services ✅
- Grafana (3002)
- Web API (9500)

**Result:** 60% service reduction, simpler startup, faster execution

---

## Troubleshooting

### Problem: "Port already in use"
```powershell
# Stop all services first
.\scripts\obs_stop.ps1 -Aggressive

# Then start fresh
.\scripts\obs_start_clean.ps1
```

### Problem: "Grafana won't start"
```powershell
# Check if another Grafana is running
Get-Process grafana-server, grafana -ErrorAction SilentlyContinue

# Force kill if needed
Get-Process grafana-server, grafana -ErrorAction SilentlyContinue | Stop-Process -Force
```

### Problem: "Web API not responding"
```powershell
# Check if Python process is running
Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*uvicorn*" }

# Check Web API health
Invoke-WebRequest -Uri http://127.0.0.1:9500/health
```

---

## Future Improvements

1. **Consolidate tasks.json** - Migrate all tasks to use `obs_start_clean.ps1`
2. **Consider removing auto_stack.ps1** - After verifying no dependencies
3. **Add systemd/Windows Service support** - For production deployments
4. **Create simple start.ps1 alias** - Single entry point for users

---

## Summary

**Use this:**
- ✅ `obs_start_clean.ps1` - Start everything (canonical)
- ✅ `obs_stop.ps1` - Stop everything

**Avoid these:**
- ❌ `obs_start.ps1.deprecated` - Old version (deprecated)
- ⚠️ `auto_stack.ps1` - Complex legacy (migrate away)
- ⚠️ `restart_stack_and_open_analytics.ps1` - Specialized use only

---

*Generated during Phase 2 optimization cleanup - October 25, 2025*
