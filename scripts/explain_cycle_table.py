"""Explain the cycle table columns and test the fixes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.logstream.formatter import format_cycle_table

print("=" * 80)
print("Cycle Table Column Explanations")
print("=" * 80)
print()

columns = [
    ("Dur(s)", "Cycle duration in seconds"),
    ("Opts", "Total options collected across all indices"),
    ("OpM", "Options per minute (Opts / Duration * 60)"),
    ("API(ms)", "Average API response time in milliseconds"),
    ("API%", "API success rate percentage"),
    ("Coll%", "Collection success rate (strike coverage avg across indices)"),
    ("Stall", "Stall flag - indicates if collection is stalled/stuck (always '-' = no stall)"),
    ("Status", "Overall cycle status: OK, DEGRADED, NO_DATA, or STALL")
]

for col, desc in columns:
    print(f"  {col:10} - {desc}")

print()
print("=" * 80)
print("Testing Fixed OpM and Coll% Calculation")
print("=" * 80)
print()

# Test case: 336 options in 6.87 seconds with 95% collection success
header, value = format_cycle_table(
    duration_s=6.87,
    options=336,
    options_per_min=None,  # Should be calculated: 336/6.87*60 = 2935.4
    cpu=None,
    mem_mb=None,
    api_latency_ms=17.6,
    api_success_pct=100.0,
    collection_success_pct=95.0,  # Should show 95.0
    indices=4,
    stall_flag=None  # Means no stall
)

print("Expected OpM: ~2935 (336 options / 6.87s * 60)")
print("Expected Coll%: 95.0%")
print()
print("Header:")
print(header)
print()
print("Values:")
print(value)
print()

print("=" * 80)
print("Status Values Explained:")
print("=" * 80)
print()
print("  OK       - Normal operation, good data quality")
print("  DEGRADED - API or collection success < 90%")
print("  NO_DATA  - Zero options collected")
print("  STALL    - Collection appears stuck (stall_flag set)")
print()
print("Note: Stall flag is currently always None (unused feature)")
print("      Could be used to detect when cycles take abnormally long")
print()
