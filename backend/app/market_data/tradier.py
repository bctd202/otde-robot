"""Tradier market-data adapter. This module has no trading or account capabilities."""

import logging
import time
from datetime import date, datetime, time as datetime_time
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.core.config import Settings, get_settings
from app.market_data.base import MarketDataProvider
from app.schemas.market import CandleOut, OptionContractOut, ProviderStatus, Quote

logger = logging.getLogger(__name__)
NY = ZoneInfo("America/New_York")


class TradierProviderError(RuntimeError):
    """Base error for unavailable Tradier market data."""


class TradierAuthenticationError(TradierProviderError):
    """Raised when Tradier rejects or is missing the configured token."""


def _as_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return [value] if isinstance(value, dict) else []


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


class TradierMarketDataProvider(MarketDataProvider):
    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None):
        self.settings = settings or get_settings()
        self._client = client or httpx.Client(
            base_url=self.settings.tradier_base_url.rstrip("/"),
            timeout=httpx.Timeout(self.settings.tradier_timeout_seconds),
        )
        self._latest_timestamp = datetime.now(NY)
        self._last_error: str | None = None
        self._request_succeeded = False
        self._rate_limit_remaining: str | None = None
        self._expiration_cache: dict[str, tuple[float, list[date]]] = {}
        self._chain_cache: dict[tuple[str, date], tuple[float, list[OptionContractOut]]] = {}
        self._unavailable_reasons: dict[str, str] = {}

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.tradier_access_token}",
            "Accept": "application/json",
        }

    def status(self) -> ProviderStatus:
        token_configured = bool(self.settings.tradier_access_token)
        status = "unavailable" if self._last_error or not token_configured else "healthy" if self._request_succeeded else "configured"
        message = self._last_error or (
            "Tradier live market data configured; paper-only signals, no order connectivity."
            if token_configured else "TRADIER_ACCESS_TOKEN is not configured."
        )
        if self._rate_limit_remaining is not None:
            message += f" Rate-limit remaining: {self._rate_limit_remaining}."
        return ProviderStatus(
            provider="tradier",
            mode="live",
            status=status,
            delay_seconds=0,
            latest_timestamp=self._latest_timestamp,
            message=message,
        )

    def unavailable_reason(self, symbol: str) -> str | None:
        return self._unavailable_reasons.get(symbol.upper())

    def _request(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.tradier_access_token:
            self._last_error = "Tradier authentication unavailable: TRADIER_ACCESS_TOKEN is missing."
            raise TradierAuthenticationError(self._last_error)

        for attempt in range(3):
            try:
                url = f"{self.settings.tradier_base_url.rstrip('/')}/{path.lstrip('/')}"
                response = self._client.get(url, params=params, headers=self.headers)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt < 2:
                    time.sleep(0.1 * 2**attempt)
                    continue
                self._last_error = f"Tradier data unavailable: {exc.__class__.__name__}."
                logger.warning(self._last_error)
                raise TradierProviderError(self._last_error) from exc

            self._rate_limit_remaining = response.headers.get("X-Ratelimit-Available")
            if response.status_code in {401, 403}:
                self._last_error = "Tradier authentication failed; verify TRADIER_ACCESS_TOKEN and endpoint environment."
                raise TradierAuthenticationError(self._last_error)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 2:
                    try:
                        retry_after = min(float(response.headers.get("Retry-After", "0.1")), 1.0)
                    except ValueError:
                        retry_after = 0.1
                    time.sleep(retry_after)
                    continue
                self._last_error = f"Tradier data unavailable: HTTP {response.status_code}."
                raise TradierProviderError(self._last_error)
            try:
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                self._last_error = "Tradier returned an invalid market-data response."
                raise TradierProviderError(self._last_error) from exc
            self._last_error = None
            self._request_succeeded = True
            self._latest_timestamp = datetime.now(NY)
            return payload if isinstance(payload, dict) else {}
        raise TradierProviderError("Tradier data unavailable after retries.")

    @staticmethod
    def _market_timestamp(value: Any) -> datetime:
        number = _number(value)
        if number is not None:
            seconds = number / 1000 if number > 10_000_000_000 else number
            return datetime.fromtimestamp(seconds, tz=NY)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(NY)
            except ValueError:
                pass
        return datetime.now(NY)

    def quotes(self, symbols: list[str]) -> list[Quote]:
        try:
            payload = self._request("/markets/quotes", {"symbols": ",".join(symbols), "greeks": "false"})
        except TradierProviderError:
            return []
        rows = _as_list(payload.get("quotes", {}).get("quote"))
        quotes: list[Quote] = []
        for row in rows:
            price = _number(row.get("last"))
            symbol = str(row.get("symbol", "")).upper()
            if not symbol or price is None:
                self._unavailable_reasons[symbol] = "data unavailable"
                continue
            timestamp = self._market_timestamp(row.get("trade_date"))
            self._latest_timestamp = max(self._latest_timestamp, timestamp)
            quotes.append(Quote(symbol=symbol, price=price, timestamp=timestamp))
        return quotes

    def candles(self, symbol: str, timeframe: str = "1m") -> list[CandleOut]:
        interval = "5min" if timeframe == "5m" else "1min"
        today = datetime.now(NY).date()
        start = datetime.combine(today, datetime_time(9, 30), tzinfo=NY)
        end = datetime.combine(today, datetime_time(16, 0), tzinfo=NY)
        try:
            payload = self._request("/markets/timesales", {
                "symbol": symbol, "interval": interval,
                "start": start.isoformat(), "end": end.isoformat(), "session_filter": "open",
            })
        except TradierProviderError:
            return []
        candles: list[CandleOut] = []
        for row in _as_list(payload.get("series", {}).get("data")):
            values = [_number(row.get(field)) for field in ("open", "high", "low", "close")]
            if any(value is None for value in values):
                continue
            candles.append(CandleOut(
                symbol=symbol, timeframe=timeframe,
                timestamp=self._market_timestamp(row.get("time")),
                open=values[0], high=values[1], low=values[2], close=values[3],
                volume=_integer(row.get("volume")) or 0,
            ))
        return candles

    def expirations(self, symbol: str) -> list[date]:
        now = time.monotonic()
        cached = self._expiration_cache.get(symbol)
        if cached and now - cached[0] < 3600:
            return cached[1]
        payload = self._request("/markets/options/expirations", {
            "symbol": symbol, "includeAllRoots": "true", "strikes": "false",
        })
        raw_dates = payload.get("expirations", {}).get("date")
        values = raw_dates if isinstance(raw_dates, list) else [raw_dates] if raw_dates else []
        expirations = []
        for value in values:
            try:
                expirations.append(date.fromisoformat(str(value)))
            except ValueError:
                continue
        self._expiration_cache[symbol] = (now, expirations)
        return expirations

    def option_chain(self, symbol: str) -> list[OptionContractOut]:
        symbol = symbol.upper()
        today = datetime.now(NY).date()
        try:
            expirations = self.expirations(symbol)
        except TradierProviderError:
            self._unavailable_reasons[symbol] = "data unavailable"
            return []
        if today not in expirations:
            self._unavailable_reasons[symbol] = "no same-day expiration"
            return []

        cache_key = (symbol, today)
        now = time.monotonic()
        cached = self._chain_cache.get(cache_key)
        if cached and now - cached[0] < self.settings.tradier_cache_seconds:
            return cached[1]
        try:
            payload = self._request("/markets/options/chains", {
                "symbol": symbol, "expiration": today.isoformat(), "greeks": "true",
            })
        except TradierProviderError:
            self._unavailable_reasons[symbol] = "data unavailable"
            return []

        contracts: list[OptionContractOut] = []
        for row in _as_list(payload.get("options", {}).get("option")):
            raw_greeks = row.get("greeks")
            greeks: dict[str, Any] = raw_greeks if isinstance(raw_greeks, dict) else {}
            expiration_value = row.get("expiration_date") or row.get("expiration")
            try:
                expiration = date.fromisoformat(str(expiration_value))
            except ValueError:
                continue
            strike = _number(row.get("strike"))
            option_symbol = str(row.get("symbol", ""))
            if not option_symbol or strike is None:
                continue
            contracts.append(OptionContractOut(
                symbol=symbol, option_symbol=option_symbol, expiration=expiration,
                strike=strike, right=str(row.get("option_type", "")).lower(),
                bid=_number(row.get("bid")), ask=_number(row.get("ask")), last=_number(row.get("last")),
                volume=_integer(row.get("volume")), open_interest=_integer(row.get("open_interest")),
                iv=_number(greeks.get("mid_iv") or greeks.get("smv_vol")),
                delta=_number(greeks.get("delta")), gamma=_number(greeks.get("gamma")),
                theta=_number(greeks.get("theta")), vega=_number(greeks.get("vega")),
                timestamp=self._market_timestamp(row.get("trade_date")),
            ))
        self._chain_cache[cache_key] = (now, contracts)
        self._unavailable_reasons.pop(symbol, None)
        return contracts
