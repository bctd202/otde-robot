from functools import lru_cache

from app.core.config import get_settings
from app.market_data.base import MarketDataProvider
from app.market_data.mock import MockMarketDataProvider
from app.market_data.tradier import TradierMarketDataProvider


@lru_cache(maxsize=4)
def _build_provider(
    provider_name: str,
    access_token: str,
    base_url: str,
    stream_url: str,
    timeout_seconds: float,
    cache_seconds: int,
) -> MarketDataProvider:
    if provider_name == "mock":
        return MockMarketDataProvider()
    if provider_name == "tradier":
        return TradierMarketDataProvider()
    raise ValueError(
        f"Unsupported MARKET_DATA_PROVIDER={provider_name!r}; expected 'mock' or 'tradier'."
    )


def get_provider() -> MarketDataProvider:
    settings = get_settings()
    return _build_provider(
        settings.market_data_provider.strip().lower(),
        settings.tradier_access_token,
        settings.tradier_base_url,
        settings.tradier_stream_url,
        settings.tradier_timeout_seconds,
        settings.tradier_cache_seconds,
    )
