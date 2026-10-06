from __future__ import annotations

from collections import deque
from datetime import date, datetime, time, timedelta, timezone
import json
import logging
import math
from threading import Condition, Event, RLock, Thread
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import httpx

from app.core.config import get_settings
from app.schemas.market import CandleOut, OptionContractOut, ProviderStatus, Quote
from app.services.market_calendar import is_market_day

NY = ZoneInfo("America/New_York")
logger = logging.getLogger(__name__)


def _items(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    value = (payload or {}).get("data", {}).get("items", [])
    return value if isinstance(value, list) else []


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value) if value is not None else default
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _stamp(value: Any, default: datetime | None = None) -> datetime:
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return default or datetime.now(timezone.utc)


def _occ_compact(symbol: str) -> str:
    return symbol.replace(" ", "").upper()


def _latest_market_date(now: datetime | None = None) -> date:
    local = (now or datetime.now(NY)).astimezone(NY)
    candidate = local.date() if local.time() >= time(9, 30) else local.date() - timedelta(days=1)
    while not is_market_day(candidate):
        candidate -= timedelta(days=1)
    return candidate


class DXLinkSnapshotClient:
    """Small, read-only DXLink client for bounded candle and option-metric snapshots."""

    EVENT_FIELDS = {
        "Candle": ["eventType", "eventSymbol", "eventTime", "time", "sequence", "count",
                   "open", "high", "low", "close", "volume", "vwap", "bidVolume",
                   "askVolume", "impVolatility", "openInterest"],
        "Greeks": ["eventType", "eventSymbol", "volatility", "delta", "gamma", "theta", "rho", "vega"],
        "Summary": ["eventType", "eventSymbol", "openInterest", "dayOpenPrice", "dayHighPrice",
                    "dayLowPrice", "prevDayClosePrice"],
    }

    def __init__(self, url: str, token: str, timeout: float = 4.0):
        self.url = url
        self.token = token
        self.timeout = max(1.0, timeout)

    @staticmethod
    def _events(data: Any, requested: dict[str, list[str]]) -> Iterable[dict[str, Any]]:
        """Decode DXLink COMPACT packets, including batched flat event arrays.

        A FEED_DATA payload names an event type and then supplies one or more
        arrays. Each array may contain several records concatenated together,
        rather than one nested array per record.
        """
        if not isinstance(data, list):
            return []
        output: list[dict[str, Any]] = []
        event_type: str | None = None
        for item in data:
            if isinstance(item, str) and item in requested:
                event_type = item
                continue
            if event_type is None or not isinstance(item, list):
                continue
            fields = requested[event_type]
            width = len(fields)
            if not width:
                continue
            rows = item if item and isinstance(item[0], list) else [item]
            for packed in rows:
                if not isinstance(packed, list):
                    continue
                for offset in range(0, len(packed), width):
                    row = packed[offset:offset + width]
                    if len(row) == width:
                        output.append(dict(zip(fields, row)))
        return output

    def snapshot(self, subscriptions: list[dict[str, Any]], event_types: set[str]) -> list[dict[str, Any]]:
        from websockets.sync.client import connect
        requested = {key: self.EVENT_FIELDS[key] for key in event_types}
        output: list[dict[str, Any]] = []
        deadline = datetime.now(timezone.utc) + timedelta(seconds=self.timeout)
        with connect(self.url, open_timeout=self.timeout, close_timeout=1) as ws:
            ws.send(json.dumps({"type": "SETUP", "channel": 0, "version": "0.1-DXF-JS/0.3.0",
                                "keepaliveTimeout": 60, "acceptKeepaliveTimeout": 60}))
            authorized = opened = configured = False
            while datetime.now(timezone.utc) < deadline:
                remaining = max(.1, (deadline - datetime.now(timezone.utc)).total_seconds())
                try:
                    message = json.loads(ws.recv(timeout=remaining))
                except TimeoutError:
                    break
                kind = message.get("type")
                if kind == "AUTH_STATE" and message.get("state") == "UNAUTHORIZED":
                    ws.send(json.dumps({"type": "AUTH", "channel": 0, "token": self.token}))
                elif kind == "AUTH_STATE" and message.get("state") == "AUTHORIZED" and not authorized:
                    authorized = True
                    ws.send(json.dumps({"type": "CHANNEL_REQUEST", "channel": 3, "service": "FEED",
                                        "parameters": {"contract": "AUTO"}}))
                elif kind == "CHANNEL_OPENED" and not opened:
                    opened = True
                    ws.send(json.dumps({"type": "FEED_SETUP", "channel": 3,
                                        "acceptAggregationPeriod": .1, "acceptDataFormat": "COMPACT",
                                        "acceptEventFields": requested}))
                elif kind == "FEED_CONFIG" and not configured:
                    configured = True
                    ws.send(json.dumps({"type": "FEED_SUBSCRIPTION", "channel": 3,
                                        "reset": True, "add": subscriptions}))
                elif kind == "FEED_DATA":
                    output.extend(self._events(message.get("data"), requested))
            return output


class DXLinkCandleStreamClient:
    """One reconnecting DXLink session that continuously maintains candle history."""

    def __init__(self, url: str, token: str, symbols: list[str], start: datetime,
                 on_events, timeout: float = 4.0):
        self.url = url
        self.token = token
        self.symbols = list(dict.fromkeys(symbol.upper() for symbol in symbols))
        self.start_at = start
        self.on_events = on_events
        self.timeout = max(1.0, timeout)
        self._stop = Event()
        self._thread: Thread | None = None
        self._lock = RLock()
        self._connected = False
        self._last_event_at: datetime | None = None
        self._last_error: str | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = Thread(target=self._run, name="tastytrade-candle-stream", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)

    def health(self) -> dict[str, Any]:
        with self._lock:
            return {
                "connected": self._connected,
                "last_event_at": self._last_event_at,
                "last_error": self._last_error,
                "subscription_count": len(self.symbols),
            }

    def _set_state(self, *, connected: bool | None = None, error: str | None = None) -> None:
        with self._lock:
            if connected is not None:
                self._connected = connected
            self._last_error = error

    def _run(self) -> None:
        delay = 1.0
        while not self._stop.is_set():
            try:
                self._session()
                delay = 1.0
            except Exception as exc:  # the reconnect loop must survive transport failures
                self._set_state(connected=False, error=f"{type(exc).__name__}: {exc}")
                logger.warning("Tastytrade DXLink candle stream disconnected: %s", type(exc).__name__)
            if not self._stop.is_set():
                self._stop.wait(delay)
                delay = min(30.0, delay * 2)

    def _session(self) -> None:
        from websockets.sync.client import connect

        requested = {"Candle": DXLinkSnapshotClient.EVENT_FIELDS["Candle"]}
        subscriptions = [{"type": "Candle", "symbol": f"{symbol}{{=m}}",
                          "fromTime": int(self.start_at.timestamp() * 1000)}
                         for symbol in self.symbols]
        with connect(self.url, open_timeout=self.timeout, close_timeout=1) as ws:
            ws.send(json.dumps({"type": "SETUP", "channel": 0, "version": "0.1-DXF-JS/0.3.0",
                                "keepaliveTimeout": 60, "acceptKeepaliveTimeout": 60}))
            authorized = opened = configured = False
            while not self._stop.is_set():
                try:
                    message = json.loads(ws.recv(timeout=5))
                except TimeoutError:
                    continue
                kind = message.get("type")
                if kind == "AUTH_STATE" and message.get("state") == "UNAUTHORIZED":
                    ws.send(json.dumps({"type": "AUTH", "channel": 0, "token": self.token}))
                elif kind == "AUTH_STATE" and message.get("state") == "AUTHORIZED" and not authorized:
                    authorized = True
                    ws.send(json.dumps({"type": "CHANNEL_REQUEST", "channel": 3, "service": "FEED",
                                        "parameters": {"contract": "AUTO"}}))
                elif kind == "CHANNEL_OPENED" and not opened:
                    opened = True
                    ws.send(json.dumps({"type": "FEED_SETUP", "channel": 3,
                                        "acceptAggregationPeriod": .1, "acceptDataFormat": "COMPACT",
                                        "acceptEventFields": requested}))
                elif kind == "FEED_CONFIG" and not configured:
                    configured = True
                    ws.send(json.dumps({"type": "FEED_SUBSCRIPTION", "channel": 3,
                                        "reset": True, "add": subscriptions}))
                    self._set_state(connected=True, error=None)
                elif kind == "FEED_DATA":
                    events = list(DXLinkSnapshotClient._events(message.get("data"), requested))
                    if events:
                        self.on_events(events)
                        with self._lock:
                            self._last_event_at = datetime.now(timezone.utc)
                            self._last_error = None
            self._set_state(connected=False, error=None)


class TastytradeMarketDataProvider:
    """Read-only tastytrade OAuth + REST/DXLink adapter. It never calls trading endpoints."""

    def __init__(self, client_id: str | None, client_secret: str | None,
                 refresh_token: str | None, base_url: str, user_agent: str,
                 client: httpx.Client | None = None, streamer_factory=DXLinkSnapshotClient,
                 candle_stream_factory=DXLinkCandleStreamClient):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.client = client or httpx.Client(timeout=12.0)
        self.streamer_factory = streamer_factory
        self.candle_stream_factory = candle_stream_factory
        self._access_token: str | None = None
        self._access_expires_at = datetime.min.replace(tzinfo=timezone.utc)
        self._quote_token: str | None = None
        self._quote_url: str | None = None
        self._quote_expires_at = datetime.min.replace(tzinfo=timezone.utc)
        self._latest = datetime.now(NY)
        self._error = self._configuration_error()
        self._last_http_status: int | None = None
        self._request_times: deque[datetime] = deque()
        self._candle_cache: dict[tuple[str, str], list[CandleOut]] = {}
        self._candle_cached_at = datetime.min.replace(tzinfo=timezone.utc)
        self._candle_condition = Condition(RLock())
        self._candle_stream: DXLinkCandleStreamClient | None = None
        self._candle_stream_day: date | None = None
        self._candle_warmup_attempted = False
        self._instrument_cache: dict[str, tuple[datetime, list[dict[str, Any]]]] = {}

    def _configuration_error(self) -> str | None:
        if not self.client_secret or not self.refresh_token:
            return "Tastytrade OAuth credentials are not configured."
        if "api.cert.tastyworks.com" in self.base_url:
            return "Tastytrade sandbox does not provide market data; use the production API for paper research quotes."
        if "/" not in self.user_agent:
            return "TASTYTRADE_USER_AGENT must use product/version format."
        return None

    def _budget_available(self) -> bool:
        now = datetime.now(timezone.utc)
        while self._request_times and now - self._request_times[0] >= timedelta(minutes=1):
            self._request_times.popleft()
        limit = max(1, get_settings().tastytrade_request_budget_per_minute)
        if len(self._request_times) >= limit:
            self._error = f"Tastytrade request safety budget reached ({limit}/minute)."
            return False
        self._request_times.append(now)
        return True

    def _authenticate(self) -> bool:
        if self._configuration_error():
            self._error = self._configuration_error()
            return False
        if self._access_token and datetime.now(timezone.utc) < self._access_expires_at:
            return True
        if not self._budget_available():
            return False
        payload = {"grant_type": "refresh_token", "refresh_token": self.refresh_token,
                   "client_secret": self.client_secret}
        if self.client_id:
            payload["client_id"] = self.client_id
        try:
            response = self.client.post(f"{self.base_url}/oauth/token", json=payload,
                                        headers={"User-Agent": self.user_agent, "Accept": "application/json"})
            response.raise_for_status()
            data = response.json()
            self._access_token = data.get("access_token") or data.get("data", {}).get("access-token")
            if not self._access_token:
                raise ValueError("missing access token")
            expires = int(data.get("expires_in") or 900)
            self._access_expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(60, expires - 60))
            self._error = None
            self._last_http_status = None
            return True
        except httpx.HTTPStatusError as exc:
            self._last_http_status = exc.response.status_code
            self._error = f"Tastytrade OAuth unavailable: HTTP {exc.response.status_code}."
        except (httpx.RequestError, TypeError, ValueError) as exc:
            self._last_http_status = None
            self._error = f"Tastytrade OAuth unavailable: {type(exc).__name__}."
        logger.warning("Tastytrade OAuth refresh failed: %s", self._error)
        return False

    def _request(self, method: str, path: str, *, params: Any = None) -> dict[str, Any] | None:
        if not self._authenticate() or not self._budget_available():
            return None
        try:
            response = self.client.request(method, f"{self.base_url}{path}", params=params,
                headers={"Authorization": f"Bearer {self._access_token}", "User-Agent": self.user_agent,
                         "Accept": "application/json"})
            if response.status_code == 401:
                self._access_token = None
            response.raise_for_status()
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError("response is not an object")
            self._error = None
            self._last_http_status = None
            return value
        except httpx.HTTPStatusError as exc:
            self._last_http_status = exc.response.status_code
            self._error = f"Tastytrade data unavailable: HTTP {exc.response.status_code}."
        except (httpx.RequestError, TypeError, ValueError) as exc:
            self._last_http_status = None
            self._error = f"Tastytrade data unavailable: {type(exc).__name__}."
        logger.warning("Tastytrade request failed endpoint=%s error=%s", path, self._error)
        return None

    def _quote_credentials(self) -> tuple[str, str] | None:
        now = datetime.now(timezone.utc)
        if not self._quote_token or now >= self._quote_expires_at:
            payload = self._request("GET", "/api-quote-tokens")
            data = (payload or {}).get("data", {})
            self._quote_token = data.get("token")
            self._quote_url = data.get("dxlink-url")
            if not self._quote_token or not self._quote_url:
                self._error = "Tastytrade DXLink credentials were unavailable."
                return None
            self._quote_expires_at = now + timedelta(hours=23)
        return self._quote_url, self._quote_token

    def _streamer(self) -> DXLinkSnapshotClient | None:
        credentials = self._quote_credentials()
        if credentials is None:
            return None
        url, token = credentials
        return self.streamer_factory(url, token,
                                     get_settings().tastytrade_stream_timeout_seconds)

    def _accept_candle_events(self, events: list[dict[str, Any]]) -> None:
        changed = False
        with self._candle_condition:
            for event in events:
                try:
                    event_symbol = str(event["eventSymbol"])
                    symbol = event_symbol.split("{")[0].upper()
                    stamp = _stamp(event.get("time")).astimezone(NY)
                    # Strategies are regular-session models. Extended-hours bars must not
                    # silently change their indicators or expected candle counts.
                    if not time(9, 30) <= stamp.time() < time(16, 0):
                        continue
                    row = CandleOut(symbol=symbol, timeframe="1m", timestamp=stamp,
                        open=float(event["open"]), high=float(event["high"]),
                        low=float(event["low"]), close=float(event["close"]),
                        volume=int(_number(event.get("volume"))))
                except (KeyError, TypeError, ValueError, OSError):
                    continue
                key = (symbol, "1m")
                merged = {item.timestamp: item for item in self._candle_cache.get(key, [])}
                merged[stamp] = row
                self._candle_cache[key] = [merged[value] for value in sorted(merged)]
                self._latest = max(self._latest, stamp)
                changed = True
            if changed:
                self._candle_cached_at = datetime.now(timezone.utc)
                self._candle_condition.notify_all()

    def start(self) -> None:
        self._ensure_candle_stream()

    def close(self) -> None:
        stream = self._candle_stream
        if stream is not None:
            stream.stop()
        self._candle_stream = None

    def _ensure_candle_stream(self) -> None:
        trading_day = _latest_market_date()
        current = self._candle_stream
        if current is not None and self._candle_stream_day == trading_day:
            current.start()
            return
        if current is not None:
            current.stop()
        credentials = self._quote_credentials()
        if credentials is None:
            return
        url, token = credentials
        start = datetime.combine(trading_day, time(9, 30), NY)
        self._candle_stream = self.candle_stream_factory(
            url, token, get_settings().parlay_symbol_list, start,
            self._accept_candle_events, get_settings().tastytrade_stream_timeout_seconds,
        )
        self._candle_stream_day = trading_day
        self._candle_warmup_attempted = False
        self._candle_stream.start()

    def data_quality_status(self) -> dict[str, Any]:
        stream = self._candle_stream
        stream_health = stream.health() if stream is not None else {
            "connected": False, "last_event_at": None, "last_error": None,
            "subscription_count": 0,
        }
        with self._candle_condition:
            latest = {symbol: (rows[-1].timestamp if rows else None)
                      for (symbol, timeframe), rows in self._candle_cache.items()
                      if timeframe == "1m"}
        configured = get_settings().parlay_symbol_list
        return {
            **stream_health,
            "provider": "tastytrade",
            "configured_symbols": len(configured),
            "symbols_with_candles": sum(1 for symbol in configured if latest.get(symbol) is not None),
            "latest_candles": {symbol: stamp.isoformat() if stamp else None
                               for symbol, stamp in latest.items()},
        }

    def budget_status(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        while self._request_times and now - self._request_times[0] >= timedelta(minutes=1):
            self._request_times.popleft()
        limit = max(1, get_settings().tastytrade_request_budget_per_minute)
        used = len(self._request_times)
        return {"safety_limit": limit, "used_last_minute": used, "remaining": max(0, limit-used),
                "provider_allowed": None, "provider_used": None, "provider_available": None,
                "resets_at": None, "paused": used >= limit}

    def status(self) -> ProviderStatus:
        configured = self._configuration_error() is None
        stream_health = self._candle_stream.health() if self._candle_stream is not None else None
        stream_error = stream_health.get("last_error") if stream_health else None
        with self._candle_condition:
            symbols_with_candles = sum(1 for rows in self._candle_cache.values() if rows)
        if not configured:
            health = "unavailable"
        elif self._last_http_status == 429 or (self._error and "safety budget" in self._error):
            health = "rate_limited"
        elif self._error or stream_error:
            health = "degraded"
        elif self._candle_warmup_attempted and symbols_with_candles == 0:
            health = "degraded"
        else:
            health = "healthy"
        message = (self._error or
                   (f"Tastytrade DXLink candle stream unavailable: {stream_error}" if stream_error else None) or
                   ("Tastytrade DXLink is connected but completed candles are not ready."
                    if self._candle_warmup_attempted and symbols_with_candles == 0 else None) or
                   "Tastytrade funded-account real-time market data; paper research only.")
        return ProviderStatus(provider="tastytrade", mode="live", status=health, delay_seconds=0,
                              latest_timestamp=self._latest, message=message)

    def quotes(self, symbols: list[str]) -> list[Quote]:
        if not symbols:
            return []
        payload = self._request("GET", "/market-data/by-type",
                                params={"equity": ",".join(dict.fromkeys(s.upper() for s in symbols))})
        result = []
        for row in _items(payload):
            price = _number(row.get("last") or row.get("mark") or row.get("mid"))
            if price <= 0:
                continue
            stamp = _stamp(row.get("updated-at") or row.get("updatedAt")).astimezone(NY)
            result.append(Quote(symbol=str(row.get("symbol", "")).upper(), price=price, timestamp=stamp))
            self._latest = max(self._latest, stamp)
        return result

    def _candle_snapshot(self, symbols: list[str], timeframe: str, start: datetime) -> list[CandleOut]:
        streamer = self._streamer()
        if streamer is None:
            return []
        period = "m" if timeframe == "1m" else timeframe
        subscriptions = [{"type": "Candle", "symbol": f"{symbol}{{={period}}}",
                          "fromTime": int(start.timestamp() * 1000)} for symbol in symbols]
        try:
            events = streamer.snapshot(subscriptions, {"Candle"})
        except Exception as exc:
            self._error = f"Tastytrade DXLink candles unavailable: {type(exc).__name__}."
            logger.warning("Tastytrade DXLink candle snapshot failed: %s", type(exc).__name__)
            return []
        rows = []
        for event in events:
            try:
                event_symbol = str(event["eventSymbol"])
                symbol = event_symbol.split("{")[0].upper()
                stamp = _stamp(event.get("time")).astimezone(NY)
                if stamp < start.astimezone(NY):
                    continue
                rows.append(CandleOut(symbol=symbol, timeframe=timeframe, timestamp=stamp,
                    open=float(event["open"]), high=float(event["high"]), low=float(event["low"]),
                    close=float(event["close"]), volume=int(_number(event.get("volume")))))
                self._latest = max(self._latest, stamp)
            except (KeyError, TypeError, ValueError, OSError):
                continue
        return sorted(rows, key=lambda row: (row.symbol, row.timestamp))

    def candles(self, symbol: str, timeframe: str = "1m") -> list[CandleOut]:
        if timeframe not in {"1m", "5m"}:
            return []
        self._ensure_candle_stream()
        key = (symbol.upper(), "1m")
        with self._candle_condition:
            if not self._candle_cache.get(key) and not self._candle_warmup_attempted:
                self._candle_warmup_attempted = True
                self._candle_condition.wait(timeout=max(
                    1.0, get_settings().tastytrade_stream_warmup_seconds))
            rows = list(self._candle_cache.get(key, []))
        if timeframe == "1m":
            return rows
        from app.market_data.cached import aggregate_candles
        return aggregate_candles(rows, 5)

    def historical_candles(self, symbol: str, timeframe: str, start: date, end: date) -> list[CandleOut]:
        if timeframe not in {"1m", "5m", "15m"}:
            return []
        start_at = datetime.combine(start, time(9, 30), NY)
        end_at = datetime.combine(end, time(16, 0), NY)
        return [row for row in self._candle_snapshot([symbol.upper()], timeframe, start_at)
                if start_at <= row.timestamp.astimezone(NY) <= end_at]

    def _chain_rows(self, symbol: str) -> list[dict[str, Any]]:
        key = symbol.upper()
        cached = self._instrument_cache.get(key)
        if cached and datetime.now(timezone.utc) - cached[0] < timedelta(hours=6):
            return list(cached[1])
        rows = _items(self._request("GET", f"/option-chains/{key}"))
        if rows:
            self._instrument_cache[key] = (datetime.now(timezone.utc), rows)
        return list(rows)

    def expirations(self, symbol: str) -> list[date]:
        output = set()
        for row in self._chain_rows(symbol):
            try:
                output.add(date.fromisoformat(str(row["expiration-date"])))
            except (KeyError, TypeError, ValueError):
                continue
        return sorted(output)

    def _option_metrics(self, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        streamer = self._streamer()
        if streamer is None:
            return {}
        subscriptions: list[dict[str, Any]] = []
        for row in rows:
            streamer_symbol = row.get("streamer-symbol")
            if streamer_symbol:
                subscriptions.extend(({"type": "Greeks", "symbol": streamer_symbol},
                                      {"type": "Summary", "symbol": streamer_symbol}))
        try:
            events = streamer.snapshot(subscriptions, {"Greeks", "Summary"})
        except Exception as exc:
            self._error = f"Tastytrade DXLink option metrics unavailable: {type(exc).__name__}."
            logger.warning("Tastytrade DXLink option metrics failed: %s", type(exc).__name__)
            return {}
        output: dict[str, dict[str, Any]] = {}
        for event in events:
            output.setdefault(str(event.get("eventSymbol", "")), {}).update(event)
        return output

    def option_chain(self, symbol: str, expiration: date | None = None) -> list[OptionContractOut]:
        selected = expiration or self._latest.astimezone(NY).date()
        instruments = [row for row in self._chain_rows(symbol)
                       if str(row.get("expiration-date")) == selected.isoformat() and row.get("active", True)]
        if not instruments:
            return []
        quote_rows: dict[str, dict[str, Any]] = {}
        for offset in range(0, len(instruments), 100):
            batch = instruments[offset:offset+100]
            symbols = [str(row.get("symbol", "")) for row in batch if row.get("symbol")]
            payload = self._request("GET", "/market-data/by-type", params={"equity-option": ",".join(symbols)})
            for row in _items(payload):
                quote_rows[_occ_compact(str(row.get("symbol", "")))] = row
        metrics = self._option_metrics(instruments)
        result = []
        for row in instruments:
            raw_symbol = str(row.get("symbol", ""))
            quote = quote_rows.get(_occ_compact(raw_symbol))
            if not quote:
                continue
            stamp = _stamp(quote.get("updated-at") or quote.get("updatedAt")).astimezone(NY)
            metric = metrics.get(str(row.get("streamer-symbol", "")), {})
            try:
                result.append(OptionContractOut(symbol=symbol.upper(), option_symbol=_occ_compact(raw_symbol),
                    expiration=date.fromisoformat(str(row["expiration-date"])),
                    strike=float(row["strike-price"]), right="call" if row.get("option-type") == "C" else "put",
                    bid=_number(quote.get("bid")), ask=_number(quote.get("ask")),
                    last=_number(quote.get("last") or quote.get("mark")),
                    volume=int(_number(quote.get("volume"))), open_interest=int(_number(metric.get("openInterest"))),
                    iv=metric.get("volatility"), delta=metric.get("delta"), gamma=metric.get("gamma"),
                    theta=metric.get("theta"), vega=metric.get("vega"), timestamp=stamp,
                    bid_timestamp=stamp, ask_timestamp=stamp, provider="tastytrade", data_mode="live"))
                self._latest = max(self._latest, stamp)
            except (KeyError, TypeError, ValueError):
                continue
        return result
