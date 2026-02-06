"""Per-index aggregate metric registrations (extracted)."""
from __future__ import annotations

import logging

from prometheus_client import REGISTRY, Counter, Gauge

logger = logging.getLogger(__name__)

def init_index_aggregate_metrics(registry: MetricsRegistry) -> None:
    core = registry._core_reg  # type: ignore[attr-defined]
    core('index_options_processed', Gauge, 'g6_index_options_processed', 'Options processed for index last cycle', ['index'])
    core('index_options_processed_total', Counter, 'g6_index_options_processed_total', 'Cumulative options processed per index (monotonic)', ['index'])
    core('index_avg_processing_time', Gauge, 'g6_index_avg_processing_time_seconds', 'Average per-option processing time last cycle', ['index'])
    core('index_success_rate', Gauge, 'g6_index_success_rate_percent', 'Per-index success rate percent', ['index'])
    core('index_last_collection_unixtime', Gauge, 'g6_index_last_collection_unixtime', 'Last successful collection timestamp (unix)', ['index'])
    core('index_current_atm', Gauge, 'g6_index_current_atm_strike', 'Current ATM strike (redundant but stable label set)', ['index'])
    core('index_current_volatility', Gauge, 'g6_index_current_volatility', 'Current representative IV (e.g., ATM option)', ['index'])
    core('metric_group_state', Gauge, 'g6_metric_group_state', 'Metric group activation flag', ['group'])
    core('index_attempts_total', Counter, 'g6_index_attempts_total', 'Total index collection attempts (per index, resets never)', ['index'])
    core('index_failures_total', Counter, 'g6_index_failures_total', 'Total index collection failures (per index, labeled by error_type)', ['index','error_type'])
    core('index_cycle_attempts', Gauge, 'g6_index_cycle_attempts', 'Attempts in the most recent completed cycle (per index)', ['index'])
    core('index_cycle_success_percent', Gauge, 'g6_index_cycle_success_percent', 'Success percent for the most recent completed cycle (per index)', ['index'])
