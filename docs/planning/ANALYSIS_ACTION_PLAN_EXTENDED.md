# Extended Action Plan: Future Phases Detail

**Supplement to ANALYSIS_ACTION_PLAN.md**  
**Created:** 2025-11-16  
**Purpose:** Detailed execution plans for incomplete phases

---

## Phase 1.2: Legacy Loop Removal - Extended Plan

**Status:** ⏸️ READY FOR EXECUTION

### Week-by-Week Breakdown

**Week 1: Pre-Removal Audit**
```powershell
# Day 1: Code inventory
$loopRefs = Select-String -Path .\**\*.py -Pattern "collection_loop" -Recurse
$flagRefs = Select-String -Path .\**\*.py -Pattern "G6_ENABLE_LEGACY_LOOP" -Recurse
$suppressRefs = Select-String -Path .\**\*.py -Pattern "G6_SUPPRESS_LEGACY_LOOP_WARN" -Recurse

Write-Host "Collection Loop References: $($loopRefs.Count)"
Write-Host "Flag References: $($flagRefs.Count)"
Write-Host "Suppress Flag References: $($suppressRefs.Count)"

# Day 2-3: Test with flag disabled
$env:G6_ENABLE_LEGACY_LOOP = '0'
python -m pytest -n auto --tb=short 2>&1 | Tee-Object -FilePath "test_baseline.txt"

# Day 4-5: Documentation audit
Select-String -Path .\docs\**\*.md -Pattern "legacy.*loop|collection_loop" -Recurse
Select-String -Path .\*.md -Pattern "G6_ENABLE_LEGACY_LOOP" -Recurse
```

### Removal Execution

**Code Changes:**
```python
# src/unified_main.py - REMOVE THIS FUNCTION
def collection_loop(
    config: Config,
    max_cycles: Optional[int] = None,
    ...
) -> None:
    """DEPRECATED: Use run_loop from orchestrator."""
    # ~200 lines to delete

# src/config/env_config.py - REMOVE THESE LINES
def get_enable_legacy_loop(self) -> bool:
    return self._get_bool("G6_ENABLE_LEGACY_LOOP", False)

def get_suppress_legacy_loop_warn(self) -> bool:
    return self._get_bool("G6_SUPPRESS_LEGACY_LOOP_WARN", False)
```

**Test Removal:**
```bash
rm tests/test_legacy_loop_gating.py
rm tests/test_deprecation_legacy_loop.py
```

### Validation Checklist
- [ ] Zero references to `collection_loop` in src/
- [ ] Zero references to `G6_ENABLE_LEGACY_LOOP` in code
- [ ] All tests pass: 1462 passed, 539 skipped
- [ ] Documentation updated (4 files)
- [ ] CHANGELOG.md entry added
- [ ] DEPRECATIONS.md moved to "Removed" section

---

## Phase 1.3: CSV Writer Consolidation - Extended Plan

**Status:** ⏸️ REQUIRES DESIGN REVIEW

### Phase 1: Discovery (Week 1)

**Day 1: Writer Inventory**
```powershell
# Find all CSV write implementations
Get-ChildItem -Path src -Filter "*.py" -Recurse | 
  Select-String -Pattern "class.*Writer|def.*write.*csv|\.to_csv\(" | 
  Group-Object Path

# Output files:
# - src/storage/csv_sink.py
# - src/storage/csv_writer.py
# - src/storage/csv_batcher.py
# - src/storage/csvio/writer.py
# - src/storage/csvio/writer_thread.py
```

**Day 2: Call Site Audit**
```powershell
# Create comprehensive audit
$writers = @(
    "CsvWriter",
    "CsvBatcher", 
    "CsvSink",
    "write_csv_atomic",
    "AsyncCsvWriter"
)

foreach ($writer in $writers) {
    Write-Host "`n=== $writer ==="
    Select-String -Path .\src\**\*.py -Pattern $writer -Recurse |
        Select-Object Path, LineNumber |
        Format-Table
}
```

**Day 3-4: Feature Matrix**

| Writer | Atomic | Batch | Async | Schema Val | Retry | Status |
|--------|--------|-------|-------|------------|-------|--------|
| csv_sink.py | ✅ | ❌ | ❌ | ✅ | ✅ | Primary |
| csv_writer.py | ⚠️ | ❌ | ❌ | ❌ | ❌ | Legacy |
| csv_batcher.py | ❌ | ✅ | ❌ | ❌ | ❌ | Partial |
| csvio/writer.py | ✅ | ⚠️ | ⚠️ | ✅ | ✅ | Facade |

**Day 5: Gap Analysis**
Missing from facade:
- High-performance batch writes (>10k rows)
- Streaming writes for large datasets
- Transaction support across multiple files
- Write-ahead logging for crash recovery

### Phase 2: Facade Enhancement (Week 2-3)

**Enhanced API Design:**
```python
# src/storage/csvio/unified_api.py
from typing import Iterator, Sequence, Protocol
from pathlib import Path
from contextlib import contextmanager

class CsvRecord(Protocol):
    """Protocol for CSV-writable records."""
    def to_dict(self) -> dict: ...

class UnifiedCsvWriter:
    """Single unified CSV writer with all capabilities."""
    
    def __init__(
        self,
        base_dir: Path,
        enable_wal: bool = True,
        batch_size: int = 1000,
    ):
        self.base_dir = base_dir
        self._wal = WriteAheadLog(base_dir / ".wal") if enable_wal else None
        self._batch_size = batch_size
    
    def write_single(
        self,
        relative_path: str,
        record: dict,
        schema_version: str = "v2",
    ) -> None:
        """Atomic single record write."""
        full_path = self.base_dir / relative_path
        if self._wal:
            self._wal.log_write(full_path, record)
        
        _write_atomic(full_path, [record], schema_version)
        
        if self._wal:
            self._wal.commit(full_path)
    
    def write_batch(
        self,
        writes: Sequence[tuple[str, dict]],
        fail_mode: str = "abort",  # or "continue"
    ) -> BatchResult:
        """Batch multiple writes efficiently."""
        results = []
        
        with self._batch_context():
            for rel_path, record in writes:
                try:
                    self.write_single(rel_path, record)
                    results.append((rel_path, "success"))
                except Exception as e:
                    results.append((rel_path, f"failed: {e}"))
                    if fail_mode == "abort":
                        raise
        
        return BatchResult(results)
    
    def write_stream(
        self,
        relative_path: str,
        records: Iterator[dict],
        flush_interval: int = 100,
    ) -> StreamResult:
        """Stream large datasets with periodic flushes."""
        full_path = self.base_dir / relative_path
        count = 0
        buffer = []
        
        for record in records:
            buffer.append(record)
            count += 1
            
            if len(buffer) >= flush_interval:
                _append_atomic(full_path, buffer)
                buffer.clear()
        
        if buffer:
            _append_atomic(full_path, buffer)
        
        return StreamResult(count)
    
    @contextmanager
    def transaction(self):
        """Multi-file atomic transaction."""
        ctx = TransactionContext(self.base_dir, self._wal)
        try:
            yield ctx
            ctx.commit()  # All writes or none
        except Exception:
            ctx.rollback()
            raise

# Usage examples:
writer = UnifiedCsvWriter(Path("data/csv"))

# Single write
writer.write_single("options/NIFTY/data.csv", {"strike": 18000, "iv": 15.5})

# Batch writes
writer.write_batch([
    ("options/NIFTY/data.csv", {"strike": 18000}),
    ("options/BANKNIFTY/data.csv", {"strike": 44000}),
])

# Streaming
def data_generator():
    for i in range(1000000):
        yield {"id": i, "value": i * 2}

writer.write_stream("large_dataset.csv", data_generator())

# Transaction
with writer.transaction() as txn:
    txn.write("file1.csv", data1)
    txn.write("file2.csv", data2)
    # Both succeed or both rollback
```

### Phase 3: Migration (Week 4-5)

**Migration Script:**
```python
# scripts/migrate_csv_writers.py
import ast
from pathlib import Path
import re

def migrate_file(file_path: Path) -> tuple[int, list[str]]:
    """Migrate a file to use UnifiedCsvWriter."""
    content = file_path.read_text()
    changes = []
    
    # Pattern 1: Old CsvWriter
    if "from src.storage.csv_writer import CsvWriter" in content:
        content = content.replace(
            "from src.storage.csv_writer import CsvWriter",
            "from src.storage.csvio.unified_api import UnifiedCsvWriter"
        )
        content = content.replace("CsvWriter()", "UnifiedCsvWriter(base_dir)")
        changes.append("Replaced CsvWriter import")
    
    # Pattern 2: CsvBatcher
    if "from src.storage.csv_batcher import CsvBatcher" in content:
        content = content.replace(
            "from src.storage.csv_batcher import CsvBatcher",
            "from src.storage.csvio.unified_api import UnifiedCsvWriter"
        )
        # More complex: batch calls need transformation
        content = re.sub(
            r'batcher\.write_batch\((.*?)\)',
            r'writer.write_batch(\1)',
            content
        )
        changes.append("Replaced CsvBatcher import")
    
    # Pattern 3: Direct csv_sink calls
    content = re.sub(
        r'csv_sink\.write\((.*?)\)',
        r'writer.write_single(\1)',
        content
    )
    
    if changes:
        file_path.write_text(content)
    
    return len(changes), changes

# Run migration
total_files = 0
total_changes = 0

for py_file in Path("src").rglob("*.py"):
    if ".archived" in str(py_file):
        continue
    
    change_count, changes = migrate_file(py_file)
    if change_count > 0:
        print(f"{py_file}: {change_count} changes")
        for change in changes:
            print(f"  - {change}")
        total_files += 1
        total_changes += change_count

print(f"\nMigrated {total_files} files with {total_changes} total changes")
```

### Phase 4: Validation & Cleanup (Week 6)

**Validation Tests:**
```python
# tests/storage/test_unified_writer.py
import pytest
from pathlib import Path
from src.storage.csvio.unified_api import UnifiedCsvWriter

def test_single_write_creates_file(tmp_path):
    writer = UnifiedCsvWriter(tmp_path)
    writer.write_single("test.csv", {"a": 1, "b": 2})
    
    assert (tmp_path / "test.csv").exists()
    # Verify content

def test_batch_write_atomic(tmp_path):
    writer = UnifiedCsvWriter(tmp_path)
    
    with pytest.raises(ValueError):
        writer.write_batch([
            ("file1.csv", {"a": 1}),
            ("file2.csv", {"invalid"}),  # Causes error
        ], fail_mode="abort")
    
    # Neither file should exist (atomic failure)
    assert not (tmp_path / "file1.csv").exists()
    assert not (tmp_path / "file2.csv").exists()

def test_transaction_rollback(tmp_path):
    writer = UnifiedCsvWriter(tmp_path, enable_wal=True)
    
    try:
        with writer.transaction() as txn:
            txn.write("file1.csv", {"a": 1})
            txn.write("file2.csv", {"b": 2})
            raise ValueError("Simulated error")
    except ValueError:
        pass
    
    # No files should be created
    assert not (tmp_path / "file1.csv").exists()
    assert not (tmp_path / "file2.csv").exists()

@pytest.mark.slow
def test_stream_large_dataset(tmp_path):
    writer = UnifiedCsvWriter(tmp_path)
    
    def generate_million_records():
        for i in range(1_000_000):
            yield {"id": i, "value": i * 2}
    
    result = writer.write_stream(
        "large.csv",
        generate_million_records(),
        flush_interval=10000
    )
    
    assert result.count == 1_000_000
    assert (tmp_path / "large.csv").exists()
```

**Performance Benchmark:**
```python
# scripts/bench_csv_writers.py
import time
from pathlib import Path
import tempfile

def benchmark_writer(writer_class, num_records=10000):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        writer = writer_class(tmp_path)
        
        records = [{"id": i, "value": i * 2} for i in range(num_records)]
        
        start = time.perf_counter()
        
        if hasattr(writer, 'write_batch'):
            writer.write_batch([("test.csv", r) for r in records])
        else:
            for record in records:
                writer.write_single("test.csv", record)
        
        elapsed = time.perf_counter() - start
        
        return {
            "writer": writer_class.__name__,
            "records": num_records,
            "elapsed_sec": elapsed,
            "records_per_sec": num_records / elapsed
        }

# Run benchmarks
from src.storage.csvio.unified_api import UnifiedCsvWriter
from src.storage.csv_writer import CsvWriter  # Legacy

results = [
    benchmark_writer(UnifiedCsvWriter),
    benchmark_writer(CsvWriter),
]

for result in results:
    print(f"{result['writer']}: {result['records_per_sec']:.0f} rec/sec")
```

**Cleanup Checklist:**
- [ ] Remove `src/storage/csv_writer.py` (move to `.archived/`)
- [ ] Remove `src/storage/csv_batcher.py` (move to `.archived/`)
- [ ] Remove `G6_USE_CSVIO_FACADE` flag from config
- [ ] Update all documentation
- [ ] Performance benchmark shows no regression (<5% slower acceptable)
- [ ] All 1462 tests still passing

---

## Phase 2: High Priority Tasks - Extended Plans

### 2.3 Deprecation Cleanup - Extended Plan

**Status:** ⏸️ READY - Most items already removed

**Remaining Work:**

**Week 1: Final Sweep**
```powershell
# Check for any lingering deprecated code
Select-String -Path .\src\**\*.py -Pattern "DEPRECATED|TODO.*remove|REMOVE.*\d{4}" -Recurse

# Check DEPRECATIONS.md for any missed items
Select-String -Path .\DEPRECATIONS.md -Pattern "REMOVED.*2025" | 
    Select-String -Pattern "202[45]-(0[1-9]|10)" # Jan-Oct 2024-2025
```

**Items Still Needing Cleanup:**
1. Cycle table flags (no-op, safe to remove):
   - `G6_DISABLE_CYCLE_TABLES`
   - `G6_DEFER_CYCLE_TABLES`
   - `G6_CYCLE_TABLE_GRACE_MS`
   - `G6_CYCLE_TABLE_GRACE_MAX_MS`

2. Metric alias: `perf_cache` → `cache` (removal target R+1)

3. Launcher script: `start_live_dashboard_v2.ps1` (removal target R+1)

**Action Plan:**
```powershell
# Day 1: Remove cycle table flags
$files = Select-String -Path .\**\*.py -Pattern "G6_.*CYCLE_TABLE" -Recurse
# Remove flag parsing from each file

# Day 2: Remove metric alias
# Edit src/metrics/registry.py to remove perf_cache alias

# Day 3: Remove deprecated launcher
Remove-Item .\scripts\start_live_dashboard_v2.ps1
# Update any scripts that reference it

# Day 4: Update documentation
# Update docs/env_dict.md, DEPRECATIONS.md, CHANGELOG.md

# Day 5: Final validation
python -m pytest -n auto
python scripts/dev_smoke.py one-cycle
```

---

## Phase 3: Medium Priority - Extended Plans

### 3.1 Documentation Restructuring - Complete Plan

**Status:** ⏸️ LARGE UNDERTAKING - 3 weeks minimum

**Current Problem:**
- 107 markdown files in root directory
- No clear hierarchy or organization
- Difficult to find relevant documentation
- Duplicated information across multiple files

**Target Structure:**
```
docs/
├── README.md                      # Documentation hub
├── getting-started/
│   ├── quick-start.md
│   ├── installation.md
│   └── first-cycle.md
├── architecture/
│   ├── system-overview.md
│   ├── data-flow.md
│   ├── module-structure.md
│   └── dependencies.md
├── configuration/
│   ├── environment-variables.md   # Consolidated env_dict.md
│   ├── config-files.md
│   └── runtime-settings.md
├── operations/
│   ├── deployment.md
│   ├── monitoring.md
│   ├── troubleshooting.md
│   └── maintenance.md
├── development/
│   ├── setup.md
│   ├── testing.md
│   ├── contributing.md
│   └── code-style.md
├── features/
│   ├── collectors.md
│   ├── metrics.md
│   ├── dashboards.md
│   ├── ml-forecasting.md
│   └── advisor.md
├── api-reference/
│   ├── collectors-api.md
│   ├── storage-api.md
│   ├── metrics-api.md
│   └── web-api.md
├── roadmaps/
│   ├── current-quarter.md
│   ├── completed.md
│   └── backlog.md
└── archive/
    └── [Historical documents]

README.md                          # Project overview only (max 300 lines)
CHANGELOG.md                       # Keep in root
CONTRIBUTING.md                    # Keep in root
LICENSE                            # Keep in root
```

**Week 1-2: Categorization & Migration**

**Day 1-2: Automated Categorization**
```powershell
# scripts/docs/categorize_docs.ps1
$categories = @{
    "architecture" = @("ARCHITECTURE", "DESIGN", "STRUCTURE", "FLOW")
    "config" = @("ENV", "CONFIG", "SETTINGS", "FLAGS")
    "operations" = @("DEPLOYMENT", "MONITORING", "OBS", "RUNBOOK")
    "development" = @("DEV", "TEST", "CONTRIBUTION")
    "features" = @("COLLECTOR", "METRIC", "DASHBOARD", "ML", "ADVISOR")
    "roadmap" = @("ROADMAP", "TODO", "PLAN", "SCOPE", "PHASE")
    "archive" = @("TEMP", "OLD", "DEPRECATED", "ARCHIVE")
}

Get-ChildItem -Filter "*.md" | ForEach-Object {
    $file = $_
    $content = Get-Content $file.FullName -Raw
    
    foreach ($cat in $categories.Keys) {
        $patterns = $categories[$cat]
        foreach ($pattern in $patterns) {
            if ($file.Name -match $pattern) {
                Write-Host "$($file.Name) -> $cat"
                break
            }
        }
    }
}
```

**Day 3-5: Manual Review**
- Review automated categorization
- Identify documents that need splitting
- Mark documents for merging (duplicates)
- Create migration plan

**Week 2: README Consolidation**

Current README.md is 1,530 lines. Split into:
```
README.md (300 lines max)
├── Quick start
├── Key features (bullets)
├── Installation
├── Basic usage
├── Links to detailed docs
└── Contributing

docs/getting-started/complete-guide.md
├── Detailed installation
├── Configuration walkthrough
└── First cycle tutorial

docs/architecture/system-overview.md
├── Full architecture description
├── Component diagrams
└── Design decisions
```

**Week 3: Linking & Validation**

**Create docs/README.md (Hub):**
```markdown
# G6 Documentation Hub

## 📚 Documentation Structure

### Getting Started
- [Quick Start](getting-started/quick-start.md) - Get running in 5 minutes
- [Installation Guide](getting-started/installation.md) - Detailed setup
- [First Cycle Tutorial](getting-started/first-cycle.md) - Walk through your first cycle

### Architecture
- [System Overview](architecture/system-overview.md) - High-level design
- [Data Flow](architecture/data-flow.md) - How data moves through the system
- [Module Structure](architecture/module-structure.md) - Code organization

### Configuration
- [Environment Variables](configuration/environment-variables.md) - All G6_* vars
- [Config Files](configuration/config-files.md) - YAML/JSON configuration
- [Runtime Settings](configuration/runtime-settings.md) - Dynamic settings

### Operations
- [Deployment](operations/deployment.md) - Deploy to production
- [Monitoring](operations/monitoring.md) - Metrics, dashboards, alerts
- [Troubleshooting](operations/troubleshooting.md) - Common issues

### Development
- [Development Setup](development/setup.md) - Dev environment
- [Testing Guide](development/testing.md) - Running and writing tests
- [Contributing](development/contributing.md) - How to contribute

### Features
- [Collectors](features/collectors.md) - Data collection system
- [Metrics](features/metrics.md) - Metrics and observability
- [Dashboards](features/dashboards.md) - Grafana integration
- [ML Forecasting](features/ml-forecasting.md) - Machine learning features

### API Reference
- [Collectors API](api-reference/collectors-api.md)
- [Storage API](api-reference/storage-api.md)
- [Metrics API](api-reference/metrics-api.md)

## 🔍 Quick Links

- [Changelog](docs/reference/CHANGELOG.md)
- [Current Roadmap](roadmaps/current-quarter.md)
- [Known Issues](https://github.com/ayushrajani07/G-v1.0/issues)
```

**Validation Script:**
```powershell
# scripts/docs/validate_links.ps1
$docs = Get-ChildItem -Path docs -Filter "*.md" -Recurse

foreach ($doc in $docs) {
    $content = Get-Content $doc.FullName -Raw
    
    # Extract markdown links
    $links = [regex]::Matches($content, '\[([^\]]+)\]\(([^)]+)\)')
    
    foreach ($link in $links) {
        $linkPath = $link.Groups[2].Value
        
        if ($linkPath -match '^http') {
            # External link - skip
            continue
        }
        
        # Resolve relative path
        $basePath = Split-Path $doc.FullName
        $fullPath = Join-Path $basePath $linkPath | Resolve-Path -ErrorAction SilentlyContinue
        
        if (-not $fullPath) {
            Write-Warning "Broken link in $($doc.Name): $linkPath"
        }
    }
}
```

---

## Phase 3.2: Performance Improvements - Async I/O Plan

**Status:** ⏸️ DESIGN PHASE

**Goal:** Non-blocking I/O for CSV writes and provider calls

### Current Performance Issues

1. **Synchronous CSV writes block collector execution**
   - Each write takes 5-50ms depending on data size
   - 50+ collectors × 50ms = 2.5 seconds blocked per cycle
   - No parallelism during writes

2. **Provider API calls are synchronous**
   - Network latency 50-200ms per call
   - Multiple sequential calls compound latency
   - Rate limiting can cause long waits

### Async Architecture Design

```python
# src/storage/async_writer.py
import asyncio
from typing import Dict, Optional
from pathlib import Path
from dataclasses import dataclass
import aiofiles

@dataclass
class WriteRequest:
    path: Path
    data: Dict
    priority: int = 0  # Higher = more urgent
    timestamp: float = field(default_factory=time.time)

class AsyncCsvWriter:
    """Non-blocking CSV writer with queue and backpressure."""
    
    def __init__(
        self,
        base_dir: Path,
        max_queue_size: int = 1000,
        flush_interval: float = 1.0,
        workers: int = 4,
    ):
        self.base_dir = base_dir
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=max_queue_size)
        self.flush_interval = flush_interval
        self.workers = workers
        self._worker_tasks = []
        self._running = False
        
        # Metrics
        self._queue_size_gauge = Gauge("csv_write_queue_size")
        self._write_latency_hist = Histogram("csv_write_latency_seconds")
        self._drops_counter = Counter("csv_write_drops_total")
    
    async def start(self):
        """Start background writer workers."""
        self._running = True
        self._worker_tasks = [
            asyncio.create_task(self._worker(i))
            for i in range(self.workers)
        ]
    
    async def stop(self):
        """Stop workers and flush remaining writes."""
        self._running = False
        
        # Wait for queue to drain
        await self.queue.join()
        
        # Cancel workers
        for task in self._worker_tasks:
            task.cancel()
        
        await asyncio.gather(*self._worker_tasks, return_exceptions=True)
    
    async def write(
        self,
        relative_path: str,
        data: Dict,
        priority: int = 0,
        timeout: Optional[float] = None,
    ) -> None:
        """Non-blocking write with optional timeout."""
        request = WriteRequest(
            path=self.base_dir / relative_path,
            data=data,
            priority=priority
        )
        
        try:
            await asyncio.wait_for(
                self.queue.put((priority, request)),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            # Backpressure - queue full
            self._drops_counter.inc()
            raise BackpressureError(f"Write queue full, dropped {relative_path}")
    
    def write_nowait(
        self,
        relative_path: str,
        data: Dict,
        priority: int = 0,
    ) -> None:
        """Non-blocking write, raises if queue full."""
        request = WriteRequest(
            path=self.base_dir / relative_path,
            data=data,
            priority=priority
        )
        
        try:
            self.queue.put_nowait((priority, request))
        except asyncio.QueueFull:
            self._drops_counter.inc()
            raise BackpressureError(f"Write queue full, dropped {relative_path}")
    
    async def _worker(self, worker_id: int):
        """Background worker that processes write requests."""
        logger = logging.getLogger(f"async_writer.worker_{worker_id}")
        
        while self._running:
            try:
                # Get request from queue
                priority, request = await asyncio.wait_for(
                    self.queue.get(),
                    timeout=1.0
                )
                
                # Update metrics
                queue_size = self.queue.qsize()
                self._queue_size_gauge.set(queue_size)
                
                # Perform write
                start = time.perf_counter()
                await self._write_async(request)
                elapsed = time.perf_counter() - start
                
                self._write_latency_hist.observe(elapsed)
                
                self.queue.task_done()
                
            except asyncio.TimeoutError:
                # No items in queue, continue
                continue
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}", exc_info=True)
                self.queue.task_done()
    
    async def _write_async(self, request: WriteRequest):
        """Actually write the file asynchronously."""
        # Ensure parent directory exists
        request.path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write to temporary file first (atomic)
        temp_path = request.path.with_suffix('.tmp')
        
        async with aiofiles.open(temp_path, mode='w', encoding='utf-8') as f:
            import csv
            import io
            
            # Build CSV in memory first (csv module is sync)
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=request.data.keys())
            writer.writeheader()
            writer.writerow(request.data)
            
            # Write buffer to file
            await f.write(buffer.getvalue())
        
        # Atomic rename
        temp_path.replace(request.path)

# Usage in collector:
async def collector_main():
    writer = AsyncCsvWriter(Path("data/csv"))
    await writer.start()
    
    try:
        # Collectors can write without blocking
        for collector in collectors:
            data = collector.collect()
            
            # Non-blocking write
            await writer.write(
                f"options/{collector.index}/data.csv",
                data,
                priority=collector.priority
            )
        
    finally:
        await writer.stop()  # Flush remaining writes
```

### Async Provider Integration

```python
# src/broker/kite/async_provider.py
import aiohttp
import asyncio
from typing import List, Dict

class AsyncKiteProvider:
    """Async version of Kite provider with connection pooling."""
    
    def __init__(
        self,
        api_key: str,
        access_token: str,
        max_connections: int = 10,
        timeout: float = 5.0,
    ):
        self.api_key = api_key
        self.access_token = access_token
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        
        # Connection pool
        self.session: Optional[aiohttp.ClientSession] = None
        self.max_connections = max_connections
    
    async def __aenter__(self):
        connector = aiohttp.TCPConnector(limit=self.max_connections)
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=self.timeout,
            headers=self._get_headers()
        )
        return self
    
    async def __aexit__(self, *args):
        await self.session.close()
    
    async def get_quotes_batch(
        self,
        symbols: List[str],
        batch_size: int = 100,
    ) -> Dict[str, Dict]:
        """Get quotes for multiple symbols in parallel."""
        results = {}
        
        # Split into batches (API limit)
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i+batch_size]
            
            # Parallel requests within batch
            tasks = [
                self._get_quote_single(symbol)
                for symbol in batch
            ]
            
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for symbol, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    logger.warning(f"Failed to get quote for {symbol}: {result}")
                    continue
                results[symbol] = result
        
        return results
    
    async def _get_quote_single(self, symbol: str) -> Dict:
        """Get quote for single symbol."""
        url = f"https://api.kite.trade/quote/{symbol}"
        
        async with self.session.get(url) as response:
            response.raise_for_status()
            return await response.json()

# Usage:
async def collect_all_quotes():
    symbols = ["NSE:NIFTY50", "NSE:BANKNIFTY", ...]
    
    async with AsyncKiteProvider(api_key, token) as provider:
        quotes = await provider.get_quotes_batch(symbols)
    
    return quotes
```

### Performance Impact Estimation

**Before (Synchronous):**
- 50 collectors × 50ms CSV write = 2,500ms
- 100 provider calls × 100ms = 10,000ms
- Total: ~12.5 seconds per cycle

**After (Asynchronous):**
- CSV writes: non-blocking, <100ms queue time
- Provider calls: parallel batches of 10 = 100ms × 10 batches = 1,000ms
- Total: ~2 seconds per cycle (6x faster!)

---

## Success Metrics & Tracking

### Exception Handling Progress
```powershell
# Track weekly
$date = Get-Date -Format "yyyy-MM-dd"
$count = (Get-ChildItem -Path "src" -Filter "*.py" -Recurse | 
         Select-String -Pattern "except Exception:" -CaseSensitive).Count

"$date,$count" | Add-Content exceptions_progress.csv

# Visualize
Import-Csv exceptions_progress.csv | 
    ForEach-Object { [PSCustomObject]@{Date=[DateTime]$_.Date; Count=[int]$_.Count} } |
    Format-Table
```

### Phase Completion Dashboard
```markdown
## Phase Completion Status

| Phase | Target | Current | % Complete | ETA |
|-------|--------|---------|------------|-----|
| 1.1 Exception Handling | <500 | 1,867 | 42% | Week 5 |
| 1.2 Legacy Loop | Remove | Present | 0% | Week 2 |
| 1.3 CSV Consolidation | 1 writer | 4 writers | 0% | Week 6 |
| 2.1 Test Infrastructure | 0 serial | 1 serial | 98% | Week 1 |
| 2.2 Config Unification | Single config | Partial | 60% | Week 10 |
| 2.3 Deprecation Cleanup | 0 expired | ~5 items | 90% | Week 1 |
| 3.1 Documentation | Organized | 107 root files | 0% | Week 13 |
| 3.2 Async I/O | Implemented | Sync only | 0% | Week 16 |
```

---

**End of Extended Action Plan**
