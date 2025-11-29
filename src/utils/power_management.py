"""Power management utilities to prevent system sleep during collection.

Prevents the system from entering sleep/hibernate mode while the orchestrator
is actively collecting data. This is critical for unattended operation where
collection cycles must complete without interruption.

Platform Support:
    - Windows: Uses SetThreadExecutionState to prevent sleep
    - Linux/macOS: Uses caffeine-like approach with periodic wake signals
    - Fallback: No-op if platform-specific calls unavailable

Environment Variables:
    G6_PREVENT_SLEEP: Enable sleep prevention (default: True)
    G6_WAKE_REASON: Custom reason string for wake lock (Windows)

Usage:
    with prevent_sleep():
        # System won't sleep during this block
        run_collection_cycle()
"""
from __future__ import annotations

import logging
import platform
import sys
from contextlib import contextmanager
from typing import Any, Generator

from src.config.env_config import EnvConfig

logger = logging.getLogger(__name__)

__all__ = ["prevent_sleep", "allow_sleep", "is_sleep_prevention_enabled"]


def is_sleep_prevention_enabled() -> bool:
    """Check if sleep prevention is enabled via environment."""
    return EnvConfig.get_bool('G6_PREVENT_SLEEP', True)


class _WindowsSleepPrevention:
    """Windows-specific sleep prevention using SetThreadExecutionState."""
    
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ES_DISPLAY_REQUIRED = 0x00000002
    ES_AWAYMODE_REQUIRED = 0x00000040
    
    def __init__(self):
        self._ctypes = None
        self._kernel32 = None
        self._previous_state = None
        self._active = False
        self._init_windows_api()
    
    def _init_windows_api(self):
        """Initialize Windows API access via ctypes."""
        try:
            import ctypes
            self._ctypes = ctypes
            self._kernel32 = ctypes.windll.kernel32
        except Exception as e:
            logger.debug("Failed to initialize Windows API: %s", e)
    
    def prevent_sleep(self) -> bool:
        """Prevent system from sleeping. Returns True if successful.
        
        Note: SetThreadExecutionState works with standard user privileges.
        No administrator rights required.
        """
        if not self._kernel32 or self._active:
            return False
        
        try:
            # ES_CONTINUOUS | ES_SYSTEM_REQUIRED prevents system sleep
            # ES_DISPLAY_REQUIRED keeps display on (optional, can be removed if not needed)
            # These flags work with standard user privileges (no admin needed)
            flags = self.ES_CONTINUOUS | self.ES_SYSTEM_REQUIRED
            
            # Optional: Add display required if you want to keep screen on too
            # flags |= self.ES_DISPLAY_REQUIRED
            
            result = self._kernel32.SetThreadExecutionState(flags)
            if result == 0:
                # API call failed (rare, but possible)
                logger.warning("SetThreadExecutionState returned 0 (may indicate permission issue)")
                return False
            
            self._previous_state = result
            self._active = True
            logger.info("Sleep prevention enabled (Windows) - no admin rights required")
            return True
        except Exception as e:
            logger.warning("Failed to prevent sleep on Windows: %s", e)
            logger.debug("Note: Sleep prevention should work without admin rights", exc_info=True)
            return False
    
    def allow_sleep(self) -> bool:
        """Allow system to sleep again. Returns True if successful."""
        if not self._kernel32 or not self._active:
            return False
        
        try:
            # ES_CONTINUOUS alone resets to normal power management
            self._kernel32.SetThreadExecutionState(self.ES_CONTINUOUS)
            self._active = False
            logger.info("Sleep prevention disabled (Windows)")
            return True
        except Exception as e:
            logger.warning("Failed to restore normal sleep mode on Windows: %s", e)
            return False


class _UnixSleepPrevention:
    """Unix-like (Linux/macOS) sleep prevention using systemd-inhibit or caffeinate."""
    
    def __init__(self):
        self._process = None
        self._method = self._detect_method()
    
    def _detect_method(self) -> str | None:
        """Detect available sleep prevention method."""
        import shutil
        
        # macOS: caffeinate
        if platform.system() == 'Darwin' and shutil.which('caffeinate'):
            return 'caffeinate'
        
        # Linux: systemd-inhibit
        if platform.system() == 'Linux' and shutil.which('systemd-inhibit'):
            return 'systemd-inhibit'
        
        logger.debug("No native sleep prevention method found for %s", platform.system())
        return None
    
    def prevent_sleep(self) -> bool:
        """Prevent system from sleeping. Returns True if successful."""
        if not self._method or self._process:
            return False
        
        try:
            import subprocess
            
            if self._method == 'caffeinate':
                # macOS: caffeinate -d prevents display sleep, -i prevents idle sleep
                self._process = subprocess.Popen(
                    ['caffeinate', '-i', '-w', str(subprocess.os.getpid())],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                logger.info("Sleep prevention enabled (macOS/caffeinate)")
                return True
            
            elif self._method == 'systemd-inhibit':
                # Linux: systemd-inhibit prevents sleep/shutdown
                reason = EnvConfig.get_str('G6_WAKE_REASON', 'G6 options collection in progress')
                self._process = subprocess.Popen(
                    ['systemd-inhibit', '--what=sleep:idle', f'--who=g6_platform', f'--why={reason}',
                     '--mode=block', 'sleep', 'infinity'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                logger.info("Sleep prevention enabled (Linux/systemd-inhibit)")
                return True
            
        except Exception as e:
            logger.warning("Failed to prevent sleep on %s: %s", platform.system(), e)
            return False
        
        return False
    
    def allow_sleep(self) -> bool:
        """Allow system to sleep again. Returns True if successful."""
        if not self._process:
            return False
        
        try:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except Exception:
                self._process.kill()
            self._process = None
            logger.info("Sleep prevention disabled (%s)", platform.system())
            return True
        except Exception as e:
            logger.warning("Failed to restore sleep on %s: %s", platform.system(), e)
            return False


# Select appropriate implementation based on platform
_sleep_prevention: Any = None

if platform.system() == 'Windows':
    _sleep_prevention = _WindowsSleepPrevention()
elif platform.system() in ('Linux', 'Darwin'):
    _sleep_prevention = _UnixSleepPrevention()
else:
    logger.debug("Sleep prevention not implemented for platform: %s", platform.system())


def prevent_sleep() -> bool:
    """Prevent system from entering sleep mode.
    
    Works with standard user privileges - no administrator rights required.
    Uses user-level APIs that are available to all processes:
    - Windows: SetThreadExecutionState (user-level API)
    - macOS: caffeinate (user utility)
    - Linux: systemd-inhibit (user-level when run as current user)
    
    Returns:
        True if sleep prevention was successfully enabled, False otherwise
        
    Note:
        Failure to prevent sleep is non-fatal. The application will continue
        running but may be interrupted if the system enters sleep mode.
    """
    if not is_sleep_prevention_enabled():
        logger.debug("Sleep prevention disabled via G6_PREVENT_SLEEP=false")
        return False
    
    if not _sleep_prevention:
        logger.debug("Sleep prevention not available on this platform")
        return False
    
    return _sleep_prevention.prevent_sleep()


def allow_sleep() -> bool:
    """Allow system to enter sleep mode again.
    
    Returns:
        True if normal sleep behavior was restored, False otherwise
    """
    if not _sleep_prevention:
        return False
    
    return _sleep_prevention.allow_sleep()


@contextmanager
def prevent_sleep_context() -> Generator[None, None, None]:
    """Context manager to prevent sleep during a block of code.
    
    Example:
        with prevent_sleep_context():
            run_long_operation()
    """
    enabled = prevent_sleep()
    try:
        yield
    finally:
        if enabled:
            allow_sleep()
