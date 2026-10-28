from datetime import datetime, timedelta
import json

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import LotteryQuoteSnapshot
from app.db.session import Base
from app.market_data.cached import CachedMarketDataProvider
from app.market_data.tastytrade import DXLinkSnapshotClient, TastytradeMarketDataProvider
from app.services.lotto_trials import fresh_point
from tests.test_lotto_trials import NOW, quote, tracker


def test_collector_persists_transport_receipt_separately_from_processing_time():
    from tests.test_lottery_tracker import LiveLotteryProvider
    from app.services.lottery_tracker import track_lottery_scan
    class Tasty(LiveLotteryProvider):
        def status(self):
            return super().status().model_copy(update={'provider':'tastytrade'})
        def option_chain(self,symbol,expiration=None):
            return [row.model_copy(update={'provider':'tastytrade','received_at':self.now-timedelta(seconds=20),
                'receipt_basis':'REST_RESPONSE_RECEIVED_V1'}) for row in super().option_chain(symbol,expiration)]
    engine=create_engine('sqlite://'); Base.metadata.create_all(engine)
    provider=Tasty()
    with Session(engine) as db:
        track_lottery_scan(db,provider,['SPY'],provider.now-timedelta(minutes=1),now=provider.now)
        db.commit(); db.expire_all()
        point=db.scalar(select(LotteryQuoteSnapshot))
        assert point is not None
        received=datetime.fromisoformat(point.receipt_evidence['received_at'])
        processed=datetime.fromisoformat(point.receipt_evidence['processed_at'])
        assert processed-received==timedelta(seconds=20)
        assert point.receipt_evidence['basis']=='REST_RESPONSE_RECEIVED_V1'


@pytest.mark.parametrize('receipt', [None, 'bad', '2026-10-19T14:00:00',
    (NOW-timedelta(seconds=61)).isoformat(), (NOW+timedelta(seconds=1)).isoformat()])
def test_new_receipt_evidence_cannot_be_refreshed_by_scan_time(receipt):
    engine=create_engine('sqlite://'); Base.metadata.create_all(engine)
    with Session(engine) as db:
        row=tracker(db)
        quote(db,row,NOW,receipt_evidence={'basis':'REST_RESPONSE_RECEIVED_V1','received_at':receipt})
        assert fresh_point(db,row.id,NOW) is None


def test_actual_arrival_must_follow_decision_and_survives_reload():
    engine=create_engine('sqlite://'); Base.metadata.create_all(engine)
    with Session(engine) as db:
        row=tracker(db)
        quote(db,row,NOW,receipt_evidence={'basis':'REST_RESPONSE_RECEIVED_V1',
            'received_at':(NOW-timedelta(seconds=2)).isoformat()})
        db.commit(); db.expire_all()
        assert fresh_point(db,row.id,NOW) is not None
        assert fresh_point(db,row.id,NOW,after=NOW-timedelta(seconds=1)) is None
        assert db.scalar(select(LotteryQuoteSnapshot)).receipt_evidence['received_at']


def make_market(monkeypatch, stamp):
    clock=[NOW]
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            return clock[0].astimezone(tz) if tz else clock[0].replace(tzinfo=None)
    monkeypatch.setattr('app.market_data.tastytrade.datetime',Clock)
    def handler(request):
        if request.url.path=='/oauth/token':
            return httpx.Response(200,json={'access_token':'test','expires_in':900})
        if request.url.path=='/option-chains/SPY':
            return httpx.Response(200,json={'data':{'items':[{'symbol':'SPY261019C00100000',
                'expiration-date':'2026-10-19','strike-price':'100','option-type':'C'}]}})
        if request.url.path=='/market-data/by-type':
            return httpx.Response(200,json={'data':{'items':[{'symbol':'SPY261019C00100000',
                'bid':.18,'ask':.20,'updated-at':stamp}]}})
        raise AssertionError(request.url)
    market=TastytradeMarketDataProvider('id','secret','refresh','https://example.test','test/1',
        client=httpx.Client(transport=httpx.MockTransport(handler)))
    def slow_metrics(rows):
        clock[0]+=timedelta(seconds=30)
        return {}
    monkeypatch.setattr(market,'_option_metrics',slow_metrics)
    return market


def test_transport_receipt_precedes_slow_metrics_and_cache_does_not_restamp(monkeypatch):
    market=make_market(monkeypatch,NOW.isoformat())
    cached=CachedMarketDataProvider(market)
    first=cached.option_chain('SPY',NOW.date())[0]
    second=cached.option_chain('SPY',NOW.date())[0]
    assert first.received_at == second.received_at == NOW
    assert first.receipt_basis=='REST_RESPONSE_RECEIVED_V1'
    assert first.timestamp == NOW


@pytest.mark.parametrize('stamp',[None,'garbage','2026-10-19T14:00:00'])
def test_missing_invalid_or_naive_quote_time_never_becomes_now(monkeypatch,stamp):
    assert make_market(monkeypatch,stamp).option_chain('SPY',NOW.date()) == []


def test_numeric_upstream_timestamp_remains_supported(monkeypatch):
    chain=make_market(monkeypatch,NOW.timestamp()*1000).option_chain('SPY',NOW.date())
    assert chain[0].timestamp==NOW


def test_optional_research_enforces_hard_reserve_without_changing_baseline_budget(monkeypatch):
    market=make_market(monkeypatch,NOW.isoformat())
    limit=market.budget_status()['safety_limit']
    before=market._error
    with market.research_request_reserve(20):
        for _ in range(limit-20):assert market._budget_available()
        assert not market._budget_available()
        assert market._error==before
    assert market.budget_status()['remaining']==20
    assert market._budget_available()  # Baseline context can still use its reserve.


@pytest.mark.parametrize('mode',['complete','partial','candles'])
def test_snapshot_only_finishes_early_when_all_metric_pairs_arrived(monkeypatch,mode):
    fields=DXLinkSnapshotClient.EVENT_FIELDS
    def packet(kind,symbol):
        return {'type':'FEED_DATA','data':[kind,[[kind,symbol]+[0]*(len(fields[kind])-2)]]}
    events=[{'type':'FEED_CONFIG'}]
    if mode=='candles':
        events += [packet('Candle','SPY{=m}'),packet('Candle','SPY{=m}')]
        subscriptions=[{'type':'Candle','symbol':'SPY{=m}'}]; kinds={'Candle'}
    else:
        events += [packet('Greeks','SPY'),packet('Greeks','SPY')]
        if mode=='complete': events.append(packet('Summary','SPY'))
        subscriptions=[{'type':kind,'symbol':'SPY'} for kind in ('Greeks','Summary')]
        kinds={'Greeks','Summary'}
    class Socket:
        timed_out=False
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def send(self,message): pass
        def recv(self,timeout):
            if events:return json.dumps(events.pop(0))
            self.timed_out=True
            raise TimeoutError()
    socket=Socket()
    monkeypatch.setattr('websockets.sync.client.connect',lambda *args,**kwargs:socket)
    result=DXLinkSnapshotClient('wss://example.test','secret').snapshot(subscriptions,kinds)
    assert len(result)==(3 if mode=='complete' else 2)
    assert socket.timed_out == (mode!='complete')
