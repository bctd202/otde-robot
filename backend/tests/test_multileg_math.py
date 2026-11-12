"""Independent payoff vectors; this lab is not wired into any account or signal."""
from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal
import math
from statistics import NormalDist

import pytest

from app.services.cost_model import CostPolicy
from app.services.multileg_math import Leg, Position, Interval, analyze, leg_cash, model_profit_probability

EXPIRY=date(2026,12,18)


def leg(right, strike, quantity):
    return Leg('SPY',EXPIRY,right,Decimal(str(strike)),quantity)


@pytest.mark.parametrize('legs,premium,profit,loss,roots',[
    ([('call',600,1),('call',605,-1)],-28000,220,280,['602.8']),
    ([('put',595,1),('put',600,-1)],18000,180,320,['598.2']),
    ([('put',570,1),('put',575,-1),('call',625,-1),('call',635,1)],20000,200,800,['573','627']),
    ([('put',575,-1),('call',625,-1)],41000,410,None,['570.9','629.1']),
    ([('put',600,1)],-85000,59150,850,['591.5']),
    ([('call',600,1),('call',610,-2)],2000,1020,None,['620.2']),
    ([('put',600,1),('put',590,-2)],3000,1030,57970,['579.7']),
    ([('put',585,-1),('call',610,-1),('call',612,1)],23800,238,58262,['582.62']),
    ([('put',575,-1)],21000,210,57290,['572.9']),
    ([('call',600,-1)],10000,100,None,['601']),
    ([('put',600,1),('call',600,1)],-200000,None,2000,['580','620']),
    ([('put',590,1),('call',610,1)],-100000,None,1000,['580','620']),
    ([('put',600,-1),('call',600,-1)],200000,2000,None,['580','620']),
])
def test_cash_sized_expiry_vectors(legs,premium,profit,loss,roots):
    position=Position(tuple(leg(*v) for v in legs),premium)
    result=analyze(position)
    assert result.max_profit_dollars==profit
    assert result.max_loss_dollars==loss
    assert result.breakevens==tuple(Decimal(v) for v in roots)
    assert all(position.payoff(root)==0 for root in result.breakevens)
    assert result.basis=='THEORETICAL_EXPIRY_BEFORE_FEES_NOT_ACCOUNT_RETURN'


def test_short_sign_is_applied_once():
    short=Position((leg('call',600,-1),),10000)
    assert short.payoff(610)==-900


def test_normalized_shape_keeps_actual_economic_size_and_cash():
    position=Position((leg('call',600,2),leg('call',605,-2)),-56000)
    assert position.shape.scale==2
    assert [v.quantity for v in position.shape.legs]==[1,-1]
    assert [v.quantity for v in position.legs]==[2,-2]
    assert position.contracts==4
    assert position.payoff(605)==440
    assert analyze(position).max_loss_dollars==560
    with pytest.raises(FrozenInstanceError):
        position.opening_premium_cents=0


def test_ratio_is_two_legs_six_contracts_at_double_size():
    position=Position((leg('call',600,2),leg('call',610,-4)),4000)
    assert len(position.legs)==2 and position.contracts==6
    assert position.shape.scale==2
    assert analyze(position).max_profit_dollars==2040


def test_duplicate_netting_preserves_size_without_invented_fills():
    position=Position((leg('call',600,2),leg('call',600,-1),leg('call',605,-1)),-28000)
    assert position.contracts==2
    assert position.payoff(605)==220
    with pytest.raises(ValueError):
        Position((leg('call',600,1),leg('call',600,-1)),0)


def test_zero_payoff_regions_are_not_reported_as_single_breakevens():
    full_width=Position((leg('call',600,1),leg('call',605,-1)),-50000)
    result=analyze(full_width)
    assert result.breakevens==()
    assert result.zero_payoff_intervals==(Interval(Decimal(605),None),)
    assert result.profit_intervals==()
    no_debit=Position(full_width.legs,0)
    assert analyze(no_debit).zero_payoff_intervals==(Interval(Decimal(0),Decimal(600)),)
    assert no_debit.payoff(600)==0
    assert model_profit_probability(no_debit,600,volatility_fraction=0,years=1).probability==0


def test_tangent_zero_does_not_create_a_profitable_interval():
    position=Position((leg('put',600,-1),leg('call',600,-1)),0)
    assert analyze(position).breakevens==(Decimal(600),)
    assert analyze(position).profit_intervals==()


@pytest.mark.parametrize('right,strike,qty',[
    ('call','NaN',1),('put','Infinity',1),('call',0,1),('call',600,True),
    ('call',600,0),('call',600,1.5),('stock',600,1),
])
def test_invalid_leg_rejected(right,strike,qty):
    with pytest.raises(ValueError):
        leg(right,strike,qty)


def test_diagonal_mixed_underlying_and_adjusted_multiplier_are_not_modeled():
    original=leg('call',600,1)
    for other in (replace(original,expiration=date(2027,1,15)),replace(original,underlying='QQQ')):
        with pytest.raises(ValueError):
            Position((original,other),-10000)
    with pytest.raises(ValueError):
        replace(original,multiplier=10)
    with pytest.raises(ValueError):
        Position((original,),True)
    with pytest.raises(ValueError):
        Position((original,),-10000).payoff(-1)


def test_long_vol_probability_is_outside_breakevens_and_short_is_inside():
    long=Position((leg('put',600,1),leg('call',600,1)),-200000)
    short=Position((leg('put',600,-1),leg('call',600,-1)),200000)
    sigma=.25;t=30/365
    distribution=NormalDist(math.log(600)-.5*sigma*sigma*t,sigma*math.sqrt(t))
    outside=distribution.cdf(math.log(580))+1-distribution.cdf(math.log(620))
    l=model_profit_probability(long,600,volatility_fraction=sigma,years=t)
    s=model_profit_probability(short,600,volatility_fraction=sigma,years=t)
    assert l.probability==pytest.approx(outside)
    assert l.probability+s.probability==pytest.approx(1)
    assert l.basis=='LOGNORMAL_EXPIRY_MODEL_NOT_OBSERVED_WIN_RATE'


def test_degenerate_distribution_carry_and_strict_profit():
    position=Position((leg('call',600,1),),0)
    assert model_profit_probability(position,600,volatility_fraction=.2,years=0).probability==0
    assert model_profit_probability(position,601,volatility_fraction=.2,years=0).probability==1
    assert model_profit_probability(position,600,volatility_fraction=0,years=1,risk_free_rate=.05).probability==1
    assert model_profit_probability(position,600,volatility_fraction=0,years=1,dividend_yield=.05).probability==0


@pytest.mark.parametrize('spot,sigma,t',[(0,.2,1),(600,-1,1),(600,.2,-1),(600,float('nan'),1)])
def test_invalid_probability_input(spot,sigma,t):
    with pytest.raises(ValueError):
        model_profit_probability(Position((leg('call',600,1),),-10000),spot,
            volatility_fraction=sigma,years=t)


def test_signed_cash_worked_example_is_82_dollars_after_costs():
    c=CostPolicy()
    opening=leg_cash(-1,2,2.1,c,opening=True)+leg_cash(1,1,1.1,c,opening=True)
    closing=leg_cash(1,.1,.1,c,opening=False)+leg_cash(-1,.1,.1,c,opening=False)
    assert opening==8500
    assert closing==-300
    assert opening+closing==8200
    assert leg_cash(-2,2,2.1,c,opening=True)==2*19750


def test_short_buyback_outflow_and_per_contract_rounding_are_preserved():
    c=CostPolicy()
    assert leg_cash(1,0,0,c,opening=False)+leg_cash(-1,3,3,c,opening=False)==-30200
    no_cost=CostPolicy(0,0,0,0)
    assert leg_cash(2,.00005,.00005,no_cost,opening=True)==-2
    with pytest.raises(ValueError):
        leg_cash(1,2,1,c,opening=True)
    with pytest.raises(ValueError):
        leg_cash(-1,1,1,CostPolicy(-1,0,0,0),opening=False)
