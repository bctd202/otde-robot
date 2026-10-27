"""Inert entry-timing research component; NOT an account or a production scanner.

No imports from scanner/account writers, database access, provider requests, clock reads,
activation, fills, or order execution. ENTRY_ELIGIBLE is evidence for a future account
adapter, not a booked trade. See docs/RETEST_RESEARCH_PREPARATION.md for integration gates.
"""
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from typing import Literal

from app.schemas.market import CandleOut, OptionContractOut
from app.services.contracts import validate_contract
from app.services.market_calendar import HOLIDAYS_BY_YEAR, NY, is_market_day, market_close

VERSION = "retest-entry-preparation-v1"
MINUTE = timedelta(minutes=1)


def stamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Evidence requires timezone-aware timestamps")
    return value.astimezone(timezone.utc)


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class FrozenSetup:
    ticker: str
    direction: Literal["call", "put"]
    breakout_at: datetime  # Completed candle START, not decision time.
    observed_at: datetime  # Actual decision/observation clock; never backdated.
    breakout: float
    stop: float
    target: float
    planning_risk: float   # Exact production planning risk; NOT abs(entry-stop).
    entry_low: float
    entry_high: float
    no_chase: float
    entry_cutoff: datetime  # Must be explicitly resolved by reviewed baseline adapter.
    timed_exit: datetime
    contract_json: str
    completed_evidence_json: str
    configuration_json: str
    strategy_version: str

    def __post_init__(self):
        for key in ("breakout_at", "observed_at", "entry_cutoff", "timed_exit"):
            object.__setattr__(self, key, stamp(getattr(self, key)))
        if self.direction not in ("call", "put"):
            raise ValueError("Unknown direction")
        numbers = (self.breakout, self.stop, self.target, self.planning_risk,
                   self.entry_low, self.entry_high, self.no_chase)
        if not all(math.isfinite(n) and n > 0 for n in numbers):
            raise ValueError("Frozen prices/risk must be finite and positive")
        if not self.entry_low <= self.entry_high <= self.no_chase:
            raise ValueError("Invalid premium band")
        if not (self.stop < self.breakout < self.target if self.direction == "call"
                else self.target < self.breakout < self.stop):
            raise ValueError("Invalid frozen direction/levels")
        if self.breakout_at.second or self.breakout_at.microsecond:
            raise ValueError("Breakout must identify a minute candle")
        day = self.breakout_at.astimezone(NY).date()
        if day.year not in HOLIDAYS_BY_YEAR or not is_market_day(day):
            raise ValueError("Unsupported or closed exchange session")
        opening = datetime.combine(day, datetime.min.time().replace(hour=9, minute=30), NY)
        closing = datetime.combine(day, market_close(day), NY)
        if not (opening <= self.breakout_at and self.breakout_at + MINUTE <= self.observed_at
                < self.entry_cutoff <= self.timed_exit <= closing):
            raise ValueError("Invalid chronology/cutoffs; early-close policy must be explicit")
        contract = OptionContractOut.model_validate_json(self.contract_json)
        if (contract.symbol != self.ticker or contract.right != self.direction
                or contract.expiration != day):
            raise ValueError("Frozen contract must match ticker, direction, and session")
        # Canonical immutable strings prevent a caller mutating frozen evidence dictionaries.
        for key in ("contract_json", "completed_evidence_json", "configuration_json"):
            payload = json.loads(getattr(self, key))
            if not payload:
                raise ValueError("Missing frozen evidence/configuration")
            object.__setattr__(self, key, canonical(payload))
        if not self.strategy_version:
            raise ValueError("Missing strategy version")

    @property
    def identity(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()

    def to_json(self) -> str:
        fields = asdict(self)
        for key in ("breakout_at", "observed_at", "entry_cutoff", "timed_exit"):
            fields[key] = fields[key].isoformat()
        return canonical(fields)

    @classmethod
    def from_json(cls, data: str) -> "FrozenSetup":
        fields = json.loads(data)
        for key in ("breakout_at", "observed_at", "entry_cutoff", "timed_exit"):
            fields[key] = datetime.fromisoformat(fields[key])
        return cls(**fields)


@dataclass(frozen=True)
class TimingState:
    setup_identity: str
    phase: str  # WAIT_RETEST, PENDING_ENTRY, CANCELLED, ENTRY_ELIGIBLE
    checked_through: datetime
    processed_at: datetime
    requested_at: datetime | None = None
    retest_at: datetime | None = None
    reason: str | None = None
    events: tuple[str, ...] = ()  # canonical immutable decision/evidence payloads

    def to_json(self) -> str:
        fields = asdict(self)
        for key in ("checked_through", "processed_at", "requested_at", "retest_at"):
            fields[key] = fields[key].isoformat() if fields[key] else None
        return canonical(fields)

    @classmethod
    def from_json(cls, data: str) -> "TimingState":
        fields = json.loads(data)
        for key in ("checked_through", "processed_at", "requested_at", "retest_at"):
            fields[key] = stamp(datetime.fromisoformat(fields[key])) if fields[key] else None
        fields["events"] = tuple(fields["events"])
        return cls(**fields)


def _event(state: TimingState, now: datetime, kind: str, **evidence) -> TimingState:
    event = canonical({"version": VERSION, "sequence": len(state.events),
        "setup_identity": state.setup_identity, "at": now.isoformat(), "kind": kind, **evidence})
    return replace(state, processed_at=now, events=(*state.events, event))


def start(setup: FrozenSetup) -> TimingState:
    state = TimingState(setup.identity, "WAIT_RETEST", setup.breakout_at, setup.observed_at)
    return _event(state, setup.observed_at, "FROZEN", setup=json.loads(setup.to_json()))


def _cancel(state: TimingState, now: datetime, reason: str, **evidence) -> TimingState:
    return _event(replace(state, phase="CANCELLED", reason=reason), now, "CANCELLED",
                  reason=reason, **evidence)


def _quote_problem(setup: FrozenSetup, quote: OptionContractOut | None,
                   now: datetime, earliest: datetime) -> str | None:
    if quote is None:
        return "QUOTE_UNAVAILABLE"
    original = OptionContractOut.model_validate_json(setup.contract_json)
    if ((quote.option_symbol.strip().upper(), quote.symbol, quote.expiration, quote.strike, quote.right)
            != (original.option_symbol.strip().upper(), original.symbol, original.expiration,
                original.strike, original.right)):
        return "CONTRACT_CHANGED"
    if quote.provider != "tastytrade" or quote.data_mode != "live":
        return "PROVENANCE_FAILED"
    if not all(math.isfinite(n) for n in (quote.bid, quote.ask, quote.strike)):
        return "INVALID_PRICE"
    clocks = (quote.bid_timestamp, quote.ask_timestamp, quote.received_at)
    if quote.receipt_basis != "REST_RESPONSE_RECEIVED_V1" or any(t is None for t in clocks):
        return "QUOTE_UNAVAILABLE"
    try:
        times = [stamp(t) for t in clocks if t is not None]
    except ValueError:
        return "QUOTE_UNAVAILABLE"
    if not all(max(earliest, now-timedelta(seconds=60)) <= t <= now for t in times):
        return "QUOTE_NOT_FRESH_OR_LATER"
    if not validate_contract(quote, setup.ticker, now=now).actionable:
        return "CONTRACT_INELIGIBLE"
    if not setup.entry_low <= quote.ask <= min(setup.entry_high, setup.no_chase):
        return "PREMIUM_OUTSIDE_FROZEN_BAND"
    return None


def advance(setup: FrozenSetup, state: TimingState, *, now: datetime,
            candles: list[CandleOut], quote: OptionContractOut | None,
            capacity_available: bool) -> TimingState:
    """One deterministic observation. Caller must persist state/events atomically.

    This gate only signals entry eligibility; it neither deducts cash nor allocates
    slots. `capacity_available` must include settled cash, slots and closing-cost
    reserves under the future reviewed account adapter. No global ticker/day gate
    or full experiment persistence is implied by this standalone component.
    """
    now = stamp(now)
    if setup.identity != state.setup_identity:
        raise ValueError("Cannot replace the frozen setup")
    if state.phase in ("CANCELLED", "ENTRY_ELIGIBLE") or now <= state.processed_at:
        return state  # Restart/replayed or backwards observation cannot invent a decision.
    if state.phase not in ("WAIT_RETEST", "PENDING_ENTRY"):
        raise ValueError("Unknown research timing phase")
    if now >= setup.entry_cutoff:
        return _cancel(state, now, "SESSION_CUTOFF")
    latest = now.replace(second=0, microsecond=0)-MINUTE
    by_time: dict[datetime, CandleOut] = {}
    for candle in candles:
        at = stamp(candle.timestamp)
        if not state.checked_through < at <= latest:
            continue
        if candle.symbol != setup.ticker or candle.timeframe != "1m":
            continue
        values = (candle.open, candle.high, candle.low, candle.close)
        if (at.second or at.microsecond or not all(math.isfinite(x) and x > 0 for x in values)
                or not candle.low <= min(candle.open, candle.close) <= max(candle.open, candle.close) <= candle.high):
            return _cancel(state, now, "INVALID_CANDLE")
        if at in by_time and by_time[at] != candle:
            return _cancel(state, now, "CONFLICTING_CANDLE")
        by_time[at] = candle
    next_at = state.checked_through+MINUTE
    while next_at <= latest:
        if state.phase == "WAIT_RETEST" and next_at > setup.breakout_at+5*MINUTE:
            return _cancel(state, now, "FIVE_BAR_EXPIRY")
        completed = by_time.get(next_at)
        if completed is None:
            return _cancel(state, now, "MISSING_REQUIRED_CANDLE", missing_at=next_at.isoformat())
        candle = completed
        state = replace(state, checked_through=next_at)
        state = _event(state, now, "COMPLETED_BAR", candle=candle.model_dump(mode="json"))
        stop = candle.low <= setup.stop if setup.direction == "call" else candle.high >= setup.stop
        target = candle.high >= setup.target if setup.direction == "call" else candle.low <= setup.target
        if stop or target:
            return _cancel(state, now, "STOP_BEFORE_ENTRY" if stop else "TARGET_BEFORE_ENTRY",
                           stop_touched=stop, target_touched=target)
        retest = (candle.low <= setup.breakout <= candle.high and
                  (candle.close > setup.breakout if setup.direction == "call" else candle.close < setup.breakout))
        if state.phase == "WAIT_RETEST" and retest:
            # No historical quote/request time manufactured after a collector outage.
            if next_at != latest:
                return _cancel(state, now, "LATE_RETEST_OBSERVATION")
            extension = ((candle.close-setup.breakout) if setup.direction == "call"
                         else (setup.breakout-candle.close))/setup.planning_risk
            if extension > 1.35:
                return _cancel(state, now, "EXTENSION_EXCEEDED", extension=extension)
            problem = _quote_problem(setup, quote, now, now-timedelta(seconds=60))
            if problem:
                return _cancel(state, now, "RETEST_VERIFICATION_FAILED", verification=problem)
            if not capacity_available:
                return _cancel(state, now, "CAPACITY_SKIP")
            assert quote is not None
            state = replace(state, phase="PENDING_ENTRY", requested_at=now, retest_at=next_at)
            return _event(state, now, "ENTRY_REQUEST", extension=extension,
                          quote=quote.model_dump(mode="json"))
        next_at += MINUTE
    if state.phase == "WAIT_RETEST":
        if state.checked_through >= setup.breakout_at+5*MINUTE:
            return _cancel(state, now, "FIVE_BAR_EXPIRY")
        return replace(state, processed_at=now)
    assert state.requested_at is not None
    # Every newly completed bar has been invalidation-checked before this gate.
    if now > state.requested_at+timedelta(seconds=120):
        return _cancel(state, now, "ENTRY_QUOTE_DEADLINE")
    if not capacity_available:
        return _cancel(state, now, "CAPACITY_SKIP")
    problem = _quote_problem(setup, quote, now, state.requested_at+timedelta(seconds=1))
    if problem in ("QUOTE_UNAVAILABLE", "QUOTE_NOT_FRESH_OR_LATER"):
        return _event(state, now, "ENTRY_QUOTE_WAIT", reason=problem)
    if problem:
        return _cancel(state, now, "ENTRY_VERIFICATION_FAILED", verification=problem)
    assert quote is not None
    # Not an account fill: exact cost/cash reservation must be checked atomically downstream.
    return _event(replace(state, phase="ENTRY_ELIGIBLE"), now, "ENTRY_ELIGIBLE",
                  quote=quote.model_dump(mode="json"))
