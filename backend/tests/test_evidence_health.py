from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import SignalScan
from app.db.session import Base
from app.services.evidence_health import collection_evidence
from app.services.market_calendar import NY


def test_missing_weekday_sessions_stay_visible_over_weekend():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        result = collection_evidence(db, datetime(2026, 10, 25, 12, tzinfo=NY), None)
    assert result["status"] == "CLOSED"
    assert result["has_coverage_gaps"]
    assert [day["date"] for day in result["sessions"]] == [f"2026-10-{d}" for d in range(23, 18, -1)]
    assert all(day["expected_minutes"] == 390 for day in result["sessions"])
    assert result['scan_timing']['measured_scans']==0
    assert result['scan_timing']['p95_seconds'] is None


def test_timing_summary_is_bounded_and_does_not_invent_old_durations():
    engine=create_engine('sqlite://'); Base.metadata.create_all(engine)
    now=datetime(2026,10,26,14,tzinfo=NY)
    with Session(engine) as db:
        for index in range(125):
            at=now-timedelta(minutes=125-index)
            payload={'scan_timing_v1':{'total_ms':70000,'phases_ms':{'lotto':50000}}} if index%2 else {}
            db.add(SignalScan(trading_date=now.date(),scanned_at=at,evaluation_candle_at=at-timedelta(minutes=1),
                              provider_status=payload,universe=[],candidates=[]))
        db.flush()
        result=collection_evidence(db,now,None)['scan_timing']
        assert result['window_scans']==120
        assert result['measured_scans']==60
        assert result['over_minute_scans']==60
        assert result['p95_seconds']==70
        assert result['latest_phases_ms']=={'lotto':50000}


def test_unique_minutes_partial_session_and_stale_runtime():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime(2026, 10, 26, 9, 35, tzinfo=NY)
    opening = now.replace(minute=30).astimezone(timezone.utc)
    runtime = SimpleNamespace(operator_hold=False, last_evaluation_candle_at=opening)
    with Session(engine) as db:
        for minute in [0, 0, 1]:
            db.add(SignalScan(trading_date=now.date(), scanned_at=opening+timedelta(minutes=minute+1),
                              evaluation_candle_at=opening+timedelta(minutes=minute),
                              provider_status={}, universe=[], candidates=[]))
        db.flush()
        result = collection_evidence(db, now, runtime)
        assert result["status"] == "STALE"
        assert result["sessions"][0]["expected_minutes"] == 5
        assert result["sessions"][0]["observed_minutes"] == 2
        assert result["sessions"][0]["coverage_percent"] == 40
        runtime.last_evaluation_candle_at = (opening+timedelta(minutes=4)).replace(tzinfo=None)
        assert collection_evidence(db, now, runtime)["status"] == "CURRENT"
        runtime.operator_hold = True
        assert collection_evidence(db, now, runtime)["status"] == "HELD"


def test_holidays_early_close_and_opening_grace():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        result = collection_evidence(db, datetime(2026, 11, 27, 14, tzinfo=NY), None)
        assert result["sessions"][0]["expected_minutes"] == 210
        assert result["sessions"][1]["date"] == "2026-11-25"
        assert collection_evidence(db, datetime(2026, 10, 26, 9, 31, tzinfo=NY), None)["status"] == "WARMING_UP"


def test_resume_control_persists_next_open_as_utc(monkeypatch):
    from app.api import routes
    from app.db.models import ScannerRuntime
    from app.schemas.market import ScannerControlRequest
    from app.services.signal_engine import ENGINE_KEY

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 25, 12, tzinfo=timezone.utc)

    monkeypatch.setattr(routes, "datetime", Clock)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        routes.scanner_control(ScannerControlRequest(action="RESUME"), db)
        db.expire_all()
        assert db.get(ScannerRuntime, ENGINE_KEY).next_evaluation_at == datetime(2026, 10, 26, 13, 30)
