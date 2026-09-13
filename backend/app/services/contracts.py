import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.schemas.market import OptionContractOut

ACCEPTED_ACTIONABLE_DATA_MODES = {"live"}
from app.services.indicators import spread_pct

OCC = re.compile(r"^([A-Z0-9]{1,6})(\d{6})([CP])(\d{8})$")


@dataclass(frozen=True)
class ContractDecision:
    authentic: bool
    actionable: bool
    reason: str


def _identity_decision(contract: OptionContractOut, underlying: str) -> ContractDecision | None:
    """Return a rejection when the OCC symbol and chain identity disagree."""
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
    return None


def validate_contract(contract: OptionContractOut, underlying: str, *, now: datetime | None = None,
                      max_spread: float = 20, min_volume: int = 250, min_open_interest: int = 500,
                      min_dte: int = 0, max_dte: int = 0) -> ContractDecision:
    """Independently parse OCC identity, compare the chain row, then apply liquidity policy."""
    identity_rejection = _identity_decision(contract, underlying)
    if identity_rejection is not None:
        return identity_rejection
    if contract.provider != "tradier":
        return ContractDecision(contract.data_mode == "demo", False, "Only Tradier contracts can be actionable")
    if contract.data_mode == "demo":
        return ContractDecision(True, False, "Demo contracts are never actionable")
    if contract.data_mode == "unknown":
        return ContractDecision(
            True, False,
            "TRADIER_DATA_MODE must be explicitly set to live or delayed; unknown data is not actionable",
        )
    if contract.data_mode == "delayed":
        return ContractDecision(True, False, "Delayed Tradier data is research-only and not actionable")
    if contract.data_mode not in ACCEPTED_ACTIONABLE_DATA_MODES:
        return ContractDecision(True, False, "Provider data mode is not explicitly accepted for trading")
    now = now or datetime.now(timezone.utc)
    trading_date = now.astimezone(contract.timestamp.tzinfo).date()
    dte = (contract.expiration - trading_date).days
    if not min_dte <= dte <= max_dte:
        required_window = "same-day" if min_dte == max_dte == 0 else f"{min_dte}–{max_dte} DTE"
        return ContractDecision(True, False, f"Contract is outside the required {required_window} window")
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


def validate_exit_quote(contract: OptionContractOut, underlying: str, expected_symbol: str,
                        event_at: datetime, max_lag_seconds: int) -> ContractDecision:
    """Validate an exact live exit quote without applying entry-liquidity filters.

    A zero bid is accepted as explicit evidence of zero liquidation value. It is
    materially different from a missing contract row or missing bid timestamp.
    """
    identity_rejection = _identity_decision(contract, underlying)
    if identity_rejection is not None:
        return identity_rejection
    if contract.option_symbol.strip().upper() != expected_symbol.strip().upper():
        return ContractDecision(True, False, "Tradier row is not the selected entry contract")
    if contract.provider != "tradier" or contract.data_mode != "live":
        return ContractDecision(True, False, "Exit quote is not explicit live Tradier data")
    if contract.bid < 0 or contract.ask <= 0 or contract.ask < contract.bid:
        return ContractDecision(True, False, "Invalid exit bid/ask")
    if contract.bid_timestamp is None or contract.ask_timestamp is None:
        return ContractDecision(True, False, "Exit bid/ask timestamps unavailable")
    event = event_at.astimezone(timezone.utc) if event_at.tzinfo else event_at.replace(tzinfo=timezone.utc)
    bid_at = contract.bid_timestamp.astimezone(timezone.utc)
    ask_at = contract.ask_timestamp.astimezone(timezone.utc)
    earliest, latest = min(bid_at, ask_at), max(bid_at, ask_at)
    if earliest < event:
        return ContractDecision(True, False, "Exit quote predates the underlying exit event")
    if (latest - event).total_seconds() > max_lag_seconds:
        return ContractDecision(True, False, "Exit quote arrived outside the allowed lag window")
    return ContractDecision(True, True, "Verified exact Tradier quote after the underlying exit event")


def annotate_chain(chain: list[OptionContractOut], underlying: str, now: datetime, *,
                   max_spread: float = 20, min_volume: int = 250,
                   min_open_interest: int = 500, min_dte: int = 0,
                   max_dte: int = 0) -> list[OptionContractOut]:
    for contract in chain:
        decision = validate_contract(contract, underlying, now=now, max_spread=max_spread,
            min_volume=min_volume, min_open_interest=min_open_interest,
            min_dte=min_dte, max_dte=max_dte)
        contract.verification_status = "verified" if decision.authentic else "unverified"
        contract.verification_reason = decision.reason
        contract.actionable = decision.actionable
        contract.normalized_symbol = contract.option_symbol.strip().upper() if decision.authentic else None
    return chain


def has_complete_provenance(contract: OptionContractOut) -> bool:
    return all([
        contract.provider, contract.data_mode, contract.verification_status, contract.verification_reason,
        contract.option_symbol, contract.normalized_symbol, contract.bid_timestamp, contract.ask_timestamp,
        contract.timestamp, contract.expiration, contract.strike is not None, contract.right,
    ])


def is_verified_actionable_contract(contract: OptionContractOut | None) -> bool:
    return bool(contract and contract.actionable is True and contract.verification_status == "verified"
                and contract.provider == "tradier" and contract.data_mode in ACCEPTED_ACTIONABLE_DATA_MODES
                and has_complete_provenance(contract))
