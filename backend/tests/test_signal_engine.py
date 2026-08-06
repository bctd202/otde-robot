from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import SignalAlert, SignalLifecycle
from app.db.session import Base
from app.schemas.market import ParlayCandidateOut, ProviderStatus
from app.services import signal_engine

NOW = datetime(2026, 8, 5, 14, 5, tzinfo=timezone.utc)


def candidate(status: str, *, price: float = 101, direction: str = "call") -> ParlayCandidateOut:
    active = status in {"WATCH", "BUY", "MISSED"}
    return ParlayCandidateOut(symbol="SPY", rank="PLAY" if active else "PASS",
        direction=direction if active else "none", signal_status=status,
        score=90 if active else 30, score_label="PLAY" if active else "PASS",
        underlying_price=price, underlying_trigger=100 if active else None,
        underlying_invalidation=99 if active else None,
        first_underlying_target=102 if active else None,
        primary_action=f"{status} TEST", generated_at=NOW, data_freshness="live_current")


def test_watch_buy_invalidated_lifecycle_and_alert_history():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        watch = candidate("WATCH")
        signal_engine.apply_lifecycle(db, [watch], NOW)
        db.commit()
        assert watch.lifecycle_status == "WATCH"
        assert watch.valid_until == NOW + timedelta(minutes=2)

        buy = candidate("BUY")
        signal_engine.apply_lifecycle(db, [buy], NOW + timedelta(minutes=1))
        db.commit()
        assert buy.lifecycle_id == watch.lifecycle_id
        assert buy.lifecycle_status == "BUY"
        assert buy.triggered_at == NOW + timedelta(minutes=2)

        passed = candidate("PASS", price=98)
        signal_engine.apply_lifecycle(db, [passed], NOW + timedelta(minutes=2))
        db.commit()
        row = db.get(SignalLifecycle, watch.lifecycle_id)
        assert row is not None and row.status == "INVALIDATED" and row.valid_until is None
        assert passed.lifecycle_status == "INVALIDATED"
        assert [alert.event_type for alert in db.scalars(select(SignalAlert).order_by(SignalAlert.id)).all()] == [
            "NEW_WATCH", "BUY", "INVALIDATED"
        ]


def test_same_symbol_can_hold_independent_active_lifecycles_for_both_strategies():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        fast = candidate("WATCH")
        structured = candidate("WATCH")
        structured.strategy_mode = "STRUCTURED_INTRADAY"
        structured.strategy_version = "structured-intraday-v1"
        signal_engine.apply_lifecycle(db, [fast, structured], NOW)
        db.commit()
        rows = list(db.scalars(select(SignalLifecycle).where(SignalLifecycle.symbol == "SPY")).all())
        assert {row.strategy_mode for row in rows} == {"ONE_MIN_0DTE", "STRUCTURED_INTRADAY"}
        assert len({row.id for row in rows}) == 2


class Provider:
    def status(self):
        return ProviderStatus(provider="tradier", mode="live", status="healthy", delay_seconds=0,
            latest_timestamp=NOW, message="test")


def test_scan_runs_once_per_completed_candle_and_uses_cached_snapshot(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    calls = 0

    def rank(_provider, symbols, *, completed_at=None):
        nonlocal calls
        calls += 1
        assert completed_at == NOW.replace(second=0, microsecond=0) - timedelta(minutes=1)
        return [candidate("PASS") for _ in symbols]

    monkeypatch.setattr(signal_engine, "rank_parlays", rank)
    monkeypatch.setattr(signal_engine, "rank_structured_intraday", lambda *args, **kwargs: [])
    monkeypatch.setattr(signal_engine, "track_candidates", lambda *args, **kwargs: None)
    with Session(engine) as db:
        first = signal_engine.run_signal_scan(db, Provider(), ["SPY"])
        second = signal_engine.run_signal_scan(db, Provider(), ["SPY"])
        assert first is not None and second is not None and first.id == second.id
        assert calls == 1
        assert signal_engine.cached_candidates(second)[0].symbol == "SPY"
