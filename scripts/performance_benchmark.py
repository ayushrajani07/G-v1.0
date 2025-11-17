"""Performance benchmarking utilities for G6 Platform.

Part of Phase 3.2: Performance Improvements (2025-11-16)

Provides tools to benchmark and compare performance of various components:
- CSV write throughput
- Memory usage patterns
- Collection cycle timing
- Queue backpressure behavior

Usage:
    python scripts/performance_benchmark.py csv-write --rows 10000
    python scripts/performance_benchmark.py memory-stress --duration 30
    python scripts/performance_benchmark.py full-cycle --cycles 5
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.csv_writer import CsvWriter
from src.storage.memory_monitor import MemoryMonitor, MemoryState

# Phase 3: Use simplified logging setup
from src.utils.logging_utils import setup_logging
setup_logging(terminal_level='INFO')
logger = logging.getLogger(__name__)


@dataclass
class BenchmarkResult:
    """Results from a performance benchmark."""
    name: str
    duration_sec: float
    operations: int
    ops_per_sec: float
    memory_peak_mb: float
    memory_avg_mb: float
    success: bool
    details: dict[str, Any]


class PerformanceBenchmark:
    """Performance benchmarking suite."""
    
    def __init__(self):
        self.results: list[BenchmarkResult] = []
    
    def benchmark_csv_write(self, num_rows: int = 10000) -> BenchmarkResult:
        """Benchmark CSV write throughput.
        
        Args:
            num_rows: Number of rows to write
            
        Returns:
            BenchmarkResult with timing and throughput data
        """
        logger.info(f"Benchmarking CSV write with {num_rows} rows...")
        
        with TemporaryDirectory() as tmpdir:
            writer = CsvWriter(tmpdir)
            
            # Sample data
            header = ['timestamp', 'symbol', 'strike', 'expiry', 'ltp', 'volume', 'oi']
            rows = [
                ['2025-11-16T10:00:00', 'NIFTY', '24000', '2025-11-28', '150.5', '1000', '50000']
                for _ in range(num_rows)
            ]
            
            # Start memory monitoring
            monitor = MemoryMonitor(check_interval=0.1)
            monitor.start()
            
            memory_samples = []
            
            def collect_memory(stats):
                memory_samples.append(stats.rss_mb)
            
            monitor.register_callback(collect_memory)
            
            # Benchmark
            start = time.time()
            
            try:
                writer.append_many_rows('test/benchmark.csv', rows, header)
                success = True
            except Exception as e:
                logger.error(f"CSV write failed: {e}")
                success = False
            
            duration = time.time() - start
            
            monitor.stop()
            
            # Calculate metrics
            ops_per_sec = num_rows / duration if duration > 0 else 0
            memory_peak = max(memory_samples) if memory_samples else 0
            memory_avg = sum(memory_samples) / len(memory_samples) if memory_samples else 0
            
            result = BenchmarkResult(
                name='csv_write',
                duration_sec=duration,
                operations=num_rows,
                ops_per_sec=ops_per_sec,
                memory_peak_mb=memory_peak,
                memory_avg_mb=memory_avg,
                success=success,
                details={
                    'rows': num_rows,
                    'row_size_bytes': sys.getsizeof(rows[0]),
                    'total_bytes': sys.getsizeof(rows),
                }
            )
            
            self.results.append(result)
            return result
    
    def benchmark_memory_stress(self, duration_sec: int = 30, allocation_mb: int = 100) -> BenchmarkResult:
        """Benchmark memory backpressure behavior under stress.
        
        Args:
            duration_sec: Test duration in seconds
            allocation_mb: MB to allocate per second
            
        Returns:
            BenchmarkResult with backpressure metrics
        """
        logger.info(f"Benchmarking memory stress for {duration_sec}s...")
        
        monitor = MemoryMonitor(warn_mb=1024, critical_mb=2048, check_interval=0.5)
        monitor.start()
        
        backpressure_events = 0
        critical_events = 0
        memory_samples = []
        
        def check_backpressure(stats):
            memory_samples.append(stats.rss_mb)
            if stats.state == MemoryState.WARNING:
                nonlocal backpressure_events
                backpressure_events += 1
            elif stats.state == MemoryState.CRITICAL:
                nonlocal critical_events
                critical_events += 1
        
        monitor.register_callback(check_backpressure)
        
        allocations = []
        start = time.time()
        
        try:
            while time.time() - start < duration_sec:
                # Allocate memory
                chunk = bytearray(allocation_mb * 1024 * 1024)
                allocations.append(chunk)
                time.sleep(1)
            
            success = True
        except Exception as e:
            logger.error(f"Memory stress test failed: {e}")
            success = False
        finally:
            # Clean up
            allocations.clear()
        
        duration = time.time() - start
        monitor.stop()
        
        result = BenchmarkResult(
            name='memory_stress',
            duration_sec=duration,
            operations=len(allocations),
            ops_per_sec=len(allocations) / duration if duration > 0 else 0,
            memory_peak_mb=max(memory_samples) if memory_samples else 0,
            memory_avg_mb=sum(memory_samples) / len(memory_samples) if memory_samples else 0,
            success=success,
            details={
                'backpressure_events': backpressure_events,
                'critical_events': critical_events,
                'allocation_mb_per_sec': allocation_mb,
            }
        )
        
        self.results.append(result)
        return result
    
    def print_results(self) -> None:
        """Print benchmark results in a formatted table."""
        if not self.results:
            logger.info("No benchmark results to display")
            return
        
        print("\n" + "=" * 80)
        print("PERFORMANCE BENCHMARK RESULTS")
        print("=" * 80)
        
        for result in self.results:
            print(f"\n{result.name.upper()} ({'' if result.success else '❌ FAILED'})")
            print(f"  Duration:        {result.duration_sec:.3f}s")
            print(f"  Operations:      {result.operations:,}")
            print(f"  Throughput:      {result.ops_per_sec:,.0f} ops/sec")
            print(f"  Memory Peak:     {result.memory_peak_mb:.1f} MB")
            print(f"  Memory Avg:      {result.memory_avg_mb:.1f} MB")
            if result.details:
                print("  Details:")
                for key, value in result.details.items():
                    print(f"    {key}: {value}")
        
        print("\n" + "=" * 80)
    
    def export_json(self, filepath: Path) -> None:
        """Export results to JSON file.
        
        Args:
            filepath: Path to output JSON file
        """
        data = [asdict(r) for r in self.results]
        filepath.write_text(json.dumps(data, indent=2), encoding='utf-8')
        logger.info(f"Results exported to {filepath}")


def main():
    parser = argparse.ArgumentParser(description='G6 Performance Benchmarks')
    subparsers = parser.add_subparsers(dest='command', help='Benchmark to run')
    
    # CSV write benchmark
    csv_parser = subparsers.add_parser('csv-write', help='Benchmark CSV write throughput')
    csv_parser.add_argument('--rows', type=int, default=10000, help='Number of rows to write')
    
    # Memory stress benchmark
    mem_parser = subparsers.add_parser('memory-stress', help='Benchmark memory backpressure')
    mem_parser.add_argument('--duration', type=int, default=30, help='Test duration (seconds)')
    mem_parser.add_argument('--allocation-mb', type=int, default=100, help='MB to allocate per second')
    
    # Full suite
    subparsers.add_parser('full', help='Run full benchmark suite')
    
    # Export options
    parser.add_argument('--export', type=Path, help='Export results to JSON file')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    bench = PerformanceBenchmark()
    
    if args.command == 'csv-write':
        bench.benchmark_csv_write(num_rows=args.rows)
    elif args.command == 'memory-stress':
        bench.benchmark_memory_stress(duration_sec=args.duration, allocation_mb=args.allocation_mb)
    elif args.command == 'full':
        bench.benchmark_csv_write(num_rows=10000)
        bench.benchmark_memory_stress(duration_sec=10, allocation_mb=50)
    
    bench.print_results()
    
    if args.export:
        bench.export_json(args.export)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
