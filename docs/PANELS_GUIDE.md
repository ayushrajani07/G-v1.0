# G6 Platform - Panels & Dashboards Guide

**Complete User Guide for Real-Time Panel System**

---

## Table of Contents

1. [Overview](#1-overview)
2. [Panel Factory](#2-panel-factory)
3. [Summary Application](#3-summary-application)
4. [Panel Integrity](#4-panel-integrity)
5. [Status Manifests](#5-status-manifests)
6. [Complete Workflows](#6-complete-workflows)
7. [Configuration Reference](#7-configuration-reference)
8. [Monitoring & Troubleshooting](#8-monitoring--troubleshooting)
9. [Best Practices](#9-best-practices)
10. [Summary](#10-summary)

---

## 1. Overview

### What are Panels?

**Panels** are structured JSON artifacts representing real-time platform state. They power:

- **Terminal UIs**: Rich console dashboards (via `rich` library)
- **Plain text summaries**: Simplified logging/monitoring output
- **SSE streaming**: Real-time browser dashboards
- **External integrations**: Status APIs for third-party tools

### Key Features

✅ **Structured JSON output** (`data/panels/*.json`)  
✅ **Panel types**: Provider, Resources, Loop, Health, Indices  
✅ **Integrity monitoring**: Hash-based verification  
✅ **Live updates**: File-watch triggers + SSE streaming  
✅ **Plain & Rich modes**: Terminal rendering flexibility  
✅ **Snapshot isolation**: Per-cycle atomic writes  

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                 G6 Collection Pipeline                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Orchestrator │→│ StatusWriter │→│ RuntimeStatus│      │
│  │              │  │              │  │  .json       │      │
│  └──────────────┘  └──────────────┘  └──────┬───────┘      │
└────────────────────────────────────────────┼───────────────┘
                                             │
                                    ┌────────▼─────────┐
                                    │  Panel Factory   │
                                    │  (builders)      │
                                    └────────┬─────────┘
                                             │
                          ┌──────────────────┼──────────────────┐
                          │                  │                  │
                ┌─────────▼────────┐ ┌──────▼───────┐ ┌───────▼──────┐
                │ provider.json    │ │ loop.json    │ │indices.json  │
                │ resources.json   │ │ health.json  │ │...           │
                └─────────┬────────┘ └──────┬───────┘ └───────┬──────┘
                          │                  │                  │
                          └──────────────────┼──────────────────┘
                                             │
                                    ┌────────▼─────────┐
                                    │ Summary App      │
                                    │ (Rich/Plain)     │
                                    └────────┬─────────┘
                                             │
                                    ┌────────▼─────────┐
                                    │  Terminal UI     │
                                    │  (Live Dashboard)│
                                    └──────────────────┘
```

### File Structure

```
data/panels/
├── provider.json       # Provider state (Kite/Mock/Synthetic)
├── resources.json      # CPU, memory metrics
├── loop.json           # Collection cycle info
├── health.json         # Component health status
├── indices.json        # Per-index summary (NIFTY, BANKNIFTY, ...)
├── indices_stream.jsonl # Append-only event log
└── manifest.json       # Panel catalog with hashes

scripts/summary/
├── app.py              # Main summary application
├── panel_registry.py   # Panel providers
├── panel_types.py      # TypedDict models
├── layout.py           # Rich layout builder
├── derive.py           # Domain extraction from status
├── domain.py           # Domain models (CycleInfo, AlertsInfo)
└── plugins/
    ├── base.py         # OutputPlugin protocol
    ├── rich_renderer.py # Rich console output
    └── plain_renderer.py # Plain text output

src/panels/
├── factory.py          # Panel builders (build_loop_panel, etc.)
├── models.py           # TypedDict panel schemas
├── integrity_monitor.py # Hash-based integrity checker
├── validate.py         # JSON schema validation
└── helpers.py          # Utility functions
```

---

## 2. Panel Factory

### Panel Builders

**Location**: `src/panels/factory.py`

Central factory for constructing panel payloads from `StatusReader`.

#### Key Functions

```python
from src.panels.factory import (
    build_provider_panel,
    build_resources_panel,
    build_loop_panel,
    build_health_panel,
    build_indices_summary,
)
from src.utils.status_reader import StatusReader

# Load status
reader = StatusReader("data/runtime_status.json")
status = reader.get_raw_status()

# Build panels
provider = build_provider_panel(reader, status)
resources = build_resources_panel(reader, status)
loop = build_loop_panel(reader, status)
health = build_health_panel(reader, status)
indices = build_indices_summary(reader, status)
```

### Panel Types

#### 1. ProviderPanel

```python
class ProviderPanel(TypedDict, total=False):
    name: str | None          # "kite_live" / "mock" / "synthetic"
    auth: bool | None         # True if authenticated
    expiry: str | None        # Token expiry timestamp
    latency_ms: float | None  # Average API latency
```

**Example JSON** (`data/panels/provider.json`):
```json
{
  "name": "kite_live",
  "auth": true,
  "expiry": "2025-01-30T15:30:00Z",
  "latency_ms": 42.5
}
```

#### 2. ResourcesPanel

```python
class ResourcesPanel(TypedDict, total=False):
    cpu: float | None        # CPU usage percent (0-100)
    rss: int | None          # Resident set size (bytes)
    memory_mb: float | None  # Memory MB (RSS / 1024^2)
```

**Example JSON** (`data/panels/resources.json`):
```json
{
  "cpu": 12.5,
  "rss": 524288000,
  "memory_mb": 500.0
}
```

#### 3. LoopPanel

```python
class LoopPanel(TypedDict, total=False):
    cycle: int | None              # Current cycle number
    last_start: str | None         # Last cycle start timestamp
    last_duration: float | None    # Last cycle duration (seconds)
    success_rate: float | None     # Success rate (0-1)
```

**Example JSON** (`data/panels/loop.json`):
```json
{
  "cycle": 42,
  "last_start": "2025-01-25T10:15:30Z",
  "last_duration": 1.234,
  "success_rate": 0.98
}
```

#### 4. IndicesSummaryPanel

```python
class IndicesSummaryPanel(TypedDict):
    # map index -> metrics
    # {"NIFTY": {"status": "OK", "legs": 120, "dq_score": 99}, ...}
```

**Example JSON** (`data/panels/indices.json`):
```json
{
  "NIFTY": {
    "status": "OK",
    "legs": 120,
    "dq_score": 99.5,
    "dq_issues": 0
  },
  "BANKNIFTY": {
    "status": "OK",
    "legs": 105,
    "dq_score": 98.2,
    "dq_issues": 1
  }
}
```

#### 5. IndicesStreamItem

Append-only event log (`data/panels/indices_stream.jsonl`):

```python
class IndicesStreamItem(TypedDict, total=False):
    index: str
    status: str
    cycle: int | None
    time: str | None
    legs: int | None
    dq_score: float | None
```

**Example JSONL**:
```jsonl
{"index":"NIFTY","status":"OK","cycle":1,"time":"2025-01-25T10:15:30Z","legs":120,"dq_score":99.5}
{"index":"BANKNIFTY","status":"OK","cycle":1,"time":"2025-01-25T10:15:31Z","legs":105,"dq_score":98.2}
```

---

## 3. Summary Application

### Main Application

**Location**: `scripts/summary/app.py`

The **summary application** reads panels and renders terminal dashboards.

#### Basic Usage

```bash
# Plain text mode
python -m scripts.summary.app --no-rich

# Rich mode (default)
python -m scripts.summary.app

# Auto-refresh every 0.5s
python -m scripts.summary.app --refresh 0.5

# Panels mode (prefer data/panels/*.json)
python -m scripts.summary.app --panels on

# SSE streaming mode
python -m scripts.summary.app --sse-url http://127.0.0.1:9315/events
```

### Rendering Modes

#### Plain Mode

**Enabled**: `--no-rich` flag

**Output**:
```
G6 Summary (plain)
══════════════════
Cycle: 42 | Last: 2025-01-25T10:15:30 | Duration: 1.234s | Success: 98.0%
Indices: NIFTY, BANKNIFTY, FINNIFTY, SENSEX (4)
Provider: kite_live | Auth: ✓ | Latency: 42ms
Resources: CPU=12.5% | Memory=500MB
Alerts: 2 (warning:1, info:1)
```

**Use Case**: Logging, CI/CD, headless environments

#### Rich Mode

**Enabled**: Default (requires `rich` library)

**Output**:
```
╭─────────────────────────── G6 Platform Summary ───────────────────────────╮
│                                                                            │
│  ╭──── Cycle ───────────────────────────────────────────────────────────╮ │
│  │  Cycle: 42                                                           │ │
│  │  Last Start: 2025-01-25T10:15:30                                     │ │
│  │  Duration: 1.234s                                                    │ │
│  │  Success Rate: 98.0%                                                 │ │
│  ╰──────────────────────────────────────────────────────────────────────╯ │
│                                                                            │
│  ╭──── Indices ─────────────────────────────────────────────────────────╮ │
│  │  NIFTY       ✓  Legs: 120  DQ: 99.5                                  │ │
│  │  BANKNIFTY   ✓  Legs: 105  DQ: 98.2  ⚠ 1 issue                      │ │
│  │  FINNIFTY    ✓  Legs: 95   DQ: 97.8                                  │ │
│  │  SENSEX      ✓  Legs: 80   DQ: 96.5                                  │ │
│  ╰──────────────────────────────────────────────────────────────────────╯ │
╰────────────────────────────────────────────────────────────────────────────╯
```

**Use Case**: Interactive monitoring, development debugging

### Panel Providers

**Location**: `scripts/summary/panel_registry.py`

Panel providers **extract** domain data from raw status.

```python
from scripts.summary.panel_registry import DEFAULT_PANEL_PROVIDERS
from scripts.summary.domain import SummaryDomainSnapshot

# Build snapshot from status
snapshot = derive_cycle(status, metrics_data, env_config)

# Render panels
for provider in DEFAULT_PANEL_PROVIDERS:
    panel = provider.build(snapshot)
    print(f"{panel.title}: {panel.lines}")
```

**Available Providers**:
- `CyclePanelProvider`: Cycle number, duration, success rate
- `IndicesPanelProvider`: Index list and count
- `AlertsPanelProvider`: Alert summary by severity
- `ResourcesPanelProvider`: CPU/memory usage
- `StoragePanelProvider`: Storage lag, queue depth
- `PerfPanelProvider`: Performance metrics

---

## 4. Panel Integrity

### IntegrityMonitor

**Location**: `src/panels/integrity_monitor.py`

Verifies panel file integrity using **SHA-256 hashes**.

#### Workflow

```python
from src.panels.integrity_monitor import IntegrityMonitor

# Initialize monitor
monitor = IntegrityMonitor(panels_dir="data/panels")

# Check integrity
result = monitor.check_integrity()

if result.ok:
    print(f"✓ All {result.checked_count} panels valid")
else:
    print(f"✗ {result.mismatch_count} mismatches detected")
    for error in result.errors:
        print(f"  - {error}")
```

#### Manifest File

**Location**: `data/panels/manifest.json`

Catalog of all panels with expected hashes:

```json
{
  "version": "1.0",
  "updated": "2025-01-25T10:15:30Z",
  "panels": {
    "provider": {
      "path": "provider.json",
      "hash": "a3b2c1d4e5f6...",
      "size": 128,
      "updated": "2025-01-25T10:15:30Z"
    },
    "loop": {
      "path": "loop.json",
      "hash": "b4c3d2e1f0a9...",
      "size": 256,
      "updated": "2025-01-25T10:15:30Z"
    }
  }
}
```

#### Integrity Checks

**Automated**: Via `panels_integrity_checks` metric

```python
from src.metrics import get_metrics_registry

metrics = get_metrics_registry()

# Run integrity check
result = monitor.check_integrity()

# Emit metrics
if hasattr(metrics, 'panels_integrity_checks'):
    metrics.panels_integrity_checks.inc()

if result.ok:
    if hasattr(metrics, 'panels_integrity_ok'):
        metrics.panels_integrity_ok.set(1)
else:
    if hasattr(metrics, 'panels_integrity_ok'):
        metrics.panels_integrity_ok.set(0)
    if hasattr(metrics, 'panels_integrity_failures'):
        metrics.panels_integrity_failures.inc()
    if hasattr(metrics, 'panels_integrity_mismatches'):
        metrics.panels_integrity_mismatches.inc(result.mismatch_count)
```

**Grafana Alert**:
```yaml
# prometheus_alerts.yml
- alert: PanelIntegrityFailure
  expr: panels_integrity_ok == 0
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "Panel integrity check failing"
```

---

## 5. Status Manifests

### StatusReader

**Location**: `src/utils/status_reader.py`

Unified interface for reading runtime status + panels.

```python
from src.utils.status_reader import StatusReader

# Initialize reader
reader = StatusReader("data/runtime_status.json")

# Get raw status
status = reader.get_raw_status()

# Get typed data
provider = reader.get_provider_data()
resources = reader.get_resources_data()
cycle = reader.get_cycle_data()
health = reader.get_health_data()
indices = reader.get_indices_data()
```

### Panel vs Status Priority

**Precedence** (if both exist):

1. **data/panels/*.json** (higher priority - structured, typed)
2. **data/runtime_status.json** (fallback - monolithic, legacy)

**Example**:
```python
# StatusReader checks panels first
provider = reader.get_provider_data()

# If data/panels/provider.json exists → use it
# Else → extract from status["provider"]
```

---

## 6. Complete Workflows

### Workflow 1: Add New Panel Type

**Scenario**: Track storage backlog in a dedicated panel.

#### Step 1: Define Panel Model

Edit `src/panels/models.py`:

```python
class StoragePanel(TypedDict, total=False):
    backlog_size: int | None
    last_flush: str | None
    flush_duration_ms: float | None
```

#### Step 2: Create Builder Function

Edit `src/panels/factory.py`:

```python
def build_storage_panel(reader: StatusReader, status: dict[str, Any] | None) -> StoragePanel:
    storage = reader.get_storage_data() or {}
    out: StoragePanel = {}
    
    if isinstance(storage, dict):
        out["backlog_size"] = storage.get("backlog_size")
        out["last_flush"] = storage.get("last_flush")
        out["flush_duration_ms"] = storage.get("flush_duration_ms")
    
    return out
```

#### Step 3: Write Panel to Disk

In orchestrator (`src/orchestrator/orchestrator.py`):

```python
from src.panels.factory import build_storage_panel
import json

# At end of cycle
storage_panel = build_storage_panel(reader, status)

# Write to disk
with open("data/panels/storage.json", "w") as f:
    json.dump(storage_panel, f, indent=2)
```

#### Step 4: Add Panel Provider

Edit `scripts/summary/panel_registry.py`:

```python
class StorageBacklogPanelProvider:
    key = "storage_backlog"
    
    def build(self, snapshot: SummaryDomainSnapshot) -> PanelData:
        # Extract from storage info
        s = snapshot.storage
        lines = [
            f"backlog: {s.backlog_size} items" if s.backlog_size else "backlog: —",
            f"last_flush: {s.last_flush or '—'}",
        ]
        return PanelData(
            key=self.key,
            title="Storage Backlog",
            lines=lines,
            meta={"backlog_size": s.backlog_size},
        )

# Add to registry
DEFAULT_PANEL_PROVIDERS = (
    CyclePanelProvider(),
    StorageBacklogPanelProvider(),  # NEW
    # ... existing providers
)
```

#### Step 5: Test

```bash
# Run platform
python -m src.main

# Check panel file created
cat data/panels/storage.json

# View in summary
python -m scripts.summary.app --refresh 1
```

---

### Workflow 2: SSE Live Updates

**Scenario**: Stream panel updates to browser dashboard.

#### Step 1: Start SSE Server

```bash
# In orchestrator, enable SSE
export G6_SSE_ENABLED=1
export G6_SSE_PORT=9315

python -m src.main
```

#### Step 2: Subscribe from Browser

```javascript
// browser_dashboard.html
const eventSource = new EventSource('http://127.0.0.1:9315/events');

eventSource.addEventListener('panel_update', (event) => {
  const data = JSON.parse(event.data);
  console.log('Panel update:', data.panel_key, data.data);
  
  // Update DOM
  if (data.panel_key === 'loop') {
    document.getElementById('cycle').textContent = data.data.cycle;
  }
});

eventSource.addEventListener('error', (error) => {
  console.error('SSE error:', error);
});
```

#### Step 3: Emit Panel Updates

In orchestrator:

```python
from src.sse.emitter import SSEEmitter

emitter = SSEEmitter(port=9315)

# After writing panel
with open("data/panels/loop.json", "w") as f:
    json.dump(loop_panel, f)

# Emit SSE event
emitter.emit('panel_update', {
    'panel_key': 'loop',
    'data': loop_panel,
    'timestamp': datetime.now(UTC).isoformat()
})
```

---

### Workflow 3: Integrity Monitoring

**Scenario**: Detect corrupted panel files.

#### Step 1: Enable Integrity Checks

```bash
export G6_PANELS_INTEGRITY_ENABLED=1
export G6_PANELS_INTEGRITY_INTERVAL=30  # Check every 30s
```

#### Step 2: Run Platform with Monitoring

```python
from src.panels.integrity_monitor import IntegrityMonitor
import time

monitor = IntegrityMonitor("data/panels")

while True:
    result = monitor.check_integrity()
    
    if not result.ok:
        print(f"⚠ Panel integrity check failed!")
        for error in result.errors:
            print(f"  {error}")
        
        # Trigger alert
        # send_alert("Panel integrity failure", errors=result.errors)
    
    time.sleep(30)
```

#### Step 3: Create Grafana Dashboard

Panel: **Panel Integrity Status**

**Query**:
```promql
panels_integrity_ok
```

**Alert**:
```promql
panels_integrity_ok == 0
```

---

## 7. Configuration Reference

### Environment Variables

#### Panels System

| Variable | Default | Description |
|----------|---------|-------------|
| `G6_PANELS_DIR` | `data/panels` | Panel output directory |
| `G6_PANELS_ENABLED` | `1` | Enable panel writing |
| `G6_PANELS_INTEGRITY_ENABLED` | `0` | Enable integrity monitoring |
| `G6_PANELS_INTEGRITY_INTERVAL` | `60` | Integrity check interval (seconds) |

#### Summary Application

| Variable | Default | Description |
|----------|---------|-------------|
| `G6_STATUS_FILE` | `data/runtime_status.json` | Status file path |
| `G6_METRICS_URL` | `http://127.0.0.1:9108/metrics` | Metrics endpoint |
| `G6_SUMMARY_SSE_URL` | ` ` | SSE endpoint for live updates |
| `G6_SUMMARY_REFRESH_SEC` | `0.5` | UI frame refresh interval |

#### SSE Streaming

| Variable | Default | Description |
|----------|---------|-------------|
| `G6_SSE_ENABLED` | `0` | Enable SSE server |
| `G6_SSE_PORT` | `9315` | SSE server port |
| `G6_SSE_HOST` | `127.0.0.1` | SSE bind address |

---

## 8. Monitoring & Troubleshooting

### Health Checks

#### Panels Directory Exists?

```bash
ls -la data/panels/

# Expected:
# provider.json
# resources.json
# loop.json
# health.json
# indices.json
# manifest.json
```

#### Panels Updated Recently?

```bash
# Check file modification times
find data/panels -name "*.json" -mmin -5

# Should list files modified in last 5 minutes
```

#### Integrity Status?

```bash
# Query Prometheus
curl -s http://localhost:9090/api/v1/query?query=panels_integrity_ok | jq .

# Expected: {"status":"success","data":{"result":[{"value":[<ts>,"1"]}]}}
```

### Common Issues

#### Issue 1: Panels Not Created

**Symptom**: `data/panels/` directory empty or missing files.

**Causes:**
1. **Panels disabled**: Check `G6_PANELS_ENABLED`
2. **Directory permissions**: Cannot write to `data/panels/`
3. **Platform not running**: Orchestrator not started

**Fix:**
```bash
# Enable panels
export G6_PANELS_ENABLED=1

# Create directory
mkdir -p data/panels

# Check permissions
chmod 755 data/panels

# Start platform
python -m src.main
```

#### Issue 2: Rich Mode Not Working

**Symptom**: `ImportError: No module named 'rich'`

**Cause**: Rich library not installed.

**Fix:**
```bash
# Install rich
pip install rich

# Or use plain mode
python -m scripts.summary.app --no-rich
```

#### Issue 3: Stale Panel Data

**Symptom**: Summary shows old data.

**Causes:**
1. **Platform stopped**: Not updating panels
2. **File watch broken**: Summary not detecting changes
3. **Cache issue**: Old data cached in memory

**Fix:**
```bash
# Check platform running
ps aux | grep "python.*src.main"

# Force summary refresh
# Ctrl+C and restart:
python -m scripts.summary.app --refresh 0.5

# Check panel timestamps
stat data/panels/loop.json
```

#### Issue 4: Integrity Check Failing

**Symptom**: `panels_integrity_ok == 0`

**Causes:**
1. **Partial write**: Panel file corrupted mid-write
2. **Manual edit**: File modified outside platform
3. **Manifest stale**: Manifest not updated after panel write

**Fix:**
```bash
# Rebuild panels
rm data/panels/*.json

# Restart platform
python -m src.main

# Regenerate manifest
python -c "from src.panels.integrity_monitor import IntegrityMonitor; IntegrityMonitor('data/panels').update_manifest()"
```

---

## 9. Best Practices

### DO ✅

1. **Use atomic writes for panels**
   ```python
   # Good: atomic write via temp file
   import tempfile, os, shutil
   
   with tempfile.NamedTemporaryFile('w', delete=False) as tmp:
       json.dump(panel_data, tmp)
       tmp_path = tmp.name
   
   shutil.move(tmp_path, "data/panels/loop.json")
   
   # Bad: direct write (can corrupt during write)
   with open("data/panels/loop.json", "w") as f:
       json.dump(panel_data, f)
   ```

2. **Validate panel schema**
   ```python
   from src.panels.validate import validate_panel
   
   # Validate before writing
   errors = validate_panel("loop", loop_panel)
   if errors:
       logger.error(f"Panel validation failed: {errors}")
       return
   
   # Write validated panel
   write_panel("data/panels/loop.json", loop_panel)
   ```

3. **Use TypedDict for type safety**
   ```python
   from src.panels.models import LoopPanel
   
   # Good: typed, IDE autocomplete, mypy checks
   panel: LoopPanel = {
       "cycle": 42,
       "last_duration": 1.234
   }
   
   # Bad: untyped, prone to errors
   panel = {"cycle": 42, "last_duration": 1.234}
   ```

4. **Update manifest after writes**
   ```python
   # After writing all panels
   monitor = IntegrityMonitor("data/panels")
   monitor.update_manifest()
   ```

5. **Handle missing panels gracefully**
   ```python
   # Good: fallback to status file
   provider = reader.get_provider_data()
   if not provider:
       provider = status.get("provider", {})
   
   # Bad: crash if panel missing
   provider = reader.get_provider_data()
   name = provider["name"]  # KeyError if None
   ```

### DON'T ❌

1. **Don't block on panel writes**
   ```python
   # Bad: synchronous write blocks collection loop
   with open("data/panels/loop.json", "w") as f:
       json.dump(loop_panel, f)
   
   # Good: async write via queue
   panel_queue.put(("loop", loop_panel))
   ```

2. **Don't store large data in panels**
   ```python
   # Bad: 10MB option chain in panel
   indices_panel = {
       "NIFTY": {
           "option_chain": [...],  # 10,000 strikes
       }
   }
   
   # Good: summary metrics only
   indices_panel = {
       "NIFTY": {
           "legs": 120,
           "dq_score": 99.5
       }
   }
   ```

3. **Don't skip integrity checks**
   ```python
   # Bad: no verification
   write_panel("loop.json", panel)
   
   # Good: verify after write
   write_panel("loop.json", panel)
   result = monitor.check_integrity()
   if not result.ok:
       logger.error("Panel integrity check failed")
   ```

---

## 10. Summary

### Quick Start

```bash
# 1. Start platform (generates panels)
python -m src.main

# 2. View panels (plain mode)
python -m scripts.summary.app --no-rich

# 3. View panels (rich mode)
python -m scripts.summary.app --refresh 0.5

# 4. Check integrity
python scripts/panels_integrity_check.py

# 5. Stream to browser
python -m scripts.summary.app --sse-url http://127.0.0.1:9315/events
```

### Key Concepts

| Concept | Description |
|---------|-------------|
| **Panel Factory** | Builds typed JSON payloads from status |
| **Panel Providers** | Extract domain data for rendering |
| **Summary App** | Terminal UI (Rich/Plain modes) |
| **Integrity Monitor** | Hash-based verification |
| **SSE Streaming** | Real-time browser updates |
| **Status Manifests** | Panel catalog with metadata |

### VS Code Tasks

```bash
# Start summary (panels mode)
Task: "Smoke: Summary (panels mode)"

# Start summary (plain one-shot)
Task: "Summary: plain one-shot"

# Panels one-shot demo
Task: "Panels: One-shot Demo (chain)"

# Check panel integrity
python scripts/panels_integrity_check.py
```

### Related Guides

- **[Collector System Guide](COLLECTOR_SYSTEM_GUIDE.md)**: Status generation
- **[Metrics Guide](METRICS_GUIDE.md)**: Panel integrity metrics
- **[Configuration Guide](CONFIGURATION_GUIDE.md)**: Panel configuration

---

**End of Panels Guide**
