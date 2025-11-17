"""Test script to demonstrate phase timing formatting."""
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.collectors.cycle_context import CycleContext
from src.utils.logging_utils import setup_logging

# Setup logging
setup_logging(terminal_level='INFO')
logger = logging.getLogger(__name__)

print("=" * 70)
print("Testing Phase Timing Formatting")
print("=" * 70)
print()

# Create a cycle context with minimal required params
ctx = CycleContext(
    index_params={},
    providers=None,
    csv_sink=None,
    metrics=None
)

# Simulate phase timings
ctx.record('resolve_expiry', 4.614)
ctx.record('fetch_instruments', 1.463)
ctx.record('enrich_quotes', 1.429)
ctx.record('iv_estimation', 0.989)
ctx.record('index_get_data', 0.340)
ctx.record('greeks_compute', 0.144)
ctx.record('persist_and_metrics', 0.106)
ctx.record('field_coverage_metrics', 0.001)
ctx.record('bootstrap', 0.000)

# Emit the consolidated log
ctx.emit_consolidated_log()

print()
print("=" * 70)
print("✓ Phase timing format test complete!")
print("=" * 70)
