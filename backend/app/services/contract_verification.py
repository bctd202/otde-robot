from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.core.config import get_settings

NY = ZoneInfo("America/New_York")


def verify_contract(contract, provider_status, *, symbol: str, right: str | None = None):
    """Annotate the exact provider-returned contract; never synthesize a replacement."""
    contract.original_option_symbol = contract.original_option_symbol or contract.option_symbol
    contract.provider = provider_status.provider
    contract.data_mode = "mock" if provider_status.mode == "mock" else (
        "delayed" if provider_status.delay_seconds > 0 else "live")
    if provider_status.status == "unavailable":
        reason = "provider unavailable"
    elif contract.data_mode == "mock":
        contract.verification_status = "demo"
        reason = "explicit mock option data"
    elif contract.symbol.upper() != symbol.upper():
        reason = "option underlying does not match recommendation"
    elif right and contract.right != right:
        reason = "option type does not match recommendation"
    elif not contract.option_symbol or contract.original_option_symbol != contract.option_symbol:
        reason = "quote symbol does not match selected contract"
    elif contract.expiration < datetime.now(NY).date():
        reason = "contract is expired"
    elif contract.bid <= 0 or contract.ask <= 0 or contract.ask < contract.bid:
        reason = "invalid bid/ask"
    else:
        quote_time = contract.timestamp
        if quote_time.tzinfo is None:
            reason = "quote timestamp is ambiguous"
        else:
            age = (datetime.now(timezone.utc) - quote_time.astimezone(timezone.utc)).total_seconds()
            if age > get_settings().option_quote_freshness_seconds:
                contract.quote_freshness = "stale"
                reason = "stale quote"
            elif age < -30:
                reason = "quote timestamp is in the future"
            else:
                contract.quote_freshness = "current"
                contract.verification_status = "verified"
                contract.verification_reason = "Exact current contract returned by provider chain"
                contract.actionable = True
                return contract
    contract.verification_reason = reason
    contract.actionable = False
    return contract
