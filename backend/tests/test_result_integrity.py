from datetime import timedelta, timezone
import json

import pytest
from sqlalchemy import select

from app.db.models import SignalPerformance
from app.services import result_model
from app.services.performance import track_candidates, evaluate_open_signals, update_outcome
from test_performance import database, shadow_candidate, row, CandleProvider, candle, SHADOW_START


@pytest.mark.parametrize('direction,quote,trigger,stop,target',[
    ('call',100.4,100,99,101.5),('put',99.6,100,101,98.5)])
def test_new_benchmark_uses_observed_quote_and_preserves_original_plan(direction,quote,trigger,stop,target):
    with database()() as db:
        old=row(signal_id='historical');old.exit_reason='TARGET';old.result_r=1.5
        db.add(old);db.commit()
        before=json.dumps({c.name:getattr(old,c.name) for c in old.__table__.columns},default=str,sort_keys=True)
        c=shadow_candidate();c.direction=direction;c.underlying_price=quote
        c.underlying_trigger=trigger;c.underlying_invalidation=stop;c.first_underlying_target=target
        track_candidates(db,[c])
        new=db.scalar(select(SignalPerformance).where(SignalPerformance.signal_id!='historical'))
        assert new.entry_price==quote and new.stop_price==stop and new.target_price==target
        assert new.strategy_snapshot['result_model']['underlying_trigger']==trigger
        update_outcome(new,max(quote,target),min(quote,target),target,SHADOW_START+timedelta(minutes=2))
        assert new.result_r==pytest.approx(.7857)
        assert new.result_r<old.result_r
        assert json.dumps({c.name:getattr(old,c.name) for c in old.__table__.columns},default=str,sort_keys=True)==before


def make_candidate(second=4):
    c=shadow_candidate();c.generated_at=SHADOW_START+timedelta(seconds=second)
    c.input_evidence={'evaluation_at':(SHADOW_START-timedelta(minutes=1)).isoformat()}
    return c


def test_partial_entry_minute_close_proves_stop_without_backdating_exit():
    with database()() as db:
        c=make_candidate();track_candidates(db,[c])
        trade=db.scalar(select(SignalPerformance))
        assert trade.last_evaluated_at.replace(tzinfo=timezone.utc)==SHADOW_START-timedelta(minutes=1)
        bars=[candle(SHADOW_START,100.2,98.8,98.9),candle(SHADOW_START+timedelta(minutes=1),100.3,99.8,100.1)]
        provider=CandleProvider(bars,SHADOW_START+timedelta(minutes=3))
        evaluate_open_signals(db,provider)
        assert trade.exit_reason=='STOP' and trade.result_r==-1
        assert trade.exit_at==SHADOW_START+timedelta(minutes=1)
        assert trade.exit_at>result_model.utc(trade.triggered_at) and trade.duration_minutes==0
        assert trade.last_evaluated_at==SHADOW_START
        previous=(trade.exit_at,trade.result_r,trade.mfe_r)
        evaluate_open_signals(db,provider)
        assert previous==(trade.exit_at,trade.result_r,trade.mfe_r)


@pytest.mark.parametrize('high,low,close',[(100.2,98.8,100.1),(101.6,99.5,100.2),(102,98,101.8)])
def test_pre_entry_or_both_boundary_touches_stay_unknown(high,low,close):
    with database()() as db:
        track_candidates(db,[make_candidate()])
        trade=db.scalar(select(SignalPerformance))
        evaluate_open_signals(db,CandleProvider([candle(SHADOW_START,high,low,close)],SHADOW_START+timedelta(minutes=2)))
        assert trade.exit_reason=='DATA_GAP' and trade.result_r is None and trade.exit_at is None
        assert trade.condition_snapshot['analytics_data_quality']['reason']=='ENTRY_MINUTE_ORDER_UNKNOWN'


def test_entry_minute_excursion_uses_close_not_pre_entry_extremes():
    with database()() as db:
        track_candidates(db,[make_candidate()])
        trade=db.scalar(select(SignalPerformance))
        evaluate_open_signals(db,CandleProvider([candle(SHADOW_START,101.4,99.1,100.2)],SHADOW_START+timedelta(minutes=1,seconds=5)))
        assert trade.exit_reason=='OPEN'
        assert trade.mfe_r==.2 and trade.mae_r==0


def test_missing_entry_minute_is_not_silently_skipped():
    with database()() as db:
        track_candidates(db,[make_candidate()])
        trade=db.scalar(select(SignalPerformance))
        evaluate_open_signals(db,CandleProvider([candle(SHADOW_START+timedelta(minutes=1),102,99.5,101.6)],SHADOW_START+timedelta(minutes=3)))
        assert trade.exit_reason=='DATA_GAP' and trade.result_r is None
        assert trade.condition_snapshot['analytics_data_quality']['reason']=='MISSING_POST_ENTRY_CANDLE'


def test_exact_minute_entry_evaluates_entire_entry_bar():
    with database()() as db:
        track_candidates(db,[make_candidate(second=0)])
        trade=db.scalar(select(SignalPerformance))
        evaluate_open_signals(db,CandleProvider([candle(SHADOW_START,100.2,98.8,100.1)],SHADOW_START+timedelta(minutes=2)))
        assert trade.exit_reason=='STOP' and trade.result_r==-1


@pytest.mark.parametrize('change', ['invalid_plan','late_quote','bad_boundary'])
def test_unscorable_benchmarks_do_not_create_fake_resolved_R(change):
    c=make_candidate()
    if change=='invalid_plan':c.underlying_price=102
    elif change=='late_quote':c.generated_at+=timedelta(minutes=2)
    else:c.input_evidence={'evaluation_at':'invalid'}
    with database()() as db:
        track_candidates(db,[c])
        trade=db.scalar(select(SignalPerformance))
        assert trade.exit_reason=='DATA_GAP' and trade.result_r is None
        assert result_model.definition(trade)['quality_error']


def test_legacy_open_row_keeps_original_cursor_and_clock():
    with database()() as db:
        trade=row();trade.triggered_at+=timedelta(seconds=4);trade.last_evaluated_at=trade.triggered_at
        db.add(trade);db.commit()
        evaluate_open_signals(db,CandleProvider([candle(SHADOW_START,100.2,98.8,98.9),
            candle(SHADOW_START+timedelta(minutes=1),101.5,99.5,101.5)],SHADOW_START+timedelta(minutes=3)))
        assert trade.exit_reason=='TARGET' and trade.result_r==1.5
        assert result_model.definition(trade) is None


def test_a_better_post_confirmation_quote_can_increase_R_without_changing_the_plan():
    with database()() as db:
        c=make_candidate(second=0);c.underlying_price=99.8
        track_candidates(db,[c]);trade=db.scalar(select(SignalPerformance))
        update_outcome(trade,101.5,100,101.5,SHADOW_START+timedelta(minutes=2))
        assert trade.entry_price==99.8 and trade.result_r==2.125
        assert trade.strategy_snapshot['result_model']['underlying_trigger']==100


def test_measurement_cohorts_are_separate_and_reads_preserve_old_R():
    from app.services.performance import measurement_integrity
    with database()() as db:
        old=row(signal_id='old');old.result_r=1.5;old.exit_reason='TARGET'
        db.add(old);db.commit()
        track_candidates(db,[make_candidate(second=0)])
        new=db.scalar(select(SignalPerformance).where(SignalPerformance.signal_id!='old'))
        update_outcome(new,101.5,100.2,101.5,SHADOW_START+timedelta(minutes=1))
        result=measurement_integrity([old,new])
        assert result['mixed_models'] and len(result['cohorts'])==2
        assert old.result_r==1.5 and result['historical_records_changed'] is False


def test_invalid_first_buy_still_owns_ticker_day_instead_of_being_replaced_by_later_winner():
    from app.services.performance import deduplicate_positions, analytics_exclusion_reason
    with database()() as db:
        first=make_candidate(second=0);first.underlying_price=first.underlying_invalidation
        track_candidates(db,[first])
        second=make_candidate(second=0);second.lifecycle_id='later-valid'
        second.generated_at+=timedelta(minutes=1)
        second.input_evidence={'evaluation_at':SHADOW_START.isoformat()}
        track_candidates(db,[second])
        selected=deduplicate_positions(list(db.scalars(select(SignalPerformance))))
        assert len(selected)==1 and selected[0].entry_price==first.underlying_price
        assert analytics_exclusion_reason(selected[0])=='ZERO_RISK' and selected[0].result_r is None


def test_new_partial_entry_minute_on_short_session_uses_exchange_cutoff():
    from datetime import datetime
    from app.services.market_calendar import NY
    with database()() as db:
        c=make_candidate(second=0)
        c.generated_at=datetime(2026,11,27,12,44,tzinfo=NY)
        c.input_evidence={'evaluation_at':(c.generated_at-timedelta(minutes=1)).isoformat()}
        track_candidates(db,[c]);trade=db.scalar(select(SignalPerformance))
        start=c.generated_at
        candles=[candle(start,100.2,99.8,100.1),candle(start+timedelta(minutes=1),100.3,99.8,100.2)]
        evaluate_open_signals(db,CandleProvider(candles,start+timedelta(minutes=3)))
        assert trade.exit_reason=='TIMED_EXIT'
        assert trade.exit_at==result_model.utc(start+timedelta(minutes=2))
