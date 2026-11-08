from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db.models import SignalPerformance
from app.schemas.market import CandleOut, OptionContractOut
from app.services import backtest
from app.services.market_calendar import NY
from app.services.parlay import UnderlyingEvaluation
from app.services.one_minute_gate import evaluate
from app.services.performance import analytics_exclusion_reason, metrics
from app.services.result_model import utc
from test_performance import database

DAY=date(2026,11,2)


def bars(day=DAY, n=10):
    start=datetime.combine(day,datetime.min.time().replace(hour=9,minute=30),NY)
    return [CandleOut(symbol='SPY',timeframe='1m',timestamp=start+timedelta(minutes=i),
        open=100.4,high=100.6,low=99.8,close=100.5,volume=1000) for i in range(n)]


def contract(at):
    day=at.astimezone(NY).date()
    return OptionContractOut(symbol='SPY',option_symbol=f'SPY{day:%y%m%d}C00100000',expiration=day,
        strike=100,right='call',bid=.48,ask=.50,last=.49,volume=1500,open_interest=1200,
        timestamp=at,bid_timestamp=at,ask_timestamp=at,provider='tastytrade',data_mode='live')


class History:
    def __init__(self,rows):self.rows=rows
    def historical_candles(self,*_):return self.rows
    def option_chain(self,*_):raise AssertionError('Current option chains must never enter replay')


class ArchivedHistory(History):
    def __init__(self,rows,*,change=None):super().__init__(rows);self.change=change
    def historical_option_chain(self,symbol,at):return [contract(at).model_copy(update=self.change or {})]


@pytest.fixture
def setup(monkeypatch):
    value=UnderlyingEvaluation('call',5,['synthetic completed-bar checks'],100,99,101.5,True,.2)
    monkeypatch.setattr(backtest,'replay_evaluation',lambda *_:value)
    return value


def test_missing_historical_options_cannot_manufacture_live_BUYs(setup):
    with database()() as db:
        run=backtest.run_backtest(db,History(bars()),DAY,DAY,['SPY'])
        trade=db.scalar(select(SignalPerformance))
        assert trade.backend_status=='UNDERLYING_ONLY' and trade.option_snapshot is None
        assert analytics_exclusion_reason(trade)=='UNVERIFIED_HISTORICAL_OPTION_GATE'
        assert metrics([trade])['resolved_signals']==0
        assert run.strategy_snapshot['evidence_mode']=='UNDERLYING_ONLY'
        assert any('not verified live BUYs' in warning for warning in run.warnings)


def test_evidenced_replay_uses_full_shared_score_next_bar_open_and_entry_bar_stop(setup):
    rows=bars();rows[8]=rows[8].model_copy(update={'low':98.8,'close':99.0})
    with database()() as db:
        run=backtest.run_backtest(db,ArchivedHistory(rows),DAY,DAY,['SPY'])
        trade=db.scalar(select(SignalPerformance))
        gate=evaluate(setup,contract(rows[8].timestamp))
        assert trade.backend_status=='BUY' and trade.score==round(gate.score,1)
        assert trade.entry_price==rows[8].open>setup.trigger
        assert trade.stop_price==setup.stop and trade.target_price==setup.target
        assert trade.exit_reason=='STOP' and trade.result_r==-1
        assert utc(trade.exit_at)==utc(rows[8].timestamp)+timedelta(minutes=1)
        assert utc(trade.last_evaluated_at)==utc(rows[8].timestamp)
        assert run.strategy_snapshot['diagnostics']['verified_buy_entries']==1


@pytest.mark.parametrize('failure',['extended','score','liquidity','premium'])
def test_live_non_buy_gates_never_produce_replay_BUY_rows(monkeypatch,setup,failure):
    value=setup;change={}
    if failure=='extended':value=UnderlyingEvaluation('call',6,[],100,99,101.5,True,1.36)
    elif failure=='score':value=UnderlyingEvaluation('call',3,[],100,99,101.5,True,.2)
    elif failure=='liquidity':change={'volume':100,'open_interest':100}
    else:change={'ask':.65,'last':.49,'bid':.55}
    monkeypatch.setattr(backtest,'replay_evaluation',lambda *_:value)
    with database()() as db:
        run=backtest.run_backtest(db,ArchivedHistory(bars(),change=change),DAY,DAY,['SPY'])
        assert list(db.scalars(select(SignalPerformance)))==[]
        assert run.strategy_snapshot['diagnostics']['rejected_live_gate']>0


def test_sessions_are_isolated_and_next_day_open_cannot_fill_prior_day_setup(monkeypatch,setup):
    recorded=[]
    def evaluate_prefix(prefix,price):recorded.append(prefix);return setup
    monkeypatch.setattr(backtest,'replay_evaluation',evaluate_prefix)
    first=bars(n=8);second=bars(DAY+timedelta(days=1))
    with database()() as db:
        backtest.run_backtest(db,ArchivedHistory(first+second),DAY,DAY+timedelta(days=1),['SPY'])
        trade=db.scalar(select(SignalPerformance))
        assert trade.trading_date==DAY+timedelta(days=1)
        assert all(len({b.timestamp.astimezone(NY).date() for b in prefix})==1 for prefix in recorded)
        assert all(prefix[0].timestamp.astimezone(NY).time()==datetime.min.time().replace(hour=9,minute=30) for prefix in recorded)


def test_missing_entry_bar_is_not_replaced_by_later_bar_or_last_close(setup):
    rows=bars();rows.pop(8)
    with database()() as db:
        run=backtest.run_backtest(db,ArchivedHistory(rows),DAY,DAY,['SPY'])
        assert list(db.scalars(select(SignalPerformance)))==[]
        assert run.strategy_snapshot['diagnostics']['input_gaps']>0


def test_future_archived_option_quotes_remain_unavailable(setup):
    class FutureHistory(ArchivedHistory):
        def historical_option_chain(self,symbol,at):return [contract(at+timedelta(seconds=1))]
    with database()() as db:
        backtest.run_backtest(db,FutureHistory(bars()),DAY,DAY,['SPY'])
        assert db.scalar(select(SignalPerformance)).backend_status=='UNDERLYING_ONLY'


def test_entry_cutoff_and_short_session_do_not_admit_late_entries(monkeypatch,setup):
    day=date(2026,11,27);rows=bars(day,n=210)
    monkeypatch.setattr(backtest,'replay_evaluation',lambda prefix,_:
        setup if prefix[-1].timestamp.astimezone(NY).hour>=12 and prefix[-1].timestamp.minute>=45
        else SimpleNamespace(direction=None,confirmed=False))
    with database()() as db:
        backtest.run_backtest(db,ArchivedHistory(rows),day,day,['SPY'])
        assert list(db.scalars(select(SignalPerformance)))==[]
