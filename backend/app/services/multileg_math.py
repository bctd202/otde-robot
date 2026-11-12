"""Unwired research arithmetic: expiry scenarios and signed cash, never fills.

No strategy, provider, account, database, clock or activation dependency. Original
quantities price the position; GCD normalization is a separate shape descriptor.
USD values use Decimal. Cash quotes use the unchanged per-contract cost helpers.
"""
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import reduce
import math
from statistics import NormalDist
from typing import Literal

from app.services.cost_model import CostPolicy, entry_premium_cents, exit_premium_cents

Number = Decimal | str | int | float


def decimal(value: Number) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('Finite decimal required') from None
    if not result.is_finite():
        raise ValueError('Finite decimal required')
    return result


@dataclass(frozen=True)
class Leg:
    underlying: str
    expiration: date
    right: Literal['call', 'put']
    strike: Decimal
    quantity: int
    multiplier: int = 100

    def __post_init__(self):
        object.__setattr__(self, 'strike', decimal(self.strike))
        if (not self.underlying or self.underlying != self.underlying.strip().upper()
                or type(self.expiration) is not date or self.right not in ('call', 'put')
                or self.strike <= 0 or type(self.quantity) is not int or not self.quantity
                or type(self.multiplier) is not int or self.multiplier != 100):
            raise ValueError('Standard equity option identity and signed integer quantity required')


@dataclass(frozen=True)
class Shape:
    scale: int
    legs: tuple[Leg, ...]


@dataclass(frozen=True)
class Position:
    legs: tuple[Leg, ...]
    # Total opening PREMIUM cash in cents: positive credit, negative debit.
    # Fees, assignment and execution are excluded from this expiry scenario.
    opening_premium_cents: int

    def __post_init__(self):
        if not self.legs or type(self.opening_premium_cents) is not int:
            raise ValueError('Legs and signed integer-cent premium required')
        identities = {(leg.underlying, leg.expiration, leg.multiplier) for leg in self.legs}
        if len(identities) != 1:
            raise ValueError('One underlying, expiration and multiplier required; diagonals unsupported')
        merged: dict[tuple[str, Decimal], Leg] = {}
        for leg in self.legs:
            key = leg.right, leg.strike
            quantity = leg.quantity + (merged[key].quantity if key in merged else 0)
            if quantity:
                merged[key] = replace(leg, quantity=quantity)
            else:
                merged.pop(key)
        if not merged or len(merged) > 4:
            raise ValueError('One to four distinct net option legs required')
        object.__setattr__(self, 'legs', tuple(merged[key] for key in sorted(merged)))

    @property
    def contracts(self) -> int:
        return sum(abs(leg.quantity) for leg in self.legs)

    @property
    def shape(self) -> Shape:
        scale = reduce(math.gcd, (abs(leg.quantity) for leg in self.legs))
        return Shape(scale, tuple(replace(leg, quantity=leg.quantity // scale) for leg in self.legs))

    def payoff(self, underlying_price: Number) -> Decimal:
        """Signed hypothetical expiry P/L in USD, before fees; no cash booking."""
        price = decimal(underlying_price)
        if price < 0:
            raise ValueError('Underlying cannot be negative')
        return Decimal(self.opening_premium_cents) / 100 + sum(
            (max(Decimal(0), price-leg.strike if leg.right == 'call' else leg.strike-price)
             * leg.quantity * leg.multiplier for leg in self.legs), Decimal(0))


@dataclass(frozen=True)
class Interval:
    lower: Decimal
    upper: Decimal | None  # None means +infinity, never a fabricated price.


@dataclass(frozen=True)
class ExpiryAnalysis:
    max_profit_dollars: Decimal | None  # None = unbounded profit.
    max_loss_dollars: Decimal | None  # Nonnegative magnitude; None = unbounded loss.
    breakevens: tuple[Decimal, ...]
    zero_payoff_intervals: tuple[Interval, ...]
    profit_intervals: tuple[Interval, ...]
    basis: str = 'THEORETICAL_EXPIRY_BEFORE_FEES_NOT_ACCOUNT_RETURN'


def _merge(intervals: list[Interval], position: Position, *, zero=False) -> tuple[Interval, ...]:
    result: list[Interval] = []
    for interval in intervals:
        if (result and result[-1].upper == interval.lower
                and (zero or position.payoff(interval.lower) > 0)):
            result[-1] = Interval(result[-1].lower, interval.upper)
        else:
            result.append(interval)
    return tuple(result)


def analyze(position: Position) -> ExpiryAnalysis:
    nodes = sorted({Decimal(0), *(leg.strike for leg in position.legs)})
    values = [position.payoff(node) for node in nodes]
    slope = sum(leg.quantity * leg.multiplier for leg in position.legs if leg.right == 'call')
    roots = {node for node, value in zip(nodes, values) if value == 0}
    zeros: list[Interval] = []
    for a, b, fa, fb in zip(nodes, nodes[1:], values, values[1:]):
        if fa == fb == 0:
            zeros.append(Interval(a, b))
        elif fa * fb < 0:
            roots.add(a-fa*(b-a)/(fb-fa))
    if slope:
        root = nodes[-1]-values[-1]/slope
        if root >= nodes[-1]:
            roots.add(root)
    elif values[-1] == 0:
        zeros.append(Interval(nodes[-1], None))
    zero_intervals = _merge(zeros, position, zero=True)
    isolated_roots = tuple(sorted(root for root in roots if not any(
        interval.lower <= root and (interval.upper is None or root <= interval.upper)
        for interval in zero_intervals)))
    knots = sorted(set(nodes) | roots)
    positive = [Interval(a, b) for a, b in zip(knots, knots[1:]) if position.payoff((a+b)/2) > 0]
    if position.payoff(knots[-1]+1) > 0:
        positive.append(Interval(knots[-1], None))
    return ExpiryAnalysis(None if slope > 0 else max(Decimal(0), max(values)),
        None if slope < 0 else max(Decimal(0), -min(values)), isolated_roots,
        zero_intervals, _merge(positive, position))


@dataclass(frozen=True)
class ModelProbability:
    probability: float
    volatility_fraction: float
    years: float
    risk_free_rate: float
    dividend_yield: float
    basis: str = 'LOGNORMAL_EXPIRY_MODEL_NOT_OBSERVED_WIN_RATE'


def model_profit_probability(position: Position, spot: Number, *, volatility_fraction: float,
                             years: float, risk_free_rate: float = 0, dividend_yield: float = 0) -> ModelProbability:
    """Integrate positive payoff intervals, including outside long-vol breakevens.

    Risk-neutral lognormal scenario with explicit constant carry/volatility; no
    inference that its probability is a real-world win rate or evidence of edge.
    Exactly zero payoff is not a win. Point masses are evaluated directly.
    """
    price = float(decimal(spot))
    sigma, t, r, q = volatility_fraction, years, risk_free_rate, dividend_yield
    if not all(math.isfinite(v) for v in (price, sigma, t, r, q)) or price <= 0 or sigma < 0 or t < 0:
        raise ValueError('Positive spot and finite nonnegative volatility/time required')
    if t == 0 or sigma == 0:
        forward = decimal(spot) if t == 0 or r == q else decimal(price*math.exp((r-q)*t))
        probability = float(position.payoff(forward) > 0)
    else:
        deviation = sigma*math.sqrt(t)
        center = math.log(price)+(r-q-0.5*sigma*sigma)*t
        if not math.isfinite(center) or not math.isfinite(deviation):
            raise ValueError('Finite derived distribution required')
        def cdf(bound: Decimal | None) -> float:
            if bound is None:
                return 1.0
            return NormalDist().cdf((math.log(float(bound))-center)/deviation) if bound > 0 else 0.0
        probability = sum(cdf(interval.upper)-cdf(interval.lower) for interval in analyze(position).profit_intervals)
    return ModelProbability(min(1.0, max(0.0, probability)), sigma, t, r, q)


def leg_cash(quantity: int, bid: float, ask: float, cost: CostPolicy, *, opening: bool) -> int:
    """Signed arithmetic only, not quote validation or an executable-fill claim.

    Each contract is rounded using existing helpers before multiplying quantity.
    Opening/closing fees apply on every contract, including short buybacks.
    """
    if (type(quantity) is not int or quantity == 0 or not all(math.isfinite(v) and v >= 0 for v in (bid, ask))
            or bid > ask or any(type(v) is not int or v < 0 for v in cost.as_dict().values())):
        raise ValueError('Signed quantity, noncrossed prices and nonnegative integer costs required')
    buy = (quantity > 0) == opening
    premium = -entry_premium_cents(ask, cost) if buy else exit_premium_cents(bid, cost)
    fees = cost.opening_cost_cents if opening else cost.closing_cost_cents
    return abs(quantity)*(premium-fees)
