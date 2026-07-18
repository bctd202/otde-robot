from datetime import date, datetime
from zoneinfo import ZoneInfo
from fastapi.testclient import TestClient
from app.core.config import get_settings
from app.db.seed import seed
from app.db.session import Base, engine
from app.main import app
from app.market_data.mock import MockMarketDataProvider
from app.services.indicators import opening_range, spread_pct, swings, vwap
from app.services.market_calendar import is_market_day, market_session
from app.services.setup_engine import lottery_candidates, structured_setups

client = TestClient(app)

def test_health(): assert client.get('/api/health').json()['paper_only'] is True

def test_market_holiday(): assert is_market_day(date(2026, 7, 3)) is False

def test_market_session_regular(): assert market_session(datetime(2026,7,6,10,0,tzinfo=ZoneInfo('America/New_York'))) == 'regular'

def test_indicators_and_patterns():
    p=MockMarketDataProvider(); c=p.candles('SPY')
    assert vwap(c) > 0
    assert opening_range(c,5)['high'] >= opening_range(c,5)['low']
    hi, lo = swings(c); assert isinstance(hi, list) and isinstance(lo, list)

def test_spread_calculation(): assert spread_pct(0.07,0.10) == 35.29

def test_lottery_filtering_and_structured():
    p=MockMarketDataProvider(); q=p.quotes(['SPY'])[0]; c=p.candles('SPY'); chain=p.option_chain('SPY')
    assert structured_setups('SPY', c, q, chain)
    lottos=lottery_candidates('SPY', c, q, chain)
    assert len(lottos) <= 3
    assert all(x.total_debit <= 40 for x in lottos)

def test_dashboard_no_live_claims():
    data=client.get('/api/dashboard').json()
    assert data['provider_status']['mode'] == 'mock'
    assert data['paper_account']['mode'] == 'PAPER ONLY'

def test_dashboard_has_all_symbols_and_candidates():
    data=client.get('/api/dashboard').json()
    assert {q['symbol'] for q in data['quotes']} == {'SPY','QQQ','IWM'}
    assert data['normal_setups']
    assert data['lottery_setups']
    assert len(data['lottery_setups']) <= 3

def test_no_trade_scenario():
    settings=get_settings(); original=settings.mock_scenario
    settings.mock_scenario='no_trade'
    try:
        data=client.get('/api/dashboard').json()
        assert data['no_trade'] is True
        assert data['normal_setups'] == []
        assert data['lottery_setups'] == []
    finally:
        settings.mock_scenario=original

def test_seeded_journal_and_analytics():
    Base.metadata.create_all(bind=engine)
    seed()
    journal=client.get('/api/journal').json()
    analytics=client.get('/api/analytics').json()
    assert any(row['signal_type'] == 'no_trade' for row in journal)
    assert any(row['signal_type'] == 'lottery' for row in journal)
    assert analytics['sample_size'] == 6
    assert analytics['statistically_promising'] is False

def test_candle_validation():
    assert client.get('/api/candles/DIA').status_code == 404
    assert client.get('/api/candles/SPY?timeframe=1h').status_code == 422
