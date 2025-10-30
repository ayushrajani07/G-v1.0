"""Dummy/mock classes for testing without real dependencies.

These minimal stub classes replace duplicated implementations that
appeared in 50+ test files. Each provides just enough interface to
satisfy the components under test.
"""
import datetime as dt
from types import SimpleNamespace


class DummyProviders:
    """Minimal provider stub for tests.
    
    Provides synthetic LTP/ATM/quote data without real broker connection.
    Used in 40+ collector/pipeline test files.
    """
    def __init__(self, atm_strike: float = 100.0):
        self._atm = atm_strike
    
    def get_index_data(self, index):
        """Return (LTP, quotes) tuple."""
        return self._atm, None
    
    def get_atm_strike(self, index):
        """Return ATM strike price."""
        return self._atm
    
    def get_ltp(self, index_symbol):
        """Return last traded price."""
        return self._atm
    
    def get_expiry_dates(self, index_symbol):
        """Return two future expiries (today and +7 days)."""
        today = dt.date.today()
        return [today, today + dt.timedelta(days=7)]
    
    def option_instruments(self, index_symbol, expiry_date, strikes):
        """Return synthetic option instrument list."""
        out = []
        for s in strikes:
            out.append({
                'exchange': 'NFO',
                'tradingsymbol': f'{index_symbol}X{s}CE',
                'instrument_type': 'CE',
                'strike': s
            })
            out.append({
                'exchange': 'NFO',
                'tradingsymbol': f'{index_symbol}X{s}PE',
                'instrument_type': 'PE',
                'strike': s
            })
        return out
    
    def get_quote(self, instruments):
        """Return synthetic quotes dict."""
        out = {}
        for item in instruments:
            exch, sym = item
            out[f"{exch}:{sym}"] = {
                "last_price": 10.0,
                "volume": 5,
                "oi": 50,
                "timestamp": "2025-09-26T10:00:00Z"
            }
        return out


class DummyMetrics:
    """Minimal metrics stub for tests.
    
    Provides no-op implementations of metrics methods.
    Used in 30+ test files.
    """
    class NullTimer:
        """Context manager that does nothing."""
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
    
    def create_timer(self, *args, **kwargs):
        """Return no-op timer context manager."""
        return self.NullTimer()
    
    def record_collection_run(self, *args, **kwargs):
        """No-op: record collection run."""
        pass
    
    def record_phase_duration(self, *args, **kwargs):
        """No-op: record phase duration."""
        pass
    
    def inc(self, *args, **kwargs):
        """No-op: increment counter."""
        pass
    
    def observe(self, *args, **kwargs):
        """No-op: observe histogram/summary."""
        pass
    
    def set(self, *args, **kwargs):
        """No-op: set gauge value."""
        pass


class DummyCsvSink:
    """Minimal CSV sink stub for tests.
    
    Provides no-op write methods.
    Used in 15+ test files.
    """
    def save_option_quotes(self, *args, **kwargs):
        """No-op: save option quotes to CSV."""
        pass
    
    def write_overview_snapshot(self, *args, **kwargs):
        """No-op: write overview snapshot."""
        pass
    
    def write_snapshot(self, *args, **kwargs):
        """No-op: write snapshot."""
        pass


class DummyInfluxSink:
    """Minimal InfluxDB sink stub for tests.
    
    Provides no-op write methods.
    Used in 12+ test files.
    """
    def write_option_quotes(self, *args, **kwargs):
        """No-op: write option quotes to InfluxDB."""
        pass
    
    def write_overview_snapshot(self, *args, **kwargs):
        """No-op: write overview snapshot."""
        pass
    
    def write_snapshot(self, *args, **kwargs):
        """No-op: write snapshot."""
        pass


class DummySink:
    """Universal sink stub (CSV + Influx combined).
    
    Provides all write methods from both CSV and Influx sinks.
    Used in 10+ test files.
    """
    def save_option_quotes(self, *args, **kwargs):
        pass
    
    def write_overview_snapshot(self, *args, **kwargs):
        pass
    
    def write_snapshot(self, *args, **kwargs):
        pass
    
    def write_option_quotes(self, *args, **kwargs):
        pass


class DummyGauge:
    """Minimal Prometheus gauge stub."""
    def set(self, *args, **kwargs):
        pass
    
    def inc(self, *args, **kwargs):
        pass
    
    def dec(self, *args, **kwargs):
        pass


class DummyCounter:
    """Minimal Prometheus counter stub."""
    def inc(self, *args, **kwargs):
        pass
    
    def labels(self, *args, **kwargs):
        return self


class DummySummary:
    """Minimal Prometheus summary stub."""
    def observe(self, *args, **kwargs):
        pass
    
    def labels(self, *args, **kwargs):
        return self
    
    def time(self):
        """Return context manager for timing."""
        class _Timer:
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False
        return _Timer()


class DummyLogger:
    """Minimal logger stub."""
    def debug(self, *args, **kwargs):
        pass
    
    def info(self, *args, **kwargs):
        pass
    
    def warning(self, *args, **kwargs):
        pass
    
    def error(self, *args, **kwargs):
        pass
    
    def exception(self, *args, **kwargs):
        pass
