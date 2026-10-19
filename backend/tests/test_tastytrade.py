from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import httpx

from app.market_data.tastytrade import (DXLinkCandleStreamClient,
                                        DXLinkSnapshotClient,
                                        TastytradeMarketDataProvider)


class FakeStreamer:
    def __init__(self, url, token, timeout):
        assert url == "wss://quotes.example"
        assert token == "quote-token"

    def snapshot(self, subscriptions, event_types):
        if event_types == {"Candle"}:
            return [{"eventType": "Candle", "eventSymbol": "SPY{=m}",
                     "time": 1788351060000, "open": 100, "high": 101,
                     "low": 99.5, "close": 100.5, "volume": 5000}]
        return [
            {"eventType": "Greeks", "eventSymbol": ".SPY260902C102",
             "volatility": .33, "delta": .16, "gamma": .05, "theta": -.08, "vega": .02},
            {"eventType": "Summary", "eventSymbol": ".SPY260902C102", "openInterest": 1500},
        ]


class FakeCandleStream:
    def __init__(self, url, token, symbols, start, on_events, timeout):
        self.symbols = symbols
        self.on_events = on_events
        self.started = False
        self.stopped = False

    def start(self):
        if self.started:
            return
        self.started = True
        self.on_events([
            {"eventType": "Candle", "eventSymbol": "SPY{=m}",
             "time": 1788360660000, "open": 100, "high": 101,
             "low": 99.5, "close": 100.5, "volume": 5000},
        ])

    def stop(self):
        self.stopped = True

    def health(self):
        return {"connected": self.started and not self.stopped, "last_event_at": None,
                "last_error": None, "subscription_count": len(self.symbols)}


def provider(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return TastytradeMarketDataProvider("client", "secret", "refresh", "https://api.tastyworks.com",
                                        "parlay-test/1.0", client=client, streamer_factory=FakeStreamer)


def test_tastytrade_oauth_quotes_candles_and_option_chain_are_normalized():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            assert request.headers["user-agent"] == "parlay-test/1.0"
            return httpx.Response(200, json={"access_token": "access", "expires_in": 900})
        assert request.headers["authorization"] == "Bearer access"
        if request.url.path == "/api-quote-tokens":
            return httpx.Response(200, json={"data": {"token": "quote-token", "dxlink-url": "wss://quotes.example"}})
        if request.url.path == "/option-chains/SPY":
            return httpx.Response(200, json={"data": {"items": [{"active": True,
                "expiration-date": "2026-09-02", "option-type": "C", "strike-price": "102",
                "symbol": "SPY   260902C00102000", "streamer-symbol": ".SPY260902C102"}]}})
        if request.url.path == "/market-data/by-type" and "equity-option" in request.url.params:
            return httpx.Response(200, json={"data": {"items": [{"symbol": "SPY   260902C00102000",
                "updated-at": "2026-09-02T14:05:00Z", "bid": ".18", "ask": ".20",
                "last": ".19", "volume": "1200"}]}})
        if request.url.path == "/market-data/by-type":
            return httpx.Response(200, json={"data": {"items": [{"symbol": "SPY",
                "updated-at": "2026-09-02T14:05:00Z", "last": "100.50"}]}})
        raise AssertionError(request.url)

    market = provider(handler)
    quotes = market.quotes(["SPY"])
    assert quotes[0].price == 100.5
    chain = market.option_chain("SPY", date(2026, 9, 2))
    assert chain[0].option_symbol == "SPY260902C00102000"
    assert chain[0].provider == "tastytrade"
    assert chain[0].delta == .16
    assert chain[0].open_interest == 1500
    assert market.expirations("SPY") == [date(2026, 9, 2)]


def test_tastytrade_fails_closed_without_oauth_credentials():
    market = TastytradeMarketDataProvider(None, None, None, "https://api.tastyworks.com", "parlay/1.0")
    assert market.status().status == "unavailable"
    assert market.quotes(["SPY"]) == []
    assert "not configured" in market.status().message.lower()


def test_tastytrade_never_labels_sandbox_market_data_healthy():
    market = TastytradeMarketDataProvider("client", "secret", "refresh",
                                          "https://api.cert.tastyworks.com", "parlay/1.0")
    assert market.status().status == "unavailable"
    assert "sandbox" in market.status().message.lower()


def test_dxlink_compact_decoder_keeps_every_packed_record():
    fields = {"Candle": ["eventType", "eventSymbol", "time", "open", "high", "low", "close"]}
    packed = [
        "Candle", "SPY{=m}", 1788351000000, 100, 101, 99, 100.5,
        "Candle", "SPY{=m}", 1788351060000, 100.5, 102, 100, 101.5,
    ]

    events = list(DXLinkSnapshotClient._events(["Candle", packed], fields))

    assert [event["time"] for event in events] == [1788351000000, 1788351060000]
    assert [event["close"] for event in events] == [100.5, 101.5]


def test_dxlink_snapshot_method_belongs_to_bounded_snapshot_client():
    assert callable(DXLinkSnapshotClient.snapshot)
    assert not hasattr(DXLinkCandleStreamClient, "snapshot")


def test_tastytrade_persistent_candle_stream_populates_quality_and_can_close(monkeypatch):
    monkeypatch.setattr("app.market_data.tastytrade._latest_market_date", lambda: date(2026, 9, 2))
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "access", "expires_in": 900})
        if request.url.path == "/api-quote-tokens":
            return httpx.Response(200, json={"data": {
                "token": "quote-token", "dxlink-url": "wss://quotes.example"}})
        raise AssertionError(request.url)

    market = TastytradeMarketDataProvider(
        "client", "secret", "refresh", "https://api.tastyworks.com", "parlay-test/1.0",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        streamer_factory=FakeStreamer, candle_stream_factory=FakeCandleStream,
    )

    rows = market.candles("SPY")
    quality = market.data_quality_status()

    assert len(rows) == 1 and rows[0].close == 100.5
    assert quality["connected"] is True
    assert quality["symbols_with_candles"] == 1
    market.close()
    assert market.data_quality_status()["connected"] is False


@pytest.mark.parametrize("first,second", [(date(2026, 10, 13), date(2026, 10, 14)),
                                         (date(2026, 10, 9), date(2026, 10, 12)),
                                         (date(2026, 9, 4), date(2026, 9, 8))])
def test_candle_rollover_clears_history_and_rejects_late_old_stream(monkeypatch, first, second):
    day = [first]
    streams = []

    class Stream(FakeCandleStream):
        def __init__(self, *args):
            super().__init__(*args)
            self.day = args[3].date()
            streams.append(self)

        def start(self):
            self.started = True

    def event(day, hour=9, minute=30, close=100):
        at = datetime.combine(day, datetime.min.time(), ZoneInfo("America/New_York")).replace(hour=hour, minute=minute)
        return {"eventSymbol": "SPY{=m}", "time": at.timestamp()*1000,
                "open": close, "high": close+1, "low": close-1, "close": close, "volume": 100}

    market = TastytradeMarketDataProvider("id", "secret", "refresh", "https://api.tastyworks.com", "test/1",
                                         candle_stream_factory=Stream)
    monkeypatch.setattr(market, "_quote_credentials", lambda: ("wss://quotes.example", "quote-token"))
    monkeypatch.setattr("app.market_data.tastytrade._latest_market_date", lambda: day[0])
    market.start()
    streams[0].on_events([event(first)])
    assert len(market.candles("SPY")) == 1
    day[0] = second
    market.start()
    assert streams[0].stopped
    assert not market._candle_cache
    # Reject both prior dates from the new stream and callbacks from the old
    # stream (even if that callback happens to contain a current-day event).
    streams[0].on_events([event(second, close=999)])
    streams[1].on_events([event(first), event(second-timedelta(days=1)), event(second, 8),
                          event(second, 16), event(second, close=102)])
    rows = market.candles("SPY")
    assert len(rows) == 1 and rows[0].timestamp.date() == second and rows[0].close == 102
    market.close()
    streams[1].on_events([event(second, close=999)])
    assert not market._candle_cache
    market.start()  # A same-session restart has a new generation, too.
    streams[1].on_events([event(second, close=999)])
    streams[2].on_events([event(second, close=103)])
    assert market.candles("SPY")[0].close == 103
