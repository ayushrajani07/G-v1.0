"""Memory backpressure control system for G6 Platform.

Part of Phase 3.2: Performance Improvements (2025-11-16)

Provides memory monitoring and backpressure controls to prevent OOM errors
during high-throughput data collection cycles.

Features:
- Real-time memory usage monitoring
- Configurable memory thresholds (warn, critical)
- Automatic backpressure triggers
- Integration with CSV writer queue
- Metrics for observability

Environment Variables:
    G6_MEMORY_WARN_MB: Warning threshold in MB (default: 2048)
    G6_MEMORY_CRITICAL_MB: Critical threshold in MB (default: 3072)
    G6_MEMORY_CHECK_INTERVAL_SEC: Check interval (default: 5)
    G6_ENABLE_MEMORY_BACKPRESSURE: Enable backpressure (default: 1)

Usage:
    from src.storage.memory_monitor import MemoryMonitor
    
    monitor = MemoryMonitor()
    monitor.start()
    
    # Check before adding to queue
    if monitor.should_apply_backpressure():
        logger.warning("Memory backpressure active, slowing collection")
        await asyncio.sleep(1)
"""
from __future__ import annotations

import logging
import os
import platform
import psutil
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from src.config.env_config import EnvConfig

logger = logging.getLogger(__name__)


class MemoryState(Enum):
    """Memory pressure states."""
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class MemoryStats:
    """Memory usage statistics."""
    rss_mb: float  # Resident set size (actual RAM usage)
    vms_mb: float  # Virtual memory size
    percent: float  # Percentage of total system memory
    available_mb: float  # Available system memory
    total_mb: float  # Total system memory
    state: MemoryState
    timestamp: float


class MemoryMonitor:
    """Monitors process memory usage and applies backpressure when needed.
    
    Uses psutil to track RSS (Resident Set Size) and applies backpressure
    when memory usage exceeds configured thresholds.
    """
    
    def __init__(
        self,
        warn_mb: int | None = None,
        critical_mb: int | None = None,
        check_interval: float | None = None,
    ):
        """Initialize memory monitor.
        
        Args:
            warn_mb: Warning threshold in MB (default from env or 2048)
            critical_mb: Critical threshold in MB (default from env or 3072)
            check_interval: Check interval in seconds (default from env or 5)
        """
        self.warn_mb = warn_mb or EnvConfig.get_int('G6_MEMORY_WARN_MB', 2048)
        self.critical_mb = critical_mb or EnvConfig.get_int('G6_MEMORY_CRITICAL_MB', 3072)
        self.check_interval = check_interval or EnvConfig.get_float('G6_MEMORY_CHECK_INTERVAL_SEC', 5.0)
        self.enabled = EnvConfig.get_bool('G6_ENABLE_MEMORY_BACKPRESSURE', True)
        
        self._process = psutil.Process()
        self._current_stats: MemoryStats | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[MemoryStats], None]] = []
        
        # Metrics (optional - only if metrics system available)
        self._setup_metrics()
    
    def _setup_metrics(self) -> None:
        """Setup Prometheus metrics if available."""
        try:
            from src.metrics.metrics import g6_memory_usage_mb, g6_memory_backpressure_active
            self._memory_gauge = g6_memory_usage_mb
            self._backpressure_gauge = g6_memory_backpressure_active
        except ImportError:
            self._memory_gauge = None
            self._backpressure_gauge = None
    
    def start(self) -> None:
        """Start background monitoring thread."""
        if not self.enabled:
            logger.info("Memory backpressure disabled (G6_ENABLE_MEMORY_BACKPRESSURE=0)")
            return
        
        if self._thread is not None and self._thread.is_alive():
            return
        
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name='memory-monitor',
            daemon=True
        )
        self._thread.start()
        logger.info(
            "Memory monitor started: warn=%dMB critical=%dMB interval=%.1fs",
            self.warn_mb,
            self.critical_mb,
            self.check_interval
        )
    
    def stop(self, timeout: float = 5.0) -> None:
        """Stop monitoring thread.
        
        Args:
            timeout: Maximum time to wait for thread to finish
        """
        if self._thread is None:
            return
        
        self._stop_event.set()
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            logger.warning("Memory monitor thread did not stop cleanly")
    
    def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while not self._stop_event.is_set():
            try:
                stats = self._collect_stats()
                
                with self._lock:
                    old_state = self._current_stats.state if self._current_stats else MemoryState.NORMAL
                    self._current_stats = stats
                
                # Update metrics
                if self._memory_gauge:
                    self._memory_gauge.set(stats.rss_mb)
                if self._backpressure_gauge:
                    self._backpressure_gauge.set(1 if stats.state != MemoryState.NORMAL else 0)
                
                # Log state transitions
                if stats.state != old_state:
                    self._log_state_change(old_state, stats)
                
                # Notify callbacks
                for callback in self._callbacks:
                    try:
                        callback(stats)
                    except Exception as e:
                        logger.error("Memory monitor callback failed: %s", e)
                
            except Exception as e:
                logger.error("Memory monitoring failed: %s", e, exc_info=True)
            
            # Sleep with interrupt check
            self._stop_event.wait(self.check_interval)
    
    def _collect_stats(self) -> MemoryStats:
        """Collect current memory statistics."""
        mem_info = self._process.memory_info()
        sys_mem = psutil.virtual_memory()
        
        rss_mb = mem_info.rss / (1024 * 1024)
        vms_mb = mem_info.vms / (1024 * 1024)
        percent = self._process.memory_percent()
        available_mb = sys_mem.available / (1024 * 1024)
        total_mb = sys_mem.total / (1024 * 1024)
        
        # Determine state
        if rss_mb >= self.critical_mb:
            state = MemoryState.CRITICAL
        elif rss_mb >= self.warn_mb:
            state = MemoryState.WARNING
        else:
            state = MemoryState.NORMAL
        
        return MemoryStats(
            rss_mb=rss_mb,
            vms_mb=vms_mb,
            percent=percent,
            available_mb=available_mb,
            total_mb=total_mb,
            state=state,
            timestamp=time.time()
        )
    
    def _log_state_change(self, old_state: MemoryState, stats: MemoryStats) -> None:
        """Log memory state transitions."""
        if stats.state == MemoryState.CRITICAL:
            logger.error(
                "CRITICAL memory usage: %.1fMB (%.1f%% of system) - backpressure active",
                stats.rss_mb,
                stats.percent
            )
        elif stats.state == MemoryState.WARNING:
            logger.warning(
                "HIGH memory usage: %.1fMB (%.1f%% of system) - approaching limit",
                stats.rss_mb,
                stats.percent
            )
        else:
            logger.info(
                "Memory usage returned to normal: %.1fMB (%.1f%% of system)",
                stats.rss_mb,
                stats.percent
            )
    
    def get_current_stats(self) -> MemoryStats | None:
        """Get current memory statistics.
        
        Returns:
            Current MemoryStats or None if not started
        """
        with self._lock:
            return self._current_stats
    
    def should_apply_backpressure(self) -> bool:
        """Check if backpressure should be applied.
        
        Returns:
            True if memory usage is WARNING or CRITICAL
        """
        if not self.enabled:
            return False
        
        stats = self.get_current_stats()
        if stats is None:
            return False
        
        return stats.state in (MemoryState.WARNING, MemoryState.CRITICAL)
    
    def is_critical(self) -> bool:
        """Check if memory usage is critical.
        
        Returns:
            True if memory usage is CRITICAL
        """
        stats = self.get_current_stats()
        if stats is None:
            return False
        
        return stats.state == MemoryState.CRITICAL
    
    def register_callback(self, callback: Callable[[MemoryStats], None]) -> None:
        """Register a callback to be notified of memory stats updates.
        
        Args:
            callback: Function to call with MemoryStats on each check
        """
        self._callbacks.append(callback)
    
    def get_memory_info(self) -> dict[str, float]:
        """Get formatted memory information for logging.
        
        Returns:
            Dictionary with memory metrics
        """
        stats = self.get_current_stats()
        if stats is None:
            return {'error': 'Monitor not started'}
        
        return {
            'rss_mb': round(stats.rss_mb, 1),
            'vms_mb': round(stats.vms_mb, 1),
            'percent': round(stats.percent, 2),
            'available_mb': round(stats.available_mb, 1),
            'state': stats.state.value,
            'warn_threshold_mb': self.warn_mb,
            'critical_threshold_mb': self.critical_mb,
        }


# Global singleton instance
_monitor: MemoryMonitor | None = None


def get_memory_monitor() -> MemoryMonitor:
    """Get global memory monitor instance (lazy initialization).
    
    Returns:
        Global MemoryMonitor instance
    """
    global _monitor
    if _monitor is None:
        _monitor = MemoryMonitor()
    return _monitor


def start_memory_monitoring() -> None:
    """Start global memory monitoring (idempotent)."""
    monitor = get_memory_monitor()
    monitor.start()


def stop_memory_monitoring() -> None:
    """Stop global memory monitoring."""
    if _monitor is not None:
        _monitor.stop()


__all__ = [
    'MemoryMonitor',
    'MemoryState',
    'MemoryStats',
    'get_memory_monitor',
    'start_memory_monitoring',
    'stop_memory_monitoring',
]
