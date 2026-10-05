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


class LotteryExitScenarioOut(BaseModel):
    target_multiple: float | None = None
    target_hit: bool
    exit_reason: str
    exit_at: datetime | None = None
    exit_bid: float | None = None
    exit_value: float | None = None
    multiple: float | None = None
    return_percent: float | None = None


class LotteryExitScenariosOut(BaseModel):
    hold_to_last: LotteryExitScenarioOut
    take_2x: LotteryExitScenarioOut
    take_5x: LotteryExitScenarioOut


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
    max_quote_gap_minutes: float
    collection_interrupted: bool
    entry_wave_id: str
    exit_scenarios: LotteryExitScenariosOut
    currently_qualified: bool
    provider: str
    data_mode: str
    verification_status: str
    verification_reason: str
    actionable: bool


class LotteryRuleComparisonOut(BaseModel):
    key: str
    label: str
    ending_value: float
    pnl: float
    return_percent: float | None = None


class LotteryCollectionHealthOut(BaseModel):
    status: str
    interrupted_contracts: int
    max_quote_gap_minutes: float
    message: str


class LotterySessionSummaryOut(BaseModel):
    contract_count: int
    entry_wave_count: int
    total_entry_cost: float
    hit_2x_count: int
    hit_5x_count: int
    hit_10x_count: int
    best_observed_multiple: float
    rule_comparisons: list[LotteryRuleComparisonOut] = Field(default_factory=list)
    collection_health: LotteryCollectionHealthOut


class LotteryCashDailyOut(BaseModel):
    trading_date: date
    entries: int
    closed: int
    skipped: int
    daily_realized_pnl: float
    cumulative_realized_pnl: float
    cash: float
    book_equity: float


class LotteryCashPortfolioOut(BaseModel):
    key: str
    label: str
    starting_cash: float
    daily_debit_cap: float
    cash_available: float
    book_equity: float
    pnl: float
    return_percent: float
    maximum_drawdown: float
    positions_taken: int
    closed_positions: int
    active_positions: int
    skipped_insufficient_cash: int
    skipped_daily_cap: int
    wins: int
    losses: int
    daily: list[LotteryCashDailyOut] = Field(default_factory=list)


class LotteryCashTrackerOut(BaseModel):
    starting_cash: float
    daily_debit_cap: float
    quantity_per_entry: int
    selection_rule: str
    portfolios: list[LotteryCashPortfolioOut] = Field(default_factory=list)
    entry_basis: str
    exit_basis: str
    forward_only: bool
    historical_records_changed: bool
    paper_only: bool


class LotteryTrackerListOut(BaseModel):
    trading_date: date
    available_dates: list[date] = Field(default_factory=list)
    summary: LotterySessionSummaryOut
    trackers: list[LotteryTrackerSummaryOut] = Field(default_factory=list)
    cash_tracker: LotteryCashTrackerOut
    entry_basis: str = "First qualifying ask"
    performance_basis: str = "Subsequent sellable bid"
    accounting_note: str = (
        "Rule comparisons assume one contract in every logged row. Adjacent strikes from the same "
        "scanner wave are correlated and are not independent trade alerts."
    )
    paper_only: bool = True


class LotteryTrackerDetailOut(BaseModel):
    tracker: LotteryTrackerSummaryOut
    points: list[LotteryTrackerPointOut] = Field(default_factory=list)
    entry_basis: str = "First qualifying ask"
    performance_basis: str = "Subsequent sellable bid"
    paper_only: bool = True
