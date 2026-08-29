from collections import deque
from datetime import date, datetime, timedelta, timezone
import logging
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.core.config import get_settings
from app.schemas.market import CandleOut, OptionContractOut, ProviderStatus, Quote
from app.services.market_calendar import is_market_day

NY = ZoneInfo("America/New_York")
logger = logging.getLogger(__name__)


def _latest_available_market_date(
    trading_date: date | None = None, now: datetime | None = None,
) -> date:
    """Return the latest regular session whose 09:30 open is not in the future."""
    if trading_date is not None:
        candidate = trading_date
    else:
        local_now = (now or datetime.now(NY)).astimezone(NY)
        candidate = local_now.date()
        if (local_now.hour, local_now.minute) < (9, 30):
            candidate -= timedelta(days=1)
    while not is_market_day(candidate):
        candidate -= timedelta(days=1)
    return candidate


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
                 trading_date: date | None = None, data_mode: str | None = None):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=10.0)
        self._trading_date = trading_date
        self._error = "Tradier API token is not configured." if not token else None
        self._latest = datetime.now(NY)
        self._request_times: deque[datetime] = deque()
        self._rate_allowed: int | None = None
        self._rate_used: int | None = None
        self._rate_available: int | None = None
        self._rate_expires_at: datetime | None = None
        self._last_http_status: int | None = None
        mode = (data_mode if data_mode is not None else get_settings().tradier_data_mode).strip().lower()
        self._data_mode = mode if mode in {"live", "delayed", "unknown"} else "unknown"
        if token and self._data_mode == "unknown":
            logger.warning(
                "Tradier data mode is unknown; set TRADIER_DATA_MODE explicitly to live or delayed. "
                "Candidates remain non-actionable."
            )

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any] | None:
        if not self.token:
            return None
        now = datetime.now(timezone.utc)
        while self._request_times and now - self._request_times[0] >= timedelta(minutes=1):
            self._request_times.popleft()
        budget = max(1, min(get_settings().tradier_request_budget_per_minute, 120))
        if len(self._request_times) >= budget:
            self._error = f"Tradier request safety budget reached ({budget}/minute); waiting for capacity."
            return None
        self._request_times.append(now)
        try:
            response = self.client.get(
                f"{self.base_url}{path}", params=params,
                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
            )
            self._capture_rate_headers(response)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("response is not an object")
            expected_root = {
                "/markets/quotes": "quotes",
                "/markets/timesales": "series",
                "/markets/options/expirations": "expirations",
                "/markets/options/chains": "options",
            }.get(path)
            if expected_root is not None and not isinstance(data.get(expected_root), dict):
                raise ValueError(f"missing {expected_root} response object")
            self._error = None
            self._last_http_status = None
            return data
        except httpx.HTTPStatusError as exc:
            self._capture_rate_headers(exc.response)
            self._last_http_status = exc.response.status_code
            self._error = f"Tradier data unavailable: HTTP {exc.response.status_code}."
            logger.warning("Tradier request failed endpoint=%s status=%s", path, exc.response.status_code)
            return None
        except httpx.RequestError as exc:
            self._last_http_status = None
            self._error = f"Tradier data unavailable: {type(exc).__name__}."
            logger.warning("Tradier request failed endpoint=%s error=%s", path, type(exc).__name__)
            return None
        except (TypeError, ValueError):
            self._last_http_status = None
            self._error = "Tradier returned an invalid response."
            logger.warning("Tradier returned an invalid response endpoint=%s", path)
            return None

    def _capture_rate_headers(self, response: httpx.Response) -> None:
        def integer(name: str) -> int | None:
            value = response.headers.get(name)
            try:
                return int(value) if value is not None else None
            except ValueError:
                return None

        self._rate_allowed = integer("X-Ratelimit-Allowed") or self._rate_allowed
        self._rate_used = integer("X-Ratelimit-Used") or self._rate_used
        self._rate_available = integer("X-Ratelimit-Available")
        expiry = integer("X-Ratelimit-Expiry")
        if expiry is not None:
            try:
                self._rate_expires_at = datetime.fromtimestamp(expiry, timezone.utc)
            except (OSError, ValueError):
                self._rate_expires_at = None

    def budget_status(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        while self._request_times and now - self._request_times[0] >= timedelta(minutes=1):
            self._request_times.popleft()
        safety_limit = max(1, min(get_settings().tradier_request_budget_per_minute, 120))
        local_used = len(self._request_times)
        local_remaining = max(0, safety_limit - local_used)
        remaining = min(local_remaining, self._rate_available) if self._rate_available is not None else local_remaining
        return {
            "safety_limit": safety_limit,
            "used_last_minute": local_used,
            "remaining": max(0, remaining),
            "provider_allowed": self._rate_allowed,
            "provider_used": self._rate_used,
            "provider_available": self._rate_available,
            "resets_at": self._rate_expires_at,
            "paused": remaining <= 0,
        }

    def status(self) -> ProviderStatus:
        if not self.token:
            health = "unavailable"
        elif self._last_http_status == 429 or (self._error and "request safety budget" in self._error):
            health = "rate_limited"
        elif self._error:
            health = "degraded"
        elif self._data_mode == "unknown":
            health = "degraded"
        else:
            health = "healthy"
        if self._error:
            message = self._error
        elif self._data_mode == "unknown":
            message = (
                "Tradier data mode is unknown. Set TRADIER_DATA_MODE explicitly to live or delayed; "
                "candidates cannot be actionable until configured."
            )
        else:
            message = f"Tradier market data mode: {self._data_mode}; paper research only."
        return ProviderStatus(
            provider="tradier", mode=self._data_mode, status=health,
            delay_seconds=0 if self._data_mode == "live" else 900 if self._data_mode == "delayed" else -1,
            latest_timestamp=self._latest, message=message,
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
        session_date = _latest_available_market_date(self._trading_date)
        data = self._get("/markets/timesales", {
            "symbol": symbol, "interval": "1min" if timeframe == "1m" else "5min",
            "start": f"{session_date:%Y-%m-%d} 09:30", "session_filter": "open",
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

    def historical_candles(self, symbol: str, timeframe: str, start: date, end: date) -> list[CandleOut]:
        """Fetch regular-session history; Tradier may truncate ranges by plan."""
        if timeframe not in {"1m", "5m", "15m"}:
            return []
        data = self._get("/markets/timesales", {"symbol": symbol, "interval": timeframe.replace("m", "min"),
            "start": f"{start.isoformat()} 09:30", "end": f"{end.isoformat()} 16:00", "session_filter": "open"})
        result = []
        for row in _rows(data or {}, "series", "data"):
            try:
                stamp = datetime.fromisoformat(str(row["time"]))
                if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=NY)
                result.append(CandleOut(symbol=symbol.upper(), timeframe=timeframe, timestamp=stamp, open=float(row["open"]),
                    high=float(row["high"]), low=float(row["low"]), close=float(row["close"]), volume=int(row["volume"])))
            except (KeyError, TypeError, ValueError):
                continue
        return sorted(result, key=lambda candle: candle.timestamp)

    def expirations(self, symbol: str) -> list[date]:
        data = self._get("/markets/options/expirations", {"symbol": symbol, "includeAllRoots": "true"})
        values: Any = (data or {}).get("expirations", {}).get("date", [])
        if isinstance(values, str):
            values = [values]
        result = []
        for value in values:
            try:
                result.append(date.fromisoformat(value))
            except (TypeError, ValueError):
                continue
        return result

    def option_chain(self, symbol: str, expiration: date | None = None) -> list[OptionContractOut]:
        selected = expiration or self._trading_date or datetime.now(NY).date()
        if expiration is None and selected not in self.expirations(symbol):
            return []
        data = self._get("/markets/options/chains", {"symbol": symbol, "expiration": selected.isoformat(), "greeks": "true"})
        result = []
        for row in _rows(data or {}, "options", "option"):
            greeks = row.get("greeks") or {}
            try:
                bid_stamp = datetime.fromtimestamp(int(row["bid_date"]) / 1000, NY)
                ask_stamp = datetime.fromtimestamp(int(row["ask_date"]) / 1000, NY)
                stamp = min(bid_stamp, ask_stamp)
                result.append(OptionContractOut(symbol=symbol.upper(), option_symbol=str(row["symbol"]),
                    expiration=date.fromisoformat(str(row["expiration_date"])), strike=float(row["strike"]),
                    right=str(row["option_type"]).lower(), bid=float(row.get("bid") or 0),
                    ask=float(row.get("ask") or 0), last=float(row.get("last") or 0),
                    volume=int(row.get("volume") or 0), open_interest=int(row.get("open_interest") or 0),
                    iv=greeks.get("mid_iv"), delta=greeks.get("delta"), gamma=greeks.get("gamma"),
                    theta=greeks.get("theta"), vega=greeks.get("vega"), timestamp=stamp,
                    bid_timestamp=bid_stamp, ask_timestamp=ask_stamp, provider="tradier", data_mode=self._data_mode))
                self._latest = max(self._latest, stamp)
            except (KeyError, TypeError, ValueError, OSError):
                continue
        return result
