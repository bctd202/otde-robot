from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

class ProviderStatus(BaseModel):
    provider: str
    mode: str
    status: str
    delay_seconds: int
    latest_timestamp: datetime
    message: str

class Quote(BaseModel):
    symbol: str
    price: float
    timestamp: datetime

class CandleOut(BaseModel):
    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

class OptionContractOut(BaseModel):
    symbol: str
    option_symbol: str
    expiration: date
    strike: float
    right: str
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    volume: int | None = None
    open_interest: int | None = None
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    timestamp: datetime

class SetupOut(BaseModel):
    symbol: str
    setup_type: str
    name: str
    direction: str
    grade: str
    score: float
    entry_trigger: float
    current_underlying_price: float
    invalidation: float
    target1: float
    target2: float
    reward_risk: float
    contract: OptionContractOut | None = None
    confluences: list[str]
    avoid_reasons: list[str]
    generated_at: datetime
    expires_at: datetime
    data_freshness: str

class LotteryOut(BaseModel):
    symbol: str
    right: str
    strike: float
    expiration: date
    bid: float
    ask: float
    midpoint: float
    last: float
    total_debit: float
    otm_percent: float
    delta: float | None
    gamma: float | None
    theta: float | None
    iv: float | None
    volume: int
    open_interest: int
    spread_percent: float
    underlying_trigger: float
    underlying_invalidation: float
    break_even: float
    estimated_2x_underlying: float
    estimated_5x_underlying: float
    estimated_10x_underlying: float
    explanation: str
    catalyst: str
    setup_score: float
    max_allocation: float
    time_remaining_minutes: int
    worthless_reasons: list[str]

class LiquidityLevelsOut(BaseModel):
    previous_day_high: float
    previous_day_low: float
    opening_range_high: float
    opening_range_low: float
    session_high: float
    session_low: float
    vwap: float
    equal_highs: list[float] = Field(default_factory=list)
    equal_lows: list[float] = Field(default_factory=list)

class DashboardOut(BaseModel):
    provider_status: ProviderStatus
    quotes: list[Quote]
    market_session: str
    volatility_proxy: float | None
    levels: dict[str, LiquidityLevelsOut]
    directional_bias: dict[str, str]
    news_warning: str
    normal_setups: list[SetupOut]
    lottery_setups: list[LotteryOut]
    no_trade: bool
    paper_account: dict


class SignalStatus(StrEnum):
    PASS = "PASS"
    WATCH = "WATCH"
    BUY = "BUY"
    HOLD = "HOLD"
    TAKE_PROFIT = "TAKE_PROFIT"
    EXIT = "EXIT"
    MISSED = "MISSED"


class ParlayCandidateOut(BaseModel):
    rank: int
    symbol: str
    direction: str | None = None
    contract_symbol: str | None = None
    strike: float | None = None
    expiration: date | None = None
    bid: float | None = None
    ask: float | None = None
    midpoint: float | None = None
    total_debit: float | None = None
    spread_percent: float | None = None
    volume: int | None = None
    open_interest: int | None = None
    current_underlying_price: float | None = None
    underlying_trigger: float | None = None
    underlying_invalidation: float | None = None
    first_underlying_target: float | None = None
    stretch_underlying_target: float | None = None
    maximum_entry_premium: float | None = None
    no_chase_premium: float | None = None
    first_option_target: float | None = None
    stretch_option_target: float | None = None
    setup_score: int = 0
    score_category: str = "PASS"
    signal_status: SignalStatus = SignalStatus.PASS
    reasons: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    timestamp: datetime
    data_freshness: str


class ParlayResponse(BaseModel):
    provider_status: ProviderStatus
    paper_only: bool = True
    score_disclaimer: str = "Research score, not a probability or trade recommendation."
    candidates: list[ParlayCandidateOut]
