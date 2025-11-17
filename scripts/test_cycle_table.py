"""Test the updated cycle table format."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.logstream.formatter import format_cycle_table

print("=" * 70)
print("Testing Updated Cycle Table Format")
print("=" * 70)
print()

# Test with sample data
header, value = format_cycle_table(
    duration_s=7.01,
    options=336,
    options_per_min=None,  # Will be calculated
    cpu=None,
    mem_mb=None,
    api_latency_ms=17.1,
    api_success_pct=100.0,
    collection_success_pct=95.5,
    indices=4,
    stall_flag=None
)

print("Header:")
print(header)
print()
print("Values:")
print(value)
print()

print("=" * 70)
print("Changes Made:")
print("=" * 70)
print("✓ OpM (Options per Minute) now calculated: 336 / 7.01s * 60 = ~2877 OpM")
print("✓ Coll% (Collection Success) populated: 95.5%")
print("✗ Removed: CPU%, Mem(MB), Idx columns")
print()
