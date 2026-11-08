"""Integer-cent paper costs shared by execution and read-only comparisons.

The frozen cash policy remains authoritative. Old policy keys are read without
rewriting them. One premium cent per share is $1 for a 100-share contract.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import math
from typing import Mapping

CONTRACT_MULTIPLIER = 100
OPENING_COMMISSION_CENTS = 100
CLOSING_COMMISSION_CENTS = 0
FEE_ALLOWANCE_PER_SIDE_CENTS = 50
SLIPPAGE_CENTS_PER_SHARE = 1
DEFAULT_ROUND_TRIP_COMMISSION = (OPENING_COMMISSION_CENTS+CLOSING_COMMISSION_CENTS)/100
DEFAULT_ROUND_TRIP_FEES = 2*FEE_ALLOWANCE_PER_SIDE_CENTS/100
DEFAULT_SLIPPAGE_PER_SHARE = SLIPPAGE_CENTS_PER_SHARE/100


def cents(value: float) -> int:
    if not math.isfinite(value):
        raise ValueError("Non-finite monetary amount")
    return int((Decimal(str(value))*100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class CostPolicy:
    opening_commission_cents: int = OPENING_COMMISSION_CENTS
    closing_commission_cents: int = CLOSING_COMMISSION_CENTS
    fee_allowance_per_side_cents: int = FEE_ALLOWANCE_PER_SIDE_CENTS
    slippage_cents_per_share: int = SLIPPAGE_CENTS_PER_SHARE

    @property
    def opening_cost_cents(self) -> int:
        return self.opening_commission_cents+self.fee_allowance_per_side_cents

    @property
    def closing_cost_cents(self) -> int:
        return self.closing_commission_cents+self.fee_allowance_per_side_cents

    def as_dict(self) -> dict[str, int]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def from_policy(policy: Mapping) -> CostPolicy:
    """Compatibility adapter; frozen historical dictionaries are never mutated."""
    legacy = policy.get("slippage_premium_cents")
    value = policy.get("slippage_cents_per_share", legacy)
    if value is None:
        raise ValueError("Frozen slippage policy missing")
    if legacy is not None and legacy != value:
        raise ValueError("Conflicting old and new slippage units")
    fields = {k: policy[k] for k in ("opening_commission_cents", "closing_commission_cents",
                                  "fee_allowance_per_side_cents")}
    fields["slippage_cents_per_share"] = value
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in fields.values()):
        raise ValueError("Paper costs must be nonnegative integer cents")
    return CostPolicy(**fields)


def premium_cents(price: float, multiplier: int = CONTRACT_MULTIPLIER) -> int:
    if multiplier <= 0 or not math.isfinite(price) or price < 0:
        raise ValueError("Invalid quote or contract multiplier")
    return cents(price*multiplier)


def entry_premium_cents(ask: float, cost: CostPolicy, multiplier: int = CONTRACT_MULTIPLIER) -> int:
    return premium_cents(ask, multiplier)+cost.slippage_cents_per_share*multiplier


def exit_premium_cents(bid: float, cost: CostPolicy, multiplier: int = CONTRACT_MULTIPLIER) -> int:
    return max(0, premium_cents(bid, multiplier)-cost.slippage_cents_per_share*multiplier)


def quote_net_cents(ask: float, bid: float, *, multiplier: int = CONTRACT_MULTIPLIER,
                    round_trip_fixed_cents: int, slippage_cents_per_share: float = 0) -> int:
    """Read-only equivalent for identical quotes; distinct quote times stay distinct."""
    slip = cents(slippage_cents_per_share*multiplier/100)
    return max(0, premium_cents(bid, multiplier)-slip)-premium_cents(ask, multiplier)-slip-round_trip_fixed_cents
