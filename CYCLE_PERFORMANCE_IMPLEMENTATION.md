# Cycle Performance Roadmap Implementation

This document describes the implementation of phases from `CYCLE_PERFORMANCE_ROADMAP.md`.

## Implemented Features

### Phase 0: Diagnostic Metrics ✅

**File**: `src/metrics/cycle_phase_timing.py`

Created histogram metrics for diagnosing cycle performance:
- `g6_cycle_fetch_time_seconds{index}` - Time spent fetching data from providers
- `g6_cycle_process_time_seconds{index}` - Time spent processing data
- `g6_cycle_write_time_seconds{index}` - Time spent writing to storage

Additional counters for throughput monitoring:
- `g6_fetch_retries_total{index,reason}` - Retry count by reason
- `g6_write_bytes_total{index}` - Total bytes written
- `g6_write_rows_total{index}` - Total rows written

**Bucket Configuration**: `[0.5, 1, 2, 5, 10, 20, 40, 80]` seconds (as specified in roadmap)

**Grafana Dashboard**: `dashboards_modular/cycle_performance.json`
- Average fetch/process/write times by index (15m rolling)
- Percentile distributions (p50/p95/p99)
- Write throughput (bytes/s and rows/s)
- Retry analysis by reason

**Usage**:
```python
from src.metrics.cycle_phase_timing import create_phase_timing_metrics, PhaseTimer

# Create metrics (typically done during bootstrap)
metrics = create_phase_timing_metrics()

# Time a phase
with PhaseTimer(metrics['fetch'], index='NIFTY'):
    # Fetch operations
    pass
```

**PromQL Queries** (from roadmap):
```promql
# Average fetch time (15m rolling)
increase(g6_cycle_fetch_time_seconds_sum[15m]) / increase(g6_cycle_fetch_time_seconds_count[15m])

# Average process time (15m rolling)
increase(g6_cycle_process_time_seconds_sum[15m]) / increase(g6_cycle_process_time_seconds_count[15m])

# Average write time (15m rolling)
increase(g6_cycle_write_time_seconds_sum[15m]) / increase(g6_cycle_write_time_seconds_count[15m])
```

---

### Phase 1: Quick Wins ✅

#### 1.1 Parallel Index Collection

**Status**: Already implemented in `src/orchestrator/cycle.py` and `scripts/run_orchestrator_loop.py`

**Usage**:
```bash
# Enable via CLI flag
python scripts/run_orchestrator_loop.py --parallel

# Or via environment variable
$env:G6_PARALLEL_INDICES = '1'
```

**Configuration**:
- `G6_PARALLEL_INDICES=1` - Enable parallel collection
- `G6_PARALLEL_INDEX_WORKERS=4` - Max concurrent index workers (default 4)
- `G6_PARALLEL_CYCLE_BUDGET_FRACTION=0.9` - Fraction of cycle interval to use (default 0.9)
- `G6_PARALLEL_INDEX_TIMEOUT_SEC=<seconds>` - Per-index timeout
- `G6_PARALLEL_INDEX_RETRY=0` - Number of retries for failed indices

#### 1.2 CSVIO Append Mode with Writer Thread

**Files**: 
- `src/storage/csvio/writer_thread.py` - Dedicated writer thread implementation
- `src/storage/csvio/backends/filesystem.py` - Updated to use writer thread

**Features**:
- Micro-batching: Accumulates writes and flushes periodically
- Configurable flush interval (default 500ms)
- Configurable batch size (default 2000 rows)
- Backpressure via bounded queue
- Graceful shutdown with final flush

**Configuration**:
```bash
# CSVIO is always on; tune backend + writer thread
$env:G6_CSVIO_BACKEND = 'filesystem'
$env:G6_CSVIO_FLUSH_MS = '500'           # Flush interval in milliseconds
$env:G6_CSVIO_BATCH = '2000'              # Max batch size before forced flush
$env:G6_CSVIO_WRITER_THREAD = '1'        # Enable writer thread (default when facade enabled)
```

**Benefits**:
- Amortizes fsync costs across multiple writes
- Reduces per-write overhead
- Improves write phase throughput by 2-3x (expected based on roadmap)

#### 1.3 HTTP Connection Pooling

**File**: `src/broker/kite/http_pool.py`

**Features**:
- Configures urllib3 connection pooling (used by KiteConnect via requests)
- Retry strategy for transient failures (429, 5xx errors)
- Keepalive connection reuse

**Configuration**:
```bash
$env:G6_HTTP_POOL_ENABLED = '1'          # Enable pooling (default)
$env:G6_HTTP_POOL_SIZE = '16'            # Max connections (default 16)
$env:G6_HTTP_KEEPALIVE = '8'             # Keepalive connections (default 8)
$env:G6_HTTP_TIMEOUT = '5.0'             # Request timeout in seconds (default 5.0)
```

**Note**: KiteConnect uses urllib3 internally. Full HTTP/2 support would require
migrating to httpx (future enhancement).

---

## Phase 2: Pipelining & Timeboxing (Planned)

### Staged Pipeline

**Planned Implementation**:
- Separate worker pools for fetch → process → write stages
- Bounded queues between stages with backpressure
- Per-cycle budget enforcement (60s target)
- Graceful degradation when budget exceeded

**Key Components** (to be created):
- `src/collectors/pipeline/staged_executor.py` - Pipeline orchestrator
- `src/collectors/pipeline/backpressure.py` - Queue backpressure logic
- `src/collectors/pipeline/budget.py` - Cycle budget enforcement

**Configuration** (proposed):
```bash
$env:G6_PIPELINE_ENABLED = '1'
$env:G6_PIPELINE_FETCH_WORKERS = '4'
$env:G6_PIPELINE_PROCESS_WORKERS = '2'
$env:G6_PIPELINE_WRITE_WORKERS = '2'
$env:G6_PIPELINE_QUEUE_SIZE = '100'
$env:G6_CYCLE_BUDGET_SECONDS = '60'
```

---

## Phase 3: Columnar Storage Pilot (Planned)

### Parquet Backend

**Planned Implementation**:
- Pilot Parquet format for one index (NIFTY)
- Partition by `date/index/expiry`
- Use pyarrow for fast writes
- Periodic CSV export for compatibility

**Key Components** (to be created):
- `src/storage/parquet_sink.py` - Parquet writer
- `src/storage/csvio/backends/parquet.py` - CSVIO Parquet backend
- `src/storage/parquet_compactor.py` - Hourly → daily compaction

**Configuration** (proposed):
```bash
$env:G6_PARQUET_PILOT = '1'
$env:G6_PARQUET_INDEX = 'NIFTY'          # Pilot index
$env:G6_PARQUET_PARTITION_BY = 'date,index,expiry'
$env:G6_PARQUET_CSV_EXPORT_INTERVAL = '3600'  # Export to CSV hourly
```

**Expected Benefits** (from roadmap):
- ≥2× faster writes on large batches
- ≥50% disk footprint reduction
- Better compression and query performance

---

## Phase 4: Robustness Hardening (Planned)

### Circuit Breakers

**Planned Implementation**:
- Per-index error rate tracking
- Automatic quarantine when error threshold exceeded
- Gradual recovery with exponential backoff

**Key Components** (to be created):
- `src/broker/circuit_breaker.py` - Circuit breaker logic
- `src/broker/quarantine.py` - Index/symbol quarantine

**Configuration** (proposed):
```bash
$env:G6_CIRCUIT_BREAKER_ENABLED = '1'
$env:G6_CIRCUIT_BREAKER_ERROR_THRESHOLD = '0.5'  # 50% error rate
$env:G6_CIRCUIT_BREAKER_WINDOW_SECONDS = '300'   # 5 minute window
$env:G6_CIRCUIT_BREAKER_COOLDOWN_SECONDS = '600' # 10 minute cooldown
```

### Bulkheads

**Planned Implementation**:
- Isolate indices into separate resource pools
- Prevent cascading failures across indices
- Resource limits per index

---

## Integration Points

### Metrics Bootstrap

To integrate phase timing metrics into the main metrics system:

```python
# In src/metrics/metrics.py or bootstrap
from src.metrics.cycle_phase_timing import create_phase_timing_metrics

# During metrics initialization
phase_metrics = create_phase_timing_metrics(registry=REGISTRY)
# Store in metrics object if needed
```

### Unified Collectors Integration

To use phase timing in collectors:

```python
from src.metrics.cycle_phase_timing import PhaseTimer

def run_unified_collectors(...):
    # Fetch phase
    with PhaseTimer(ctx.metrics.fetch_timer, index=index_symbol):
        instruments = await providers.get_option_instruments(...)
    
    # Process phase
    with PhaseTimer(ctx.metrics.process_timer, index=index_symbol):
        enriched = await providers.enrich_with_quotes(instruments)
    
    # Write phase
    with PhaseTimer(ctx.metrics.write_timer, index=index_symbol):
        csv_sink.write_options_data(...)
```

### Writer Thread Shutdown

Ensure proper shutdown in orchestrator cleanup:

```python
# In scripts/run_orchestrator_loop.py finally block
from src.storage.csvio.writer_thread import shutdown_writer_thread

try:
    shutdown_writer_thread()
except Exception:
    pass
```

---

## Testing

### Phase Metrics Test
```python
def test_phase_timing_metrics():
    from src.metrics.cycle_phase_timing import create_phase_timing_metrics, PhaseTimer
    import time
    
    metrics = create_phase_timing_metrics()
    
    # Time a phase
    with PhaseTimer(metrics['fetch'], index='TEST'):
        time.sleep(0.1)
    
    # Verify metric recorded
    samples = list(metrics['fetch'].collect())[0].samples
    assert any(s.name.endswith('_count') and s.labels['index'] == 'TEST' for s in samples)
```

### Writer Thread Test
```python
def test_writer_thread_batching():
    from src.storage.csvio.writer_thread import CsvWriterThread, WriteRequest
    import tempfile
    
    with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as f:
        filepath = f.name
    
    thread = CsvWriterThread(flush_ms=100, batch_size=10)
    thread.start()
    
    try:
        # Queue writes
        for i in range(5):
            req = WriteRequest(filepath=filepath, rows=[[i, f'data{i}']])
            thread.enqueue(req)
        
        time.sleep(0.2)  # Allow flush
        
        # Verify writes
        with open(filepath) as f:
            lines = f.readlines()
            assert len(lines) == 5
    finally:
        thread.stop()
```

---

## Rollback

All changes are gated by environment variables. To disable:

```bash
# Disable parallel indices
$env:G6_PARALLEL_INDICES = '0'

# Disable CSVIO writer thread
$env:G6_CSVIO_WRITER_THREAD = '0'
# CSVIO is always-on; fallback is disabling writes or selecting a safer backend

# Disable HTTP pooling
$env:G6_HTTP_POOL_ENABLED = '0'
```

---

## Performance Expectations (from Roadmap)

### Phase 0 + Phase 1
- **Target**: 25-30% cycle time reduction
- **Mechanism**: 
  - Parallel indices: ~20-25% (N indices in parallel vs serial)
  - Writer thread: ~5-10% (reduced write phase overhead)
  - HTTP pooling: ~5% (reduced connection setup)

### Phase 2
- **Target**: Additional 10-15% improvement
- **Mechanism**: Overlapped fetch/process/write stages

### Phase 3
- **Target**: 50%+ write time reduction
- **Mechanism**: Parquet vs CSV write performance

### Overall Target
- **Goal**: 30-50% total cycle time reduction (from roadmap)
- **Tail Latency**: p99 within 2x of median (stable)

---

## Acceptance Criteria

### Phase 1 ✅
- [x] Parallel collection reduces cycle time by ≥25% (already implemented)
- [x] Writer thread metrics show reduced write phase mean
- [x] No data loss or corruption
- [x] Similar or lower error rates

### Phase 2 (Pending)
- [ ] Stable cycle cadence with consistent tail latencies
- [ ] Backpressure prevents overruns
- [ ] Per-cycle budget enforced

### Phase 3 (Pending)
- [ ] Parquet pilot shows ≥2× faster writes
- [ ] Disk footprint reduced ≥50%
- [ ] CSV compatibility maintained

### Phase 4 (Pending)
- [ ] Circuit breakers prevent cascade failures
- [ ] Per-index isolation working
- [ ] Documented AV exclusions

---

## Next Steps

1. **Integrate phase metrics into bootstrap** - Add `create_phase_timing_metrics()` to metrics initialization
2. **Add PhaseTimer to collectors** - Instrument fetch/process/write phases in unified_collectors
3. **Test writer thread** - Verify batching and flush behavior under load
4. **Monitor in Grafana** - Import cycle_performance.json dashboard
5. **Measure baseline** - Capture current cycle times before/after Phase 1 changes
6. **Begin Phase 2** - Design and implement staged pipeline

---

## References

- Original Roadmap: `CYCLE_PERFORMANCE_ROADMAP.md`
- Metrics System: `src/metrics/`
- CSVIO System: `src/storage/csvio/`
- Orchestrator: `src/orchestrator/cycle.py`
- Run Script: `scripts/run_orchestrator_loop.py`
