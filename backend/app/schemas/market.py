from datetime import date, datetime
from pydantic import BaseModel

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
    bid: float
    ask: float
    last: float
    volume: int
    open_interest: int
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

class DashboardOut(BaseModel):
    provider_status: ProviderStatus
    quotes: list[Quote]
    market_session: str
    volatility_proxy: float | None
    levels: dict[str, dict[str, float]]
    directional_bias: dict[str, str]
    news_warning: str
    normal_setups: list[SetupOut]
    lottery_setups: list[LotteryOut]
    no_trade: bool
    paper_account: dict
