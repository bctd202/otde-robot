from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.schemas.market import OptionContractOut, ProviderStatus
from app.services import contract_verification
from app.services.contract_verification import verify_contract

NOW = datetime(2026, 8, 4, 14, 0, tzinfo=timezone.utc)
NY = ZoneInfo("America/New_York")

class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz is None else NOW.astimezone(tz)

@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(contract_verification, "datetime", FixedDateTime)

def status(provider="tradier", mode="live", unavailable=False, delay=0):
    return ProviderStatus(provider=provider, mode=mode, status="unavailable" if unavailable else "healthy",
                          delay_seconds=delay, latest_timestamp=NOW, message="test")

def contract(**changes):
    values=dict(symbol="SPY", option_symbol="SPY260804C00550000", expiration=date(2026,8,4), strike=550,
        right="call", bid=.35, ask=.40, last=.38, volume=900, open_interest=2000,
        timestamp=NOW-timedelta(seconds=10))
    values.update(changes)
    return OptionContractOut(**values)

def test_exact_current_tradier_chain_contract_is_verified_without_symbol_rewrite():
    item=verify_contract(contract(),status(),symbol="SPY",right="call")
    assert item.actionable and item.verification_status=="verified"
    assert item.option_symbol==item.original_option_symbol=="SPY260804C00550000"
    assert item.expiration==date(2026,8,4) and item.data_mode=="live"

@pytest.mark.parametrize(("changes","reason"),[
    ({"symbol":"QQQ"},"underlying"),({"right":"put"},"option type"),
    ({"original_option_symbol":"DIFFERENT"},"quote symbol"),
    ({"expiration":date(2026,8,3)},"expired"),({"bid":0},"bid/ask"),
    ({"ask":.30},"bid/ask"),({"timestamp":NOW-timedelta(minutes=3)},"stale"),
])
def test_invalid_contract_provenance_is_never_actionable(changes,reason):
    item=verify_contract(contract(**changes),status(),symbol="SPY",right="call")
    assert not item.actionable and item.verification_status=="unverified"
    assert reason in item.verification_reason

def test_provider_failure_and_explicit_mock_are_distinct_without_fallback():
    failed=verify_contract(contract(),status(unavailable=True),symbol="SPY",right="call")
    demo=verify_contract(contract(),status(provider="mock",mode="mock"),symbol="SPY",right="call")
    assert (failed.verification_status,failed.verification_reason)==("unverified","provider unavailable")
    assert not failed.actionable
    assert demo.verification_status=="demo" and demo.data_mode=="mock" and not demo.actionable
