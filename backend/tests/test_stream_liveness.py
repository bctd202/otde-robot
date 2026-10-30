"""Protocol time advances without real sleeps or provider credentials."""
import json
from datetime import datetime, timezone

import pytest

from app.market_data import tastytrade


@pytest.mark.parametrize('quiet,timeout', [(True,60),(False,60),(True,12),(False,12)])
def test_keepalive_survives_multiple_timeouts_on_quiet_and_busy_feeds(monkeypatch, quiet, timeout):
    clock = [0.0]
    sent = []
    stream = tastytrade.DXLinkCandleStreamClient('wss://synthetic','token',['SPY'],
        datetime(2026,10,30,tzinfo=timezone.utc),lambda events: None)
    handshake = iter([{'type':'SETUP','keepaliveTimeout':timeout},
                      {'type':'AUTH_STATE','state':'AUTHORIZED'},
                      {'type':'CHANNEL_OPENED'}, {'type':'FEED_CONFIG'}])

    class Socket:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def send(self, message): sent.append((clock[0],json.loads(message)))
        def recv(self, timeout):
            clock[0] += timeout
            if clock[0] >= 135:
                stream._stop.set()
            message = next(handshake,None)
            if message is not None: return json.dumps(message)
            if quiet: raise TimeoutError()
            return json.dumps({'type':'FEED_DATA','data':[]})

    monkeypatch.setattr(tastytrade,'monotonic',lambda:clock[0])
    monkeypatch.setattr('websockets.sync.client.connect',lambda *a,**kw:Socket())
    stream._session()
    beats = [at for at,m in sent if m['type']=='KEEPALIVE']
    assert len(beats) >= 4
    assert max(b-a for a,b in zip(beats,beats[1:])) <= min(30,timeout/2)+.1
    assert all(m['channel']==0 for _,m in sent if m['type']=='KEEPALIVE')
    assert stream.health()['connections']==1
    assert stream.health()['last_keepalive_at'] is not None
    assert not stream.health()['connected']


def test_reconnect_backoff_resets_after_a_stable_session_and_stop_interrupts_wait(monkeypatch):
    stream = tastytrade.DXLinkCandleStreamClient('wss://synthetic','token',[],
        datetime(2026,10,30,tzinfo=timezone.utc),lambda events:None)
    waits=[]; clock=[0.0]; attempts=[0]
    class Stop:
        def is_set(self): return len(waits)>=4
        def wait(self, delay): waits.append(delay)
    stream._stop=Stop()
    def session():
        attempts[0]+=1
        if attempts[0]==3:
            stream._ready_at=clock[0];clock[0]+=61
        raise ConnectionError('Synthetic disconnect')
    monkeypatch.setattr(stream,'_session',session)
    monkeypatch.setattr(tastytrade,'monotonic',lambda:clock[0])
    stream._run()
    assert waits==[1,2,1,2]
    assert stream.health()['disconnects']==4


def test_recovery_preserves_universe_and_is_bounded_without_rest_calls(monkeypatch):
    clock=[0.0];messages=[]
    stream=tastytrade.DXLinkCandleStreamClient('wss://synthetic','token',['SPY','QQQ','IWM','USO'],
        datetime(2026,10,30,tzinfo=timezone.utc),lambda events:None)
    class Socket:
        def send(self,message):messages.append(json.loads(message))
    monkeypatch.setattr(tastytrade,'monotonic',lambda:clock[0])
    stream.request_recovery(['SPY','QQQ','IWM','USO','NOT_IN_UNIVERSE'])
    stream._recover(Socket())
    assert len(messages[0]['remove'])==3
    assert all(row['fromTime']==int(stream.start_at.timestamp()*1000) for row in messages[1]['add'])
    stream.request_recovery(['SPY','QQQ','IWM'])
    stream._recover(Socket())  # Only the remaining fourth subscription is due.
    assert len(messages[2]['remove'])==1
    stream._recover(Socket());assert len(messages)==4
    assert stream.symbols==['SPY','QQQ','IWM','USO']


@pytest.mark.parametrize('stamp',[None,'bad','2026-10-30T10:00:00',True])
def test_market_timestamps_cannot_fall_back_to_local_clock(stamp):
    with pytest.raises(ValueError):tastytrade._market_stamp(stamp)
