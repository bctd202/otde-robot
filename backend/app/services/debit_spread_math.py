"""Pure two-leg selection and signed cash math. No provider calls or orders."""
import math

from app.services.cost_model import CostPolicy, cents, entry_premium_cents, exit_premium_cents


def select_hedge(long, target: float, chain):
    if not math.isfinite(target) or target <= 0:
        return None
    eligible = [q for q in chain if q.symbol == long.symbol and q.expiration == long.expiration
                and q.right == long.right and q.option_symbol != long.option_symbol
                and math.isfinite(q.strike) and q.strike > 0
                and (q.strike >= target and q.strike > long.strike if long.right == 'call'
                     else q.strike <= target and q.strike < long.strike)]
    return min(eligible, key=lambda q: (q.strike if long.right == 'call' else -q.strike,
                                       q.option_symbol)) if eligible else None


def entry_debit(long_ask: float, short_bid: float, cost: CostPolicy) -> int:
    return (entry_premium_cents(long_ask, cost, 100)-exit_premium_cents(short_bid, cost, 100)
            +2*cost.opening_cost_cents)


def liquidation(long_bid: float, short_ask: float, cost: CostPolicy) -> int:
    # Buying back the short can make this an outflow. Never clamp the package.
    return (exit_premium_cents(long_bid, cost, 100)-entry_premium_cents(short_ask, cost, 100)
            -2*cost.closing_cost_cents)


def theoretical(long, short, premium_debit: int, cost: CostPolicy) -> dict:
    width = cents(abs(long.strike-short.strike)*100)
    return {'basis': 'EXPIRY_SCENARIO_NOT_EXECUTION_GUARANTEE', 'width_cents': width,
            'premium_debit_cents': premium_debit,
            'max_profit_before_costs_cents': width-premium_debit,
            'max_loss_before_costs_cents': premium_debit,
            'modeled_round_trip_fixed_costs_cents': 2*(cost.opening_cost_cents+cost.closing_cost_cents),
            'breakeven': long.strike+(premium_debit/100 if long.right == 'call' else -premium_debit/100)}
