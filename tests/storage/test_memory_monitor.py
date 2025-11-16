"""Tests for memory backpressure monitoring system.

Tests for Phase 3.2: Performance Improvements
"""
import time
import pytest

from src.storage.memory_monitor import (
    MemoryMonitor,
    MemoryState,
    get_memory_monitor,
    start_memory_monitoring,
    stop_memory_monitoring,
)


def test_memory_monitor_initialization():
    """Test basic monitor initialization."""
    monitor = MemoryMonitor(warn_mb=1024, critical_mb=2048, check_interval=1.0)
    
    assert monitor.warn_mb == 1024
    assert monitor.critical_mb == 2048
    assert monitor.check_interval == 1.0


def test_memory_stats_collection():
    """Test that memory stats can be collected."""
    monitor = MemoryMonitor()
    stats = monitor._collect_stats()
    
    assert stats.rss_mb > 0
    assert stats.vms_mb > 0
    assert stats.percent > 0
    assert stats.available_mb > 0
    assert stats.total_mb > 0
    assert stats.state in (MemoryState.NORMAL, MemoryState.WARNING, MemoryState.CRITICAL)


def test_monitor_start_stop():
    """Test starting and stopping the monitor."""
    monitor = MemoryMonitor(check_interval=0.1)
    
    assert monitor._thread is None
    monitor.start()
    assert monitor._thread is not None
    assert monitor._thread.is_alive()
    
    # Wait for at least one check
    time.sleep(0.2)
    
    stats = monitor.get_current_stats()
    assert stats is not None
    assert stats.rss_mb > 0
    
    monitor.stop()
    assert not monitor._thread.is_alive()


def test_backpressure_detection():
    """Test backpressure state detection."""
    # Normal state (very high thresholds)
    monitor = MemoryMonitor(warn_mb=100000, critical_mb=200000)
    monitor.start()
    time.sleep(0.1)
    
    assert not monitor.should_apply_backpressure()
    assert not monitor.is_critical()
    
    monitor.stop()
    
    # Warning state (very low warn threshold)
    monitor = MemoryMonitor(warn_mb=1, critical_mb=200000, check_interval=0.1)
    monitor.start()
    time.sleep(0.2)
    
    assert monitor.should_apply_backpressure()
    assert not monitor.is_critical()
    
    monitor.stop()
    
    # Critical state (very low critical threshold)
    monitor = MemoryMonitor(warn_mb=1, critical_mb=10, check_interval=0.1)
    monitor.start()
    time.sleep(0.2)
    
    assert monitor.should_apply_backpressure()
    assert monitor.is_critical()
    
    monitor.stop()


def test_disabled_monitor():
    """Test that disabled monitor doesn't apply backpressure."""
    monitor = MemoryMonitor(warn_mb=1, critical_mb=10)
    monitor.enabled = False
    
    monitor.start()
    time.sleep(0.1)
    
    assert not monitor.should_apply_backpressure()
    assert not monitor.is_critical()
    
    monitor.stop()


def test_memory_info():
    """Test getting formatted memory info."""
    monitor = MemoryMonitor()
    
    # Before start
    info = monitor.get_memory_info()
    assert 'error' in info
    
    # After start
    monitor.start()
    time.sleep(0.1)
    
    info = monitor.get_memory_info()
    assert 'rss_mb' in info
    assert 'state' in info
    assert 'warn_threshold_mb' in info
    assert info['rss_mb'] > 0
    
    monitor.stop()


def test_callback_registration():
    """Test callback registration and invocation."""
    monitor = MemoryMonitor(check_interval=0.1)
    
    callback_called = []
    
    def callback(stats):
        callback_called.append(stats)
    
    monitor.register_callback(callback)
    monitor.start()
    
    time.sleep(0.3)  # Wait for multiple checks
    
    monitor.stop()
    
    assert len(callback_called) >= 2  # At least 2 checks
    assert all(isinstance(s.rss_mb, float) for s in callback_called)


def test_global_monitor_singleton():
    """Test global monitor singleton."""
    monitor1 = get_memory_monitor()
    monitor2 = get_memory_monitor()
    
    assert monitor1 is monitor2  # Same instance


def test_start_stop_global_monitoring():
    """Test global monitoring start/stop."""
    start_memory_monitoring()
    monitor = get_memory_monitor()
    
    assert monitor._thread is not None
    assert monitor._thread.is_alive()
    
    stop_memory_monitoring()
    assert not monitor._thread.is_alive()


def test_multiple_start_calls():
    """Test that multiple start() calls are idempotent."""
    monitor = MemoryMonitor(check_interval=0.1)
    
    monitor.start()
    thread1 = monitor._thread
    
    monitor.start()  # Second call
    thread2 = monitor._thread
    
    assert thread1 is thread2  # Same thread
    
    monitor.stop()


def test_state_transitions(caplog):
    """Test logging of state transitions."""
    import logging
    caplog.set_level(logging.WARNING)
    
    # Start with normal, transition to warning
    monitor = MemoryMonitor(warn_mb=1, critical_mb=200000, check_interval=0.1)
    monitor.start()
    
    time.sleep(0.2)
    
    monitor.stop()
    
    # Should have logged warning about high memory
    assert any('memory usage' in record.message.lower() for record in caplog.records)
