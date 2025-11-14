"""Staged pipeline executor for overlapping fetch/process/write phases.

Implements Phase 2 of the Cycle Performance Roadmap: pipelined execution with
backpressure control to overlap fetch(t+1) with process/write(t).

Architecture:
    FetchWorkers → FetchQueue → ProcessWorkers → ProcessQueue → WriteWorkers

Key Features:
- Bounded queues with backpressure between stages
- Per-cycle budget enforcement with graceful degradation
- Configurable worker pool sizes per stage
- Timeout-based work abandonment when over budget

Environment Variables:
    G6_PIPELINE_ENABLED: Enable staged pipeline (default 0)
    G6_PIPELINE_FETCH_WORKERS: Fetch worker count (default 4)
    G6_PIPELINE_PROCESS_WORKERS: Process worker count (default 2)
    G6_PIPELINE_WRITE_WORKERS: Write worker count (default 2)
    G6_PIPELINE_QUEUE_SIZE: Queue size between stages (default 100)
    G6_CYCLE_BUDGET_SECONDS: Max cycle duration (default 60)
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class WorkItem:
    """Work item passed between pipeline stages."""
    index: str
    expiry_rule: str
    data: Any = None
    timestamp: float = 0.0
    stage: str = 'pending'
    error: Exception | None = None


@dataclass
class PipelineConfig:
    """Configuration for staged pipeline."""
    fetch_workers: int = 4
    process_workers: int = 2
    write_workers: int = 2
    queue_size: int = 100
    cycle_budget: float = 60.0
    enabled: bool = False
    
    @classmethod
    def from_env(cls) -> PipelineConfig:
        """Load configuration from environment variables."""
        from src.config.env_config import EnvConfig
        
        return cls(
            enabled=EnvConfig.get_bool('G6_PIPELINE_ENABLED', False),
            fetch_workers=EnvConfig.get_int('G6_PIPELINE_FETCH_WORKERS', 4),
            process_workers=EnvConfig.get_int('G6_PIPELINE_PROCESS_WORKERS', 2),
            write_workers=EnvConfig.get_int('G6_PIPELINE_WRITE_WORKERS', 2),
            queue_size=EnvConfig.get_int('G6_PIPELINE_QUEUE_SIZE', 100),
            cycle_budget=EnvConfig.get_float('G6_CYCLE_BUDGET_SECONDS', 60.0),
        )


class StagedPipeline:
    """Staged pipeline executor with backpressure control.
    
    Executes collection in three stages: fetch → process → write.
    Each stage runs in its own thread pool, with bounded queues providing
    backpressure between stages.
    """
    
    def __init__(
        self,
        config: PipelineConfig,
        fetch_fn: Callable[[WorkItem], Any],
        process_fn: Callable[[WorkItem], Any],
        write_fn: Callable[[WorkItem], None],
    ):
        """Initialize staged pipeline.
        
        Args:
            config: Pipeline configuration
            fetch_fn: Function to fetch data for a work item
            process_fn: Function to process fetched data
            write_fn: Function to write processed data
        """
        self.config = config
        self.fetch_fn = fetch_fn
        self.process_fn = process_fn
        self.write_fn = write_fn
        
        # Queues between stages (bounded for backpressure)
        self.fetch_queue: queue.Queue[WorkItem | None] = queue.Queue(maxsize=config.queue_size)
        self.process_queue: queue.Queue[WorkItem | None] = queue.Queue(maxsize=config.queue_size)
        self.write_queue: queue.Queue[WorkItem | None] = queue.Queue(maxsize=config.queue_size)
        
        # Thread pools for each stage
        self.fetch_pool: ThreadPoolExecutor | None = None
        self.process_pool: ThreadPoolExecutor | None = None
        self.write_pool: ThreadPoolExecutor | None = None
        
        # Cycle timing
        self.cycle_start = 0.0
        self.cycle_deadline = 0.0
        
        # Metrics
        self.completed_items = 0
        self.dropped_items = 0
        self.fetch_errors = 0
        self.process_errors = 0
        self.write_errors = 0
    
    def start_cycle(self) -> None:
        """Start a new collection cycle."""
        self.cycle_start = time.time()
        self.cycle_deadline = self.cycle_start + self.config.cycle_budget
        
        # Reset metrics
        self.completed_items = 0
        self.dropped_items = 0
        self.fetch_errors = 0
        self.process_errors = 0
        self.write_errors = 0
        
        # Create thread pools
        self.fetch_pool = ThreadPoolExecutor(max_workers=self.config.fetch_workers, thread_name_prefix='pipeline-fetch')
        self.process_pool = ThreadPoolExecutor(max_workers=self.config.process_workers, thread_name_prefix='pipeline-process')
        self.write_pool = ThreadPoolExecutor(max_workers=self.config.write_workers, thread_name_prefix='pipeline-write')
        
        # Start worker threads for each stage
        for _ in range(self.config.process_workers):
            self.process_pool.submit(self._process_worker)
        
        for _ in range(self.config.write_workers):
            self.write_pool.submit(self._write_worker)
    
    def submit_work(self, item: WorkItem) -> bool:
        """Submit work item to the pipeline.
        
        Args:
            item: Work item to process
        
        Returns:
            True if submitted, False if over budget or queue full
        """
        # Check budget
        if time.time() >= self.cycle_deadline:
            self.dropped_items += 1
            logger.debug("Dropped work item %s:%s - over budget", item.index, item.expiry_rule)
            return False
        
        # Submit to fetch queue with timeout
        try:
            self.fetch_queue.put(item, timeout=0.5)
            
            # Submit fetch task
            if self.fetch_pool:
                self.fetch_pool.submit(self._fetch_worker, item)
            
            return True
        except queue.Full:
            self.dropped_items += 1
            logger.warning("Fetch queue full, dropped work item %s:%s", item.index, item.expiry_rule)
            return False
    
    def wait_for_completion(self, timeout: float | None = None) -> dict[str, Any]:
        """Wait for all work to complete or timeout.
        
        Args:
            timeout: Max time to wait (None = use remaining budget)
        
        Returns:
            Dict with completion stats
        """
        if timeout is None:
            timeout = max(0.0, self.cycle_deadline - time.time())
        
        # Signal workers to stop by sending poison pills
        try:
            self.fetch_queue.put(None, timeout=0.5)
        except queue.Full:
            pass
        
        try:
            self.process_queue.put(None, timeout=0.5)
        except queue.Full:
            pass
        
        try:
            self.write_queue.put(None, timeout=0.5)
        except queue.Full:
            pass
        
        # Shutdown pools
        if self.fetch_pool:
            self.fetch_pool.shutdown(wait=True, cancel_futures=False)
        if self.process_pool:
            self.process_pool.shutdown(wait=True, cancel_futures=False)
        if self.write_pool:
            self.write_pool.shutdown(wait=True, cancel_futures=False)
        
        elapsed = time.time() - self.cycle_start
        
        return {
            'completed': self.completed_items,
            'dropped': self.dropped_items,
            'fetch_errors': self.fetch_errors,
            'process_errors': self.process_errors,
            'write_errors': self.write_errors,
            'elapsed': elapsed,
            'over_budget': elapsed > self.config.cycle_budget,
        }
    
    def _fetch_worker(self, item: WorkItem) -> None:
        """Fetch worker: execute fetch and enqueue for processing."""
        try:
            # Check budget
            if time.time() >= self.cycle_deadline:
                self.dropped_items += 1
                return
            
            # Execute fetch
            item.stage = 'fetching'
            item.timestamp = time.time()
            result = self.fetch_fn(item)
            
            # Update item with result
            item.data = result
            item.stage = 'fetched'
            
            # Enqueue for processing with backpressure
            try:
                remaining = max(0.0, self.cycle_deadline - time.time())
                self.process_queue.put(item, timeout=min(remaining, 1.0))
            except queue.Full:
                self.dropped_items += 1
                logger.debug("Process queue full, dropped item %s:%s", item.index, item.expiry_rule)
        
        except Exception as e:
            self.fetch_errors += 1
            item.error = e
            logger.debug("Fetch error for %s:%s - %s", item.index, item.expiry_rule, e)
    
    def _process_worker(self) -> None:
        """Process worker: consume from fetch queue, process, enqueue for write."""
        while True:
            try:
                # Get item with timeout to check budget periodically
                remaining = max(0.1, self.cycle_deadline - time.time())
                try:
                    item = self.process_queue.get(timeout=min(remaining, 1.0))
                except queue.Empty:
                    if time.time() >= self.cycle_deadline:
                        break
                    continue
                
                # Poison pill = shutdown
                if item is None:
                    break
                
                # Check budget
                if time.time() >= self.cycle_deadline:
                    self.dropped_items += 1
                    continue
                
                # Skip if fetch failed
                if item.error:
                    continue
                
                # Execute process
                item.stage = 'processing'
                result = self.process_fn(item)
                item.data = result
                item.stage = 'processed'
                
                # Enqueue for write with backpressure
                try:
                    remaining = max(0.0, self.cycle_deadline - time.time())
                    self.write_queue.put(item, timeout=min(remaining, 1.0))
                except queue.Full:
                    self.dropped_items += 1
                    logger.debug("Write queue full, dropped item %s:%s", item.index, item.expiry_rule)
            
            except Exception as e:
                self.process_errors += 1
                if 'item' in locals():
                    logger.debug("Process error for %s:%s - %s", item.index, item.expiry_rule, e)
    
    def _write_worker(self) -> None:
        """Write worker: consume from process queue and write."""
        while True:
            try:
                # Get item with timeout
                remaining = max(0.1, self.cycle_deadline - time.time())
                try:
                    item = self.write_queue.get(timeout=min(remaining, 1.0))
                except queue.Empty:
                    if time.time() >= self.cycle_deadline:
                        break
                    continue
                
                # Poison pill = shutdown
                if item is None:
                    break
                
                # Check budget
                if time.time() >= self.cycle_deadline:
                    self.dropped_items += 1
                    continue
                
                # Skip if error in earlier stage
                if item.error:
                    continue
                
                # Execute write
                item.stage = 'writing'
                self.write_fn(item)
                item.stage = 'complete'
                
                self.completed_items += 1
            
            except Exception as e:
                self.write_errors += 1
                if 'item' in locals():
                    logger.debug("Write error for %s:%s - %s", item.index, item.expiry_rule, e)


__all__ = [
    'StagedPipeline',
    'WorkItem',
    'PipelineConfig',
]
