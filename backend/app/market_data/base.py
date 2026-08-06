from abc import ABC, abstractmethod
from datetime import date

from app.schemas.market import CandleOut, OptionContractOut, ProviderStatus, Quote

class MarketDataProvider(ABC):
    @abstractmethod
    def status(self) -> ProviderStatus: ...
    @abstractmethod
    def quotes(self, symbols: list[str]) -> list[Quote]: ...
    @abstractmethod
    def candles(self, symbol: str, timeframe: str = "1m") -> list[CandleOut]: ...
    def historical_candles(self, symbol: str, timeframe: str, start, end) -> list[CandleOut]:
        """Historical data is explicitly unsupported unless a provider implements it."""
        return []
    @abstractmethod
    def option_chain(self, symbol: str, expiration: date | None = None) -> list[OptionContractOut]: ...
