"""Explicitly synthetic 60-session acceptance/uncertainty fixtures, not backfills."""
from datetime import date, datetime, timedelta

from sqlalchemy import insert, select

from app.db.models import RetestEvent, RetestObservation, RetestOpportunity, RetestPosition
from app.services.market_calendar import NY
from app.services.research_session_policy import session_limits
from app.services.retest_report import summary
from app.services import retest_trials as trial
from test_retest_trials import db as db_fixture, activate, ACTIVATION

db = db_fixture


def completed_fixture(db):
    run=activate(db)
    dates=[date.fromisoformat(d) for d in run.policy['sessions']]
    for i in range(100):
        db.add(RetestOpportunity(run_key=trial.KEY,trading_date=dates[0],ticker=f'TEST{i}',
            mode='ONE_MIN_0DTE',observed_at=ACTIVATION,selected=True,frozen={'retest_setup':'SYNTHETIC'}))
    db.flush()
    opportunity=db.scalar(select(RetestOpportunity))
    # 30 independent synthetic positions per arm/cost scenario, all with quote evidence.
    for arm in trial.ARMS:
        for scenario in trial.SCENARIOS:
            for i,o in enumerate(db.scalars(select(RetestOpportunity).limit(30))):
                p=RetestPosition(opportunity_id=o.id,account_key=trial.account_key(arm,scenario),
                    arm=arm,scenario=scenario,status='CLOSED',detail={})
                db.add(p);db.flush()
                for kind in ('ENTRY_REQUEST','ENTRY_QUOTE_AVAILABLE','EXIT_REQUEST','EXIT_QUOTE_AVAILABLE','EXIT'):
                    trial.event(db,f'test:{p.id}:{kind}',ACTIVATION,kind,position=p)
    raw=RetestPosition(opportunity_id=opportunity.id,account_key=None,arm='treatment',scenario='opportunity',
                      status='CLOSED',detail={})
    db.add(raw);db.flush()
    trial.event(db,'synthetic-verification',ACTIVATION,'RETEST_VERIFICATION',position=raw,detail={'input_complete':True})
    rows=[]
    for index,day in enumerate(dates):
        opening=datetime.combine(day,datetime.min.time().replace(hour=9,minute=30),NY)
        closing=session_limits(day)['close']
        at=opening
        while at<closing:
            accounts={trial.account_key(arm,scenario):{'equity_cents':200000+(index+1)*
                (1000 if arm=='treatment' else 500)-(index+1)*(100 if scenario=='stress' else 0)}
                for arm in trial.ARMS for scenario in trial.SCENARIOS}
            rows.append({'run_key':trial.KEY,'evaluation_at':at.astimezone(closing.tzinfo),
                'observed_at':at.astimezone(closing.tzinfo)+timedelta(minutes=1),
                'detail':{'accounts':accounts,'inputs':{'SPY':True}}})
            at+=timedelta(minutes=1)
    db.execute(insert(RetestObservation),rows);db.commit()
    return session_limits(dates[-1])['close']+timedelta(seconds=1)


def test_all_preregistered_gates_and_stress_bootstrap_on_complete_synthetic_data(db):
    now=completed_fixture(db)
    result=summary(db,now=now)
    assert result['verdict']=='PASS'
    assert result['input_coverage']==100
    assert result['uncertainty']['base']['advantage_dollars']==300
    assert all(a['complete'] and a['max_drawdown_cents']==0 for a in result['accounts'])
    # A valuation gap invalidates full drawdown/return claims even when all trades closed.
    point=db.scalar(select(RetestObservation).order_by(RetestObservation.id))
    values=dict(point.detail['accounts']);values[trial.account_key('treatment','base')]={'equity_cents':None}
    point.detail={**point.detail,'accounts':values};db.commit()
    result=summary(db,now=now)
    assert result['verdict']=='INCONCLUSIVE'
    treatment=next(a for a in result['accounts'] if a['arm']=='treatment' and a['scenario']=='base')
    assert treatment['net_pnl_cents'] is None and treatment['max_drawdown_cents'] is None


def test_coverage_denominators_include_missing_quotes_and_full_outage_sessions(db):
    now=completed_fixture(db)
    events=db.scalars(select(RetestEvent).where(RetestEvent.account_key==trial.account_key('treatment','base'),
                                               RetestEvent.kind=='ENTRY_QUOTE_AVAILABLE').limit(4)).all()
    # Alter synthetic fixtures only: represent absent quote observations.
    for e in events:db.delete(e)
    db.commit()
    result=summary(db,now=now)
    assert result['verdict']=='INCONCLUSIVE'
    treatment=next(a for a in result['accounts'] if a['arm']=='treatment' and a['scenario']=='base')
    assert treatment['entry_requests']==30 and treatment['entry_quote_coverage']==26/30*100
    assert result['expected_inputs']>20000


def test_best_session_removal_and_pnl_gate_cannot_be_replaced_by_positive_point_estimate(db):
    now=completed_fixture(db)
    last=db.scalar(select(RetestObservation).order_by(RetestObservation.evaluation_at.desc()))
    values=dict(last.detail['accounts']);values[trial.account_key('treatment','stress')]={'equity_cents':199000}
    last.detail={**last.detail,'accounts':values};db.commit()
    result=summary(db,now=now)
    assert result['verdict']=='DID_NOT_MEET_CRITERIA'
    assert result['gates']['stress']['positive_net'] is False
    assert result['gates']['stress']['drawdown'] is False


def test_structured_trades_cannot_satisfy_one_minute_treatment_sample_minimum(db):
    now=completed_fixture(db)
    opportunity=db.scalar(select(RetestOpportunity).order_by(RetestOpportunity.id))
    opportunity.mode='STRUCTURED_INTRADAY'
    db.add(RetestOpportunity(run_key=trial.KEY,trading_date=opportunity.trading_date,ticker='EXTRA',
        mode='ONE_MIN_0DTE',observed_at=ACTIVATION,selected=True,frozen={'retest_setup':'SYNTHETIC'}))
    db.commit()
    result=summary(db,now=now)
    assert result['baseline_opportunities']==100
    assert result['verdict']=='INCONCLUSIVE'
    treatment=next(a for a in result['accounts'] if a['arm']=='treatment' and a['scenario']=='base')
    assert treatment['completed_trades']==30
    assert treatment['completed_one_minute_trades']==29
