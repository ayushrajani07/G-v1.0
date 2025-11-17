"""Test script for Phase 1 simplified logging implementation."""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.logging_utils import setup_logging
from src.utils.log_helpers import (
    log_success,
    log_warning,
    log_error,
    log_cycle_complete,
    log_index_complete
)
import logging

def test_simplified_logging():
    """Test the new simplified logging system."""
    print("=" * 60)
    print("Testing Phase 1: Simplified Logging")
    print("=" * 60)
    print()
    
    # Setup logging (INFO level for testing)
    setup_logging(terminal_level="INFO", debug_file="logs/test_debug.log")
    logger = logging.getLogger("test")
    
    print("1. Testing log_success:")
    log_success(logger, "TEST", "Simplified logging works!", test_metric=123)
    print()
    
    print("2. Testing log_warning:")
    log_warning(logger, "TEST", "Partial data received", missing_fields=5)
    print()
    
    print("3. Testing log_error:")
    try:
        raise ValueError("Test error")
    except Exception as e:
        log_error(logger, "TEST", "Error occurred", exc=e, retry_count=3)
    print()
    
    print("4. Testing log_index_complete:")
    log_index_complete(
        logger,
        index="NIFTY",
        strike_count=234,
        duration_ms=1234,
        success_pct=98.5,
        field_coverage_pct=95.2,
        iv_missing=2
    )
    print()
    
    print("5. Testing log_cycle_complete:")
    log_cycle_complete(
        logger,
        duration_ms=2300,
        index_metrics={
            "NIFTY": {
                "success_pct": 98.5,
                "field_coverage_pct": 95.2,
                "strike_count": 234
            },
            "BANKNIFTY": {
                "success_pct": 87.3,
                "field_coverage_pct": 89.1,
                "strike_count": 187
            }
        }
    )
    print()
    
    print("=" * 60)
    print("✓ Phase 1 logging implementation test complete!")
    print("=" * 60)
    print()
    print("Check logs/test_debug.log for detailed debug output")

if __name__ == "__main__":
    test_simplified_logging()
