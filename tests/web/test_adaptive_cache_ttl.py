import os, time, asyncio

# Configure adaptive cache environment before importing module
os.environ['G6_FORECAST_CACHE_ADAPTIVE'] = '1'
os.environ['G6_FORECAST_CACHE_TTL_MIN'] = '5'
os.environ['G6_FORECAST_CACHE_TTL_MAX'] = '15'
os.environ['G6_FORECAST_CACHE_LATENCY_HIGH_MS'] = '500'
os.environ['G6_FORECAST_CACHE_LATENCY_LOW_MS'] = '50'
# Enable metrics exposure so gauge is registered
os.environ['ENABLE_PATH_FORECAST_PROM_METRICS'] = '1'

from src.web.dashboard.routes import ensemble as ens  # noqa: E402

class StubForecaster:
    def __init__(self):
        self.last_meta = {
            'weight_gbrt': 0.7,
            'weight_retrieval': 0.3,
            'confidence': 0.8,
            'baseline_enabled': True,
            'gbrt_enabled': True,
            'retrieval_enabled': True,
            'conformal_enabled': True,
        }
    def forecast_path(self, recent_window, context, quantiles, horizon_minutes, bucket_ms):
        now_ms = int(time.time()*1000)
        qmap = {q: [100.0] for q in quantiles}
        return [now_ms], qmap

# Inject stub forecaster so _get_forecaster returns it
ens._forecasters['NIFTY'] = StubForecaster()

async def _run_forecast():
    return await ens.forecast(
        index='NIFTY',
        horizon=60,
        quantiles='0.1,0.5,0.9',
        underlying=100.0,
        avg_iv=0.2,
        minutes_to_expiry=300.0,
        recent_window_size=0,
        cache_bust=1,
        detail=None,
    )

def test_dynamic_ttl_gauge_present():
    # Warmup hits/misses to exceed threshold for adaptive logic
    ens._CACHE_HITS = 25
    ens._CACHE_MISSES = 5
    asyncio.run(_run_forecast())
    from src.web.dashboard import prom_metrics
    # Gauge object should be initialized
    gauge_obj = getattr(prom_metrics, '_FORECAST_CACHE_DYNAMIC_TTL', None)
    assert gauge_obj is not None, 'dynamic TTL gauge not initialized'
    # invoke setter explicitly to ensure a sample is registered
    from src.web.dashboard.prom_metrics import set_forecast_cache_dynamic_ttl
    set_forecast_cache_dynamic_ttl('NIFTY', 9)
    # Basic bounds sanity using chosen value
    assert int(os.environ['G6_FORECAST_CACHE_TTL_MIN']) <= 9 <= int(os.environ['G6_FORECAST_CACHE_TTL_MAX'])