from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text
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

class PositionMark(Base):
    __tablename__ = "position_marks"
    id: Mapped[int] = mapped_column(primary_key=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("paper_positions.id"))
    timestamp: Mapped[str] = mapped_column(DateTime(timezone=True))
    mark_price: Mapped[float] = mapped_column(Float)

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
