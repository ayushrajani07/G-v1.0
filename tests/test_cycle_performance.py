"""Tests for cycle performance roadmap implementations."""
import os
import tempfile
import time
from pathlib import Path

import pytest


class TestPhaseTimingMetrics:
    """Test Phase 0: diagnostic metrics."""
    
    def test_create_phase_timing_metrics(self):
        """Test creating phase timing histogram metrics."""
        from src.metrics.cycle_phase_timing import create_phase_timing_metrics
        
        metrics = create_phase_timing_metrics()
        
        assert 'fetch' in metrics
        assert 'process' in metrics
        assert 'write' in metrics
        assert 'fetch_retries' in metrics
        assert 'write_bytes' in metrics
        assert 'write_rows' in metrics
    
    def test_phase_timer_context_manager(self):
        """Test PhaseTimer context manager."""
        from src.metrics.cycle_phase_timing import create_phase_timing_metrics, PhaseTimer
        
        metrics = create_phase_timing_metrics()
        
        # Time a phase
        with PhaseTimer(metrics['fetch'], index='NIFTY'):
            time.sleep(0.01)
        
        # Verify metric recorded (check samples)
        samples = list(metrics['fetch'].collect())[0].samples
        count_samples = [s for s in samples if s.name.endswith('_count') and s.labels.get('index') == 'NIFTY']
        assert len(count_samples) > 0
        assert count_samples[0].value > 0
    
    def test_phase_timer_with_error(self):
        """Test PhaseTimer handles errors gracefully."""
        from src.metrics.cycle_phase_timing import create_phase_timing_metrics, PhaseTimer
        
        metrics = create_phase_timing_metrics()
        
        # Timer should still record even if exception occurs
        with pytest.raises(ValueError):
            with PhaseTimer(metrics['process'], index='TEST'):
                raise ValueError("test error")
        
        # Verify metric recorded
        samples = list(metrics['process'].collect())[0].samples
        count_samples = [s for s in samples if s.name.endswith('_count') and s.labels.get('index') == 'TEST']
        assert len(count_samples) > 0


class TestWriterThread:
    """Test Phase 1: CSV writer thread."""
    
    def test_writer_thread_basic(self):
        """Test writer thread basic functionality."""
        from src.storage.csvio.writer_thread import CsvWriterThread, WriteRequest
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            filepath = f.name
        
        try:
            thread = CsvWriterThread(flush_ms=100, batch_size=10)
            thread.start()
            
            # Queue some writes
            for i in range(5):
                req = WriteRequest(
                    filepath=filepath,
                    rows=[[i, f'data{i}', 100 + i]],
                    header=['id', 'name', 'value']
                )
                assert thread.enqueue(req)
            
            # Wait for flush
            time.sleep(0.2)
            
            # Stop thread
            thread.stop(timeout=2.0)
            
            # Verify writes
            with open(filepath) as f:
                lines = f.readlines()
                assert len(lines) >= 5  # 5 data rows (header written once)
                assert 'id,name,value' in lines[0]
        
        finally:
            Path(filepath).unlink(missing_ok=True)
    
    def test_writer_thread_batching(self):
        """Test writer thread batches multiple writes."""
        from src.storage.csvio.writer_thread import CsvWriterThread, WriteRequest
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            filepath = f.name
        
        try:
            thread = CsvWriterThread(flush_ms=500, batch_size=100)
            thread.start()
            
            # Queue many writes quickly
            for i in range(20):
                req = WriteRequest(filepath=filepath, rows=[[i, f'test{i}']])
                thread.enqueue(req)
            
            # Small delay then stop
            time.sleep(0.6)
            thread.stop(timeout=2.0)
            
            # Verify all writes made it
            with open(filepath) as f:
                lines = f.readlines()
                assert len(lines) == 20
        
        finally:
            Path(filepath).unlink(missing_ok=True)
    
    def test_writer_thread_queue_full(self):
        """Test writer thread handles queue full gracefully."""
        from src.storage.csvio.writer_thread import CsvWriterThread, WriteRequest
        
        thread = CsvWriterThread(flush_ms=1000, batch_size=1000, queue_maxsize=5)
        thread.start()
        
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
                filepath = f.name
            
            # Fill queue
            for i in range(10):
                req = WriteRequest(filepath=filepath, rows=[[i]])
                result = thread.enqueue(req, timeout=0.01)
                # Some should succeed, some should fail when queue full
                if not result:
                    break
        
        finally:
            thread.stop(timeout=2.0)
            Path(filepath).unlink(missing_ok=True)


class TestCircuitBreaker:
    """Test Phase 4: circuit breaker."""
    
    def test_circuit_breaker_closed_state(self):
        """Test circuit breaker in closed state."""
        from src.broker.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState
        
        config = CircuitBreakerConfig(enabled=True, error_threshold=0.5)
        breaker = CircuitBreaker('test', config)
        
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_request_allowed()
        
        # Record successes
        for _ in range(10):
            breaker.record_success()
        
        assert breaker.state == CircuitState.CLOSED
    
    def test_circuit_breaker_opens_on_errors(self):
        """Test circuit breaker opens when error threshold exceeded."""
        from src.broker.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState
        
        config = CircuitBreakerConfig(enabled=True, error_threshold=0.5, window_seconds=60)
        breaker = CircuitBreaker('test', config)
        
        # Record mix of success/failure below threshold
        for _ in range(5):
            breaker.record_success()
        for _ in range(4):
            breaker.record_failure()
        
        # Still closed (4/9 = 44% < 50%)
        assert breaker.state == CircuitState.CLOSED
        
        # One more failure should trip it (5/10 = 50%)
        breaker.record_failure()
        
        assert breaker.state == CircuitState.OPEN
        assert not breaker.is_request_allowed()
    
    def test_circuit_breaker_half_open_recovery(self):
        """Test circuit breaker half-open recovery."""
        from src.broker.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState
        
        config = CircuitBreakerConfig(
            enabled=True,
            error_threshold=0.5,
            window_seconds=60,
            cooldown_seconds=0.2,  # Short cooldown for test
            half_open_attempts=2
        )
        breaker = CircuitBreaker('test', config)
        
        # Trip the breaker
        for _ in range(10):
            breaker.record_failure()
        
        assert breaker.state == CircuitState.OPEN
        
        # Wait for cooldown
        time.sleep(0.3)
        
        # Should transition to half-open
        assert breaker.state == CircuitState.HALF_OPEN
        assert breaker.is_request_allowed()
        
        # Successful half-open attempts should close
        breaker.record_success()
        breaker.record_success()
        
        assert breaker.state == CircuitState.CLOSED
    
    def test_circuit_breaker_call_wrapper(self):
        """Test circuit breaker call wrapper."""
        from src.broker.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitBreakerError
        
        config = CircuitBreakerConfig(enabled=True, error_threshold=0.5)
        breaker = CircuitBreaker('test', config)
        
        # Success case
        result = breaker.call(lambda x: x * 2, 5)
        assert result == 10
        
        # Trip breaker
        for _ in range(10):
            breaker.record_failure()
        
        # Should raise CircuitBreakerError when open
        with pytest.raises(CircuitBreakerError):
            breaker.call(lambda: None)


class TestStagedPipeline:
    """Test Phase 2: staged pipeline."""
    
    def test_pipeline_config_from_env(self):
        """Test pipeline configuration from environment."""
        from src.collectors.pipeline.staged_executor import PipelineConfig
        
        os.environ['G6_PIPELINE_ENABLED'] = '1'
        os.environ['G6_PIPELINE_FETCH_WORKERS'] = '8'
        
        try:
            config = PipelineConfig.from_env()
            assert config.enabled
            assert config.fetch_workers == 8
        finally:
            os.environ.pop('G6_PIPELINE_ENABLED', None)
            os.environ.pop('G6_PIPELINE_FETCH_WORKERS', None)
    
    def test_staged_pipeline_basic(self):
        """Test staged pipeline basic execution."""
        from src.collectors.pipeline.staged_executor import StagedPipeline, WorkItem, PipelineConfig
        
        # Simple pipeline: fetch adds 1, process multiplies by 2, write stores result
        results = []
        
        def fetch_fn(item):
            return item.data + 1 if item.data else 1
        
        def process_fn(item):
            return item.data * 2
        
        def write_fn(item):
            results.append(item.data)
        
        config = PipelineConfig(
            fetch_workers=2,
            process_workers=1,
            write_workers=1,
            queue_size=10,
            cycle_budget=5.0
        )
        
        pipeline = StagedPipeline(config, fetch_fn, process_fn, write_fn)
        pipeline.start_cycle()
        
        # Submit work
        for i in range(5):
            item = WorkItem(index='TEST', expiry_rule='this_week', data=i)
            pipeline.submit_work(item)
        
        # Wait for completion
        stats = pipeline.wait_for_completion(timeout=3.0)
        
        assert stats['completed'] > 0
        assert len(results) > 0
    
    def test_pipeline_budget_enforcement(self):
        """Test pipeline enforces cycle budget."""
        from src.collectors.pipeline.staged_executor import StagedPipeline, WorkItem, PipelineConfig
        
        def slow_fetch(item):
            time.sleep(0.5)
            return item.data
        
        def fast_process(item):
            return item.data
        
        def fast_write(item):
            pass
        
        config = PipelineConfig(
            fetch_workers=1,
            process_workers=1,
            write_workers=1,
            queue_size=5,
            cycle_budget=1.0  # Short budget
        )
        
        pipeline = StagedPipeline(config, slow_fetch, fast_process, fast_write)
        pipeline.start_cycle()
        
        # Submit many items
        for i in range(10):
            item = WorkItem(index='TEST', expiry_rule='this_week', data=i)
            pipeline.submit_work(item)
        
        stats = pipeline.wait_for_completion(timeout=2.0)
        
        # Some items should be dropped due to budget
        assert stats['dropped'] > 0


@pytest.mark.skipif(
    not pytest.importorskip('pyarrow', reason='pyarrow not installed'),
    reason='Parquet tests require pyarrow'
)
class TestParquetSink:
    """Test Phase 3: Parquet storage."""
    
    def test_parquet_sink_write(self):
        """Test Parquet sink write."""
        from src.storage.parquet_sink import ParquetSink
        import datetime
        
        with tempfile.TemporaryDirectory() as tmpdir:
            sink = ParquetSink(base_dir=tmpdir)
            
            # Write some data
            data = {
                '12345': {
                    'strike': 18000,
                    'option_type': 'CE',
                    'ltp': 100.5,
                    'oi': 1000000,
                },
                '12346': {
                    'strike': 18000,
                    'option_type': 'PE',
                    'ltp': 95.0,
                    'oi': 950000,
                },
            }
            
            sink.write_options_data(
                index_symbol='NIFTY',
                expiry_date=datetime.date.today(),
                data=data,
                timestamp=datetime.datetime.now(datetime.UTC)
            )
            
            # Verify file created
            parquet_files = list(Path(tmpdir).rglob('*.parquet'))
            assert len(parquet_files) > 0
    
    def test_parquet_sink_read(self):
        """Test Parquet sink read."""
        from src.storage.parquet_sink import ParquetSink
        import datetime
        
        with tempfile.TemporaryDirectory() as tmpdir:
            sink = ParquetSink(base_dir=tmpdir)
            
            # Write data
            data = {
                '12345': {'strike': 18000, 'ltp': 100.5},
            }
            
            now = datetime.datetime.now(datetime.UTC)
            expiry = datetime.date.today()
            
            sink.write_options_data(
                index_symbol='NIFTY',
                expiry_date=expiry,
                data=data,
                timestamp=now
            )
            
            # Read back
            records = sink.read_options_data('NIFTY', expiry)
            assert len(records) > 0
            assert records[0]['strike'] == 18000
