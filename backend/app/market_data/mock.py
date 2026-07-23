from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from app.schemas.market import CandleOut, OptionContractOut, ProviderStatus, Quote
from app.core.config import get_settings

NY = ZoneInfo("America/New_York")
BASE = {"SPY": 550.0, "QQQ": 485.0, "IWM": 220.0}

class MockMarketDataProvider:
    def __init__(self):
        self.now = datetime.combine(date.today(), time(10, 5), tzinfo=NY)

    def status(self):
        return ProviderStatus(provider="mock", mode="mock", status="healthy", delay_seconds=0, latest_timestamp=self.now, message="Deterministic mock data; not live market data.")

    def quotes(self, symbols):
        return [Quote(symbol=s, price=round(BASE[s] + (1.6 if s == "SPY" else 0.8), 2), timestamp=self.now) for s in symbols]

    def candles(self, symbol, timeframe="1m"):
        base = BASE[symbol]
        step = 5 if timeframe == "5m" else 1
        start = datetime.combine(date.today(), time(9, 30), tzinfo=NY)
        rows = []
        for i in range(36 // step):
            t = start + timedelta(minutes=i * step)
            drift = 0 if get_settings().mock_scenario == "no_trade" else i * 0.05 * step
            wave = ((i % 6) - 2) * 0.08
            o = base + drift + wave
            h = o + 0.35 + (0.4 if i == 10 and symbol == "SPY" else 0)
            l = o - 0.25
            c = o if get_settings().mock_scenario == "no_trade" else o + (0.18 if i % 3 else -0.05)
            if get_settings().mock_scenario != "no_trade" and symbol == "SPY" and i == 11:
                c = base + 1.55
                h = c + 0.25
            rows.append(CandleOut(symbol=symbol, timeframe=timeframe, timestamp=t, open=round(o,2), high=round(h,2), low=round(l,2), close=round(c,2), volume=100000 + i * 12000))
        return rows

    def option_chain(self, symbol):
        today = date.today()
        underlying = BASE[symbol] + 1.6
        rows = []
        for right in ["call", "put"]:
            for n in range(1, 8):
                strike = round(underlying + (n if right == "call" else -n), 0)
                ask = round(0.06 + n * 0.045, 2)
                bid = max(round(ask - 0.03, 2), 0.01)
                delta = round((0.27 - n * 0.025) * (1 if right == "call" else -1), 3)
                rows.append(OptionContractOut(symbol=symbol, option_symbol=f"{symbol}{today:%y%m%d}{right[0].upper()}{int(strike*1000)}", expiration=today, strike=strike, right=right, bid=bid, ask=ask, last=round((bid+ask)/2,2), volume=300 + n*80, open_interest=700+n*100, iv=0.22+n*0.01, delta=delta, gamma=0.03+n*0.004, theta=-0.08, vega=0.02, timestamp=self.now))
        return rows
