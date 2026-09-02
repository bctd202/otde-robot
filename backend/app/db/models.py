from datetime import date, datetime
from typing import Literal

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base

class TradingDay(Base):
    __tablename__ = "trading_days"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[str] = mapped_column(Date, unique=True)
    session: Mapped[str] = mapped_column(String(32), default="regular")
    is_holiday: Mapped[bool] = mapped_column(Boolean, default=False)
    is_early_close: Mapped[bool] = mapped_column(Boolean, default=False)

class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    price: Mapped[float] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    delay_seconds: Mapped[int] = mapped_column(Integer, default=0)
    timestamp: Mapped[str] = mapped_column(DateTime(timezone=True))

class Candle(Base):
    __tablename__ = "candles"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    timestamp: Mapped[str] = mapped_column(DateTime(timezone=True), index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer)

class OptionContract(Base):
    __tablename__ = "option_contracts"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    option_symbol: Mapped[str] = mapped_column(String(64), unique=True)
    expiration: Mapped[str] = mapped_column(Date)
    strike: Mapped[float] = mapped_column(Float)
    right: Mapped[str] = mapped_column(String(4))

class OptionQuote(Base):
    __tablename__ = "option_quotes"
    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("option_contracts.id"))
    bid: Mapped[float] = mapped_column(Float)
    ask: Mapped[float] = mapped_column(Float)
    last: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer)
    open_interest: Mapped[int] = mapped_column(Integer)
    iv: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    gamma: Mapped[float | None] = mapped_column(Float, nullable=True)
    theta: Mapped[float | None] = mapped_column(Float, nullable=True)
    vega: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamp: Mapped[str] = mapped_column(DateTime(timezone=True))
    contract = relationship("OptionContract")

class LiquidityLevel(Base):
    __tablename__ = "liquidity_levels"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    level_type: Mapped[str] = mapped_column(String(64))
    price: Mapped[float] = mapped_column(Float)
    timestamp: Mapped[str] = mapped_column(DateTime(timezone=True))

class DetectedEvent(Base):
    __tablename__ = "detected_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    direction: Mapped[str] = mapped_column(String(8))
    price: Mapped[float] = mapped_column(Float)
    timestamp: Mapped[str] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JSON, default=dict)

class Setup(Base):
    __tablename__ = "setups"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    setup_type: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    direction: Mapped[str] = mapped_column(String(8))
    grade: Mapped[str] = mapped_column(String(8), default="B")
    score: Mapped[float] = mapped_column(Float, default=0)
    entry_trigger: Mapped[float] = mapped_column(Float)
    invalidation: Mapped[float] = mapped_column(Float)
    target1: Mapped[float] = mapped_column(Float)
    target2: Mapped[float] = mapped_column(Float)
    reward_risk: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="candidate")
    generated_at: Mapped[str] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[str] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JSON, default=dict)

class SetupConfluence(Base):
    __tablename__ = "setup_confluences"
    id: Mapped[int] = mapped_column(primary_key=True)
    setup_id: Mapped[int] = mapped_column(ForeignKey("setups.id"))
    tag: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)

class Signal(Base):
    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(primary_key=True)
    setup_id: Mapped[int | None] = mapped_column(ForeignKey("setups.id"), nullable=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    signal_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    generated_at: Mapped[str] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

class PaperOrder(Base):
    __tablename__ = "paper_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"), nullable=True)
    symbol: Mapped[str] = mapped_column(String(12))
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[int] = mapped_column(Integer)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True))

class PaperPosition(Base):
    __tablename__ = "paper_positions"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12))
    quantity: Mapped[int] = mapped_column(Integer)
    avg_price: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32))

class DailyWatchSymbol(Base):
    __tablename__ = "daily_watch_symbols"
    __table_args__ = (UniqueConstraint("trading_date", "symbol", name="uq_daily_watch_date_symbol"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    symbol: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SignalScan(Base):
    __tablename__ = "signal_scans"
    id: Mapped[int] = mapped_column(primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    evaluation_candle_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    provider_status: Mapped[dict] = mapped_column(JSON)
    universe: Mapped[list] = mapped_column(JSON)
    candidates: Mapped[list] = mapped_column(JSON)


class LotteryTracker(Base):
    __tablename__ = "lottery_trackers"
    __table_args__ = (
        UniqueConstraint("trading_date", "option_symbol", name="uq_lottery_tracker_date_contract"),
        Index("ix_lottery_trackers_date_status", "trading_date", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    option_symbol: Mapped[str] = mapped_column(String(64), index=True)
    normalized_option_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expiration: Mapped[date] = mapped_column(Date)
    right: Mapped[str] = mapped_column(String(8))
    strike: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_qualified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_quote_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_ask: Mapped[float] = mapped_column(Float)
    entry_bid: Mapped[float] = mapped_column(Float)
    entry_underlying_price: Mapped[float] = mapped_column(Float)
    setup_score: Mapped[float] = mapped_column(Float)
    initial_snapshot: Mapped[dict] = mapped_column(JSON)
    provider: Mapped[str] = mapped_column(String(32))
    data_mode: Mapped[str] = mapped_column(String(32))
    verification_status: Mapped[str] = mapped_column(String(32))
    verification_reason: Mapped[str] = mapped_column(String(255))
    actionable: Mapped[bool] = mapped_column(Boolean, default=False)
    latest_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_midpoint: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_last: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_underlying_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_bid: Mapped[float] = mapped_column(Float, default=0)
    peak_bid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hit_2x_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hit_5x_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hit_10x_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LotteryQuoteSnapshot(Base):
    __tablename__ = "lottery_quote_snapshots"
    __table_args__ = (
        UniqueConstraint("tracker_id", "observed_at", name="uq_lottery_snapshot_tracker_observed"),
        Index("ix_lottery_quote_tracker_observed", "tracker_id", "observed_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tracker_id: Mapped[str] = mapped_column(ForeignKey("lottery_trackers.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    quote_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    bid_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ask_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bid: Mapped[float] = mapped_column(Float)
    ask: Mapped[float] = mapped_column(Float)
    midpoint: Mapped[float] = mapped_column(Float)
    last: Mapped[float] = mapped_column(Float)
    underlying_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread_percent: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer)
    open_interest: Mapped[int] = mapped_column(Integer)
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    gamma: Mapped[float | None] = mapped_column(Float, nullable=True)
    theta: Mapped[float | None] = mapped_column(Float, nullable=True)
    iv: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_qualified: Mapped[bool] = mapped_column(Boolean, default=False)
    setup_score: Mapped[float | None] = mapped_column(Float, nullable=True)


class SignalLifecycle(Base):
    __tablename__ = "signal_lifecycles"
    __table_args__ = (Index("ix_signal_lifecycle_active", "trading_date", "symbol", "status"),
                      Index("ix_signal_lifecycle_strategy_active", "trading_date", "symbol",
                            "strategy_mode", "status"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    direction: Mapped[str] = mapped_column(String(8))
    strategy_mode: Mapped[str] = mapped_column(String(32), default="ONE_MIN_0DTE",
                                               server_default="ONE_MIN_0DTE", index=True)
    strategy_version: Mapped[str] = mapped_column(String(40), default="parlay-v1",
                                                  server_default="parlay-v1")
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evaluation_candle_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(255))
    candidate_snapshot: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SignalAlert(Base):
    __tablename__ = "signal_alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(180), unique=True)
    lifecycle_id: Mapped[str | None] = mapped_column(ForeignKey("signal_lifecycles.id"), nullable=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    message: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)


class ScannerRuntime(Base):
    __tablename__ = "scanner_runtime"
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(32))
    last_scan_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_scan_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_evaluation_candle_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_evaluation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

class PositionMark(Base):
    __tablename__ = "position_marks"
    id: Mapped[int] = mapped_column(primary_key=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("paper_positions.id"))
    timestamp: Mapped[str] = mapped_column(DateTime(timezone=True))
    mark_price: Mapped[float] = mapped_column(Float)

class ParlayPaperPosition(Base):
    __tablename__ = "parlay_paper_positions"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    option_symbol: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[Literal["call", "put"]] = mapped_column(String(8))
    strategy_mode: Mapped[str] = mapped_column(String(32), default="ONE_MIN_0DTE",
                                               server_default="ONE_MIN_0DTE", index=True)
    strategy_version: Mapped[str] = mapped_column(String(40), default="parlay-v1",
                                                  server_default="parlay-v1")
    expiration: Mapped[date] = mapped_column(Date)
    strike: Mapped[float] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    entry_option_price: Mapped[float] = mapped_column(Float)
    entry_underlying_price: Mapped[float] = mapped_column(Float)
    total_debit: Mapped[float] = mapped_column(Float)
    underlying_trigger: Mapped[float] = mapped_column(Float)
    underlying_invalidation: Mapped[float] = mapped_column(Float)
    first_underlying_target: Mapped[float] = mapped_column(Float)
    stretch_underlying_target: Mapped[float] = mapped_column(Float)
    first_option_target: Mapped[float] = mapped_column(Float)
    stretch_option_target: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float)
    score_label: Mapped[str] = mapped_column(String(32))
    entry_reasons: Mapped[list] = mapped_column(JSON, default=list)
    provider_mode: Mapped[str] = mapped_column(String(32))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_option_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_underlying_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lifecycle_status: Mapped[Literal["ACTIVE", "EXPIRED", "CLOSED"]] = mapped_column(String(16), default="ACTIVE", index=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_option_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_underlying_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_freshness: Mapped[str] = mapped_column(String(32), default="current")
    provenance_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provenance_data_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verification_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verification_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actionable: Mapped[bool] = mapped_column(Boolean, default=False)
    original_occ_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalized_option_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bid_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ask_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quote_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    requested_start: Mapped[date] = mapped_column(Date)
    requested_end: Mapped[date] = mapped_column(Date)
    actual_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    tickers: Mapped[list] = mapped_column(JSON)
    strategy_snapshot: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), index=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    failures: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LiveWaitCandidate(Base):
    __tablename__ = "live_wait_candidates"
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(12), index=True)
    direction: Mapped[str] = mapped_column(String(4))
    strategy_mode: Mapped[str] = mapped_column(String(32), default="ONE_MIN_0DTE",
                                               server_default="ONE_MIN_0DTE", index=True)
    strategy_version: Mapped[str] = mapped_column(String(40), default="parlay-v1",
                                                  server_default="parlay-v1")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    condition_snapshot: Mapped[dict] = mapped_column(JSON)


class SignalPerformance(Base):
    __tablename__ = "signal_performance"
    __table_args__ = (UniqueConstraint("source", "dedupe_key", name="uq_signal_performance_source_key"),
        Index("ix_signal_performance_filters", "source", "trading_date", "ticker", "exit_reason"))
    signal_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source: Mapped[str] = mapped_column(String(12))
    dedupe_key: Mapped[str] = mapped_column(String(160))
    backtest_run_id: Mapped[str | None] = mapped_column(ForeignKey("backtest_runs.id"), nullable=True, index=True)
    ticker: Mapped[str] = mapped_column(String(12), index=True)
    direction: Mapped[str] = mapped_column(String(4))
    backend_status: Mapped[str] = mapped_column(String(16))
    setup_type: Mapped[str] = mapped_column(String(64), index=True)
    strategy_mode: Mapped[str] = mapped_column(String(32), default="ONE_MIN_0DTE",
                                               server_default="ONE_MIN_0DTE", index=True)
    strategy_version: Mapped[str] = mapped_column(String(32))
    strategy_snapshot: Mapped[dict] = mapped_column(JSON)
    condition_snapshot: Mapped[dict] = mapped_column(JSON)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    first_wait_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_price: Mapped[float] = mapped_column(Float)
    target_price: Mapped[float] = mapped_column(Float)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str] = mapped_column(String(16), default="OPEN", index=True)
    result_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    mfe_r: Mapped[float] = mapped_column(Float, default=0)
    mae_r: Mapped[float] = mapped_column(Float, default=0)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float] = mapped_column(Float)
    user_entered: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    paper_position_id: Mapped[int | None] = mapped_column(ForeignKey("parlay_paper_positions.id"), nullable=True)
    option_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    conservative_same_candle: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provenance_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provenance_data_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verification_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verification_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actionable: Mapped[bool] = mapped_column(Boolean, default=False)
    original_occ_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    normalized_option_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bid_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ask_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quote_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    contract_expiration: Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    contract_option_type: Mapped[str | None] = mapped_column(String(8), nullable=True)


class TradeOutcome(Base):
    __tablename__ = "trade_outcomes"
    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"), nullable=True)
    max_favorable_excursion: Mapped[float] = mapped_column(Float, default=0)
    max_adverse_excursion: Mapped[float] = mapped_column(Float, default=0)
    max_return_multiple: Mapped[float] = mapped_column(Float, default=0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

class EconomicEvent(Base):
    __tablename__ = "economic_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_name: Mapped[str] = mapped_column(String(128))
    scheduled_at: Mapped[str] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(64), default="unavailable")
    tradable: Mapped[bool] = mapped_column(Boolean, default=False)

class DailyReport(Base):
    __tablename__ = "daily_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_date: Mapped[str] = mapped_column(Date, unique=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

class WeeklyReport(Base):
    __tablename__ = "weekly_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    week_start: Mapped[str] = mapped_column(Date, unique=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

class UserSetting(Base):
    __tablename__ = "user_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True)
    value: Mapped[dict] = mapped_column(JSON)

class DataQualityEvent(Base):
    __tablename__ = "data_quality_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[str] = mapped_column(DateTime(timezone=True))
