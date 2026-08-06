from datetime import date, datetime, timedelta, timezone

from app.market_data.cached import CachedMarketDataProvider
from app.schemas.market import CandleOut, OptionContractOut, ProviderStatus, Quote


class CountingProvider:
    def __init__(self):
        self.calls = {"quotes": 0, "candles": 0, "expirations": 0, "chains": 0}
        self.now = datetime(2026, 8, 5, 14, 30, tzinfo=timezone.utc)

    def status(self):
        return ProviderStatus(provider="test", mode="live", status="healthy", delay_seconds=0,
                              latest_timestamp=self.now, message="test")

    def quotes(self, symbols):
        self.calls["quotes"] += 1
        return [Quote(symbol=symbol, price=100, timestamp=self.now) for symbol in symbols]

    def candles(self, symbol, timeframe="1m"):
        self.calls["candles"] += 1
        return [CandleOut(symbol=symbol, timeframe="1m", timestamp=self.now - timedelta(minutes=15-index),
            open=100, high=101, low=99, close=100.5, volume=1000) for index in range(15)]

    def expirations(self, symbol):
        self.calls["expirations"] += 1
        return [date(2026, 8, 12)]

    def option_chain(self, symbol, expiration=None):
        self.calls["chains"] += 1
        return [OptionContractOut(symbol=symbol, option_symbol="SPY260812C00100000",
            expiration=expiration or date(2026, 8, 12), strike=100, right="call", bid=1, ask=1.1,
            last=1.05, volume=1000, open_interest=2000, timestamp=self.now)]


def test_cache_shares_quotes_candles_expirations_and_chains_across_consumers():
    upstream = CountingProvider()
    provider = CachedMarketDataProvider(upstream)
    assert len(provider.quotes(["SPY", "QQQ"])) == 2
    assert provider.quotes(["SPY"])[0].symbol == "SPY"
    assert provider.candles("SPY", "1m")
    assert len(provider.candles("SPY", "5m")) == 3
    assert provider.candles("SPY", "15m")
    assert provider.expirations("SPY") == provider.expirations("SPY")
    expiration = date(2026, 8, 12)
    assert provider.option_chain("SPY", expiration) == provider.option_chain("SPY", expiration)
    assert upstream.calls == {"quotes": 1, "candles": 1, "expirations": 1, "chains": 1}


def test_cache_never_promotes_a_forming_candle_to_completed():
    upstream = CountingProvider()
    forming = CandleOut(symbol="SPY", timeframe="1m", timestamp=upstream.now.replace(second=0),
        open=100, high=110, low=90, close=109, volume=1000)
    upstream.candles = lambda symbol, timeframe="1m": [forming]
    provider = CachedMarketDataProvider(upstream)

    assert provider.candles("SPY") == []
    upstream.now += timedelta(minutes=1)
    # The partial row was never cached, so it cannot silently become completed.
    assert provider.candles("SPY") == []
