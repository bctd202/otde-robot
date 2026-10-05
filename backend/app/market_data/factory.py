from functools import lru_cache

from app.core.config import get_settings
from app.market_data.cached import CachedMarketDataProvider
from app.market_data.live import LiveProviderPlaceholder
from app.market_data.mock import MockMarketDataProvider
from app.market_data.tradier import TradierMarketDataProvider
from app.market_data.tastytrade import TastytradeMarketDataProvider

@lru_cache(maxsize=1)
def get_provider():
    settings = get_settings()
    if settings.market_data_provider == "mock":
        return CachedMarketDataProvider(MockMarketDataProvider())
    if settings.market_data_provider == "tradier":
        return CachedMarketDataProvider(TradierMarketDataProvider(
            settings.tradier_api_token, settings.tradier_base_url,
            data_mode=settings.tradier_data_mode))
    if settings.market_data_provider == "tastytrade":
        return CachedMarketDataProvider(TastytradeMarketDataProvider(
            client_id=settings.tastytrade_client_id,
            client_secret=settings.tastytrade_client_secret,
            refresh_token=settings.tastytrade_refresh_token,
            base_url=settings.tastytrade_base_url,
            user_agent=settings.tastytrade_user_agent,
        ))
    return CachedMarketDataProvider(LiveProviderPlaceholder())
