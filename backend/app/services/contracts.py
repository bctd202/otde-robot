import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.schemas.market import OptionContractOut
from app.services.indicators import spread_pct

OCC = re.compile(r"^([A-Z0-9]{1,6})(\d{6})([CP])(\d{8})$")


@dataclass(frozen=True)
class ContractDecision:
    authentic: bool
    actionable: bool
    reason: str


def validate_contract(contract: OptionContractOut, underlying: str, *, now: datetime | None = None,
                      max_spread: float = 20, min_volume: int = 250, min_open_interest: int = 500) -> ContractDecision:
    """Independently parse OCC identity, compare the chain row, then apply liquidity policy."""
    match = OCC.fullmatch(contract.option_symbol.strip().upper())
    if not match:
        return ContractDecision(False, False, "Invalid OCC option symbol")
    root, expiry_text, cp, strike_text = match.groups()
    try:
        expiry = datetime.strptime(expiry_text, "%y%m%d").date()
    except ValueError:
        return ContractDecision(False, False, "Invalid OCC expiration")
    strike = int(strike_text) / 1000
    right = "call" if cp == "C" else "put"
    expected = (underlying.upper(), contract.expiration, contract.strike, contract.right.lower())
    parsed = (root, expiry, strike, right)
    if parsed != expected or contract.symbol.upper() != underlying.upper():
        return ContractDecision(False, False, "OCC identity disagrees with Tradier chain row")
    if contract.provider != "tradier" or contract.data_mode != "live":
        return ContractDecision(contract.data_mode == "demo", False, "Demo contracts are never actionable")
    now = now or datetime.now(timezone.utc)
    if contract.expiration != now.astimezone(contract.timestamp.tzinfo).date():
        return ContractDecision(True, False, "No valid same-day expiration")
    if contract.bid <= 0 or contract.ask <= 0 or contract.ask < contract.bid:
        return ContractDecision(True, False, "Invalid bid/ask")
    if contract.bid_timestamp is None or contract.ask_timestamp is None:
        return ContractDecision(True, False, "Bid/ask timestamps unavailable")
    if now - contract.bid_timestamp.astimezone(timezone.utc) > timedelta(minutes=2) or now - contract.ask_timestamp.astimezone(timezone.utc) > timedelta(minutes=2):
        return ContractDecision(True, False, "Stale bid/ask quote")
    if spread_pct(contract.bid, contract.ask) > max_spread:
        return ContractDecision(True, False, "Spread too wide")
    if contract.volume < min_volume:
        return ContractDecision(True, False, "Option volume too low")
    if contract.open_interest < min_open_interest:
        return ContractDecision(True, False, "Open interest too low")
    return ContractDecision(True, True, "Verified against exact Tradier chain response")


def annotate_chain(chain: list[OptionContractOut], underlying: str, now: datetime) -> list[OptionContractOut]:
    for contract in chain:
        decision = validate_contract(contract, underlying, now=now)
        contract.verification_status = "verified" if decision.authentic else "unverified"
        contract.verification_reason = decision.reason
        contract.actionable = decision.actionable
        contract.normalized_symbol = contract.option_symbol.strip().upper() if decision.authentic else None
    return chain
