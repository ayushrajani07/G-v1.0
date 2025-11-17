"""Diagnostic script to investigate SENSEX field coverage calculation."""
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Sample data structure based on the logs
sensex_data = {
    "index": "SENSEX",
    "status": "unknown",
    "expiries": [
        {"rule": "this_week", "status": "OK", "strike_cov": 1.0, "field_cov": 1.0, "options": 42},
        {"rule": "next_week", "status": "PARTIAL", "strike_cov": 1.0, "field_cov": 0.0, "options": 42},
        {"rule": "this_month", "status": "PARTIAL", "strike_cov": 1.0, "field_cov": 0.0, "options": 42},
        {"rule": "next_month", "status": "PARTIAL", "strike_cov": 1.0, "field_cov": 0.2619, "options": 42}
    ],
    "option_count": 168
}

print("=" * 70)
print("SENSEX Field Coverage Investigation")
print("=" * 70)
print()

# Calculate field coverage the same way the code does
expiries = sensex_data.get('expiries', [])
total_field_cov = sum(float(e.get('field_cov', 0.0) or 0.0) for e in expiries)
field_coverage_avg = (total_field_cov / len(expiries)) if expiries else 0.0
field_coverage_pct = field_coverage_avg * 100.0

print("Expiry Breakdown:")
print("-" * 70)
for exp in expiries:
    rule = exp.get('rule', 'unknown')
    status = exp.get('status', 'unknown')
    field_cov = float(exp.get('field_cov', 0.0) or 0.0)
    strike_cov = float(exp.get('strike_cov', 0.0) or 0.0)
    options = exp.get('options', 0)
    print(f"  {rule:12} | Status: {status:7} | Field: {field_cov*100:5.1f}% | Strike: {strike_cov*100:5.1f}% | Options: {options}")

print()
print("-" * 70)
print(f"Total field coverage sum: {total_field_cov:.4f}")
print(f"Number of expiries: {len(expiries)}")
print(f"Average field coverage: {field_coverage_avg:.4f} ({field_coverage_pct:.1f}%)")
print()

print("=" * 70)
print("Explanation:")
print("=" * 70)
print()
print("The 25% coverage comes from averaging field coverage across all 4 expiries:")
print()
print("  (100% + 0% + 0% + 26%) / 4 = 31.5%")
print()
print("But the actual value shown (25%) suggests that the field_cov values")
print("stored in the data structure are slightly different.")
print()
print("Possible reasons for low coverage:")
print("  1. IV (Implied Volatility) calculation failures")
print("  2. Greeks computation errors")
print("  3. Missing market data for far-dated expiries")
print("  4. API rate limiting or incomplete responses")
print("  5. Stale instrument cache for future expiries")
print()
print("The 'next_month' expiry shows ~26% coverage, meaning only about")
print("11 out of 42 options have complete field data (IV, Greeks, etc.)")
print()
