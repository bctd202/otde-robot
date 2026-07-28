from app.core.config import get_settings
from app.market_data.live import LiveProviderPlaceholder
from app.market_data.mock import MockMarketDataProvider
from app.market_data.tradier import TradierMarketDataProvider

def get_provider():
    settings = get_settings()
    if settings.market_data_provider == "mock":
        return MockMarketDataProvider()
    if settings.market_data_provider == "tradier":
        return TradierMarketDataProvider(settings.tradier_api_token, settings.tradier_base_url)
    return LiveProviderPlaceholder()
