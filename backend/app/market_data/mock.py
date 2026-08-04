from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.schemas.market import CandleOut, OptionContractOut, ProviderStatus, Quote
from app.services.contract_verification import verify_contract

NY = ZoneInfo("America/New_York")
BASE = {"SPY": 550.0, "QQQ": 485.0, "IWM": 220.0, "TSLA": 182.0, "NVDA": 138.0,
        "AAPL": 225.0, "AMZN": 198.0, "META": 515.0, "MSFT": 440.0, "GOOGL": 175.0,
        "AVGO": 168.0, "IBIT": 54.0}
# Each profile changes market structure, not the scanner's rules.
PROFILE = {"SPY": "buy_call", "QQQ": "buy_put", "IWM": "watch_call", "TSLA": "watch_put",
           "NVDA": "buy_call", "AAPL": "missed_call", "AMZN": "pass", "META": "pass",
           "MSFT": "pass", "GOOGL": "pass", "AVGO": "pass", "IBIT": "pass"}


class MockMarketDataProvider:
    def __init__(self):
        self.now = datetime.combine(date.today(), time(10, 5), tzinfo=NY)

    def status(self):
        return ProviderStatus(provider="mock", mode="mock", status="healthy", delay_seconds=0,
            latest_timestamp=self.now, message="Deterministic mock data; not live market data.")

    def quotes(self, symbols):
        return [Quote(symbol=s, price=self.candles(s)[-1].close, timestamp=self.now) for s in symbols]

    def candles(self, symbol, timeframe="1m"):
        base, profile = BASE[symbol], PROFILE[symbol]
        step = 5 if timeframe == "5m" else 1
        start = datetime.combine(date.today(), time(9, 30), tzinfo=NY)
        rows = []
        sign = -1 if profile.endswith("put") else 1
        for i in range(36 // step):
            t = start + timedelta(minutes=i * step)
            if get_settings().mock_scenario == "no_trade" or profile == "pass":
                close = base + ((i % 4) - 1.5) * .025
            else:
                close = base + sign * (.04 + min(i, 30) * .012 * step)
                if i == (36 // step) - 1:
                    if profile.startswith("watch"):
                        close = base + sign * .10
                    elif profile.startswith("missed"):
                        close = base + sign * 1.45
                    else:
                        close = base + sign * .62
            open_price = close - sign * .04
            rows.append(CandleOut(symbol=symbol, timeframe=timeframe, timestamp=t,
                open=round(open_price, 2), high=round(max(open_price, close) + .08, 2),
                low=round(min(open_price, close) - .08, 2), close=round(close, 2),
                volume=100_000 + i * 8_000 + (30_000 if i == (36 // step) - 1 else 0)))
        return rows

    def option_chain(self, symbol):
        today = date.today()
        underlying = BASE[symbol] + .25 if PROFILE[symbol].startswith("missed") else self.candles(symbol)[-1].close
        rows = []
        for right in ["call", "put"]:
            for n in range(1, 6):
                offset = n * .25
                strike = round(underlying + (offset if right == "call" else -offset), 2)
                ask = round(.36 + n * .04, 2)
                bid = round(ask - .04, 2)
                delta = round((.27 - n * .035) * (1 if right == "call" else -1), 3)
                rows.append(verify_contract(OptionContractOut(symbol=symbol,
                    option_symbol=f"{symbol}{today:%y%m%d}{right[0].upper()}{int(strike * 1000):08d}",
                    expiration=today, strike=strike, right=right, bid=bid, ask=ask,
                    last=round((bid + ask) / 2, 2), volume=700 + n * 110,
                    open_interest=1200 + n * 180, iv=.24 + n * .01, delta=delta,
                    gamma=.035 + n * .003, theta=-.08, vega=.02, timestamp=self.now), self.status(),
                    symbol=symbol, right=right))
        return rows
