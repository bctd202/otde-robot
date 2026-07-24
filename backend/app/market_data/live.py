from datetime import datetime
from zoneinfo import ZoneInfo
from app.schemas.market import ProviderStatus

class LiveProviderPlaceholder:
    def status(self):
        return ProviderStatus(provider="live-placeholder", mode="unconfigured", status="unavailable", delay_seconds=0, latest_timestamp=datetime.now(ZoneInfo("America/New_York")), message="Live provider is not configured. No data is fabricated.")
    def quotes(self, symbols): return []
    def candles(self, symbol, timeframe="1m"): return []
    def option_chain(self, symbol): return []
