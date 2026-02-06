# Transitional: formerly src.collectors.pipeline module moved to avoid name collision with package 'src.collectors.pipeline'
# Original content preserved below.
"""Collector pipeline abstraction (Phase 4.1 Action #2).

(Original docstring truncated for brevity in rename; full history retained in VCS.)
"""
from __future__ import annotations

import datetime
import logging
from collections.abc import Iterable

# ...original code moved from pipeline.py...
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)

@dataclass
class ExpiryWorkItem:
    index: str
    expiry_rule: str
    expiry_date: datetime.date | datetime.datetime | Any
    strikes: list[float]
    index_price: float
    atm_strike: float

@dataclass
class EnrichedExpiry:
    work: ExpiryWorkItem
    instruments: list[dict[str, Any]]
    enriched: dict[str, dict[str, Any]]

@dataclass
class PersistOutcome:
    option_count: int
    pcr: float | None
    failed: bool
    day_width: int | None = None
    snapshot_timestamp: datetime.datetime | None = None
    expiry_code: str | None = None

class ExpiryResolver(Protocol):
    def resolve(self, wi: ExpiryWorkItem) -> ExpiryWorkItem: ...

class InstrumentFetcher(Protocol):
    def fetch(self, wi: ExpiryWorkItem) -> list[dict[str, Any]]: ...

class QuoteEnricher(Protocol):
    def enrich(self, wi: ExpiryWorkItem, instruments: list[dict[str, Any]]) -> dict[str, dict[str, Any]]: ...

class AnalyticsBlock(Protocol):
    def apply(self, ee: EnrichedExpiry) -> None: ...

class PersistenceBlock(Protocol):
    def persist(self, ee: EnrichedExpiry) -> PersistOutcome: ...

class ProvidersAdapter:
    def __init__(self, providers: Any, metrics: Any | None = None) -> None:
        self.providers = providers
        self.metrics = metrics
    def resolve(self, wi: ExpiryWorkItem) -> ExpiryWorkItem:
        # If expiry_date is already provided (common in unit tests), do not force provider resolution.
        try:
            import datetime as _dt
            if isinstance(wi.expiry_date, (_dt.date, _dt.datetime)):
                return wi
        except Exception:
            pass
        expiry_date = self.providers.resolve_expiry(wi.index, wi.expiry_rule)
        wi.expiry_date = expiry_date
        return wi
    def fetch(self, wi: ExpiryWorkItem) -> list[dict[str, Any]]:
        instruments = self.providers.get_option_instruments(wi.index, wi.expiry_date, wi.strikes)
        if not isinstance(instruments, list):
            return []
        return [i for i in instruments if isinstance(i, dict)]
    def enrich(self, wi: ExpiryWorkItem, instruments: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        enriched = self.providers.enrich_with_quotes(instruments)
        if not isinstance(enriched, dict):
            return {}
        out: dict[str, dict[str, Any]] = {}
        for k, v in enriched.items():
            if isinstance(v, dict):
                out[str(k)] = v
        return out

class NoOpAnalytics(AnalyticsBlock):
    def apply(self, ee: EnrichedExpiry) -> None:  # noqa: D401
        return None

class CollectorPipeline:
    def __init__(self, resolver: ExpiryResolver, fetcher: InstrumentFetcher, enricher: QuoteEnricher, analytics: Iterable[AnalyticsBlock], persistence: PersistenceBlock) -> None:
        self.resolver = resolver
        self.fetcher = fetcher
        self.enricher = enricher
        self.analytics = list(analytics)
        self.persistence = persistence
    def run_expiry(self, wi: ExpiryWorkItem) -> tuple[EnrichedExpiry | None, PersistOutcome | None]:
        try:
            wi = self.resolver.resolve(wi)
            instruments = self.fetcher.fetch(wi)
            if not instruments:
                return None, None
            enriched = self.enricher.enrich(wi, instruments)
            if not enriched:
                return None, None
            ee = EnrichedExpiry(work=wi, instruments=instruments, enriched=enriched)
            for block in self.analytics:
                try:
                    block.apply(ee)
                except (AttributeError, TypeError, ValueError) as e:
                    logger.debug("analytics block failure: %s", e, exc_info=True)
            outcome = self.persistence.persist(ee)
            return ee, outcome
        except (AttributeError, TypeError, ValueError, KeyError) as e:
            logger.error("Pipeline expiry failure: %s", e, exc_info=True)
            return None, None
        except Exception as e:
            # In unit tests and mock-provider scenarios, expiry resolution can be unsupported.
            # Treat known resolution errors as non-fatal and return an empty outcome.
            try:
                from src.utils.exceptions import ResolveExpiryError
                if isinstance(e, ResolveExpiryError):
                    logger.error("Pipeline expiry resolve failure: %s", e)
                    return None, None
            except Exception:
                pass
            logger.critical("Unexpected pipeline expiry failure: %s", e, exc_info=True)
            raise

def build_default_pipeline(
    providers: Any,
    csv_sink: Any,
    *args: Any,
    metrics: Any | None = None,
    influx_sink: Any | None = None,
    compute_greeks: bool = False,  # retained for signature compatibility
    estimate_iv: bool = False,
    risk_free_rate: float = 0.05,
    iv_max_iterations: int = 100,
    iv_min: float = 0.01,
    iv_max: float = 5.0,
    iv_precision: float = 1e-5,
) -> CollectorPipeline:  # noqa: D401
    # Signature compatibility: allow legacy positional (influx_sink, metrics) or (metrics).
    if args:
        if len(args) >= 2:
            if influx_sink is None:
                influx_sink = args[0]
            if metrics is None:
                metrics = args[1]
        else:
            if metrics is None:
                metrics = args[0]

    adapter = ProvidersAdapter(providers, metrics=metrics)
    analytics: list[AnalyticsBlock] = [NoOpAnalytics()]

    class CsvPersistAdapter(PersistenceBlock):
        def __init__(self, csv_sink: Any, metrics: Any | None = None) -> None:  # noqa: D401
            self.csv = csv_sink

        def persist(self, ee: EnrichedExpiry) -> PersistOutcome:  # noqa: D401
            try:
                metrics_payload = self.csv.write_options_data(
                    ee.work.index,
                    ee.work.expiry_date,
                    ee.enriched,
                    datetime.datetime.now(datetime.UTC),
                    index_price=ee.work.index_price,
                    index_ohlc={},
                    suppress_overview=True,
                    return_metrics=True,
                    expiry_rule_tag=ee.work.expiry_rule,
                )
            except (AttributeError, TypeError, ValueError, KeyError) as e:
                logger.error("CSV write failed: %s", e, exc_info=True)
                return PersistOutcome(option_count=0, pcr=None, failed=True)
            except Exception as e:
                logger.critical("Unexpected CSV write error: %s", e, exc_info=True)
                return PersistOutcome(option_count=0, pcr=None, failed=True)
            pcr: float | None = None
            day_width: int | None = None
            ts: datetime.datetime | None = None
            expiry_code: str | None = None
            if metrics_payload:
                pcr = metrics_payload.get("pcr")
                day_width = metrics_payload.get("day_width")
                ts = metrics_payload.get("timestamp")
                expiry_code = metrics_payload.get("expiry_code")
            return PersistOutcome(
                option_count=len(ee.enriched),
                pcr=pcr,
                failed=False,
                day_width=day_width,
                snapshot_timestamp=ts,
                expiry_code=expiry_code,
            )

    persist: PersistenceBlock = CsvPersistAdapter(csv_sink, metrics=metrics)
    return CollectorPipeline(
        resolver=adapter,
        fetcher=adapter,
        enricher=adapter,
        analytics=analytics,
        persistence=persist,
    )

__all__ = [
    'ExpiryWorkItem','EnrichedExpiry','PersistOutcome','CollectorPipeline','build_default_pipeline'
]
