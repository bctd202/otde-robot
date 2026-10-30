from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import func,select

from app.db.models import DataQualityEvent,ScannerRuntime,SignalScan
from app.services.collection_integrity import record_close,snapshot
from app.services.evidence_health import collection_evidence
from app.services.market_calendar import NY
from app.services import readiness
from test_performance import database


def test_optional_input_failure_is_explicit_and_cannot_abort_trading_scan():
    class Feed:
        def completed_candle_evidence(self,at):raise RuntimeError('Synthetic cache failure')
    result=snapshot(Feed(),datetime(2026,10,30,tzinfo=timezone.utc))
    assert result['inputs']=={} and result['error_type']=='RuntimeError'


def test_close_records_real_cache_evidence_once_without_creating_a_trading_scan():
    now=datetime(2026,10,30,16,0,15,tzinfo=NY)
    class Feed:
        def completed_candle_evidence(self, at):
            assert at==datetime(2026,10,30,19,59,tzinfo=timezone.utc)
            return {'SPY':True,'USO':False}
    with database()() as db:
        record_close(db,Feed(),now);db.flush();record_close(db,Feed(),now)
        assert db.scalar(select(func.count()).select_from(DataQualityEvent))==1
        assert db.scalar(select(func.count()).select_from(SignalScan))==0
        result=collection_evidence(db,now,None)['sessions'][0]
        assert result['observed_minutes']==0
        assert result['input_coverage']==[
            {'symbol':'SPY','valid_minutes':1,'expected_minutes':1},
            {'symbol':'USO','valid_minutes':0,'expected_minutes':1}]


def test_late_restart_does_not_manufacture_final_bar_observations():
    with database()() as db:
        record_close(db,object(),datetime(2026,10,30,17,tzinfo=NY))
        assert not db.scalar(select(DataQualityEvent.id))


def test_readiness_reports_feed_failures_without_writing_or_activating(monkeypatch):
    now=datetime(2026,10,30,11,tzinfo=NY)
    monkeypatch.setattr(readiness,'get_settings',lambda:SimpleNamespace(
        paper_only=True,parlay_background_scanner_enabled=True))
    class Feed:
        def data_quality_status(self):return {'connected':False,'stale_symbols':['USO']}
    with database()() as db:
        db.add(ScannerRuntime(key='parlay',status='healthy',heartbeat_at=now,
            operator_hold=False,last_evaluation_candle_at=now-timedelta(minutes=1)))
        db.commit();before=db.connection().connection.driver_connection.total_changes
        result=readiness.snapshot(db,Feed(),now=now)
        assert result['status']=='ATTENTION'
        assert 'Candle stream disconnected' in result['problems']
        assert 'Required symbol candles are stale' in result['problems']
        assert db.connection().connection.driver_connection.total_changes==before


def test_closed_hours_are_sleeping_and_do_not_claim_stream_failure(monkeypatch):
    monkeypatch.setattr(readiness,'get_settings',lambda:SimpleNamespace(
        paper_only=True,parlay_background_scanner_enabled=True))
    class Feed:
        def data_quality_status(self):return {'connected':False,'stale_symbols':[]}
    with database()() as db:
        result=readiness.snapshot(db,Feed(),now=datetime(2026,10,30,18,tzinfo=NY))
        assert result['status']=='SLEEPING' and result['problems']==[]
