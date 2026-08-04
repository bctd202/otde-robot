import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.core.config import get_settings

NY = ZoneInfo("America/New_York")
OCC_PATTERN = re.compile(r"^(?P<root>[A-Z]{1,6})(?P<date>\d{6})(?P<right>[CP])(?P<strike>\d{8})$")


def parse_occ_symbol(value: str) -> tuple[str, date, str, float] | None:
    """Parse compact OCC/OSI symbols without altering the provider value."""
    match = OCC_PATTERN.fullmatch(value)
    if not match:
        return None
    try:
        expiration = datetime.strptime(match.group("date"), "%y%m%d").date()
    except ValueError:
        return None
    return (match.group("root"), expiration,
            "call" if match.group("right") == "C" else "put",
            int(match.group("strike")) / 1000)


def verify_contract(contract, provider_status, *, symbol: str, right: str | None = None):
    """Verify internally consistent fields from an actual Tradier chain row."""
    contract.provider = provider_status.provider
    contract.data_mode = "mock" if provider_status.mode == "mock" else (
        "delayed" if provider_status.delay_seconds > 0 else "live")
    contract.actionable = False
    if contract.data_mode == "mock":
        contract.verification_status = "demo"
        contract.verification_reason = "explicit mock option data"
        return contract
    if provider_status.provider != "tradier" or provider_status.status == "unavailable":
        contract.verification_reason = "provider unavailable or untrusted"
        return contract
    if not contract.chain_member:
        contract.verification_reason = "symbol was not established as a member of the returned chain"
        return contract
    original = contract.original_option_symbol
    if not original:
        contract.verification_reason = "original provider OCC symbol is missing"
        return contract
    parsed = parse_occ_symbol(original)
    if parsed is None:
        contract.verification_reason = "malformed OCC symbol"
        return contract
    root, expiration, parsed_right, strike = parsed
    if root != symbol.upper() or root != contract.symbol.upper():
        contract.verification_reason = "OCC root does not match underlying"
        return contract
    if expiration != contract.expiration:
        contract.verification_reason = "OCC expiration does not match chain row"
        return contract
    if parsed_right != contract.right or (right and parsed_right != right):
        contract.verification_reason = "OCC option type does not match chain row"
        return contract
    if abs(strike - contract.strike) > .0001:
        contract.verification_reason = "OCC strike does not match chain row"
        return contract
    if contract.expiration < datetime.now(NY).date():
        contract.verification_reason = "expired contract"
        return contract
    if contract.bid <= 0 or contract.ask <= 0 or contract.ask < contract.bid:
        contract.verification_reason = "invalid bid/ask"
        return contract
    if contract.bid_timestamp is None or contract.ask_timestamp is None:
        contract.verification_reason = "missing bid or ask timestamp"
        return contract
    now = datetime.now(timezone.utc)
    for label, stamp in (("bid", contract.bid_timestamp), ("ask", contract.ask_timestamp)):
        if stamp.tzinfo is None:
            contract.verification_reason = f"{label} timestamp is ambiguous"
            return contract
        age = (now - stamp.astimezone(timezone.utc)).total_seconds()
        if age > get_settings().option_quote_freshness_seconds:
            contract.quote_freshness = "stale"
            contract.verification_reason = f"stale {label}"
            return contract
        if age < -30:
            contract.verification_reason = f"{label} timestamp is in the future"
            return contract
    contract.timestamp = min(contract.bid_timestamp, contract.ask_timestamp)
    contract.quote_freshness = "current"
    contract.verification_status = "verified"
    contract.verification_reason = "Exact OCC-consistent contract returned by current Tradier chain"
    contract.actionable = True
    return contract
