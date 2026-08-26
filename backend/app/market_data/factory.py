from functools import lru_cache

from app.core.config import get_settings
from app.market_data.cached import CachedMarketDataProvider
from app.market_data.live import LiveProviderPlaceholder
from app.market_data.mock import MockMarketDataProvider
from app.market_data.tradier import TradierMarketDataProvider

@lru_cache(maxsize=1)
def get_provider():
    settings = get_settings()
    if settings.market_data_provider == "mock":
        return CachedMarketDataProvider(MockMarketDataProvider())
    if settings.market_data_provider == "tradier":
        return CachedMarketDataProvider(TradierMarketDataProvider(
            settings.tradier_api_token, settings.tradier_base_url,
            data_mode=settings.tradier_data_mode))
    return CachedMarketDataProvider(LiveProviderPlaceholder())
