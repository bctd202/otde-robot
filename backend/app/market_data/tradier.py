from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.schemas.market import CandleOut, OptionContractOut, ProviderStatus, Quote
from app.services.contract_verification import verify_contract

NY = ZoneInfo("America/New_York")


def _rows(payload: dict[str, Any], *path: str) -> list[dict[str, Any]]:
    value: Any = payload
    for key in path:
        if not isinstance(value, dict):
            return []
        value = value.get(key)
    if isinstance(value, dict):
        return [value]
    return value if isinstance(value, list) else []


class TradierMarketDataProvider:
    """Read-only Tradier adapter. Every upstream failure returns no fabricated data."""

    def __init__(self, token: str | None, base_url: str, client: httpx.Client | None = None,
                 trading_date: date | None = None):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=10.0)
        self._trading_date = trading_date
        self._error = "Tradier API token is not configured." if not token else None
        self._latest = datetime.now(NY)

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any] | None:
        if not self.token:
            return None
        try:
            response = self.client.get(
                f"{self.base_url}{path}", params=params,
                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("response is not an object")
            self._error = None
            return data
        except (httpx.HTTPError, ValueError) as exc:
            self._error = f"Tradier data unavailable: {type(exc).__name__}."
            return None

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider="tradier", mode="live", status="unavailable" if self._error else "healthy",
            delay_seconds=0, latest_timestamp=self._latest,
            message=self._error or "Live Tradier market data; paper research only.",
        )

    def quotes(self, symbols: list[str]) -> list[Quote]:
        data = self._get("/markets/quotes", {"symbols": ",".join(symbols), "greeks": "false"})
        result = []
        for row in _rows(data or {}, "quotes", "quote"):
            try:
                stamp = datetime.fromtimestamp(int(row["trade_date"]) / 1000, NY)
                result.append(Quote(symbol=str(row["symbol"]).upper(), price=float(row["last"]), timestamp=stamp))
                self._latest = max(self._latest, stamp)
            except (KeyError, TypeError, ValueError, OSError):
                continue
        return result

    def candles(self, symbol: str, timeframe: str = "1m") -> list[CandleOut]:
        if timeframe not in {"1m", "5m"}:
            return []
        data = self._get("/markets/timesales", {
            "symbol": symbol, "interval": "1min" if timeframe == "1m" else "5min",
            "start": f"{date.today():%Y-%m-%d} 09:30", "session_filter": "open",
        })
        result = []
        for row in _rows(data or {}, "series", "data"):
            try:
                stamp = datetime.fromisoformat(str(row["time"])).replace(tzinfo=NY)
                result.append(CandleOut(symbol=symbol.upper(), timeframe=timeframe, timestamp=stamp,
                    open=float(row["open"]), high=float(row["high"]), low=float(row["low"]),
                    close=float(row["close"]), volume=int(row["volume"])))
                self._latest = max(self._latest, stamp)
            except (KeyError, TypeError, ValueError):
                continue
        return result

    def expirations(self, symbol: str) -> list[date]:
        data = self._get("/markets/options/expirations", {"symbol": symbol, "includeAllRoots": "true"})
        values: Any = (data or {}).get("expirations", {}).get("date", [])
        if isinstance(values, str):
            values = [values]
        return [parsed for value in values if isinstance(value, str) for parsed in [date.fromisoformat(value)]]

    def option_chain(self, symbol: str) -> list[OptionContractOut]:
        today = self._trading_date or datetime.now(NY).date()
        if today not in self.expirations(symbol):
            return []
        data = self._get("/markets/options/chains", {"symbol": symbol, "expiration": today.isoformat(), "greeks": "true"})
        result = []
        for row in _rows(data or {}, "options", "option"):
            greeks = row.get("greeks") or {}
            try:
                original_symbol = str(row["symbol"])
                bid_stamp = datetime.fromtimestamp(int(row["bid_date"]) / 1000, NY)
                ask_stamp = datetime.fromtimestamp(int(row["ask_date"]) / 1000, NY)
                trade_stamp = datetime.fromtimestamp(int(row["trade_date"]) / 1000, NY) if row.get("trade_date") else None
                contract = OptionContractOut(symbol=symbol.upper(), option_symbol=original_symbol,
                    expiration=date.fromisoformat(str(row["expiration_date"])), strike=float(row["strike"]),
                    right=str(row["option_type"]).lower(), bid=float(row.get("bid") or 0),
                    ask=float(row.get("ask") or 0), last=float(row.get("last") or 0),
                    volume=int(row.get("volume") or 0), open_interest=int(row.get("open_interest") or 0),
                    iv=greeks.get("mid_iv"), delta=greeks.get("delta"), gamma=greeks.get("gamma"),
                    theta=greeks.get("theta"), vega=greeks.get("vega"), timestamp=min(bid_stamp, ask_stamp),
                    bid_timestamp=bid_stamp, ask_timestamp=ask_stamp, trade_timestamp=trade_stamp,
                    original_option_symbol=original_symbol, chain_member=True)
                result.append(verify_contract(contract, self.status(), symbol=symbol, right=contract.right))
                self._latest = max(self._latest, bid_stamp, ask_stamp, trade_stamp or bid_stamp)
            except (KeyError, TypeError, ValueError, OSError):
                continue
        return result
