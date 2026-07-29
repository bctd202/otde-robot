from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class PaperPositionCreate(BaseModel):
    symbol: str
    option_symbol: str
    direction: Literal["call", "put"]
    expiration: date
    strike: float
    quantity: Literal[1] = 1
    option_ask: float = Field(gt=0)
    underlying_entry_price: float = Field(gt=0)
    underlying_trigger: float
    underlying_invalidation: float
    first_underlying_target: float
    stretch_underlying_target: float
    first_option_target: float = Field(gt=0)
    stretch_option_target: float = Field(gt=0)
    score: float
    score_label: str
    reasons: list[str] = Field(default_factory=list)
    signal_status: Literal["BUY", "WATCH", "MISSED", "PASS", "UNAVAILABLE"]
    provider_mode: str
    entry_timestamp: datetime
    paper_only: Literal[True]


class PaperPositionExit(BaseModel):
    reason: str = Field(default="USER CONFIRMED PAPER EXIT", min_length=1, max_length=255)
    paper_only: Literal[True]


class PaperPositionOut(BaseModel):
    id: int
    symbol: str
    option_symbol: str
    direction: Literal["call", "put"]
    expiration: date
    strike: float
    quantity: int
    entry_option_price: float
    entry_underlying_price: float
    total_debit: float
    underlying_trigger: float
    underlying_invalidation: float
    first_underlying_target: float
    stretch_underlying_target: float
    first_option_target: float
    stretch_option_target: float
    score: float
    score_label: str
    entry_reasons: list[str]
    provider_mode: str
    opened_at: datetime
    closed_at: datetime | None
    exit_option_price: float | None
    exit_underlying_price: float | None
    exit_reason: str | None
    lifecycle_status: Literal["ACTIVE", "CLOSED"]
    current_option_price: float | None
    current_underlying_price: float | None
    unrealized_pnl: float | None
    realized_pnl: float | None
    pnl_percent: float | None
    decision_status: Literal["HOLD", "TAKE_PROFIT", "EXIT", "DATA_UNAVAILABLE", "CLOSED"]
    data_freshness: str
    next_action: str
    last_marked_at: datetime | None
    paper_only: bool = True


class PaperPositionsResponse(BaseModel):
    positions: list[PaperPositionOut]
    paper_only: bool = True
