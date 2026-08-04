from datetime import date, datetime, timezone

import httpx

from app.market_data.tradier import TradierMarketDataProvider
from app.services import contract_verification

NOW = datetime(2026, 8, 4, 14, 0, tzinfo=timezone.utc)
EXPIRATION = date(2026, 8, 4)


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz is None else NOW.astimezone(tz)


def test_tradier_preserves_occ_and_separate_bid_ask_trade_timestamps(monkeypatch):
    monkeypatch.setattr(contract_verification, "datetime", FixedDateTime)
    bid_ms = int((NOW.timestamp()-10)*1000)
    ask_ms = int((NOW.timestamp()-8)*1000)
    trade_ms = int((NOW.timestamp()-90)*1000)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/quotes"):
            return httpx.Response(200, json={"quotes":{"quote":{"symbol":"SPY","last":550.25,"trade_date":trade_ms}}})
        if path.endswith("/timesales"):
            return httpx.Response(200, json={"series":{"data":{"time":"2026-08-04T09:30:00","open":550,"high":551,"low":549.5,"close":550.5,"volume":1000}}})
        if path.endswith("/expirations"):
            return httpx.Response(200, json={"expirations":{"date":"2026-08-04"}})
        return httpx.Response(200, json={"options":{"option":{"symbol":"SPY260804C00550000",
            "expiration_date":"2026-08-04","strike":550,"option_type":"call","bid":.35,"ask":.40,
            "last":.38,"volume":900,"open_interest":2000,"bid_date":bid_ms,"ask_date":ask_ms,
            "trade_date":trade_ms,"greeks":{"mid_iv":.2,"delta":.4,"gamma":.03,"theta":-.1,"vega":.02}}}})

    provider=TradierMarketDataProvider("secret","https://example.test/v1",httpx.Client(transport=httpx.MockTransport(handler)),trading_date=EXPIRATION)
    assert provider.quotes(["SPY"])[0].price==550.25
    assert provider.candles("SPY")[0].volume==1000
    item=provider.option_chain("SPY")[0]
    assert item.actionable and item.original_option_symbol==item.option_symbol=="SPY260804C00550000"
    assert item.bid_timestamp.timestamp()*1000==bid_ms and item.ask_timestamp.timestamp()*1000==ask_ms
    assert item.trade_timestamp.timestamp()*1000==trade_ms
    assert item.timestamp==item.bid_timestamp  # honest display time is the older side of the market


def test_tradier_incomplete_chain_row_is_skipped_without_fabrication():
    def handler(request):
        if request.url.path.endswith("/expirations"):
            return httpx.Response(200,json={"expirations":{"date":"2026-08-04"}})
        return httpx.Response(200,json={"options":{"option":{"symbol":"SPY260804C00550000","expiration_date":"2026-08-04"}}})
    provider=TradierMarketDataProvider("secret","https://example.test/v1",httpx.Client(transport=httpx.MockTransport(handler)),trading_date=EXPIRATION)
    assert provider.option_chain("SPY")==[]


def test_tradier_fails_closed_without_token_or_on_http_error():
    missing=TradierMarketDataProvider(None,"https://example.test/v1")
    assert missing.quotes(["SPY"])==[] and missing.status().status=="unavailable"
    failing=TradierMarketDataProvider("secret","https://example.test/v1",httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(503))))
    assert failing.option_chain("SPY")==[] and "unavailable" in failing.status().message.lower()
