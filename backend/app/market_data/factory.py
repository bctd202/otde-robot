from app.core.config import get_settings
from app.market_data.live import LiveProviderPlaceholder
from app.market_data.mock import MockMarketDataProvider

def get_provider():
    return MockMarketDataProvider() if get_settings().market_data_provider == "mock" else LiveProviderPlaceholder()
