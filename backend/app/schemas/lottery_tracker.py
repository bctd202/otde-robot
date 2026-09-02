from datetime import date, datetime

from pydantic import BaseModel, Field


class LotteryTrackerPointOut(BaseModel):
    observed_at: datetime
    quote_timestamp: datetime
    bid_timestamp: datetime | None = None
    ask_timestamp: datetime | None = None
    bid: float
    ask: float
    midpoint: float
    last: float
    bid_value: float
    ask_value: float
    underlying_price: float | None = None
    spread_percent: float
    is_qualified: bool
    setup_score: float | None = None


class LotteryTrackerSummaryOut(BaseModel):
    id: str
    trading_date: date
    symbol: str
    option_symbol: str
    expiration: date
    right: str
    strike: float
    status: str
    first_seen_at: datetime
    last_qualified_at: datetime
    last_quote_at: datetime | None = None
    closed_at: datetime | None = None
    entry_ask: float
    entry_bid: float
    entry_cost: float
    entry_underlying_price: float
    setup_score: float
    latest_bid: float | None = None
    latest_ask: float | None = None
    latest_sellable_value: float | None = None
    latest_multiple: float | None = None
    latest_return_percent: float | None = None
    peak_bid: float
    peak_sellable_value: float
    peak_multiple: float
    peak_return_percent: float
    peak_bid_at: datetime | None = None
    hit_2x_at: datetime | None = None
    hit_5x_at: datetime | None = None
    hit_10x_at: datetime | None = None
    point_count: int
    currently_qualified: bool
    provider: str
    data_mode: str
    verification_status: str
    verification_reason: str
    actionable: bool


class LotteryTrackerListOut(BaseModel):
    trading_date: date
    trackers: list[LotteryTrackerSummaryOut] = Field(default_factory=list)
    entry_basis: str = "First qualifying ask"
    performance_basis: str = "Subsequent sellable bid"
    paper_only: bool = True


class LotteryTrackerDetailOut(BaseModel):
    tracker: LotteryTrackerSummaryOut
    points: list[LotteryTrackerPointOut] = Field(default_factory=list)
    entry_basis: str = "First qualifying ask"
    performance_basis: str = "Subsequent sellable bid"
    paper_only: bool = True
