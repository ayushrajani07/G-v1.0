"""
Provider Protocol - Interface for data providers.

Breaks circular dependency between:
- src.broker.kite_provider (implementation)
- src.collectors (uses providers)
- src.orchestrator (initializes providers)

This protocol allows any module to declare dependency on providers
without importing the concrete implementation.
"""

from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ProviderProtocol(Protocol):
    """
    Protocol for data providers (broker APIs).
    
    Defines the contract for fetching market data without depending
    on the concrete Kite provider implementation.
    
    Usage:
        def fetch_quotes(provider: ProviderProtocol, symbols: list[str]) -> dict:
            return provider.get_quotes(symbols)
    """
    
    def get_ltp(self, symbol: str) -> float | None:
        """
        Get Last Traded Price for a symbol.
        
        Args:
            symbol: Trading symbol (e.g., "NIFTY2410020000CE")
            
        Returns:
            Last traded price or None if unavailable
        """
        ...
    
    def get_quotes(self, symbols: list[str]) -> dict[str, Any]:
        """
        Get quotes for multiple symbols.
        
        Args:
            symbols: List of trading symbols
            
        Returns:
            Dict mapping symbol to quote data
        """
        ...
    
    def get_instruments(self, exchange: str | None = None) -> list[dict[str, Any]]:
        """
        Get instrument list for an exchange.
        
        Args:
            exchange: Exchange name (e.g., "NFO") or None for all
            
        Returns:
            List of instrument dicts
        """
        ...
    
    def get_historical_data(
        self,
        symbol: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "day"
    ) -> list[dict[str, Any]]:
        """
        Get historical OHLCV data.
        
        Args:
            symbol: Trading symbol
            from_date: Start date
            to_date: End date
            interval: Time interval (e.g., "minute", "day")
            
        Returns:
            List of OHLCV candles
        """
        ...
    
    @property
    def is_connected(self) -> bool:
        """Check if provider is connected and authenticated."""
        ...


@runtime_checkable
class ProvidersProtocol(Protocol):
    """
    Protocol for the Providers facade (wrapper around provider).
    
    This is the interface used by collectors for unified access.
    """
    
    def get_index_data(self, index: str) -> tuple[float | None, datetime | None]:
        """
        Get index LTP and timestamp.
        
        Args:
            index: Index name (e.g., "NIFTY")
            
        Returns:
            Tuple of (ltp, timestamp)
        """
        ...
    
    def get_atm_strike(self, index: str, ltp: float | None = None) -> float | None:
        """
        Get ATM strike for an index.
        
        Args:
            index: Index name
            ltp: Optional LTP (fetches if None)
            
        Returns:
            ATM strike price
        """
        ...
    
    def get_option_chain(self, index: str, expiry: str, strikes: list[float]) -> list[dict[str, Any]]:
        """
        Get option chain quotes for strikes.
        
        Args:
            index: Index name
            expiry: Expiry date (YYYY-MM-DD)
            strikes: List of strike prices
            
        Returns:
            List of option quotes
        """
        ...


__all__ = ["ProviderProtocol", "ProvidersProtocol"]
