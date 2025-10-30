"""Factory functions for creating test fixtures and data structures.

These functions create common test objects (contexts, snapshots, etc.)
that were previously duplicated across many test files.
"""
from types import SimpleNamespace
from typing import Any, Dict
from prometheus_client import CollectorRegistry, Gauge, Counter, Histogram

from tests.fixtures.dummies import (
    DummyProviders, 
    DummyMetrics,
    DummyCsvSink,
    DummyInfluxSink,
    DummySink,
)


def make_ctx(
    indices: Dict[str, Dict] | None = None,
    providers = None,
    csv_sink = None,
    influx_sink = None,
    metrics = None,
    registry: CollectorRegistry | None = None,
    **extra_attrs
) -> SimpleNamespace:
    """Create a minimal RuntimeContext for testing.
    
    Args:
        indices: Index configuration dict. Defaults to single AAA index.
        providers: Provider instance. Defaults to DummyProviders().
        csv_sink: CSV sink instance. Defaults to DummyCsvSink().
        influx_sink: InfluxDB sink instance. Defaults to DummyInfluxSink().
        metrics: Metrics instance. Defaults to DummyMetrics().
        registry: Prometheus registry. Creates new if None.
        **extra_attrs: Additional attributes to set on context.
    
    Returns:
        SimpleNamespace with all required context attributes.
    """
    if indices is None:
        indices = {
            "AAA": {
                "enable": True,
                "strikes_itm": 1,
                "strikes_otm": 1,
                "expiries": ["this_week"]
            }
        }
    
    if registry is None:
        registry = CollectorRegistry()
    
    ctx = SimpleNamespace()
    ctx.index_params = indices
    ctx.providers = providers or DummyProviders()
    ctx.csv_sink = csv_sink or DummyCsvSink()
    ctx.influx_sink = influx_sink or DummyInfluxSink()
    ctx.metrics = metrics or DummyMetrics()
    ctx.cycle_count = 0
    ctx.config = {}
    ctx.metrics_registry = registry
    
    # Set any additional attributes
    for key, value in extra_attrs.items():
        setattr(ctx, key, value)
    
    return ctx


def make_snapshot(
    cycle: int = 0,
    generated_epoch: float | None = None,
    alerts: list | None = None,
    indices: list | None = None,
    **meta_kwargs
):
    """Create a SummarySnapshot for testing.
    
    Args:
        cycle: Cycle number.
        generated_epoch: Timestamp when snapshot generated. Defaults to current time.
        alerts: List of AlertEntry instances. Defaults to empty list.
        indices: List of IndexHealth instances. Defaults to single test index.
        **meta_kwargs: Additional metadata fields.
    
    Returns:
        SummarySnapshot instance.
    """
    import time
    from src.summary.model import SummarySnapshot, AlertEntry, IndexHealth
    
    if generated_epoch is None:
        generated_epoch = time.time()
    
    if alerts is None:
        alerts = []
    
    if indices is None:
        indices = [
            IndexHealth(
                index='NIFTY',
                status='healthy',
                last_update_epoch=generated_epoch,
                success_rate_percent=100.0,
                options_last_cycle=100,
            )
        ]
    
    return SummarySnapshot(
        generated_epoch=generated_epoch,
        cycle=cycle,
        alerts=alerts,
        indices=indices,
        meta=meta_kwargs
    )


def make_batcher(enabled: bool = True, flush_interval: float = 0.05):
    """Create an EmissionBatcher for testing.
    
    Args:
        enabled: Whether batching is enabled.
        flush_interval: Flush interval in seconds.
    
    Returns:
        EmissionBatcher instance.
    """
    from src.metrics.emission_batcher import EmissionBatcher, _Config
    
    config = _Config(
        enabled=enabled,
        flush_interval=flush_interval,
        max_queue=1000,
        max_drain=500,
        max_interval=0.5
    )
    
    return EmissionBatcher(config=config)


def make_option(symbol: str, exchange: str = 'NSE', **kwargs):
    """Create an OptionQuote for testing.
    
    Args:
        symbol: Option symbol.
        exchange: Exchange name (default: NSE).
        **kwargs: Additional fields (last_price, volume, oi, timestamp, etc.).
    
    Returns:
        OptionQuote instance.
    """
    from src.domain.models import OptionQuote
    import datetime as dt
    
    defaults = {
        'last_price': 100.0,
        'volume': 1000,
        'oi': 5000,
        'timestamp': dt.datetime.now(),
    }
    defaults.update(kwargs)
    
    return OptionQuote(symbol=symbol, exchange=exchange, **defaults)


def sample_quotes():
    """Return list of sample option quotes for testing expiry filters.
    
    Note: OptionQuote doesn't have expiry/strike fields - those are derived
    from the symbol or stored in raw dict. This returns basic quotes with
    different symbols representing different expiries.
    """
    from src.domain.models import OptionQuote
    
    return [
        OptionQuote(symbol='NIFTY26JAN24000CE', exchange='NFO', last_price=50.0, volume=1000, oi=5000),
        OptionQuote(symbol='NIFTY02FEB24000CE', exchange='NFO', last_price=60.0, volume=2000, oi=6000),
        OptionQuote(symbol='NIFTY27FEB24000CE', exchange='NFO', last_price=70.0, volume=3000, oi=7000),
    ]


def sample_instruments(index: str, base_date) -> list:
    """Return list of sample instrument dicts for testing.
    
    Args:
        index: Index symbol (e.g., 'NIFTY').
        base_date: Base date for expiry calculations.
    
    Returns:
        List of instrument dicts.
    """
    import datetime as dt
    
    weekly = base_date + dt.timedelta(days=7)
    monthly = base_date + dt.timedelta(days=28)
    
    return [
        {
            'exchange': 'NFO',
            'tradingsymbol': f'{index}26JAN24000CE',
            'instrument_type': 'CE',
            'expiry': base_date,
            'strike': 24000,
        },
        {
            'exchange': 'NFO',
            'tradingsymbol': f'{index}02FEB24000CE',
            'instrument_type': 'CE',
            'expiry': weekly,
            'strike': 24000,
        },
        {
            'exchange': 'NFO',
            'tradingsymbol': f'{index}27FEB24000CE',
            'instrument_type': 'CE',
            'expiry': monthly,
            'strike': 24000,
        },
    ]
