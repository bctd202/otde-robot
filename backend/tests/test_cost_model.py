from datetime import timedelta
import json

import pytest
from sqlalchemy import select

from app.db.models import ForwardPaperAccount, ForwardPaperPosition
from app.services import forward_account
from app.services.cost_model import (CostPolicy, from_policy, entry_premium_cents,
    exit_premium_cents, quote_net_cents)
from app.services.performance import execution_cost_analysis
from test_forward_account import Quotes, START, candidate
from test_performance import database


@pytest.mark.parametrize('legacy',[False,True])
def test_identical_quotes_and_costs_reconcile_cash_ledger_and_cost_overlay(monkeypatch,legacy):
    monkeypatch.setattr(forward_account,'TRIAL_START',START-timedelta(minutes=1))
    with database()() as db:
        account=forward_account.ensure_account(db,START-timedelta(seconds=1))
        if legacy:
            old=dict(account.policy)
            old['slippage_premium_cents']=old.pop('slippage_cents_per_share')
            account.policy=old
        frozen=json.dumps(account.policy,sort_keys=True)
        trade=candidate(db)
        forward_account.advance_account(db,Quotes(START),now=START)
        forward_account.advance_account(db,Quotes(START+timedelta(seconds=2)),now=START+timedelta(seconds=2))
        trade.exit_reason='TARGET';trade.exit_at=START+timedelta(minutes=5)
        forward_account.advance_account(db,Quotes(trade.exit_at,bid=.75,ask=.80),now=trade.exit_at)
        later=trade.exit_at+timedelta(seconds=2)
        forward_account.advance_account(db,Quotes(later,bid=.75,ask=.80),now=later)
        position=db.scalar(select(ForwardPaperPosition))
        assert position.status=='UNSETTLED'
        report=execution_cost_analysis([trade],{trade.signal_id:{'status':'CLOSED','entry_ask':.45,
            'exit_bid':.75,'contract_multiplier':100}})
        assert position.detail['net_pnl_cents']==2600
        assert report['stress']['pnl_dollars']==position.detail['net_pnl_cents']/100
        assert report['assumptions']['round_trip_fixed_cost_dollars']==2
        assert json.dumps(db.get(ForwardPaperAccount,forward_account.KEY).policy,sort_keys=True)==frozen


@pytest.mark.parametrize('multiplier',[10,100])
def test_explicit_units_and_multiplier_prevent_hundredfold_slippage_error(multiplier):
    policy=CostPolicy()
    legacy=policy.as_dict()
    legacy['slippage_premium_cents']=legacy.pop('slippage_cents_per_share')
    assert from_policy(legacy)==from_policy(policy.as_dict())
    entry=entry_premium_cents(.45,policy,multiplier)
    sale=exit_premium_cents(.75,policy,multiplier)
    assert entry==45*multiplier+multiplier
    assert sale==75*multiplier-multiplier
    net=sale-policy.closing_cost_cents-entry-policy.opening_cost_cents
    assert quote_net_cents(.45,.75,multiplier=multiplier,round_trip_fixed_cents=200,
        slippage_cents_per_share=1)==net
    assert exit_premium_cents(0,policy,multiplier)==0


def test_conflicting_persisted_units_are_rejected_instead_of_silently_changing_costs():
    with pytest.raises(ValueError,match='Conflicting'):
        from_policy({**CostPolicy().as_dict(),'slippage_premium_cents':100})


def test_new_account_entries_wait_for_completed_underlying_evidence(monkeypatch):
    from test_result_integrity import make_candidate
    from app.services.result_model import benchmark
    monkeypatch.setattr(forward_account,'TRIAL_START',START-timedelta(minutes=1))
    with database()() as db:
        forward_account.ensure_account(db,START-timedelta(seconds=1))
        trade=candidate(db)
        trade.strategy_snapshot={**trade.strategy_snapshot,'result_model':benchmark(make_candidate(second=0))}
        trade.last_evaluated_at=START-timedelta(minutes=1)
        forward_account.advance_account(db,Quotes(START),now=START)
        later=START+timedelta(minutes=1,seconds=2)
        forward_account.advance_account(db,Quotes(later),now=later)
        p=db.scalar(select(ForwardPaperPosition))
        assert p.status=='PENDING_ENTRY' and p.detail['entry_evidence_wait']
        trade.last_evaluated_at=START
        forward_account.advance_account(db,Quotes(later+timedelta(seconds=1)),now=later+timedelta(seconds=1))
        assert p.status=='OPEN' and p.detail['entry_debit_cents']==4750
