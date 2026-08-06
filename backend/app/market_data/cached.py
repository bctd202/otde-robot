from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from threading import RLock
from typing import Any, TypeVar

from app.core.config import get_settings
from app.schemas.market import CandleOut, OptionContractOut, Quote

T = TypeVar("T")


@dataclass
class _CacheEntry:
    value: Any
    stored_at: datetime


def aggregate_candles(candles: list[CandleOut], minutes: int) -> list[CandleOut]:
    """Aggregate completed one-minute candles into deterministic session-aligned bars."""
    if minutes <= 1:
        return list(candles)
    buckets: dict[datetime, list[CandleOut]] = {}
    for candle in sorted(candles, key=lambda item: item.timestamp):
        stamp = candle.timestamp
        session_minutes = max(0, (stamp.hour * 60 + stamp.minute) - (9 * 60 + 30))
        bucket_start = stamp - timedelta(minutes=session_minutes % minutes,
                                         seconds=stamp.second, microseconds=stamp.microsecond)
        buckets.setdefault(bucket_start, []).append(candle)
    output = []
    for stamp, rows in sorted(buckets.items()):
        output.append(CandleOut(symbol=rows[0].symbol, timeframe=f"{minutes}m", timestamp=stamp,
            open=rows[0].open, high=max(row.high for row in rows), low=min(row.low for row in rows),
            close=rows[-1].close, volume=sum(row.volume for row in rows)))
    return output


class CachedMarketDataProvider:
    """Process-wide read-through cache that shares one upstream snapshot across consumers."""

    def __init__(self, provider: Any):
        self.provider = provider
        self._lock = RLock()
        self._quotes: dict[str, _CacheEntry] = {}
        self._candles: dict[str, _CacheEntry] = {}
        self._expirations: dict[str, _CacheEntry] = {}
        self._chains: dict[tuple[str, date | None], _CacheEntry] = {}

    def status(self):
        return self.provider.status()

    @staticmethod
    def _fresh(entry: _CacheEntry | None, ttl_seconds: int) -> bool:
        return bool(entry and datetime.now(timezone.utc) - entry.stored_at < timedelta(seconds=ttl_seconds))

    def quotes(self, symbols: list[str]) -> list[Quote]:
        requested = list(dict.fromkeys(symbol.upper() for symbol in symbols))
        ttl = get_settings().market_quote_cache_seconds
        with self._lock:
            missing = [symbol for symbol in requested if not self._fresh(self._quotes.get(symbol), ttl)]
            if missing:
                fetched = self.provider.quotes(missing)
                stored_at = datetime.now(timezone.utc)
                for quote in fetched:
                    self._quotes[quote.symbol.upper()] = _CacheEntry(quote, stored_at)
            return [self._quotes[symbol].value for symbol in requested
                    if self._fresh(self._quotes.get(symbol), ttl)]

    def candles(self, symbol: str, timeframe: str = "1m") -> list[CandleOut]:
        symbol = symbol.upper()
        ttl = get_settings().market_candle_cache_seconds
        with self._lock:
            entry = self._candles.get(symbol)
            if not self._fresh(entry, ttl):
                rows = self.provider.candles(symbol, "1m")
                entry = _CacheEntry(rows, datetime.now(timezone.utc))
                self._candles[symbol] = entry
            assert entry is not None
            rows = list(entry.value)
        if timeframe == "1m":
            return rows
        minutes = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}.get(timeframe)
        return aggregate_candles(rows, minutes) if minutes else []

    def historical_candles(self, symbol: str, timeframe: str, start, end):
        return self.provider.historical_candles(symbol, timeframe, start, end)

    def expirations(self, symbol: str) -> list[date]:
        symbol = symbol.upper()
        with self._lock:
            entry = self._expirations.get(symbol)
            if not self._fresh(entry, 6 * 60 * 60):
                values = self.provider.expirations(symbol) if hasattr(self.provider, "expirations") else []
                entry = _CacheEntry(values, datetime.now(timezone.utc))
                self._expirations[symbol] = entry
            assert entry is not None
            return list(entry.value)

    def option_chain(self, symbol: str, expiration: date | None = None) -> list[OptionContractOut]:
        symbol = symbol.upper()
        selected = expiration
        if selected is None and hasattr(self.provider, "expirations"):
            selected = self.status().latest_timestamp.date()
            if selected not in self.expirations(symbol):
                return []
        key = (symbol, selected)
        ttl = get_settings().market_chain_cache_seconds
        with self._lock:
            entry = self._chains.get(key)
            if not self._fresh(entry, ttl):
                try:
                    rows = self.provider.option_chain(symbol, selected)
                except TypeError:
                    rows = self.provider.option_chain(symbol)
                entry = _CacheEntry(rows, datetime.now(timezone.utc))
                self._chains[key] = entry
            assert entry is not None
            return list(entry.value)

    def budget_status(self) -> dict[str, Any]:
        if hasattr(self.provider, "budget_status"):
            return self.provider.budget_status()
        return {"safety_limit": None, "used_last_minute": None, "remaining": None,
                "provider_allowed": None, "provider_used": None, "provider_available": None,
                "resets_at": None, "paused": False}

    def clear(self) -> None:
        with self._lock:
            self._quotes.clear(); self._candles.clear(); self._expirations.clear(); self._chains.clear()
