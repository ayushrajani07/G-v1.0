"""Test script to demonstrate color-coded logging output."""
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.log_helpers import log_cycle_complete
from src.utils.logging_utils import setup_logging

# Setup logging
setup_logging(terminal_level='INFO')
logger = logging.getLogger(__name__)

print("=" * 70)
print("Testing Color-Coded Metrics")
print("=" * 70)
print()
print("Color Thresholds:")
print("  SUCCESS (Green):  ≥95% success AND ≥90% coverage")
print("  WARNING (Yellow): ≥80% success AND ≥75% coverage")
print("  ERROR (Red):      Below thresholds")
print()
print("Metric Colors:")
print("  Green:  Excellent (≥95% for success, ≥90% for coverage)")
print("  Yellow: Good (≥80% for success, ≥75% for coverage)")
print("  Red:    Needs attention (<80% or <75%)")
print()

# Test with varied metrics showing all threshold levels
log_cycle_complete(logger, 8100, {
    "NIFTY": {
        "success_pct": 100.0,    # Green
        "field_coverage_pct": 98.5,  # Green
        "strike_count": 104
    },
    "BANKNIFTY": {
        "success_pct": 100.0,    # Green
        "field_coverage_pct": 85.0,  # Yellow
        "strike_count": 84
    },
    "FINNIFTY": {
        "success_pct": 72.5,     # Red
        "field_coverage_pct": 45.0,  # Red
        "strike_count": 32
    },
    "SENSEX": {
        "success_pct": 100.0,    # Green
        "field_coverage_pct": 67.5,  # Red
        "strike_count": 168
    }
})

print("=" * 70)
print("✓ Color-coded logging test complete!")
print("=" * 70)
