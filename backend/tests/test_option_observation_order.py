"""Synthetic scanner regression: sample existing refreshes, never create fills."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db.models import (AutomatedOptionMark, AutomatedOptionObservation, ForwardPaperAccount,
                           ForwardPaperEvent, ForwardPaperPosition, SignalScan)
from app.services import debit_spread_runner, expanded_account, retest_trials, signal_engine
from app.services.option_research import record_option_observations
from test_performance import SHADOW_START, database, shadow_contract
from test_research_accounting import CachedProvider, entry_for_research


def prepare_scan(monkeypatch, feed, *, refresh_stage=None, quote=None):
    order = []
    monkeypatch.setattr(signal_engine, 'get_settings', lambda: SimpleNamespace(
        symbol_list=['SPY'], debit_spread_enabled=True))
    for name in ('ensure_account', 'ensure_lotto_trials', 'track_candidates',
                 'track_lottery_scan', 'advance_lotto_trials', '_position_alerts', '_performance_alerts'):
        monkeypatch.setattr(signal_engine, name, lambda *a, **kw: None)
    for name in ('rank_parlays', 'rank_structured_intraday'):
        monkeypatch.setattr(signal_engine, name, lambda *a, **kw: [])
    monkeypatch.setattr(retest_trials, 'active', lambda *a: True)

    def phase(name):
        def run(*a, **kw):
            order.append(name)
            if name == refresh_stage:
                feed.exit_contract = quote
        return run

    monkeypatch.setattr(signal_engine, 'refresh_account_quotes', phase('baseline-refresh'))
    monkeypatch.setattr(signal_engine, 'advance_account', phase('baseline-account'))
    monkeypatch.setattr(retest_trials, 'refresh_quotes', phase('retest-refresh'))
    monkeypatch.setattr(retest_trials, 'process', phase('retest-account'))
    monkeypatch.setattr(expanded_account, 'refresh_account_quotes', phase('expanded-refresh'))
    monkeypatch.setattr(expanded_account, 'advance_account', phase('expanded-account'))
    monkeypatch.setattr(debit_spread_runner, 'run', phase('spread-account'))
    return order


@pytest.mark.parametrize('refresh_stage', ['baseline-refresh', 'retest-refresh', 'expanded-refresh', 'spread-account'])
def test_sampler_sees_same_scan_refresh_after_all_account_work(monkeypatch, refresh_stage):
    now = SHADOW_START + timedelta(minutes=3)
    feed = CachedProvider(exit_contract=False)
    quote = shadow_contract(stamp=now)
    order = prepare_scan(monkeypatch, feed, refresh_stage=refresh_stage, quote=quote)

    def sample(db, provider):
        order.append('sample')
        record_option_observations(db, provider, now=now)

    monkeypatch.setattr(signal_engine, 'record_option_observations', sample)
    with database()() as db:
        trade = entry_for_research(db)
        frozen = dict(trade.strategy_snapshot)
        scan = signal_engine.run_signal_scan(db, feed, ['SPY'], evaluation_at=now-timedelta(minutes=1))
        point = db.scalar(select(AutomatedOptionObservation))
        assert point.status == 'QUOTED' and point.bid == quote.bid
        assert point.bid_timestamp == now.replace(tzinfo=None)
        assert order == ['baseline-refresh', 'baseline-account', 'retest-refresh', 'retest-account',
                         'expanded-refresh', 'expanded-account', 'spread-account', 'sample']
        assert scan.provider_status['option_observation_collection'] == {
            'version': 'after-account-refresh-v1', 'additional_requests': 0}
        assert trade.strategy_snapshot == frozen and trade.exit_reason == 'OPEN' and trade.result_r is None
        assert feed.chain_calls == 0
        signal_engine.run_signal_scan(db, feed, ['SPY'], evaluation_at=now-timedelta(minutes=1))
        assert len(list(db.scalars(select(AutomatedOptionObservation)))) == 1
        assert order.count('sample') == 1  # Same-minute retry cannot re-run account work.


@pytest.mark.parametrize('case', ['skipped-no-refresh', 'stale', 'wrong-contract'])
def test_moving_sampler_does_not_manufacture_skipped_or_invalid_quotes(monkeypatch, case):
    now = SHADOW_START + timedelta(minutes=3)
    feed = CachedProvider(exit_contract=False)
    quote = None if case == 'skipped-no-refresh' else shadow_contract(
        stamp=now-timedelta(seconds=61) if case == 'stale' else now,
        symbol='SPY260803C00101000' if case == 'wrong-contract' else 'SPY260803C00100000')
    prepare_scan(monkeypatch, feed, refresh_stage='expanded-refresh', quote=quote)
    monkeypatch.setattr(signal_engine, 'record_option_observations',
                        lambda db, provider: record_option_observations(db, provider, now=now))
    with database()() as db:
        trade = entry_for_research(db)
        if case == 'skipped-no-refresh':
            db.add(ForwardPaperAccount(key='synthetic-skipped', activated_at=SHADOW_START,
                processed_at=SHADOW_START, mark_watermark=0, revision=0, policy={}))
            db.flush()
            db.add(ForwardPaperPosition(account_key='synthetic-skipped', signal_id=trade.signal_id,
                entry_mark_id=db.scalar(select(AutomatedOptionMark.id)), status='SKIPPED',
                first_seen_at=SHADOW_START, detail={'reason': 'Entry budget exceeded, including reserved closing fee'}))
            db.commit()
        signal_engine.run_signal_scan(db, feed, ['SPY'], evaluation_at=now-timedelta(minutes=1))
        gap = db.scalar(select(AutomatedOptionObservation))
        assert gap.status == 'GAP' and gap.bid is None and gap.ask is None
        # A subsequently refreshed quote cannot overwrite the saved missing minute.
        feed.exit_contract = shadow_contract(stamp=now+timedelta(seconds=5))
        record_option_observations(db, feed, now=now+timedelta(seconds=5))
        db.commit()
        db.expire_all()
        points = list(db.scalars(select(AutomatedOptionObservation)))
        assert len(points) == 1 and points[0].status == 'GAP' and points[0].bid is None
        if case == 'skipped-no-refresh':
            assert db.scalar(select(ForwardPaperPosition)).status == 'SKIPPED'
            assert list(db.scalars(select(ForwardPaperEvent))) == []
        assert feed.chain_calls == 0


def test_sampler_failure_rolls_back_only_observations_and_keeps_completed_account_work(monkeypatch):
    now = SHADOW_START + timedelta(minutes=3)
    feed = CachedProvider()
    prepare_scan(monkeypatch, feed)

    def baseline_work(db, *_):
        db.add(ForwardPaperEvent(account_key='synthetic-account', event_key='completed-account-work',
            occurred_at=now, kind='SYNTHETIC_FUNDING', settled_cents=200000,
            unsettled_cents=0, fee_cents=0, realized_cents=0, detail={}))

    def failed_sample(db, provider):
        record_option_observations(db, provider, now=now)
        raise ValueError('Synthetic observer failure after writing')

    monkeypatch.setattr(signal_engine, 'advance_account', baseline_work)
    monkeypatch.setattr(signal_engine, 'record_option_observations', failed_sample)
    with database()() as db:
        entry_for_research(db)
        db.add(ForwardPaperAccount(key='synthetic-account', activated_at=SHADOW_START,
            processed_at=SHADOW_START, mark_watermark=0, revision=0, policy={}))
        db.commit()
        scan = signal_engine.run_signal_scan(db, feed, ['SPY'], evaluation_at=now-timedelta(minutes=1))
        assert db.get(SignalScan, scan.id) is not None
        events = list(db.scalars(select(ForwardPaperEvent)))
        assert len(events) == 1 and events[0].event_key == 'completed-account-work'
        assert events[0].settled_cents == 200000 and events[0].realized_cents == 0
        assert list(db.scalars(select(AutomatedOptionObservation))) == []
        assert scan.provider_status['option_observation_collection']['error_type'] == 'ValueError'
        assert feed.chain_calls == 0
