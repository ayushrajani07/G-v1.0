#!/usr/bin/env python3
# mypy: disable-error-code=unreachable
"""
CSV Storage Sink for G6 Platform.
"""

import csv
import datetime
import json
import logging
import os
import os as _os_env  # for env access without shadowing
import re  # added for ISO date detection in expiry tag
import shutil
import time
from typing import Any
from pathlib import Path

from src.config.env_config import EnvConfig

# Module imports (moved from late imports)
from src.errors.error_routing import route_error
from src.events import event_log
from src.broker.kite_provider import is_concise_logging
from src.filters.junk_filter import JunkFilter, JunkFilterCallbacks, JunkFilterConfig
from src.metrics import get_metrics, get_registry

from ..utils.timeutils import (
    format_ist_dt_30s,  # unified IST full datetime formatting with 30s rounding
    round_timestamp,  # generic (still used for raw rounding where needed)
    )
from src.storage.csv_writer import CsvWriter
from src.storage.csv_metrics import CsvMetricsTracker
from src.storage.csv_validator import CsvValidator
from src.storage.csv_batcher import CsvBatcher
from src.storage.csv_aggregator import CsvAggregator


class CsvSink:
    """CSV storage sink for options data."""

    def __init__(self, base_dir: str = "data/g6_data", *,
                 writer: Any | None = None,
                 metrics_tracker: Any | None = None,
                 validator: Any | None = None,
                 batcher: Any | None = None,
                 aggregator: Any | None = None) -> None:
        """
        Initialize CSV sink.
        Args:
            base_dir: Base directory for CSV files (relative to project root or absolute)
            writer: Optional CsvWriter instance for low-level I/O
            metrics_tracker: Optional CsvMetricsTracker for metrics emission
            validator: Optional CsvValidator instance for schema/junk handling
            batcher: Optional CsvBatcher for buffered writes
            aggregator: Optional CsvAggregator for overview aggregation
        """
        # Resolve base_dir relative to project root if not absolute
        if not os.path.isabs(base_dir):
            # Project root is two levels up from this file (src/storage/)
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
            resolved_dir = os.path.abspath(os.path.join(project_root, base_dir))
        else:
            resolved_dir = base_dir
        # Normalize to an absolute, OS-native path to avoid Windows path quirks
        self.base_dir = os.path.normpath(os.path.abspath(resolved_dir))
        os.makedirs(self.base_dir, exist_ok=True)
        # Initialize logger
        self.logger = logging.getLogger(__name__)
        # Downgrade to DEBUG; startup banner prints data dir at INFO
        self.logger.debug("CsvSink initialized with base_dir: %s", self.base_dir)
        # Detect global concise mode (default enabled) to reduce repetitive write logs
        self._concise = _os_env.environ.get('G6_CONCISE_LOGS', '1').lower() not in ('0','false','no','off')
        # Lazy metrics registry (optional injection later)
        self.metrics: Any | None = None
        # Configurable overview aggregation interval (seconds)
        try:
            self.overview_interval_seconds = int(_os_env.environ.get('G6_OVERVIEW_INTERVAL_SECONDS', '180'))
        except ValueError:
            self.overview_interval_seconds = 180
        # Verbose logging flag
        self.verbose = _os_env.environ.get('G6_CSV_VERBOSE', '1').lower() not in ('0','false','no')
        # Internal state for aggregation
        self._agg_last_write: dict[str, datetime.datetime] = {}
        self._agg_pcr_snapshot: dict[str, dict[str, float]] = {}
        self._agg_day_width: dict[str, float] = {}
        # Overview change tracking state (per index)
        self._index_last_price: dict[str, float] = {}
        self._index_open_price: dict[str, float] = {}
        self._index_open_date: dict[str, str] = {}
        self._tp_last: dict[str, float] = {}
        self._tp_open: dict[str, float] = {}
        self._tp_open_date: dict[str, str] = {}
        # Previous day close tracking (lazy-loaded per day per index)
        self._index_prev_close: dict[str, float] = {}
        self._tp_prev_close: dict[str, float] = {}
        self._prev_close_loaded_date: dict[str, str] = {}
        # Per-offset TP tracking for option files
        self._tp_open_by_key: dict[tuple[str, str, int], float] = {}
        self._tp_open_date_by_key: dict[tuple[str, str, int], str] = {}
        self._tp_prev_close_by_key: dict[tuple[str, str, int], float] = {}
        self._tp_prev_loaded_date_by_key: dict[tuple[str, str, int], str] = {}
        # Last known VIX (for aggregated snapshot fallback)
        self._last_vix: float | None = None
        # ---------------- Batching State (Task 10) ----------------
        try:
            self._batch_flush_threshold = int(_os_env.environ.get('G6_CSV_BATCH_FLUSH','0'))  # 0 => disabled
        except ValueError:
            self._batch_flush_threshold = 0
        # key: (index, expiry_code, date_str) -> { option_file: {'header': header, 'rows': [row,...]} }
        self._batch_buffers: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = {}
        # Track counts per key to know when to flush
        self._batch_counts: dict[tuple[str, str, str], int] = {}
        # Track which logical expiry tags have been seen per index per date for advisory (Task 35)
        self._seen_expiry_tags: dict[tuple[str, str], set[str]] = {}
        self._advisory_emitted: dict[tuple[str, str], bool] = {}
        # Frequently used dynamic attributes predeclared for type checker
        self._last_row_keys: dict[tuple[str, int], str] = {}
        self._expiry_daily_stats: dict[str, dict[str, int]] = {}
        self._last_expiry_summary_emit: float = 0.0
        self._config_cache: Any | None = None
        self._junk_cfg_loaded: bool = False
        self._junk_cfg_whitelist_val: str | None = None
        self._expiry_canonical_map: dict[tuple[str, str], str] = {}
        self._expiry_misclass_dedupe: set[tuple[str, str, str, str]] = set()
        self._expiry_misclass_accounted_map: dict[tuple[str, str], int] = {}
        self._expiry_misclass_mis_keys: set[tuple[str, str, str, str]] = set()
        self._expiry_misclass_policy: str = 'rewrite'
        self._expiry_quarantine_dir: str = 'data/quarantine/expiries'
        self._expiry_rewrite_annotate: bool = False
        self._expiry_summary_interval: int = 60
        self._rewrite_annotations: list[Any] = []
        # Track pending quarantined rows per ISO date for metrics
        self._expiry_quarantine_pending_counts: dict[str, int] = {}

        # -------------------------------- Components (extracted modules) --------------------------------
        # Note: These are injected for testability and modular adoption; defaults are created if not provided.
        try:
            self.writer = writer or CsvWriter(self.base_dir)
        except (ImportError, TypeError, ValueError, OSError) as e:
            self.logger.warning(f"Failed to initialize CsvWriter: {e}. Falling back to legacy I/O paths.")
            self.writer = None  # Fallback to legacy inline I/O paths
        except Exception as e:
            self.logger.error(f"Unexpected error initializing CsvWriter: {e}", exc_info=True)
            self.writer = None
        
        try:
            self.metrics_tracker = metrics_tracker or CsvMetricsTracker(None)
        except (ImportError, TypeError) as e:
            self.logger.warning(f"Failed to initialize CsvMetricsTracker: {e}")
            self.metrics_tracker = None
        except Exception as e:
            self.logger.error(f"Unexpected error initializing CsvMetricsTracker: {e}", exc_info=True)
            self.metrics_tracker = None
        
        try:
            self.validator = validator or CsvValidator(logger=self.logger, metrics=self.metrics_tracker, concise_mode=self._concise)
        except (ImportError, TypeError) as e:
            self.logger.warning(f"Failed to initialize CsvValidator: {e}")
            self.validator = None
        except Exception as e:
            self.logger.error(f"Unexpected error initializing CsvValidator: {e}", exc_info=True)
            self.validator = None
        
        try:
            # Use configured threshold; 0 disables batching
            flush_threshold = int(self._batch_flush_threshold) if getattr(self, '_batch_flush_threshold', 0) else 0
        except (ValueError, TypeError, AttributeError) as e:
            self.logger.debug(f"Failed to parse batch flush threshold: {e}. Using default 0.")
            flush_threshold = 0
        
        try:
            self.batcher = batcher or CsvBatcher(
                logger=self.logger,
                metrics=self.metrics_tracker,
                flush_threshold=flush_threshold if flush_threshold > 0 else 50,
                verbose=self.verbose,
            )
        except (ImportError, TypeError) as e:
            self.logger.warning(f"Failed to initialize CsvBatcher: {e}")
            self.batcher = None
        except Exception as e:
            self.logger.error(f"Unexpected error initializing CsvBatcher: {e}", exc_info=True)
            self.batcher = None
        
        try:
            self.aggregator = aggregator or CsvAggregator(
                base_dir=self.base_dir,
                logger=self.logger,
                metrics=self.metrics_tracker,
                overview_interval_seconds=self.overview_interval_seconds,
                concise_mode=self._concise,
            )
        except (ImportError, TypeError, OSError) as e:
            self.logger.warning(f"Failed to initialize CsvAggregator: {e}")
            self.aggregator = None
        except Exception as e:
            self.logger.error(f"Unexpected error initializing CsvAggregator: {e}", exc_info=True)
            self.aggregator = None

    def attach_metrics(self, metrics_registry: Any) -> None:
        """Attach metrics registry after initialization to avoid circular imports.

        Propagates to composed helpers when available.
        """
        self.metrics = metrics_registry
        try:
            if self.metrics_tracker:
                self.metrics_tracker.attach_metrics(metrics_registry)
        except (AttributeError, TypeError) as e:
            self.logger.debug(f"Failed to attach metrics to metrics_tracker: {e}")
        except Exception as e:
            self.logger.warning(f"Unexpected error attaching metrics to metrics_tracker: {e}")
        
        try:
            if self.batcher:
                self.batcher.metrics = metrics_registry  # type: ignore[attr-defined]
        except (AttributeError, TypeError) as e:
            self.logger.debug(f"Failed to attach metrics to batcher: {e}")
        except Exception as e:
            self.logger.warning(f"Unexpected error attaching metrics to batcher: {e}")
        
        try:
            if self.aggregator:
                self.aggregator.metrics = metrics_registry  # type: ignore[attr-defined]
        except (AttributeError, TypeError) as e:
            self.logger.debug(f"Failed to attach metrics to aggregator: {e}")
        except Exception as e:
            self.logger.warning(f"Unexpected error attaching metrics to aggregator: {e}")

    # ---------------- Metric Wrapper Helpers ----------------
    def _metric_inc(self, name: str, amount: int | float = 1, labels: dict[str, Any] | None = None) -> None:
        """Safely increment a metric if it exists (counter/gauge)."""
        if not self.metrics:
            return
        
        try:
            metric = getattr(self.metrics, name, None)
            if not metric:
                return
            
            if labels:
                try:
                    metric = metric.labels(**labels)  # type: ignore
                except (TypeError, KeyError, ValueError) as e:
                    self.logger.debug(f"Failed to apply labels to metric {name}: {e}")
                    return
            
            try:
                metric.inc(amount)  # type: ignore
            except (AttributeError, TypeError, ValueError) as e:
                self.logger.debug(f"Failed to increment metric {name}: {e}")
        except AttributeError:
            # Metric doesn't exist - this is expected for optional metrics
            pass
        except Exception as e:
            self.logger.warning(f"Unexpected error incrementing metric {name}: {e}")

    def _metric_set(self, name: str, value: int | float, labels: dict[str, Any] | None = None) -> None:
        """Safely set a gauge metric if it exists."""
        if not self.metrics:
            return
        
        try:
            metric = getattr(self.metrics, name, None)
            if not metric:
                return
            
            if labels:
                try:
                    metric = metric.labels(**labels)  # type: ignore
                except (TypeError, KeyError, ValueError) as e:
                    self.logger.debug(f"Failed to apply labels to metric {name}: {e}")
                    return
            
            try:
                metric.set(value)  # type: ignore
            except (AttributeError, TypeError, ValueError) as e:
                self.logger.debug(f"Failed to set metric {name}: {e}")
        except AttributeError:
            # Metric doesn't exist - this is expected for optional metrics
            pass
        except Exception as e:
            self.logger.warning(f"Unexpected error setting metric {name}: {e}")

    # ------------------------------------------------------------------
    # Expiry remediation daily summary helpers
    # ------------------------------------------------------------------
    def _update_expiry_daily_stats(self, kind: str) -> None:
        """Update in-memory daily stats for expiry remediation and emit summary events periodically.

        kind: one of 'rewritten','quarantined','rejected'. We aggregate counts per
        ISO date. Every _expiry_summary_interval seconds (default 60) we emit an
        'expiry_quarantine_summary' event with cumulative counts for the day.
        This is intentionally lightweight (best-effort) and safe if events are disabled.
        """
        try:
            event_log_ref = event_log  # Use module-level import
        except (NameError, AttributeError):
            event_log_ref = None  # type: ignore
        
        if not hasattr(self, '_expiry_daily_stats'):
            self._expiry_daily_stats = {}
        if not hasattr(self, '_last_expiry_summary_emit'):
            self._last_expiry_summary_emit = 0.0
        
        today = datetime.date.today().isoformat()
        stats = self._expiry_daily_stats.setdefault(today, {'rewritten':0,'quarantined':0,'rejected':0})
        if kind in stats:
            stats[kind] += 1
        
        now = time.time()
        interval = getattr(self, '_expiry_summary_interval', 60)
        if event_log_ref and now - self._last_expiry_summary_emit >= interval:
            try:
                aggregate = self._expiry_daily_stats.get(today, stats)
                event_log_ref.dispatch('expiry_quarantine_summary', context={
                    'date': today,
                    'rewritten': aggregate.get('rewritten',0),
                    'quarantined': aggregate.get('quarantined',0),
                    'rejected': aggregate.get('rejected',0)
                })
                self._last_expiry_summary_emit = now
            except (AttributeError, TypeError, KeyError) as e:
                self.logger.debug(f"Failed to dispatch expiry summary event: {e}")
            except Exception as e:
                self.logger.warning(f"Unexpected error dispatching expiry summary: {e}")

    def _clean_for_json(self, obj: Any) -> Any:
        """Convert non-serializable objects for JSON.

        Returns a JSON-serializable representation (str/number/dict/list) as appropriate.
        """
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        if hasattr(obj, 'to_dict'):
            try:
                return obj.to_dict()
            except (AttributeError, TypeError) as e:
                self.logger.debug(f"Failed to convert object to dict: {e}")
                return str(obj)
            except Exception as e:
                self.logger.debug(f"Unexpected error converting to dict: {e}")
                return str(obj)
        return obj if isinstance(obj, (str, int, float, bool, list, dict, type(None))) else str(obj)

    # ==================================================================
    # Public API: Orchestrates end-to-end write for a single expiry slice
    # Major phases (each delegated to extracted helpers):
    #   1. Expiry context resolution / enforcement
    #   2. Mixed-expiry pruning & expected-expiry advisory
    #   3. Schema validation & grouping
    #   4. Per-strike loop (misclassification, junk filtering, zero-row skip,
    #      duplicate suppression, batching, flush decision)
    #   5. Overview + aggregation snapshot maintenance
    # Behavior preserving refactor; helpers isolate vertical concerns so that
    # future changes remain localized and testable.
    # ==================================================================
    def write_options_data(
        self,
        index: str,
        expiry: Any,
        options_data: dict[str, dict[str, Any]],
        timestamp: datetime.datetime,
        index_price: float | None = None,
        index_ohlc: dict[str, Any] | None = None,
        suppress_overview: bool = False,
        return_metrics: bool = False,
        expiry_rule_tag: str | None = None,
        **_extra: Any,
    ) -> dict[str, Any] | None:
        """Write options data to CSV with locking, duplicate suppression, and config-tag honoring.

        expiry_rule_tag: Optional logical tag from the collector (e.g. 'this_month') used instead of
        heuristic distance-based tagging for indices whose config restricts expiries.
        """
        self.logger.debug("write_options_data called with index=%s, expiry=%s", index, expiry)
        concise_mode = False
        try:
            concise_mode = bool(is_concise_logging())
        except Exception:
            concise_mode = False
        if concise_mode:
            self.logger.debug("Options data received for %s expiry %s: %s instruments", index, expiry, len(options_data))
        else:
            self.logger.info("Options data received for %s expiry %s: %s instruments", index, expiry, len(options_data))

        # --- Extracted expiry context resolution (behavior preserved) ---
        exp_date, expiry_code, supplied_tag, expiry_str = self._resolve_expiry_context(
            index=index,
            expiry=expiry,
            expiry_rule_tag=expiry_rule_tag,
            options_data=options_data,
        )

        # ---------------- Config-based expiry enforcement (Task 29) ----------------
        # Only allow writing if the (supplied) expiry_code is within configured expiries for index.
        # If no config or tag supplied, allow heuristic result (legacy behaviour).
        if supplied_tag:  # only enforce if caller explicitly passed a tag
            try:
                # Lazy-load config once and cache on class
                if not hasattr(self, '_config_cache'):
                    proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
                    cfg_path = os.path.join(proj_root, 'config', 'g6_config.json')
                    with open(cfg_path, encoding='utf-8') as _cf:
                        self._config_cache = json.load(_cf)
                indices_cfg = (self._config_cache or {}).get('indices', {})
                _allowed_raw = indices_cfg.get(index, {}).get('expiries')
                allowed = _allowed_raw if isinstance(_allowed_raw, list) else []
                if allowed and expiry_code not in allowed:
                    # Skip writing disallowed tag
                    if self._concise:
                        self.logger.debug("CSV_SKIPPED_DISALLOWED index=%s tag=%s allowed=%s", index, expiry_code, allowed)
                    else:
                        self.logger.info("Skipping disallowed expiry tag for %s: %s not in %s", index, expiry_code, allowed)
                    # Metric (migrated to wrapper)
                    self._metric_inc('csv_skipped_disallowed', 1, {'index': index, 'expiry': expiry_code})
                    return (
                        {
                            'expiry_code': expiry_code,
                            'pcr': 0,
                            'timestamp': timestamp,
                            'day_width': 0,
                            'skipped': True,
                        }
                        if return_metrics
                        else None
                    )
            except Exception as cfg_e:  # pragma: no cover
                self.logger.debug("Config enforcement failed for %s %s: %s", index, expiry_code, cfg_e)

    # Get or calculate index price
        if not index_price:
            # Use a default value based on index if nothing else is available
            defaults = {
                "NIFTY": 24800,
                "BANKNIFTY": 54200,
                "FINNIFTY": 25900,
                "MIDCPNIFTY": 22000,
                "SENSEX": 80900
            }
            index_price = defaults.get(index, 0)

            # Try to find index price in the first option's metadata
            for data in options_data.values():
                if 'index_price' in data:
                    index_price = float(data['index_price'])
                    break

        # Calculate ATM strike (factored out)
        atm_strike = self._compute_atm_strike(index, float(index_price))

        if concise_mode:
            self.logger.debug("Index %s price: %s, ATM strike: %s", index, index_price, atm_strike)
        else:
            self.logger.info("Index %s price: %s, ATM strike: %s", index, index_price, atm_strike)

    # Calculate PCR for this expiry
        put_oi = sum(float(data.get('oi', 0)) for data in options_data.values()
                    if data.get('instrument_type') == 'PE')
        call_oi = sum(float(data.get('oi', 0)) for data in options_data.values()
                    if data.get('instrument_type') == 'CE')
        pcr = put_oi / call_oi if call_oi > 0 else 0

        # ---------------- Allowed expiry_dates validation (Task 39) ----------------
        try:
            allowed_set = getattr(self, 'allowed_expiry_dates', None)
            if allowed_set and isinstance(allowed_set, (set, list, tuple)) and exp_date not in allowed_set:
                if self._concise:
                    self.logger.debug("CSV_SKIP_INVALID_EXPIRY index=%s tag=%s expiry=%s", index, expiry_code, expiry_str)
                else:
                    self.logger.warning(
                        "Skipping write: expiry_date %s not in allowed set for %s (size=%s)", expiry_str, index, len(allowed_set)
                    )
                return (
                    {
                        'expiry_code': expiry_code,
                        'pcr': 0,
                        'timestamp': timestamp,
                        'day_width': 0,
                        'skipped_invalid_expiry': True,
                    }
                    if return_metrics
                    else None
                )
        except (TypeError, KeyError, AttributeError) as e:
            self.logger.debug(f"Failed to validate expiry date for {index}: {e}")
        except Exception as e:
            self.logger.warning(f"Unexpected error validating expiry: {e}")

        # Calculate day width if OHLC data is available
        day_width: float = 0.0
        if index_ohlc and 'high' in index_ohlc and 'low' in index_ohlc:
            day_width = float(index_ohlc.get('high', 0)) - float(index_ohlc.get('low', 0))

        # ---- Compute ATM total premium (tp) for overview, and index/tp changes ----
        # Derive ATM CE and PE prices from options_data around atm_strike
        def _nearest_price(instrument_type: str) -> float:
            best_diff: float | None = None
            best_price = 0.0
            for od in options_data.values():
                if od.get('instrument_type') != instrument_type:
                    continue
                try:
                    k = float(od.get('strike', 0) or 0)
                except (TypeError, ValueError) as e:
                    self.logger.debug(f"Failed to parse strike value: {e}")
                    continue
                except Exception as e:
                    self.logger.debug(f"Unexpected error parsing strike: {e}")
                    continue
                diff = abs(k - atm_strike)
                if best_diff is None or diff < best_diff:
                    try:
                        best_price = float(od.get('last_price', 0) or 0)
                        best_diff = diff
                    except (TypeError, ValueError) as e:
                        self.logger.debug(f"Failed to parse last_price: {e}")
                    except Exception as e:
                        self.logger.debug(f"Unexpected error parsing price: {e}")
            return best_price

        ce_atm = _nearest_price('CE')
        pe_atm = _nearest_price('PE')
        tp_value = float(ce_atm) + float(pe_atm)

    # Prepare daily open tracking for index/tp and load previous closes
        date_key = timestamp.strftime('%Y-%m-%d')
        # Ensure prev close values are available (best-effort)
        try:
            self._ensure_prev_close_loaded(index=index, date_key=date_key)
        except Exception:
            pass
        # Capture opening values near market open (9:15 AM)
        current_time = timestamp.time()
        market_open_time = datetime.time(9, 15)
        market_open_window = datetime.time(9, 30)  # 15-minute window
        
        if self._index_open_date.get(index) != date_key:
            # New day - check if we're in market open window
            if market_open_time <= current_time <= market_open_window:
                self._index_open_date[index] = date_key
                self._index_open_price[index] = float(index_price or 0.0)
            elif current_time < market_open_time:
                # Before market open - wait
                self._index_open_date[index] = date_key
                self._index_open_price[index] = float(index_price or 0.0)  # Temporary, will update
            else:
                # After window - use current as fallback
                self._index_open_date[index] = date_key
                self._index_open_price[index] = float(index_price or 0.0)
        elif self._index_open_date.get(index) == date_key and market_open_time <= current_time <= market_open_window:
            # Update if we're in the opening window (improves accuracy)
            self._index_open_price[index] = float(index_price or 0.0)
            
        if self._tp_open_date.get(index) != date_key:
            # New day - check if we're in market open window  
            if market_open_time <= current_time <= market_open_window:
                self._tp_open_date[index] = date_key
                self._tp_open[index] = float(tp_value)
            elif current_time < market_open_time:
                # Before market open - wait
                self._tp_open_date[index] = date_key
                self._tp_open[index] = float(tp_value)  # Temporary, will update
            else:
                # After window - use current as fallback
                self._tp_open_date[index] = date_key
                self._tp_open[index] = float(tp_value)
        elif self._tp_open_date.get(index) == date_key and market_open_time <= current_time <= market_open_window:
            # Update if we're in the opening window (improves accuracy)
            self._tp_open[index] = float(tp_value)

        # Index price change calculations
        prev_close_idx = self._index_prev_close.get(index)
        index_net_change = float(index_price or 0.0) - float(prev_close_idx) if prev_close_idx is not None else 0.0
        index_day_change = float(index_price or 0.0) - float(self._index_open_price.get(index, index_price or 0.0))

        # TP change calculations
        prev_close_tp = self._tp_prev_close.get(index)
        tp_net_change = float(tp_value) - float(prev_close_tp) if prev_close_tp is not None else 0.0
        tp_day_change = float(tp_value) - float(self._tp_open.get(index, tp_value))

        # ---------------- Mixed-expiry validation (Task 31 / 34) ----------------
        self._prune_mixed_expiry(options_data, exp_date, index=index, expiry_code=expiry_code)

        # ---------------- Expected-expiry presence advisory (Task 35) ----------------
        self._advise_missing_expiries(index=index, expiry_code=expiry_code, timestamp=timestamp)

        # Update the overview file (segregated by index) unless suppressed for aggregation
        if not suppress_overview:
            vix_val = None
            try:
                vix_val = _extra.get('vix')  # passed by collectors if available
            except (AttributeError, KeyError, TypeError):
                vix_val = None
            self._write_overview_file(
                index, expiry_code, pcr, day_width, timestamp, index_price,
                index_net_change=index_net_change, index_day_change=index_day_change,
                tp_value=tp_value, tp_net_change=tp_net_change, tp_day_change=tp_day_change,
                vix=vix_val,
            )
            if vix_val is not None:
                try:
                    self._last_vix = float(vix_val)
                except Exception:
                    pass

        # Update last-seen values after write
        try:
            self._index_last_price[index] = float(index_price or 0.0)
            self._tp_last[index] = float(tp_value)
        except Exception:
            pass

        # Group options by strike
        strike_data = self._group_by_strike(options_data)
        unique_strikes = len(strike_data)

        # ---------------- Schema Assertions Layer (Task 11) ----------------
        schema_issues = self._validate_schema(index=index, expiry_code=expiry_code, strike_data=strike_data)
        if return_metrics and schema_issues:
            # When metrics requested, surface schema issue count minimally; continue writing otherwise
            pass

        # Create expiry-specific directory
        expiry_dir = os.path.join(self.base_dir, index, expiry_code)
        os.makedirs(expiry_dir, exist_ok=True)

        # Create debug file
        debug_file = os.path.join(expiry_dir, f"{timestamp.strftime('%Y-%m-%d')}_debug.json")

        # Format timestamp for records - use actual collection time
        ts_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')

        # Unified IST 30s rounding + formatting (Task 12)
        try:
            ts_str_rounded = format_ist_dt_30s(timestamp)  # dd-mm-YYYY HH:MM:SS in IST
        except (TypeError, ValueError, AttributeError) as e:
            # Fallback to previous logic on unexpected failure
            self.logger.debug(f"Failed to format IST timestamp: {e}. Using fallback.")
            rounded_timestamp = round_timestamp(timestamp, step_seconds=30, strategy='nearest')
            ts_str_rounded = rounded_timestamp.strftime('%d-%m-%Y %H:%M:%S')
        except Exception as e:
            self.logger.warning(f"Unexpected error formatting timestamp: {e}. Using fallback.")
            rounded_timestamp = round_timestamp(timestamp, step_seconds=30, strategy='nearest')
            ts_str_rounded = rounded_timestamp.strftime('%d-%m-%Y %H:%M:%S')

        # Batching decision & strike processing moved to helper
        batching_enabled = self._batch_flush_threshold > 0
        batch_key = (index, expiry_code, timestamp.strftime('%Y-%m-%d'))
        if batching_enabled and batch_key not in self._batch_buffers:
            self._batch_buffers[batch_key] = {}
            self._batch_counts[batch_key] = 0
        unique_strikes, mismatched_meta, flushed = self._process_strikes_and_maybe_flush(
            index=index,
            expiry_code=expiry_code,
            expiry_str=expiry_str,
            exp_date=exp_date,
            strike_data=strike_data,
            atm_strike=atm_strike,
            index_price=index_price,
            ts_str_rounded=ts_str_rounded,
            timestamp=timestamp,
            batching_enabled=batching_enabled,
            batch_key=batch_key,
        )

        # Write debug JSON only when flushed (avoid misleading partial snapshot)
        if flushed:
            try:
                with open(debug_file, 'w') as f:
                    json.dump({
                        'timestamp': ts_str,
                        'index': index,
                        'expiry': str(expiry),
                        'expiry_code': expiry_code,
                        'index_price': index_price,
                        'atm_strike': atm_strike,
                        'pcr': pcr,
                        'day_width': day_width,
                        'data_count': len(options_data),
                        'rounded_timestamp': ts_str_rounded,
                        'batched': batching_enabled,
                        'flushed': True
                    }, f, indent=2)
            except (IOError, OSError, PermissionError) as e:
                if self.verbose:
                    self.logger.debug(f"Failed to write debug file {debug_file}: {e}")
            except (TypeError, ValueError) as e:
                self.logger.debug(f"Failed to serialize debug data: {e}")
            except Exception as e:
                if self.verbose:
                    self.logger.warning(f"Unexpected error writing debug file: {e}", exc_info=True)

        if self.verbose and not self._concise:
            self.logger.info("Data written for %s %s (unique_strikes=%s)", index, expiry_code, unique_strikes)
        else:
            self.logger.debug("Data written for %s %s (unique_strikes=%s)", index, expiry_code, unique_strikes)

        # Aggregation snapshot update (only update if not suppressed to avoid skew)
        self._update_aggregation_state(index, expiry_code, pcr, day_width, timestamp)
        self._maybe_write_aggregated_overview(index, timestamp)

        # Optionally return metrics for aggregation mode
        if return_metrics:
            return {
                'expiry_code': expiry_code,
                'pcr': pcr,
                'day_width': day_width,
                'timestamp': timestamp,
                'index_price': index_price
            }
        return None

    # ------------------------- Helper Methods -------------------------
    def _resolve_expiry_context(
        self,
        *,
        index: str,
        expiry: Any,
        expiry_rule_tag: str | None,
        options_data: dict[str, Any],
    ) -> tuple[datetime.date, str, str | None, str]:
        """Resolve expiry date, logical tag, and corrected monthly anchor.

        Mirrors legacy inlined logic in write_options_data (no behavior change):
        - Parse expiry to date
        - Prefer supplied logical tag unless it's a raw date string
        - Heuristic fallback when tag omitted or raw date
        - Monthly anchor diagnostic & auto-correction (adjust exp_date & mutate option legs)
        Returns (exp_date, expiry_code, supplied_tag, expiry_str)
        """
        # Parse date
        try:
            exp_date = expiry if isinstance(expiry, datetime.date) else datetime.datetime.strptime(str(expiry), '%Y-%m-%d').date()
        except (ValueError, TypeError, AttributeError) as e:
            # Fallback: treat unparsable expiry as today (should be rare) to avoid crash; logs at warning.
            self.logger.warning(f"CSV_EXPIRY_PARSE_FALLBACK index={index} raw={expiry}: {e}")
            exp_date = datetime.date.today()
        except Exception as e:
            self.logger.error(f"Unexpected error parsing expiry for {index}: {e}", exc_info=True)
            exp_date = datetime.date.today()
        
        supplied_tag = (expiry_rule_tag.strip() if isinstance(expiry_rule_tag, str) and expiry_rule_tag.strip() else None)
        if supplied_tag and re.fullmatch(r"\d{4}-\d{2}-\d{2}", supplied_tag):
            self.logger.debug(f"CSV_EXPIRY_TAG_RAW_DATE index={index} tag={supplied_tag} -> falling back to heuristic classification")
            supplied_tag = None
        
        expiry_code = supplied_tag or self._determine_expiry_code(exp_date)
        expiry_str = exp_date.strftime('%Y-%m-%d')
        
        # Monthly anchor correction removed: rely on centralized policy in select_expiry_for_index.
        # Emit diagnostic only; do not mutate.
        try:
            if supplied_tag in ('this_month','next_month'):
                cand = exp_date
                if isinstance(cand, datetime.date):
                    # Compute expected anchor weekday for policy coherence (log only)
                    if cand.month == 12:
                        nxt_first = datetime.date(cand.year+1,1,1)
                    else:
                        nxt_first = datetime.date(cand.year, cand.month+1,1)
                    last_day = nxt_first - datetime.timedelta(days=1)
                    # Just log mismatch; no rewrite
                    # (Rewrite previously caused divergence from unified expiry policy.)
                    pass
        except (ValueError, OverflowError) as e:
            self.logger.debug(f"Failed to compute monthly anchor for {index}: {e}")
        except Exception as e:
            self.logger.warning(f"Unexpected error in monthly anchor diagnostic: {e}")
        return exp_date, expiry_code, supplied_tag, expiry_str

    def _determine_expiry_code(self, exp_date: datetime.date, today: datetime.date | None = None) -> str:
        today = today or datetime.date.today()
        days_to_expiry = (exp_date - today).days
        if days_to_expiry <= 7:
            return "this_week"
        if days_to_expiry <= 14:
            return "next_week"
        if exp_date.month == today.month:
            return "this_month"
        return "next_month"

    def _prune_mixed_expiry(
        self,
        options_data: dict[str, dict[str, Any]] | None,
        exp_date: datetime.date,
        *,
        index: str,
        expiry_code: str,
    ) -> int:
        """Remove instruments whose embedded expiry does not match the expected expiry date.

        Mirrors legacy inlined mixed-expiry pruning logic (Task 31 / 34) without behavior change.
        Returns number of dropped instruments. Mutates options_data in place.
        """
        if not options_data:
            return 0  # type: ignore[unreachable]
        dropped = 0
        safe_expected = exp_date
        for sym, data in list(options_data.items()):
            try:
                raw_exp = data.get('expiry') or data.get('expiry_date') or data.get('instrument_expiry')
                if not raw_exp:
                    continue
                # Normalize candidate to date
                if isinstance(raw_exp, datetime.datetime):
                    cand_date = raw_exp.date()
                elif isinstance(raw_exp, datetime.date):
                    cand_date = raw_exp
                else:
                    cand_date = None
                    for fmt in ('%Y-%m-%d','%d-%m-%Y','%Y-%m-%d %H:%M:%S'):
                        try:
                            cand_date = datetime.datetime.strptime(str(raw_exp), fmt).date()
                            break
                        except Exception:
                            continue
                    if cand_date is None:
                        continue
                if cand_date != safe_expected:
                    options_data.pop(sym, None)
                    dropped += 1
            except Exception:
                continue
        if dropped:
            try:
                try:
                    route_error(
                        'csv.mixed_expiry.prune',
                        self.logger,
                        self.metrics,
                        _count=dropped,
                        index=index,
                        expiry=expiry_code,
                        dropped=dropped,
                    )
                except Exception:
                    if self._concise:
                        self.logger.debug("CSV_MIXED_EXPIRY_PRUNE index=%s tag=%s dropped=%s", index, expiry_code, dropped)
                    else:
                        self.logger.info("Pruned %s mixed-expiry records for %s %s", dropped, index, expiry_code)
                    self._metric_inc('csv_mixed_expiry_dropped', dropped, {'index': index, 'expiry': expiry_code})
            except Exception:  # pragma: no cover
                pass
        return dropped

    def _advise_missing_expiries(self, *, index: str, expiry_code: str, timestamp: datetime.datetime) -> None:
        """One-shot advisory when not all configured logical expiries have been observed for the index today.

        Mirrors legacy inline logic (Task 35) without behavior change:
        - Track seen expiry tags per (index, date)
        - Load config lazily (g6_config.json) to obtain expected expiries list
        - When at least one tag seen but some expected still missing, emit a single advisory per day
        - Respects concise mode for log level/format
        Swallows all exceptions (diagnostic-only path)."""
        try:
            date_key = timestamp.strftime('%Y-%m-%d')
            key = (index, date_key)
            seen = self._seen_expiry_tags.setdefault(key, set())
            seen.add(expiry_code)
            if self._advisory_emitted.get(key):  # already emitted for day
                return
            # Lazy config load
            if not hasattr(self, '_config_cache'):
                cfg_path = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')), 'config', 'g6_config.json')
                with open(cfg_path, encoding='utf-8') as _cf:
                    self._config_cache = json.load(_cf)
            indices_cfg = (self._config_cache or {}).get('indices', {})
            _exp_list = indices_cfg.get(index, {}).get('expiries')
            expected_tags = set(_exp_list) if isinstance(_exp_list, list) else set()
            if not expected_tags:
                return  # nothing to compare
            missing = expected_tags - seen
            if missing and len(seen) >= 1:  # at least one observed, others missing
                self._advisory_emitted[key] = True
                if self._concise:
                    self.logger.debug("CSV_EXPIRY_ADVISORY index=%s seen=%s missing=%s", index, sorted(seen), sorted(missing))
                else:
                    self.logger.info("Advisory: Not all configured expiries observed for %s today. Seen=%s Missing=%s", index, sorted(seen), sorted(missing))
        except Exception:  # pragma: no cover
            pass

    def _validate_schema(self, *, index: str, expiry_code: str, strike_data: dict[float, dict[str, Any]]) -> list[str]:
        """Validate grouped strike -> leg map structure and prune invalid entries.

        Mirrors legacy inline 'Schema Assertions Layer (Task 11)' logic:
        - Remove strikes <= 0
        - Drop legs with missing/invalid instrument_type (not CE/PE)
        - Collect issue codes in list (ordering preserved by iteration)
        Returns list of issue identifiers.
        Mutates strike_data in-place (behavior-preserving)."""
        schema_issues: list[str] = []
        for strike_key, leg_map in list(strike_data.items()):
            try:
                if strike_key <= 0:
                    schema_issues.append(f"invalid_strike:{strike_key}")
                    strike_data.pop(strike_key, None)
                    continue
                for leg_type in ('CE','PE'):
                    leg = leg_map.get(leg_type)
                    if leg:
                        inst_type = (leg.get('instrument_type') or '').upper()
                        if inst_type not in ('CE','PE'):
                            schema_issues.append(f"missing_or_bad_type:{strike_key}:{leg_type}")
                            leg_map[leg_type] = None
            except (TypeError, KeyError, AttributeError, ValueError) as e:
                # Defensive: continue collecting other issues
                self.logger.debug(f"Error validating strike {strike_key}: {e}")
                continue
            except Exception as e:
                self.logger.warning(f"Unexpected error in schema validation for strike {strike_key}: {e}")
                continue
        
        if schema_issues:
            try:
                route_error('csv.schema.issues', self.logger, self.metrics, index=index, expiry=expiry_code, count=len(schema_issues))
            except (AttributeError, TypeError) as e:
                self.logger.debug(f"Failed to route schema error: {e}")
                self.logger.warning(
                    "CSV_SCHEMA_ISSUES index=%s expiry=%s count=%d issues=%s", index, expiry_code, len(schema_issues), ','.join(schema_issues[:25]) + ("+"+str(len(schema_issues)-25) if len(schema_issues)>25 else "")
                )
            except Exception as e:
                self.logger.warning(f"Unexpected error routing schema issues: {e}")
            
            # Metrics (migrated to wrapper; preserve capped emission at 50 issues)
            try:
                for issue in schema_issues[:50]:
                    self._metric_inc('data_errors_labeled', 1, {
                        'index': index,
                        'component': 'csv_sink.schema',
                        'error_type': issue.split(':',1)[0]
                    })
            except (ValueError, IndexError, KeyError) as e:
                self.logger.debug(f"Failed to emit schema issue metrics: {e}")
            except Exception as e:
                self.logger.warning(f"Unexpected error emitting schema metrics: {e}")
        return schema_issues

    def _process_strikes_and_maybe_flush(self, *, index: str, expiry_code: str, expiry_str: str,
                                         exp_date: datetime.date, strike_data: dict[float, dict[str, Any]],
                                         atm_strike: float, index_price: float, ts_str_rounded: str,
                                         timestamp: datetime.datetime, batching_enabled: bool,
                                         batch_key: tuple[str, str, str], exp_misclass_enabled_env: bool = True) -> tuple[int, int, bool]:
        """Process grouped strike data: build rows, apply misclassification remediation, junk & zero filters,
        duplicate suppression, batching/immediate writes, and possibly flush.

        Returns (unique_strikes, mismatched_meta_count, flushed_flag).
        Mirrors legacy inline loop logic exactly (no behavior change)."""
        unique_strikes = len(strike_data)
        mismatched_meta = 0
        exp_date_loc = exp_date  # local ref
        # Pre-compute day batch key path pieces
        for strike, data in strike_data.items():
            offset = int(strike - atm_strike)
            offset_dir = f"+{offset}" if offset > 0 else f"{offset}"
            option_dir = os.path.join(self.base_dir, index, expiry_code, offset_dir)
            os.makedirs(option_dir, exist_ok=True)
            option_file = os.path.join(option_dir, f"{timestamp.strftime('%Y-%m-%d')}.csv")
            file_exists = os.path.isfile(option_file)
            call_data = data.get('CE', {})
            put_data = data.get('PE', {})
            # Mismatch meta detection
            try:
                for leg_d in (call_data, put_data):
                    if not leg_d:
                        continue
                    raw_leg_exp = leg_d.get('expiry') or leg_d.get('expiry_date') or leg_d.get('instrument_expiry')
                    if raw_leg_exp:
                        leg_date = raw_leg_exp.date() if isinstance(raw_leg_exp, datetime.datetime) else (raw_leg_exp if isinstance(raw_leg_exp, datetime.date) else None)
                        if leg_date and leg_date != exp_date_loc:
                            mismatched_meta += 1
                            break
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                self.logger.debug(f"Error checking expiry metadata for strike {strike}: {e}")
            row, header = self._prepare_option_row(index=index,
                                                   expiry_code=expiry_code,
                                                   expiry_date_str=expiry_str,
                                                   offset=offset,
                                                   index_price=index_price,
                                                   atm_strike=atm_strike,
                                                   call_data=call_data,
                                                   put_data=put_data,
                                                   ts_str_rounded=ts_str_rounded)
            # Expiry misclassification remediation (extracted helper preserves behavior)
            try:
                if exp_misclass_enabled_env:
                    new_code, skip_row = self._handle_expiry_misclassification(index=index,
                                                                               expiry_code=expiry_code,
                                                                               expiry_str=expiry_str,
                                                                               offset=offset,
                                                                               row=row,
                                                                               atm_strike=atm_strike,
                                                                               index_price=index_price)
                    expiry_code = new_code
                    if skip_row:
                        continue
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                self.logger.debug(f"Error in expiry misclassification handler: {e}")
            except Exception as e:
                self.logger.warning(f"Unexpected error in expiry misclassification: {e}")
            # Junk filtering (extracted helper); skips row if flagged
            try:
                if self._maybe_skip_as_junk(index=index,
                                             expiry_code=expiry_code,
                                             offset=offset,
                                             call_data=call_data,
                                             put_data=put_data,
                                             row_ts=row[0]):
                    continue
            except (KeyError, TypeError, ValueError, IndexError, AttributeError) as e:
                self.logger.debug(f"Error in junk filtering: {e}")
            except Exception as e:
                self.logger.warning(f"Unexpected error in junk filtering: {e}")
            # Zero-row detection (extracted helper)
            try:
                is_zero_row, skip_zero = self._handle_zero_row(index=index,
                                                               expiry_code=expiry_code,
                                                               expiry_date_str=expiry_str,
                                                               offset=offset,
                                                               call_data=call_data,
                                                               put_data=put_data)
                if skip_zero:
                    continue
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                self.logger.debug(f"Error in zero row handler: {e}")
            except Exception as e:
                self.logger.warning(f"Unexpected error in zero row handler: {e}")
            if not hasattr(self, '_last_row_keys'):
                self._last_row_keys = {}
            row_sig = (option_file, offset)
            if self._handle_duplicate_write_or_buffer(index=index,
                                                      expiry_code=expiry_code,
                                                      offset=offset,
                                                      row=row,
                                                      row_sig=row_sig,
                                                      option_file=option_file,
                                                      header=header,
                                                      file_exists=file_exists,
                                                      batching_enabled=batching_enabled,
                                                      batch_key=batch_key):
                continue
        # Post-loop: meta mismatch log & batch flush decision
        if mismatched_meta:
            self.logger.warning("CSV_EXPIRY_META_MISMATCH index=%s tag=%s mismatched_legs=%s", index, expiry_code, mismatched_meta)
        flushed = self._maybe_flush_batch(batching_enabled= batching_enabled,
                                          batch_key=batch_key)
        return unique_strikes, mismatched_meta, flushed

    def _handle_zero_row(self, *, index: str, expiry_code: str, expiry_date_str: str, offset: int,
                          call_data: dict[str, Any] | None, put_data: dict[str, Any] | None) -> tuple[bool, bool]:
        """Detect zero option row and apply skip policy.

        Returns (is_zero_row, skip_row). Mirrors original inline logic:
        - Identify zero row when all key numeric fields are 0/absent for CE and PE.
        - Increment zero_row metric.
        - If G6_SKIP_ZERO_ROWS enabled then skip; else write (skip_row False).
        Exceptions are swallowed; on failure treats as non-zero for safety.
        """
        # Prefer validator detection when available; apply same skip policy
        try:
            if getattr(self, 'validator', None):
                is_zero_row, _ = self.validator.handle_zero_row(  # type: ignore[union-attr]
                    index=index,
                    expiry_code=expiry_code,
                    expiry_date_str=expiry_date_str,
                    offset=offset,
                    call_data=call_data or {},
                    put_data=put_data or {},
                )
                if not is_zero_row:
                    return False, False
                # Metric parity
                self._metric_inc('zero_option_rows_total', 1, {'index': index, 'expiry': expiry_date_str})
                skip_flag = _os_env.environ.get('G6_SKIP_ZERO_ROWS', '0').lower() in ('1','true','yes','on')
                if skip_flag:
                    if self.verbose:
                        self.logger.debug("Skipping zero option row index=%s expiry=%s offset=%s", index, expiry_code, offset)
                    return True, True
                else:
                    if self.verbose:
                        self.logger.debug("Writing zero option row (flag not set to skip) index=%s expiry=%s offset=%s", index, expiry_code, offset)
                    return True, False
        except (AttributeError, TypeError, ValueError) as e:
            self.logger.debug(f"Error checking zero row condition: {e}")
        except Exception as e:
            self.logger.warning(f"Unexpected error in zero row check: {e}")
        
        try:
            ce_zero = (not call_data) or all(float(call_data.get(k, 0) or 0) == 0 for k in ('last_price','volume','oi','avg_price'))
            pe_zero = (not put_data) or all(float(put_data.get(k, 0) or 0) == 0 for k in ('last_price','volume','oi','avg_price'))
            is_zero = ce_zero and pe_zero
        except (TypeError, ValueError, KeyError) as e:
            self.logger.debug(f"Error calculating zero row status: {e}")
            return False, False
        except Exception as e:
            self.logger.warning(f"Unexpected error calculating zero row: {e}")
            return False, False
        if not is_zero:
            return False, False
        # Metric
        self._metric_inc('zero_option_rows_total', 1, {'index': index, 'expiry': expiry_date_str})
        skip_flag = _os_env.environ.get('G6_SKIP_ZERO_ROWS', '0').lower() in ('1','true','yes','on')
        if skip_flag:
            if self.verbose:
                self.logger.debug("Skipping zero option row index=%s expiry=%s offset=%s", index, expiry_code, offset)
            return True, True
        else:
            if self.verbose:
                self.logger.debug("Writing zero option row (flag not set to skip) index=%s expiry=%s offset=%s", index, expiry_code, offset)
            return True, False

    def _maybe_flush_batch(self, *, batching_enabled: bool, batch_key: tuple[str, str, str]) -> bool:
        """Flush accumulated batch buffers if threshold or force flag met.

        Delegates to CsvBatcher when available; preserves legacy env override G6_CSV_FLUSH_NOW.

        Returns True if data considered flushed (immediate mode or performed flush), False otherwise.
        """
        try:
            if not batching_enabled:
                return True  # immediate mode always 'flushed'
            force_flush_env = _os_env.environ.get('G6_CSV_FLUSH_NOW','0').lower() in ('1','true','yes','on')
            # Prefer delegating to batcher if present
            if self.batcher:
                flushed = self.batcher.maybe_flush_batch(batch_key=batch_key, force_flush_env=force_flush_env)
                # Mirror legacy internal buffers cleanup for health/backlog helpers
                self._batch_buffers.pop(batch_key, None)
                self._batch_counts.pop(batch_key, None)
                return bool(flushed)
            # Fallback to legacy inline implementation
            if self._batch_counts.get(batch_key,0) < self._batch_flush_threshold and not force_flush_env:
                return False
            buffers = self._batch_buffers.get(batch_key, {})
            for path, payload in buffers.items():
                try:
                    header_ref = payload.get('header')
                    rows = payload.get('rows', [])
                    if not rows:
                        continue
                    file_exists_local = os.path.isfile(path)
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    self._append_many_csv_rows(path, rows, header_ref if not file_exists_local else None)
                    if self.verbose:
                        self.logger.debug("Flushed %s rows to %s", len(rows), path)
                    self._metric_inc('csv_records_written', len(rows))
                except (IOError, OSError, PermissionError) as e:
                    self.logger.warning(f"Failed to flush batch to {path}: {e}")
                    continue
                except Exception as e:
                    self.logger.error(f"Unexpected error flushing batch: {e}", exc_info=True)
                    continue
            self._batch_buffers.pop(batch_key, None)
            self._batch_counts.pop(batch_key, None)
            return True
        except (KeyError, TypeError, AttributeError) as e:
            self.logger.debug(f"Error in batch flush: {e}")
            return False
        except Exception as e:
            self.logger.warning(f"Unexpected error in batch flush: {e}")
            return False

    def _handle_duplicate_write_or_buffer(self, *, index: str, expiry_code: str, offset: int,
                                           row: list[Any], row_sig: tuple[str, int], option_file: str,
                                           header: list[str], file_exists: bool,
                                           batching_enabled: bool, batch_key: tuple[str, str, str]) -> bool:
        """Handle duplicate suppression and either buffer or write the row.

        Returns True if the caller should continue (i.e., row was duplicate and skipped),
        False otherwise (row accepted / written / buffered).
        Preserves previous side effects: metrics increment, last_row_keys update, verbose logging.
        """
        try:
            last_ts = self._last_row_keys.get(row_sig)
            if last_ts == row[0]:
                if self.verbose:
                    self.logger.debug("Duplicate row suppressed index=%s expiry=%s offset=%s ts=%s", index, expiry_code, offset, row[0])
                return True
            if batching_enabled:
                # Delegate to batcher when available
                try:
                    if self.batcher:
                        self.batcher.buffer_row(
                            batch_key=batch_key,
                            filepath=option_file,
                            row=row,
                            header=header,
                        )
                except (AttributeError, TypeError) as e:
                    # Fall through to legacy mirror buffer update
                    self.logger.debug(f"Batcher not available, using legacy buffer: {e}")
                # Maintain legacy mirrors for health/backlog helpers
                buf = self._batch_buffers.setdefault(batch_key, {}).setdefault(option_file, {'header': header, 'rows': []})
                buf['rows'].append(row)
                self._batch_counts[batch_key] = self._batch_counts.get(batch_key, 0) + 1
            else:
                self._append_csv_row(option_file, row, header if not file_exists else None)
                self._last_row_keys[row_sig] = row[0]
                if self.verbose:
                    self.logger.debug("Option data written to %s", option_file)
                self._metric_inc('csv_records_written', 1)
        except (IOError, OSError, PermissionError) as e:
            # I/O errors - fail open to avoid crash
            self.logger.warning(f"Failed to write row: {e}")
            return False
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            # Data structure errors - fail open
            self.logger.debug(f"Error processing row: {e}")
            return False
        except Exception as e:
            # Unexpected error - fail open to avoid crash
            self.logger.error(f"Unexpected error in duplicate handler: {e}", exc_info=True)
            return False
        return False

    def _maybe_skip_as_junk(self, *, index: str, expiry_code: str, offset: int,
                             call_data: dict[str, Any] | None, put_data: dict[str, Any] | None,
                             row_ts: str) -> bool:
        """Delegate to JunkFilter (extracted). Returns True if row should be skipped.

        Parity: Maintains prior metrics & logging side effects via adapter layer.
        """
        # Delegate exclusively to JunkFilter to preserve legacy gating/whitelist semantics
        try:
            # Backward-compatible config reload semantics:
            # Legacy tests delete `_junk_cfg_loaded` to force re-evaluation of env.
            # We mirror that by recreating the filter when:
            #   - Filter not yet created
            #   - `_junk_cfg_loaded` attribute missing
            #   - Whitelist value changed since last build
            current_whitelist_env = _os_env.environ.get('G6_CSV_JUNK_WHITELIST','')
            rebuild = False
            if not hasattr(self, '_junk_filter'):
                rebuild = True
            elif not hasattr(self, '_junk_cfg_loaded'):
                rebuild = True
            elif getattr(self, '_junk_cfg_whitelist_val', None) != current_whitelist_env:
                rebuild = True
            if rebuild:
                # Lazy import & init
                cfg = JunkFilterConfig.from_env(_os_env.environ)
                callbacks = JunkFilterCallbacks(
                    log_info=lambda m: self.logger.info(m) if self.logger else None,
                    log_debug=lambda m: self.logger.debug(m) if self.logger else None,
                )
                self._junk_filter = JunkFilter(cfg, callbacks=callbacks)
                # Mark config loaded for legacy test hooks and record whitelist snapshot
                self._junk_cfg_loaded = True
                self._junk_cfg_whitelist_val = current_whitelist_env
            jf = self._junk_filter
            skip, decision = jf.should_skip(index, expiry_code, offset, call_data, put_data, row_ts)
            if not skip:
                return False
            # Metrics on first occurrence only (mirrors legacy)
            if decision.first_time:
                self._metric_inc('csv_junk_rows_skipped', 1, {'index': index, 'expiry': expiry_code})
                if decision.category == 'threshold':
                    self._metric_inc('csv_junk_rows_threshold', 1, {'index': index, 'expiry': expiry_code})
                elif decision.category == 'stale':
                    self._metric_inc('csv_junk_rows_stale', 1, {'index': index, 'expiry': expiry_code})
            if decision.summary_emitted and decision.summary_snapshot:
                snap = decision.summary_snapshot
                self.logger.info(
                    "CSV_JUNK_SUMMARY window=%ss total=%s threshold=%s stale=%s",
                    snap.get('window'),
                    snap.get('total'),
                    snap.get('threshold'),
                    snap.get('stale')
                )
            if self.verbose:
                try:
                    route_error('csv.junk.skip', self.logger, self.metrics, index=index, expiry=expiry_code, offset=offset, category=decision.category)
                except (AttributeError, TypeError) as e:
                    self.logger.debug(f"CSV_JUNK_SKIP index={index} expiry={expiry_code} offset={offset} category={decision.category} (route_error failed: {e})")
            return True
        except (AttributeError, TypeError, KeyError) as e:
            self.logger.debug(f"Error in junk skip logic: {e}")
            return False
        except Exception as e:
            self.logger.warning(f"Unexpected error in junk skip handler: {e}")
            return False

    def _handle_expiry_misclassification(self, *, index: str, expiry_code: str, expiry_str: str,
                                         offset: int, row: list[Any], atm_strike: float,
                                         index_price: float) -> tuple[str, bool]:
        """Handle expiry misclassification remediation logic.

        Mirrors previous inline logic exactly (rewrite/quarantine/reject policies) with no behavior change.
        Returns (possibly_same_or_rewritten_expiry_code, skip_row_flag).
        Swallows exceptions internally to preserve robustness of main loop.
        """
        # Gate detection by env flag
        if not EnvConfig.get_bool('G6_EXPIRY_MISCLASS_DETECT', True):
            return expiry_code, False
        try:
            if not hasattr(self, '_expiry_canonical_map'):
                self._expiry_canonical_map = {}
            # Dedupe structure to prevent duplicate misclassification increments within a single write cycle
            if not hasattr(self, '_expiry_misclass_dedupe'):
                self._expiry_misclass_dedupe = set()
            if not hasattr(self, '_expiry_policy_loaded'):
                policy = EnvConfig.get_str('G6_EXPIRY_MISCLASS_POLICY', 'rewrite').strip().lower()
                if policy not in ('rewrite','quarantine','reject'):
                    policy = 'rewrite'
                self._expiry_misclass_policy = policy
                self._expiry_quarantine_dir = EnvConfig.get_str('G6_EXPIRY_QUARANTINE_DIR','data/quarantine/expiries')
                self._expiry_rewrite_annotate = EnvConfig.get_bool('G6_EXPIRY_REWRITE_ANNOTATE', True)
                self._expiry_summary_interval = EnvConfig.get_int('G6_EXPIRY_SUMMARY_INTERVAL_SEC', 60)
                self._expiry_daily_stats = {}
                self._expiry_policy_loaded = True
            key = (index, expiry_code)
            prev = self._expiry_canonical_map.get(key)
            if prev is None:
                self._expiry_canonical_map[key] = expiry_str
                self._metric_set('expiry_canonical_date', 1, {'index': index, 'expiry_code': expiry_code, 'expiry_date': expiry_str})
                return expiry_code, False
            if prev == expiry_str:
                return expiry_code, False
            # Mismatch case
            _dedupe_key = (index, expiry_code, prev, expiry_str)
            # Additional guard: ensure only a single misclassification increment per (index, expiry_code)
            # even if multiple rows (CE/PE) processed in same conflicting cycle.
            if not hasattr(self, '_expiry_misclass_accounted_map'):
                # map (index, expiry_code) -> 1 once metric incremented
                self._expiry_misclass_accounted_map = {}
            accounted_key = (index, expiry_code)
            if accounted_key not in self._expiry_misclass_accounted_map:
                if _dedupe_key not in self._expiry_misclass_mis_keys if hasattr(self, '_expiry_misclass_mis_keys') else True:
                    # Create tracking set lazily (store mismatching tuples for debugging)
                    if not hasattr(self, '_expiry_misclass_mis_keys'):
                        self._expiry_misclass_mis_keys = set()
                    self._expiry_misclass_mis_keys.add(_dedupe_key)
                self._expiry_misclass_accounted_map[accounted_key] = 1
                self._metric_inc('expiry_misclassification_total', 1, {'index': index, 'expiry_code': expiry_code, 'expected_date': prev, 'actual_date': expiry_str})
            else:
                if EnvConfig.get_bool('G6_EXPIRY_MISCLASS_DEBUG', False):
                    self.logger.debug('misclass_duplicate_suppressed index=%s code=%s expected=%s actual=%s', index, expiry_code, prev, expiry_str)
            if EnvConfig.get_bool('G6_EXPIRY_MISCLASS_DEBUG', False):
                try:
                    # Pass metrics=None to avoid duplicate increment (we already incremented metric above)
                    route_error('csv.expiry.misclass', self.logger, None, index=index, expiry_tag=expiry_code, expected=prev, actual=expiry_str, offset=offset)
                except (AttributeError, TypeError) as e:
                    self.logger.warning("EXPIRY_MISCLASS index=%s code=%s expected=%s actual=%s offset=%s ts=%s (route_error failed: %s)", index, expiry_code, prev, expiry_str, offset, row[0], e)
            legacy_skip = EnvConfig.get_bool('G6_EXPIRY_MISCLASS_SKIP', False)
            if legacy_skip:
                try:
                    _m = get_metrics()
                    dep = getattr(_m, 'deprecated_usage_total', None)
                    if dep is not None:
                        dep.labels(component='expiry_misclass_skip_flag').inc()
                except (AttributeError, TypeError):
                    pass  # Metrics not available
            policy = 'reject' if legacy_skip else getattr(self, '_expiry_misclass_policy', 'rewrite')
            # Apply policy
            try:
                if policy == 'rewrite':
                    original_code = expiry_code
                    if getattr(self, '_expiry_rewrite_annotate', False):
                        if not hasattr(self, '_rewrite_annotations'):
                            self._rewrite_annotations = []
                        self._rewrite_annotations.append((row, original_code, prev))
                    # Logical tag preserved; rewrite in-place semantics unchanged
                    self._metric_inc('expiry_rewritten_total', 1, {'index': index, 'from_code': original_code, 'to_code': expiry_code})
                    try:
                        self._update_expiry_daily_stats('rewritten')
                    except (AttributeError, KeyError) as e:
                        self.logger.debug(f"Failed to update expiry daily stats: {e}")
                    return expiry_code, False
                elif policy == 'quarantine':
                    try:
                        qdir = getattr(self, '_expiry_quarantine_dir', 'data/quarantine/expiries')
                        qdate = datetime.date.today().strftime('%Y%m%d')
                        qpath_dir = os.path.join(qdir)
                        os.makedirs(qpath_dir, exist_ok=True)
                        qfile = os.path.join(qpath_dir, f"{qdate}.ndjson")
                        rec = {'ts': row[0], 'index': index, 'original_expiry_code': expiry_code, 'canonical_expiry_code': prev, 'reason': 'expiry_misclassification', 'row': {'expiry_date': expiry_str, 'offset': offset, 'index_price': index_price, 'atm_strike': atm_strike}}
                        with open(qfile, 'a', encoding='utf-8') as qf:
                            qf.write(json.dumps(rec) + '\n')
                    except Exception as qe:
                        if self.logger:
                            self.logger.debug("EXPIRY_QUARANTINE_WRITE_FAIL index=%s code=%s err=%s", index, expiry_code, qe)
                    self._metric_inc('expiry_quarantined_total', 1, {'index': index, 'expiry_code': expiry_code})
                    try:
                        iso_date = datetime.date.today().isoformat()
                        if not hasattr(self, '_expiry_quarantine_pending_counts'):
                            self._expiry_quarantine_pending_counts = {}
                        self._expiry_quarantine_pending_counts[iso_date] = (
                            self._expiry_quarantine_pending_counts.get(iso_date, 0) + 1
                        )
                        self._metric_set(
                            'expiry_quarantine_pending',
                            self._expiry_quarantine_pending_counts[iso_date],
                            {'date': iso_date},
                        )
                    except (AttributeError, KeyError, TypeError) as e:
                        self.logger.debug(f"Failed to update quarantine metrics: {e}")
                    try:
                        self._update_expiry_daily_stats('quarantined')
                    except (AttributeError, KeyError) as e:
                        self.logger.debug(f"Failed to update expiry daily stats: {e}")
                    return expiry_code, True
                else:  # reject
                    self._metric_inc('expiry_rejected_total', 1, {'index': index, 'expiry_code': expiry_code})
                    try:
                        self._update_expiry_daily_stats('rejected')
                    except (AttributeError, KeyError) as e:
                        self.logger.debug(f"Failed to update expiry daily stats: {e}")
                    return expiry_code, True
            except (IOError, OSError, PermissionError) as e:
                self.logger.warning(f"I/O error in expiry misclassification handler: {e}")
                return expiry_code, False
            except (KeyError, AttributeError, TypeError) as e:
                self.logger.debug(f"Data error in expiry misclassification handler: {e}")
                return expiry_code, False
            except Exception as e:
                self.logger.error(f"Unexpected error in expiry misclassification handler: {e}", exc_info=True)
                return expiry_code, False
        except (KeyError, TypeError, AttributeError) as e:
            self.logger.debug(f"Error in expiry misclassification: {e}")
            return expiry_code, False
        except Exception as e:
            self.logger.warning(f"Unexpected error in expiry misclassification: {e}")
            return expiry_code, False

    def _compute_atm_strike(self, index: str, index_price: float) -> float:
        if index in ["BANKNIFTY", "SENSEX"]:
            return round(index_price / 100) * 100
        return round(index_price / 50) * 50

    def _group_by_strike(self, options_data: dict[str, dict[str, Any]]) -> dict[float, dict[str, Any]]:
        grouped: dict[float, dict[str, Any]] = {}
        for symbol, data in options_data.items():
            strike = float(data.get('strike', 0))
            opt_type = data.get('instrument_type', '')
            if strike not in grouped:
                grouped[strike] = {'CE': None, 'PE': None}
            grouped[strike][opt_type] = data
            grouped[strike][f"{opt_type}_symbol"] = symbol
        return grouped

    # ----- Per-offset TP previous close loader -----
    def _ensure_tp_prev_close_for_key(self, *, index: str, expiry_code: str, offset: int, date_key: str) -> None:
        """Load previous day's TP close for specific (index, expiry_code, offset) series.

        Reads the last row's 'tp' from the most recent prior date's options data file.
        Caches per series per day.
        """
        try:
            key = (index, expiry_code, int(offset))
            if self._tp_prev_loaded_date_by_key.get(key) == date_key:
                return
            # Walk back up to 5 prior days
            today = datetime.datetime.strptime(date_key, '%Y-%m-%d').date()
            for back in range(1, 6):
                prev_day = today - datetime.timedelta(days=back)
                # Build option file path for this series
                offset_dir = f"+{offset}" if int(offset) > 0 else f"{int(offset)}"
                option_file = os.path.join(
                    self.base_dir,
                    index,
                    expiry_code,
                    offset_dir,
                    f"{prev_day.strftime('%Y-%m-%d')}.csv",
                )
                if not os.path.isfile(option_file):
                    continue
                try:
                    with open(option_file, encoding='utf-8') as fh:
                        rdr = csv.DictReader(fh)
                        last = None
                        for r in rdr:
                            last = r
                        if last is None:
                            continue
                        try:
                            prev_tp = float(last.get('tp', '') or 0.0)
                        except Exception:
                            prev_tp = None
                        if prev_tp is not None:
                            self._tp_prev_close_by_key[key] = prev_tp
                            break
                except Exception:
                    continue
            self._tp_prev_loaded_date_by_key[key] = date_key
        except Exception:
            fallback_key = (index, expiry_code, int(offset))
            self._tp_prev_loaded_date_by_key[fallback_key] = date_key

    def _prepare_option_row(
        self,
        index: str,
        expiry_code: str,
        *,
        expiry_date_str: str,
        offset: int,
        index_price: float,
        atm_strike: float,
        call_data: dict[str, Any] | None,
        put_data: dict[str, Any] | None,
        ts_str_rounded: str,
    ) -> tuple[list[Any], list[str]]:
        offset_price = atm_strike + offset
        # Call side values
        def f(d: dict[str, Any] | None, k: str, default: float = 0.0) -> float:
            try:
                return float(d.get(k, default)) if d else default
            except Exception:
                return default
        def i(d: dict[str, Any] | None, k: str, default: int = 0) -> int:
            try:
                return int(d.get(k, default)) if d else default
            except Exception:
                return default
        ce_price = f(call_data, 'last_price')
        ce_avg = f(call_data, 'avg_price')
        ce_vol = i(call_data, 'volume')
        ce_oi = i(call_data, 'oi')
        ce_iv = f(call_data, 'iv')
        ce_delta = f(call_data, 'delta')
        ce_theta = f(call_data, 'theta')
        ce_vega = f(call_data, 'vega')
        ce_gamma = f(call_data, 'gamma')
        ce_rho = f(call_data, 'rho')
        # Put side
        pe_price = f(put_data, 'last_price')
        pe_avg = f(put_data, 'avg_price')
        pe_vol = i(put_data, 'volume')
        pe_oi = i(put_data, 'oi')
        pe_iv = f(put_data, 'iv')
        pe_delta = f(put_data, 'delta')
        pe_theta = f(put_data, 'theta')
        pe_vega = f(put_data, 'vega')
        pe_gamma = f(put_data, 'gamma')
        pe_rho = f(put_data, 'rho')
        # Aggregates
        tp_price = ce_price + pe_price
        avg_tp = ce_avg + pe_avg
        header = [
            'timestamp', 'index', 'expiry_tag', 'expiry_date', 'offset', 'index_price', 'atm', 'strike',
            'ce', 'pe', 'tp', 'avg_ce', 'avg_pe', 'avg_tp',
            'ce_vol', 'pe_vol', 'ce_oi', 'pe_oi',
            'ce_iv', 'pe_iv', 'ce_delta', 'pe_delta', 'ce_theta', 'pe_theta',
            'ce_vega', 'pe_vega', 'ce_gamma', 'pe_gamma', 'ce_rho', 'pe_rho',
            'tp_net_change', 'tp_day_change', 'tp_net_change_pct', 'tp_day_change_pct'
        ]
        # Compute per-offset tp changes using per-series open and prev close caches
        date_key: str | None = None
        try:
            # ts_str_rounded: dd-mm-YYYY HH:MM:SS; we also have expiry_date_str as
            # YYYY-MM-DD; we want file date == expiry collection date
            # Use the date part from ts_str_rounded (dd-mm-YYYY) to derive date_key
            d,m,y = ts_str_rounded.split(' ')[0].split('-')
            date_key = f"{y}-{m}-{d}"
        except Exception:
            date_key = datetime.date.today().isoformat()
        try:
            self._ensure_tp_prev_close_for_key(index=index, expiry_code=expiry_code, offset=offset, date_key=date_key)
        except Exception:
            pass
        series_key = (index, expiry_code, int(offset))
        # Initialize per-day open if needed
        if self._tp_open_date_by_key.get(series_key) != date_key:
            self._tp_open_date_by_key[series_key] = date_key
            self._tp_open_by_key[series_key] = float(tp_price)
        prev_tp_close = self._tp_prev_close_by_key.get(series_key)
        tp_net_change = float(tp_price) - float(prev_tp_close) if prev_tp_close is not None else 0.0
        tp_day_change = float(tp_price) - float(self._tp_open_by_key.get(series_key, tp_price))
        
        # Calculate percentage changes
        tp_net_change_pct = (tp_net_change / float(prev_tp_close) * 100.0) if prev_tp_close and float(prev_tp_close) != 0.0 else 0.0
        tp_day_change_pct = (tp_day_change / float(self._tp_open_by_key.get(series_key, tp_price)) * 100.0) if self._tp_open_by_key.get(series_key, tp_price) and float(self._tp_open_by_key.get(series_key, tp_price)) != 0.0 else 0.0

        row = [
            ts_str_rounded, index, expiry_code, expiry_date_str, offset, index_price, atm_strike, offset_price,
            ce_price, pe_price, tp_price, ce_avg, pe_avg, avg_tp,
            ce_vol, pe_vol, ce_oi, pe_oi,
            ce_iv, pe_iv, ce_delta, pe_delta, ce_theta, pe_theta,
            ce_vega, pe_vega, ce_gamma, pe_gamma, ce_rho, pe_rho,
            tp_net_change, tp_day_change, tp_net_change_pct, tp_day_change_pct
        ]
        # Update greek Prometheus metrics (Option B mapping) for ATM offset only.
        # We map CE/PE side greeks into existing g6_option_<greek>{index, expiry, strike, type} metrics.
        # Guard import errors or missing registry gracefully.
        try:
            if offset == 0:  # only emit ATM row to avoid cardinality explosion
                reg = get_registry()
                # Determine expiry label: prefer expiry_code (expiry_tag) or fallback to expiry_date_str
                expiry_label = expiry_code or expiry_date_str
                strike_label = str(offset_price)  # strike/offset price chosen for consistency with csv
                # Helper to set a metric if present
                def _set(greek_name: str, ce_val: float, pe_val: float) -> None:
                    attr = f"option_{greek_name}"
                    m = getattr(reg, attr, None)
                    if m is None:
                        return
                    try:
                        # CE side
                        m.labels(index=index, expiry=expiry_label, strike=strike_label, type='CE').set(ce_val)
                        # PE side
                        m.labels(index=index, expiry=expiry_label, strike=strike_label, type='PE').set(pe_val)
                    except Exception:
                        pass
                _set('delta', ce_delta, pe_delta)
                _set('theta', ce_theta, pe_theta)
                _set('gamma', ce_gamma, pe_gamma)
                _set('vega', ce_vega, pe_vega)
                _set('rho', ce_rho, pe_rho)
                _set('iv', ce_iv, pe_iv)
        except Exception:
            pass
        return row, header

    def _append_csv_row(self, filepath: str, row: list[Any], header: list[str] | None) -> None:
        # Delegate to CsvWriter when available (uses base_dir-relative paths)
        try:
            if getattr(self, 'writer', None):
                rel = filepath
                try:
                    if os.path.isabs(filepath) and str(filepath).startswith(self.base_dir):
                        rel = os.path.relpath(filepath, self.base_dir)
                except Exception:
                    pass
                # Best-effort header write if file doesn't exist
                self.writer.append_row(rel, row, header)  # type: ignore[attr-defined]
                # Metric (best-effort)
                if not os.path.isfile(filepath):
                    try:
                        if self.metrics and hasattr(self.metrics, 'csv_files_created'):
                            self.metrics.csv_files_created.inc()  # type: ignore[call-arg]
                    except Exception:
                        pass
                return
        except Exception:
            # Fallback to legacy inline path
            pass
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        file_exists = os.path.isfile(filepath)
        # Lightweight write lock gate using .lock sentinel (best-effort, non-blocking if exists)
        lock_path = filepath + '.lock'
        lock_created = False
        if not os.path.exists(lock_path):
            try:
                with open(lock_path, 'x') as _lf:
                    _lf.write(str(os.getpid()))
                lock_created = True
            except Exception:
                pass
        try:
            with open(filepath, 'a' if file_exists else 'w', newline='') as f:
                writer = csv.writer(f)
                if not file_exists and header:
                    writer.writerow(header)
                writer.writerow(row)
            # If file was newly created, increment csv_files_created metric (best-effort)
            if not file_exists:
                try:
                    if self.metrics and hasattr(self.metrics, 'csv_files_created'):
                        self.metrics.csv_files_created.inc()  # type: ignore[call-arg]
                except Exception:
                    pass
        finally:
            if lock_created:
                try:
                    os.remove(lock_path)
                except Exception:
                    pass

    def _append_many_csv_rows(self, filepath: str, rows: list[list[Any]], header: list[str] | None) -> None:
        if not rows:
            return
        # Delegate to CsvWriter when available (uses base_dir-relative paths)
        try:
            if getattr(self, 'writer', None):
                rel = filepath
                try:
                    if os.path.isabs(filepath) and str(filepath).startswith(self.base_dir):
                        rel = os.path.relpath(filepath, self.base_dir)
                except Exception:
                    pass
                self.writer.append_many_rows(rel, rows, header)  # type: ignore[attr-defined]
                if not os.path.isfile(filepath):
                    try:
                        if self.metrics and hasattr(self.metrics, 'csv_files_created'):
                            self.metrics.csv_files_created.inc()  # type: ignore[call-arg]
                    except Exception:
                        pass
                return
        except Exception:
            # Fallback to legacy inline path
            pass
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        file_exists = os.path.isfile(filepath)
        lock_path = filepath + '.lock'
        lock_created = False
        if not os.path.exists(lock_path):
            try:
                with open(lock_path, 'x') as _lf:
                    _lf.write(str(os.getpid()))
                lock_created = True
            except Exception:
                pass
        try:
            with open(filepath, 'a' if file_exists else 'w', newline='') as f:
                writer = csv.writer(f)
                if not file_exists and header:
                    writer.writerow(header)
                writer.writerows(rows)
            # If file was newly created, increment csv_files_created metric (best-effort)
            if not file_exists:
                try:
                    if self.metrics and hasattr(self.metrics, 'csv_files_created'):
                        self.metrics.csv_files_created.inc()  # type: ignore[call-arg]
                except Exception:
                    pass
        finally:
            if lock_created:
                try:
                    os.remove(lock_path)
                except Exception:
                    pass

    # ---------------- Aggregation Support -----------------
    def _update_aggregation_state(
        self,
        index: str,
        expiry_code: str,
        pcr: float,
        day_width: float,
        timestamp: datetime.datetime,
    ) -> None:
        # Update local snapshot (backward-compat)
        snap = self._agg_pcr_snapshot.setdefault(index, {})
        snap[expiry_code] = pcr
        # Track max day_width across expiries (or last non-zero)
        prev: float = self._agg_day_width.get(index, 0.0)
        if day_width >= prev:
            self._agg_day_width[index] = day_width
        self._agg_last_write.setdefault(index, timestamp)
        # Delegate to aggregator when available
        try:
            if self.aggregator:
                self.aggregator.update_aggregation_state(
                    index=index,
                    expiry_code=expiry_code,
                    pcr=pcr,
                    day_width=day_width,
                    timestamp=timestamp,
                )
        except Exception:
            pass

    def _maybe_write_aggregated_overview(self, index: str, timestamp: datetime.datetime) -> None:
        # Prefer delegating to aggregator if configured
        try:
            if self.aggregator and self.aggregator.maybe_write_aggregated_overview(index=index, timestamp=timestamp):
                return
        except Exception:
            pass
        last = self._agg_last_write.get(index)
        if not last:
            self._agg_last_write[index] = timestamp
            return
        if (timestamp - last).total_seconds() < self.overview_interval_seconds:
            return
        snapshot = self._agg_pcr_snapshot.get(index, {})
        if not snapshot:
            return
        day_width = self._agg_day_width.get(index, 0.0)
        try:
            self.write_overview_snapshot(
                index,
                snapshot,
                timestamp,
                day_width=day_width,
                expected_expiries=list(snapshot.keys()),
            )
        except Exception as e:
            self.logger.error("Error writing aggregated overview for %s: %s", index, e)
        self._agg_last_write[index] = timestamp
        # Reset snapshot for next window
        self._agg_pcr_snapshot[index] = {}
        self._agg_day_width[index] = 0.0

    # (Cardinality suppression helpers removed)
    # ---------------- Overview Helpers (DRY) -----------------
    def _overview_round_ts(self, timestamp: datetime.datetime) -> str:
        """Round timestamp to 30s IST format using primary helper with legacy fallback.

        Centralizes duplicated try/except used by per-expiry and aggregate overview writers.
        Behavior preserved: on failure, emulate the legacy rounding logic.
        Returns dd-mm-YYYY HH:MM:SS string.
        """
        try:
            return str(format_ist_dt_30s(timestamp))
        except Exception:
            second = timestamp.second
            if second % 30 < 15:
                rounded_second = (second // 30) * 30
                rounded_timestamp = timestamp.replace(second=rounded_second, microsecond=0)
            else:
                rounded_second = ((second // 30) + 1) * 30
                if rounded_second == 60:
                    rounded_second = 0
                    rounded_timestamp = timestamp.replace(second=rounded_second, microsecond=0)
                    rounded_timestamp = rounded_timestamp + datetime.timedelta(minutes=1)
                else:
                    rounded_timestamp = timestamp.replace(second=rounded_second, microsecond=0)
            return rounded_timestamp.strftime('%d-%m-%Y %H:%M:%S')

    def _overview_compute_masks(
        self,
        collected_keys: list[str],
        expected_keys: list[str] | None,
    ) -> tuple[int,int,int,int,int]:
        """Compute bit masks and counts for expiry coverage summary.

        Returns (expected_mask, collected_mask, missing_mask, expiries_expected, expiries_collected)."""
        expiry_bit_map = {'this_week':1,'next_week':2,'this_month':4,'next_month':8}
        collected_mask = 0
        for k in collected_keys:
            collected_mask |= expiry_bit_map.get(k,0)
        if expected_keys is not None and expected_keys:
            expected_mask = 0
            for k in expected_keys:
                expected_mask |= expiry_bit_map.get(k,0)
            expiries_expected = len(expected_keys)
        else:
            expected_mask = collected_mask
            expiries_expected = len(collected_keys)
        missing_mask = expected_mask & (~collected_mask)
        return expected_mask, collected_mask, missing_mask, expiries_expected, len(collected_keys)

    # ---------------- Previous Close Helpers -----------------
    def _ensure_prev_close_loaded(self, *, index: str, date_key: str) -> None:
        """Load previous day's close values for index_price and tp from overview CSV.

        Caches results per (index, date_key) to avoid repeated disk I/O.
        Falls back gracefully if no file or columns present.
        """
        try:
            if self._prev_close_loaded_date.get(index) == date_key:
                return
            # Walk back up to 5 prior calendar days to find the last available overview file
            today = datetime.datetime.strptime(date_key, '%Y-%m-%d').date()
            base_dir = os.path.join(self.base_dir, 'overview', index)
            prev_idx_close = None
            prev_tp_close = None
            for back in range(1, 6):
                prev_day = today - datetime.timedelta(days=back)
                fp = os.path.join(base_dir, f"{prev_day.strftime('%Y-%m-%d')}.csv")
                if not os.path.isfile(fp):
                    continue
                try:
                    with open(fp, encoding='utf-8') as fh:
                        rdr = csv.DictReader(fh)
                        # Find row closest to 15:30 (3:30 PM) for previous day close
                        target_time = datetime.time(15, 30)
                        closest_row = None
                        min_time_diff = None
                        
                        for r in rdr:
                            try:
                                # Parse timestamp from row (format may vary)
                                ts_str = r.get('timestamp', '')
                                if not ts_str:
                                    continue
                                # Try parsing common formats
                                row_time = None
                                for fmt in ['%Y-%m-%d %H:%M:%S', '%d-%m-%Y %H:%M:%S', '%Y-%m-%d %H:%M']:
                                    try:
                                        dt = datetime.datetime.strptime(ts_str, fmt)
                                        row_time = dt.time()
                                        break
                                    except:
                                        continue
                                
                                if row_time:
                                    # Calculate time difference to 15:30
                                    time_diff = abs((datetime.datetime.combine(datetime.date.today(), row_time) - 
                                                    datetime.datetime.combine(datetime.date.today(), target_time)).total_seconds())
                                    if min_time_diff is None or time_diff < min_time_diff:
                                        min_time_diff = time_diff
                                        closest_row = r
                            except:
                                # If timestamp parsing fails, keep last row as fallback
                                closest_row = r
                        
                        if closest_row:
                            # index_price prev close
                            try:
                                prev_idx_close = float(closest_row.get('index_price', '') or 0.0)
                            except Exception:
                                prev_idx_close = None
                            # tp prev close (may be absent on older schema)
                            try:
                                prev_tp_close = float(closest_row.get('tp', '') or 0.0)
                            except Exception:
                                prev_tp_close = None
                            break
                except Exception:
                    continue
            if prev_idx_close is not None:
                self._index_prev_close[index] = prev_idx_close
            if prev_tp_close is not None:
                self._tp_prev_close[index] = prev_tp_close
            self._prev_close_loaded_date[index] = date_key
        except Exception:
            # Best-effort; leave unset on failure
            self._prev_close_loaded_date[index] = date_key

    def _write_overview_file(
        self,
        index: str,
        expiry_code: str,
        pcr: float,
        day_width: float,
        timestamp: datetime.datetime,
        index_price: float,
        *,
        index_net_change: float = 0.0,
        index_day_change: float = 0.0,
        tp_value: float = 0.0,
        tp_net_change: float = 0.0,
        tp_day_change: float = 0.0,
        vix: float | None = None,
    ) -> None:
        """Write overview file for a specific index."""
        # Create overview directory for this index
        overview_dir = os.path.join(self.base_dir, "overview", index)
        os.makedirs(overview_dir, exist_ok=True)

        # Determine file path
        overview_file = os.path.join(overview_dir, f"{timestamp.strftime('%Y-%m-%d')}.csv")

        # Check if file exists
        file_exists = os.path.isfile(overview_file)

        # Unified IST 30s rounding for overview timestamp (DRY helper)
        ts_str = self._overview_round_ts(timestamp)

        # Read existing data to update PCR values
        pcr_values = {
            'pcr_this_week': 0.0,
            'pcr_next_week': 0.0,
            'pcr_this_month': 0.0,
            'pcr_next_month': 0.0,
        }

        # Update the specific expiry code's PCR
        pcr_values[f'pcr_{expiry_code}'] = pcr

        # Write to CSV
        with open(overview_file, 'a' if file_exists else 'w', newline='') as f:
            writer = csv.writer(f)

            # Write header if new file
            if not file_exists:
                writer.writerow([
                    'timestamp', 'index',
                    'pcr_this_week', 'pcr_next_week', 'pcr_this_month', 'pcr_next_month',
                    'day_width',
                    'index_price', 'index_net_change', 'index_day_change',
                    'VIX',
                ])

            # Write data row
            writer.writerow([
                ts_str, index,
                pcr_values['pcr_this_week'], pcr_values['pcr_next_week'],
                pcr_values['pcr_this_month'], pcr_values['pcr_next_month'],
                day_width,
                float(index_price or 0.0), float(index_net_change), float(index_day_change),
                float(vix or 0.0),
            ])

        self.logger.info("Overview data written to %s", overview_file)
        # Metric (wrapper)
        self._metric_inc('csv_overview_writes', 1, {'index': index})

    def write_overview_snapshot(
        self,
        index: str,
        pcr_snapshot: dict[str, float],
        timestamp: datetime.datetime,
        day_width: float = 0.0,
        expected_expiries: list[str] | None = None,
        *,
        vix: float | None = None,
    ) -> None:
        """Write a single aggregated overview row with multiple expiry PCRs.

        Args:
            index: Index symbol
            pcr_snapshot: Mapping of expiry_code -> pcr value (e.g., {'this_week': 0.92, 'next_week': 1.01})
            timestamp: Base timestamp (will be rounded identically to per-expiry method)
            day_width: Representative day width (use last or max); default 0
        """
        # Delegate to CsvAggregator when available for unified behavior
        try:
            if self.aggregator:
                # Sync last price/open maps for accurate deltas
                try:
                    if isinstance(getattr(self, '_index_last_price', None), dict):
                        self.aggregator._index_last_price = dict(self._index_last_price)  # type: ignore[attr-defined]
                    if isinstance(getattr(self, '_index_open_price', None), dict):
                        self.aggregator._index_open_price = dict(self._index_open_price)  # type: ignore[attr-defined]
                    if hasattr(self, '_last_vix'):
                        self.aggregator._last_vix = getattr(self, '_last_vix', None)  # type: ignore[attr-defined]
                except Exception:
                    pass
                self.aggregator.write_overview_snapshot(
                    index=index,
                    pcr_snapshot=pcr_snapshot,
                    timestamp=timestamp,
                    day_width=day_width,
                    expected_expiries=expected_expiries,
                    vix=vix,
                )
                # Mirror metric to existing registry wrapper
                self._metric_inc('csv_overview_aggregate_writes', 1, {'index': index})
                return
        except Exception:
            pass
        # Unified IST rounding for aggregate snapshot (DRY helper)
        ts_str = self._overview_round_ts(timestamp)

        # Build output row using existing column set
        overview_dir = os.path.join(self.base_dir, "overview", index)
        os.makedirs(overview_dir, exist_ok=True)
        overview_file = os.path.join(overview_dir, f"{timestamp.strftime('%Y-%m-%d')}.csv")
        file_exists = os.path.isfile(overview_file)

        expected_mask, collected_mask, missing_mask, expiries_expected, expiries_collected = (
            self._overview_compute_masks(list(pcr_snapshot.keys()), expected_expiries)
        )

        with open(overview_file, 'a' if file_exists else 'w', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    'timestamp', 'index',
                    'pcr_this_week', 'pcr_next_week', 'pcr_this_month', 'pcr_next_month',
                    'day_width',
                    'index_price', 'index_net_change', 'index_day_change',
                    'VIX',
                    'expiries_expected', 'expiries_collected',
                    'expected_mask', 'collected_mask', 'missing_mask'
                ])

            # Use last seen index/tp values and prev closes tracked during write_options_data calls
            date_key = timestamp.strftime('%Y-%m-%d')
            try:
                self._ensure_prev_close_loaded(index=index, date_key=date_key)
            except Exception:
                pass
            idx_price = float(self._index_last_price.get(index, 0.0))
            idx_day_ch = float(idx_price - float(self._index_open_price.get(index, idx_price)))
            idx_prev_close = self._index_prev_close.get(index)
            idx_net = float(idx_price - float(idx_prev_close)) if idx_prev_close is not None else 0.0
            # TP fields removed from overview (per request)

            use_vix = float(vix) if vix is not None else float(self._last_vix or 0.0)
            writer.writerow([
                ts_str, index,
                pcr_snapshot.get('this_week', 0),
                pcr_snapshot.get('next_week', 0),
                pcr_snapshot.get('this_month', 0),
                pcr_snapshot.get('next_month', 0),
                day_width,
                idx_price, idx_net, idx_day_ch,
                use_vix,
                expiries_expected, expiries_collected,
                expected_mask, collected_mask, missing_mask
            ])

        if getattr(self, '_concise', False):
            self.logger.debug("Aggregated overview snapshot written for %s -> %s", index, overview_file)
        else:
            self.logger.info("Aggregated overview snapshot written for %s -> %s", index, overview_file)
        # Metric (wrapper)
        self._metric_inc('csv_overview_aggregate_writes', 1, {'index': index})

    def read_options_overview(self, index: str, date: datetime.date | str | None = None) -> dict[str, dict[str, Any]]:
        """
        Read overview data from CSV file.
        
        Args:
            index: Index symbol (e.g., 'NIFTY')
            date: Date to read data for (defaults to today)
            
        Returns:
            Dict of overview data by timestamp
        """
        # Use today's date if not specified
        if date is None:
            date = datetime.date.today()

        # Format date as string
        date_str = date.strftime('%Y-%m-%d') if isinstance(date, datetime.date) else date

        # Build file path
        overview_file = os.path.join(self.base_dir, "overview", index, f"{date_str}.csv")

        # Check if file exists
        if not os.path.exists(overview_file):
            self.logger.warning("No overview file found for %s on %s", index, date_str)
            return {}

        # Read CSV file
        overview_data = {}
        with open(overview_file) as f:
            reader = csv.DictReader(f)
            for row in reader:
                timestamp = row['timestamp']
                overview_data[timestamp] = {
                    'index': row['index'],
                    'pcr_this_week': float(row.get('pcr_this_week', 0)),
                    'pcr_next_week': float(row.get('pcr_next_week', 0)),
                    'pcr_this_month': float(row.get('pcr_this_month', 0)),
                    'pcr_next_month': float(row.get('pcr_next_month', 0)),
                    'day_width': float(row.get('day_width', 0)),
                    'expiries_expected': int(row.get('expiries_expected', 0)) if 'expiries_expected' in row else 0,
                    'expiries_collected': int(row.get('expiries_collected', 0)) if 'expiries_collected' in row else 0,
                    'expected_mask': int(row.get('expected_mask', 0)) if 'expected_mask' in row else 0,
                    'collected_mask': int(row.get('collected_mask', 0)) if 'collected_mask' in row else 0,
                    'missing_mask': int(row.get('missing_mask', 0)) if 'missing_mask' in row else 0
                }

        self.logger.info("Read overview data from %s", overview_file)
        return overview_data

    def read_option_data(
        self,
        index: str,
        expiry_code: str,
        offset: int | str,
        date: datetime.date | str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Read option data for a specific offset.
        
        Args:
            index: Index symbol (e.g., 'NIFTY')
            expiry_code: Expiry code (e.g., 'this_week')
            offset: Strike offset from ATM (e.g., +50, -100)
            date: Date to read data for (defaults to today)
            
        Returns:
            List of option data points
        """
        # Use today's date if not specified
        if date is None:
            date = datetime.date.today()

        # Format date as string
        date_str = date.strftime('%Y-%m-%d') if isinstance(date, datetime.date) else date

        # Format offset for directory name
        if int(offset) > 0:
            offset_dir = f"+{int(offset)}"
        else:
            offset_dir = f"{int(offset)}"

        # Build file path
        option_file = os.path.join(self.base_dir, index, expiry_code, offset_dir, f"{date_str}.csv")

        # Check if file exists
        if not os.path.exists(option_file):
            self.logger.warning("No option file found for %s %s offset %s on %s", index, expiry_code, offset, date_str)
            return []

        # Read CSV file
        with open(option_file) as f:
            reader = csv.DictReader(f)

            def _map_row(r: dict[str, Any]) -> dict[str, Any]:
                # Backward compatibility: legacy columns 'strike' (index price)
                # and 'offset_price' (strike) may exist
                index_price_val = float(r.get('index_price', r.get('strike', 0)))
                if 'index_price' in r:
                    strike_val = float(r.get('strike', r.get('offset_price', 0)))
                else:
                    strike_val = float(r.get('offset_price', 0))
                return {
                    'timestamp': r['timestamp'],
                    'index': r['index'],
                    'expiry_tag': r['expiry_tag'],
                    'offset': int(r['offset']),
                    'index_price': index_price_val,
                    'atm': float(r['atm']),
                    'strike': strike_val,
                    'ce': float(r['ce']),
                    'pe': float(r['pe']),
                    'tp': float(r['tp']),
                    'avg_ce': float(r['avg_ce']),
                    'avg_pe': float(r['avg_pe']),
                    'avg_tp': float(r['avg_tp']),
                    'ce_vol': int(r['ce_vol']),
                    'pe_vol': int(r['pe_vol']),
                    'ce_oi': int(r['ce_oi']),
                    'pe_oi': int(r['pe_oi']),
                    'ce_iv': float(r['ce_iv']),
                    'pe_iv': float(r['pe_iv']),
                    'ce_delta': float(r['ce_delta']),
                    'pe_delta': float(r['pe_delta']),
                    'ce_theta': float(r['ce_theta']),
                    'pe_theta': float(r['pe_theta']),
                    'ce_vega': float(r['ce_vega']),
                    'pe_vega': float(r['pe_vega']),
                    'ce_gamma': float(r['ce_gamma']),
                    'pe_gamma': float(r['pe_gamma']),
                    'ce_rho': float(r.get('ce_rho', 0)),
                    'pe_rho': float(r.get('pe_rho', 0)),
                }

            option_data = [_map_row(row) for row in reader]

        self.logger.info("Read %s option records from %s", len(option_data), option_file)
        return option_data

    # Add this method to the CsvSink class

    def check_health(self) -> dict[str, Any]:
        """
        Check if the CSV sink is healthy.
        
        Returns:
            Dict with health status information
        """
        try:
            components: list[dict[str, Any]] = []
            status_ok = True
            # Ensure base dir exists
            if not os.path.exists(self.base_dir):
                try:
                    os.makedirs(self.base_dir, exist_ok=True)
                except Exception as e:
                    components.append({'component': 'base_dir', 'status': 'error', 'message': f'create_failed: {e}'})
                    status_ok = False
            # Disk space check
            disk_free_mb = None
            try:
                total, used, free = shutil.disk_usage(self.base_dir)
                disk_free_mb = int(free / (1024*1024))
                min_free_mb_env = _os_env.environ.get('G6_HEALTH_MIN_FREE_MB')
                if min_free_mb_env is not None:
                    try:
                        min_free_mb = int(min_free_mb_env)
                    except Exception:
                        min_free_mb = 0
                else:
                    min_free_mb = 0
                if min_free_mb and disk_free_mb < min_free_mb:
                    components.append({
                        'component': 'disk_space',
                        'status': 'error',
                        'free_mb': disk_free_mb,
                        'required_mb': min_free_mb,
                    })
                    status_ok = False
                else:
                    components.append({
                        'component': 'disk_space',
                        'status': 'ok',
                        'free_mb': disk_free_mb,
                        'required_mb': min_free_mb,
                    })
            except Exception as e:
                components.append({'component': 'disk_space', 'status': 'error', 'message': f'usage_failed: {e}'})
                status_ok = False
            # Write latency check
            write_latency_ms = None
            try:
                test_file = os.path.join(self.base_dir, '.health_latency')
                t0 = time.time()
                with open(test_file, 'w') as f:
                    f.write('x')
                os.remove(test_file)
                t1 = time.time()
                write_latency_ms = round((t1 - t0) * 1000, 3)
                components.append({'component': 'write_latency', 'status': 'ok', 'latency_ms': write_latency_ms})
            except Exception as e:
                components.append({'component': 'write_latency', 'status': 'error', 'message': f'write_failed: {e}'})
                status_ok = False
            # Overview freshness (optional)
            overview_fresh = None
            try:
                max_age_env = _os_env.environ.get('G6_HEALTH_OVERVIEW_MAX_AGE_SEC')
                if max_age_env is not None:
                    try:
                        max_age = int(max_age_env)
                    except Exception:
                        max_age = 0
                    latest_mtime = None
                    overview_root = os.path.join(self.base_dir, 'overview')
                    if os.path.isdir(overview_root):
                        for root, _dirs, files in os.walk(overview_root):
                            for fn in files:
                                if fn.endswith('.csv'):
                                    fp = os.path.join(root, fn)
                                    try:
                                        mt = os.path.getmtime(fp)
                                        latest_mtime = self._max_mtime(latest_mtime, mt)
                                    except Exception:
                                        continue
                    if latest_mtime is not None and max_age > 0:
                        age = time.time() - latest_mtime
                        overview_fresh = age <= max_age
                        components.append({
                            'component': 'overview_freshness',
                            'status': 'ok' if overview_fresh else 'stale',
                            'age_sec': round(age, 2),
                            'max_age_sec': max_age,
                        })
                        if not overview_fresh:
                            status_ok = False
                    elif max_age > 0:
                        components.append({
                            'component': 'overview_freshness',
                            'status': 'unknown',
                            'message': 'no_overview_files',
                        })
            except Exception as e:
                components.append({'component': 'overview_freshness', 'status': 'error', 'message': f'freshness_failed: {e}'})
                status_ok = False
            # Metrics gauges (best-effort)
            try:
                self._metric_set('csv_sink_health_status', 1 if status_ok else 0, None)
                if write_latency_ms is not None:
                    self._metric_set('csv_sink_write_latency_ms', write_latency_ms, None)
                if disk_free_mb is not None:
                    self._metric_set('csv_sink_disk_free_mb', disk_free_mb, None)
            except Exception:
                pass
            # ---------------- Advanced Diagnostics (opt-in via G6_HEALTH_ADVANCED) ----------------
            issues: list[dict[str, Any]] = []
            health_score = 100 if status_ok else 0
            if _os_env.environ.get('G6_HEALTH_ADVANCED','0').lower() in ('1','true','yes','on'):
                now_ts = time.time()
                adv_components: list[dict[str, Any]] = []
                # Backlog stats
                try:
                    backlog = self._collect_backlog_stats()
                    adv_components.append({'component': 'batch_backlog', **backlog})
                    self._metric_set('csv_sink_backlog_rows', backlog.get('queued_rows', 0), None)
                    self._metric_set('csv_sink_backlog_files', backlog.get('buffer_files', 0), None)
                    # Heuristic backlog pressure alert
                    if backlog.get('queued_rows', 0) > 0 and backlog.get('flush_threshold', 0) > 0:
                        if backlog['queued_rows'] > backlog['flush_threshold'] * 5:
                            issues.append({
                                'code': 'backlog_excess',
                                'message': (
                                    f"queued_rows={backlog['queued_rows']} "
                                    f"threshold={backlog['flush_threshold']}"
                                ),
                                'severity': 'medium',
                            })
                            health_score -= 10
                except Exception:
                    adv_components.append({'component': 'batch_backlog', 'status': 'error'})
                # Idle detection
                try:
                    idle_info = self._detect_idle(now_ts)
                    adv_components.append({'component': 'idle_state', **idle_info})
                    if idle_info.get('stale'):
                        issues.append({
                            'code': 'idle_stale',
                            'message': f"idle_for_sec={idle_info.get('idle_for_sec')}",
                            'severity': 'low',
                        })
                        health_score -= 5
                except Exception:
                    adv_components.append({'component': 'idle_state', 'status': 'error'})
                # Stale lock scan
                try:
                    lock_info = self._scan_stale_locks(now_ts)
                    adv_components.append({'component': 'stale_locks', **lock_info})
                    if lock_info.get('stale_count', 0) > 0:
                        issues.append({
                            'code': 'stale_locks',
                            'message': f"stale_count={lock_info.get('stale_count')}",
                            'severity': 'medium',
                        })
                        health_score -= min(15, lock_info.get('stale_count', 0) * 2)
                except Exception:
                    adv_components.append({'component': 'stale_locks', 'status': 'error'})
                # Config validation
                try:
                    cfg_info = self._validate_config()
                    adv_components.append({'component': 'config_validation', **cfg_info})
                    if not cfg_info.get('valid'):
                        issues.append({
                            'code': 'config_invalid',
                            'message': cfg_info.get('error', 'invalid'),
                            'severity': 'high',
                        })
                        health_score -= 25
                except Exception:
                    adv_components.append({'component': 'config_validation', 'status': 'error'})
                # Clamp & emit score
                health_score = max(0, min(100, health_score))
                try:
                    self._metric_set('csv_sink_health_score', health_score, None)
                except Exception:
                    pass
                components.extend(adv_components)
            return {
                'status': 'healthy' if status_ok else 'unhealthy',
                'message': 'CSV sink is healthy' if status_ok else 'One or more health checks failed',
                'components': components,
                'disk_free_mb': disk_free_mb,
                'write_latency_ms': write_latency_ms,
                'overview_fresh': overview_fresh,
                'issues': issues,
                'health_score': health_score
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'message': f'Health check failed: {e}'
            }

    # ---------------- Advanced Health Helper Methods ----------------
    def _collect_backlog_stats(self) -> dict[str, Any]:
        """Compute backlog statistics for batched writes.

        Returns mapping with queued_rows, buffer_files, flush_threshold.
        Safe on missing attributes (returns zeros)."""
        queued_rows = 0
        buffer_files = 0
        flush_threshold = getattr(self, '_batch_flush_threshold', 0)
        batch_buffers = getattr(self, '_batch_buffers', None)
        if not batch_buffers:
            return {'queued_rows': 0, 'buffer_files': 0, 'flush_threshold': flush_threshold}
        try:
            for file_map in batch_buffers.values():
                if not isinstance(file_map, dict):
                    continue
                for payload in file_map.values():
                    if not isinstance(payload, dict):
                        continue
                    _rows_obj = payload.get('rows')
                    rows: list[Any] = _rows_obj if isinstance(_rows_obj, list) else []
                    if rows:
                        queued_rows += len(rows)
                        buffer_files += 1
        except Exception:
            pass
        return {'queued_rows': queued_rows, 'buffer_files': buffer_files, 'flush_threshold': flush_threshold}

    def _detect_idle(self, now_ts: float) -> dict[str, Any]:
        """Detect idle state based on last aggregated write per index.

        Uses env G6_HEALTH_IDLE_MAX_SEC (disabled if unset/zero)."""
        last_map = getattr(self, '_agg_last_write', None)
        if not last_map:
            return {'stale': True, 'idle_for_sec': None, 'max_idle_sec': 0}
        try:
            latest_dt = max(dt for dt in last_map.values() if isinstance(dt, datetime.datetime))
            idle_for = now_ts - latest_dt.timestamp()
        except Exception:
            return {'stale': False, 'idle_for_sec': None, 'max_idle_sec': 0}
        max_idle_env = _os_env.environ.get('G6_HEALTH_IDLE_MAX_SEC')
        if max_idle_env:
            try:
                max_idle_sec = int(max_idle_env)
            except Exception:
                max_idle_sec = 0
        else:
            max_idle_sec = 0
        stale = bool(max_idle_sec and idle_for > max_idle_sec)
        return {'stale': stale, 'idle_for_sec': round(idle_for, 2), 'max_idle_sec': max_idle_sec}

    def _scan_stale_locks(self, now_ts: float) -> dict[str, Any]:
        """Scan .lock files under base_dir and count stale ones.

        Staleness threshold controlled by G6_HEALTH_LOCK_STALE_SEC (default 300)."""
        base = getattr(self, 'base_dir', '.')
        stale_env = _os_env.environ.get('G6_HEALTH_LOCK_STALE_SEC')
        try:
            stale_threshold = int(stale_env) if stale_env else 300
        except Exception:
            stale_threshold = 300
        total = 0
        stale_count = 0
        try:
            for root, _dirs, files in os.walk(base):
                for fn in files:
                    if not fn.endswith('.lock'):
                        continue
                    total += 1
                    fp = os.path.join(root, fn)
                    try:
                        mt = os.path.getmtime(fp)
                        if now_ts - mt > stale_threshold:
                            stale_count += 1
                    except Exception:
                        continue
        except Exception:
            pass
        return {'total_locks': total, 'stale_count': stale_count, 'stale_threshold_sec': stale_threshold}

    def _max_mtime(self, current: float | None, new: float) -> float:
        """Return the newer mtime value handling None safely (helper for health checks)."""
        if current is None:
            return new
        if new > current:
            return new
        return current

    def _validate_config(self) -> dict[str, Any]:
        """Validate presence & basic structure of primary config file.

        Looks for config/g6_config.json relative to project root (two levels up)."""
        try:
            proj_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), '../..')
            )
            cfg_path = os.path.join(proj_root, 'config', 'g6_config.json')
        except Exception:
            return {'valid': False, 'error': 'path_resolve_failed'}
        if not os.path.exists(cfg_path):
            return {'valid': False, 'error': 'missing'}
        try:
            with open(cfg_path, encoding='utf-8') as f:
                data = json.load(f)
            indices = data.get('indices', {}) if isinstance(data, dict) else {}
            summary: dict[str, int] = {}
            for k, v in indices.items():
                if not isinstance(v, dict):
                    continue
                exp = v.get('expiries')
                summary[k] = len(exp) if isinstance(exp, list) else 0
            return {'valid': True, 'indices': len(indices), 'expiries_per_index': summary}
        except Exception as e:
            return {'valid': False, 'error': f'parse_error:{e}'}

    # ------------------------------------------------------------------
    # Backward Compatibility Helper Methods (restored for legacy tests)
    # ------------------------------------------------------------------
    def _compute_pcr(self, options_data: dict[str, dict[str, Any]]) -> float:
        """Compute Put/Call OI ratio.

        Mirrors legacy inline logic: sum PE oi / sum CE oi; ignores malformed entries.
        Returns 0.0 if CE OI aggregate is zero or missing.
        """
        try:
            put_oi = 0.0
            call_oi = 0.0
            for data in options_data.values():
                try:
                    typ = (data.get('instrument_type') or '').upper()
                    raw_oi = data.get('oi', 0)
                    oi_val = float(raw_oi) if isinstance(raw_oi, (int, float)) or (isinstance(raw_oi, str) and raw_oi.replace('.', '', 1).isdigit()) else 0.0
                    if typ == 'PE':
                        put_oi += oi_val
                    elif typ == 'CE':
                        call_oi += oi_val
                except Exception:
                    continue
            return put_oi / call_oi if call_oi > 0 else 0.0
        except Exception:
            return 0.0

    def _align_row_to_header(self, file_header: list[str], row: list[Any], header: list[str]) -> list[Any]:
        """Align a single row to an existing file header adding derived columns.

        Currently only derives 'atm' when present in file_header but absent in header.
        Derivation: atm = strike - offset (float conversions) per legacy tests.
        """
        try:
            mapping = {h: row[i] for i, h in enumerate(header) if i < len(row)}
            out: list[Any] = []
            for col in file_header:
                if col in mapping:
                    out.append(mapping[col])
                elif col == 'atm':
                    try:
                        strike = float(mapping.get('strike', 0))
                        offset_raw = mapping.get('offset', 0)
                        offset = float(offset_raw) if isinstance(offset_raw, (int, float, str)) else 0.0
                        out.append(strike - offset)
                    except Exception:
                        out.append(0.0)
                else:
                    # Unknown extra column -> append empty placeholder
                    out.append('')
            return out
        except Exception:
            return list(row)

    def _align_rows_for_existing_file(self, filepath: str, rows: list[list[Any]], header: list[str]) -> list[list[Any]]:
        """Read existing file header and align provided rows accordingly."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                first = f.readline().strip()
            file_header = first.split(',') if first else header
        except Exception:
            file_header = header
        aligned: list[list[Any]] = []
        for r in rows:
            aligned.append(self._align_row_to_header(file_header, r, header))
        return aligned

    def _update_open_prices(self, *, index: str, timestamp: datetime.datetime, index_price: float, tp_value: float) -> None:
        """Update per-day open prices for index and tp within 9:15-9:30 window.

        Mirrors logic embedded in write_options_data for test isolation.
        """
        try:
            date_key = timestamp.strftime('%Y-%m-%d')
            market_open_time = datetime.time(9, 15)
            market_open_window = datetime.time(9, 30)
            current_time = timestamp.time()
            # Index open tracking
            if self._index_open_date.get(index) != date_key:
                if market_open_time <= current_time <= market_open_window:
                    self._index_open_date[index] = date_key
                    self._index_open_price[index] = float(index_price)
                elif current_time < market_open_time:
                    self._index_open_date[index] = date_key
                    self._index_open_price[index] = float(index_price)
                else:
                    self._index_open_date[index] = date_key
                    self._index_open_price[index] = float(index_price)
            elif market_open_time <= current_time <= market_open_window:
                self._index_open_price[index] = float(index_price)
            # TP open tracking
            if self._tp_open_date.get(index) != date_key:
                if market_open_time <= current_time <= market_open_window:
                    self._tp_open_date[index] = date_key
                    self._tp_open[index] = float(tp_value)
                elif current_time < market_open_time:
                    self._tp_open_date[index] = date_key
                    self._tp_open[index] = float(tp_value)
                else:
                    self._tp_open_date[index] = date_key
                    self._tp_open[index] = float(tp_value)
            elif market_open_time <= current_time <= market_open_window:
                self._tp_open[index] = float(tp_value)
        except Exception:
            pass

    def _is_expiry_disallowed(self, exp_date: datetime.date) -> bool:
        """Return True if configured allowed_expiry_dates excludes exp_date; False otherwise."""
        allowed = getattr(self, 'allowed_expiry_dates', None)
        if not allowed:
            return False
        try:
            if isinstance(allowed, (set, list, tuple)):
                return exp_date not in allowed
        except Exception:
            pass
        return False

    def _resolve_index_price(self, *, index: str, options_data: dict[str, dict[str, Any]], index_price: float | None) -> float:
        """Resolve index price from explicit value, defaults mapping, or first option metadata."""
        if isinstance(index_price, (int, float)):
            return float(index_price)
        defaults = {
            'NIFTY': 24800,
            'BANKNIFTY': 54200,
            'FINNIFTY': 25900,
            'MIDCPNIFTY': 22000,
            'SENSEX': 80900,
        }
        resolved = defaults.get(index, 0.0)
        try:
            for data in options_data.values():
                if 'index_price' in data:
                    resolved = float(data.get('index_price') or resolved)
                    break
        except Exception:
            pass
        return float(resolved)

    def _compute_day_width(self, ohlc: dict[str, Any] | None) -> float:
        """Compute day width (high - low) with robust numeric parsing."""
        if not ohlc:
            return 0.0
        try:
            high = float(ohlc.get('high', 0))
            low = float(ohlc.get('low', 0))
            if high and low:
                return high - low if high >= low else 0.0
        except Exception:
            pass
        return 0.0

    def _resolve_vix(self, extra: dict[str, Any] | None) -> float:
        """Resolve VIX from extra context, cache, or external fetch."""
        try:
            if extra and 'vix' in extra:
                val = float(extra.get('vix') or 0.0)
                self._last_vix = val
                return val
            if isinstance(self._last_vix, (int, float)):
                return float(self._last_vix)
            fetch = getattr(self, '_fetch_external_vix', None)
            if callable(fetch):
                val2 = float(fetch())
                self._last_vix = val2
                return val2
        except Exception:
            pass
        return 0.0

    def _build_return_metrics(self, *, expiry_code: str, pcr: float, timestamp: datetime.datetime, day_width: float, index_price: float, flags: dict[str, bool] | None = None) -> dict[str, Any]:
        """Build metrics payload filtering out falsey flags (legacy test helper)."""
        payload = {
            'expiry_code': expiry_code,
            'pcr': float(pcr),
            'timestamp': timestamp,
            'day_width': float(day_width),
            'index_price': float(index_price),
        }
        if flags:
            for k, v in flags.items():
                if v:
                    payload[k] = True
        return payload

    def _init_batch_state_if_needed(self, *, index: str, expiry_code: str, timestamp: datetime.datetime) -> tuple[bool, tuple[str, str, str]]:
        """Initialize batch buffers for (index, expiry_code, date) when batching enabled."""
        key = (index, expiry_code, timestamp.strftime('%Y-%m-%d'))
        enabled = bool(getattr(self, '_batch_flush_threshold', 0) > 0)
        if enabled and key not in getattr(self, '_batch_buffers', {}):
            try:
                self._batch_buffers[key] = {}
                self._batch_counts[key] = 0
            except Exception:
                pass
        return enabled, key

    def _compute_change_metrics(self, *, current: float, prev_close: float | None, open_value: float | None) -> tuple[float, float, float, float]:
        """Compute net/day absolute and percentage changes with zero/None guards."""
        try:
            net = float(current - float(prev_close)) if isinstance(prev_close, (int, float)) else 0.0
        except Exception:
            net = 0.0
        try:
            day = float(current - float(open_value)) if isinstance(open_value, (int, float)) else 0.0
        except Exception:
            day = 0.0
        net_pct = (net / float(prev_close) * 100.0) if isinstance(prev_close, (int, float)) and float(prev_close) != 0.0 else 0.0
        day_pct = (day / float(open_value) * 100.0) if isinstance(open_value, (int, float)) and float(open_value) != 0.0 else 0.0
        return net, day, net_pct, day_pct

    # ------------------------------------------------------------------
    # Additional Legacy Private Helpers (restored for test compatibility)
    # ------------------------------------------------------------------
    def _build_misclass_quarantine_record(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Compatibility helper used by tests.

        Tests call with keyword names: ts, index, original_code, canonical_code,
        expiry_str, offset, index_price, atm_strike.
        Returns a record containing top-level metadata plus a nested 'row' object.
        """
        ts = kwargs.get('ts')
        index = kwargs.get('index')
        original_code = kwargs.get('original_code')
        canonical_code = kwargs.get('canonical_code')
        expiry_str = kwargs.get('expiry_str')
        offset_raw = kwargs.get('offset')
        index_price_raw = kwargs.get('index_price')
        atm_raw = kwargs.get('atm_strike')
        # Normalizations
        try:
            offset = int(float(offset_raw))
        except Exception:
            offset = 0
        try:
            index_price = float(index_price_raw)
        except Exception:
            index_price = 0.0
        try:
            atm_strike = float(atm_raw)
        except Exception:
            atm_strike = 0.0
        record = {
            'ts': str(ts),
            'index': str(index) if index is not None else '',
            'original_expiry_code': str(original_code) if original_code is not None else '',
            'canonical_expiry_code': str(canonical_code) if canonical_code is not None else '',
            'reason': 'expiry_misclassification',
            'row': {
                'expiry_date': str(expiry_str) if expiry_str is not None else '',
                'offset': offset,
                'index_price': index_price,
                'atm_strike': atm_strike,
            },
        }
        return record

    def _reorder_time_columns(
        self,
        header: list[str],
        row: list[Any],
        *,
        file_exists: bool,
    ) -> tuple[list[str], list[Any]]:
        """Reorder header/row so that 'time','time_ms' move to end when creating new file.

        Tests expect:
        - If file_exists=False and both 'time' & 'time_ms' present: move them to final two columns.
        - Preserve relative ordering of other columns.
        - If file_exists=True: return inputs unchanged.
        """
        if file_exists:
            return header, row
        try:
            if 'time' in header and 'time_ms' in header:
                # Remove time columns, append at end preserving their values
                time_idx = header.index('time')
                time_ms_idx = header.index('time_ms')
                time_val = row[time_idx]
                time_ms_val = row[time_ms_idx]
                new_header = [c for c in header if c not in ('time', 'time_ms')]
                new_row = [row[i] for i, c in enumerate(header) if c not in ('time', 'time_ms')]
                new_header.extend(['time', 'time_ms'])
                new_row.extend([time_val, time_ms_val])
                return new_header, new_row
        except Exception:
            pass
        return header, row

    def _is_preopen_and_quarantine(
        self,
        *,
        index: str,
        expiry_code: str,
        ts_str_rounded: str,
    ) -> bool:
        """Determine if timestamp falls in pre-open window and record quarantine entry.

        Tests set flags on instance (_quarantine_preopen, _allow_preopen, _preopen_cutoff, _preopen_quarantine_dir).
        Behavior:
        - If _allow_preopen True -> always False (bypass)
        - If _quarantine_preopen True and ts < cutoff -> write NDJSON record and return True
        - Else False
        """
        # Simplified deterministic implementation tailored for tests.
        if getattr(self, '_allow_preopen', False):
            return False
        if not getattr(self, '_quarantine_preopen', False):
            return False
        cutoff = str(getattr(self, '_preopen_cutoff', '09:15:30'))
        parts = ts_str_rounded.split(' ')
        if len(parts) < 2:
            return False
        try:
            hh, mm, ss = parts[1].split(':')
            c_hh, c_mm, c_ss = cutoff.split(':')
            ts_total = int(hh) * 3600 + int(mm) * 60 + int(ss)
            cutoff_total = int(c_hh) * 3600 + int(c_mm) * 60 + int(c_ss)
        except Exception:
            return False
        if ts_total < cutoff_total:
            # Write quarantine record
            try:
                import json as _json
                from datetime import datetime as _dt_local, timezone as _tz
                qdir_raw = getattr(self, '_preopen_quarantine_dir', None)
                qdir = Path(qdir_raw) if qdir_raw else (Path.cwd() / 'preopen_q')
                qdir.mkdir(parents=True, exist_ok=True)
                # Prefer timezone-aware UTC to avoid deprecation of utcnow()
                utc_name = _dt_local.now(_tz.utc).strftime('%Y%m%d')
                local_name = _dt_local.now().strftime('%Y%m%d')
                qfile = qdir / f"{utc_name}.ndjson"
                qfile_local = qdir / f"{local_name}.ndjson"
                # Ensure file exists
                if not qfile.exists():
                    qfile.touch()
                if not qfile_local.exists():
                    qfile_local.touch()
                rec = {'reason': 'preopen', 'index': index, 'expiry_code': expiry_code, 'ts_ist': ts_str_rounded}
                with qfile.open('a', encoding='utf-8') as f:
                    f.write(_json.dumps(rec) + '\n')
                if qfile_local != qfile:
                    with qfile_local.open('a', encoding='utf-8') as f:
                        f.write(_json.dumps(rec) + '\n')
            except Exception:
                try:
                    qfile.parent.mkdir(parents=True, exist_ok=True)
                    qfile.touch(exist_ok=True)
                except Exception:
                    pass
            return True
        return False
        # Fallback simplified lexicographic comparison (unreachable after return statements)

    def _nearest_price_for_type(
        self,
        options_data: dict[str, dict[str, Any]],
        instrument_type: str,
        atm_strike: float,
    ) -> float:
        """Return last_price of leg with strike nearest ATM for given instrument_type.

        Mirrors local closure used in write_options_data for compatibility with tests expecting
        private helper existence. Falls back to 0.0 on failure.
        """
        best_diff: float | None = None
        best_price: float = 0.0
        try:
            for od in options_data.values():
                if (od.get('instrument_type') or '').upper() != instrument_type.upper():
                    continue
                try:
                    k = float(od.get('strike', 0) or 0)
                except Exception:
                    continue
                diff = abs(k - atm_strike)
                if best_diff is None or diff < best_diff:
                    try:
                        best_price = float(od.get('last_price', 0) or 0)
                        best_diff = diff
                    except Exception:
                        pass
        except Exception:
            return 0.0
        return best_price
