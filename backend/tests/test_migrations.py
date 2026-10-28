import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def alembic(db: Path, *args: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "backend/alembic.ini", *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{db}", "PYTHONPATH": "backend"},
    )
    return result.stdout.strip()


def test_clean_upgrade_through_head(tmp_path):
    db = tmp_path / "clean.db"
    alembic(db, "upgrade", "head")
    assert "0018_retest_research" in alembic(db, "current")


def test_retest_tables_are_empty_and_old_ledger_preserved(tmp_path):
    db = tmp_path / 'before-retest.db'
    alembic(db, 'upgrade', '0017_quote_receipt')
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO forward_paper_accounts VALUES ('preserved', '2026-10-27', '2026-10-27', 10, 0, '{}')")
        original=conn.execute('SELECT * FROM forward_paper_accounts').fetchall()
    alembic(db, 'upgrade', 'head')
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT * FROM forward_paper_accounts').fetchall()==original
        for table in ('retest_runs','retest_accounts','retest_opportunities','retest_positions','retest_events','retest_observations'):
            assert conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0]==0


def test_receipt_migration_does_not_invent_historical_receipts(tmp_path):
    db = tmp_path / 'before-receipts.db'
    alembic(db, 'upgrade', '0016_lotto_trials')
    with sqlite3.connect(db) as conn:
        # Bootstrap uses current metadata; emulate the deployed 0016 columns.
        conn.execute('ALTER TABLE lottery_quote_snapshots DROP COLUMN receipt_evidence')
        conn.execute('''INSERT INTO lottery_quote_snapshots
            (tracker_id,observed_at,quote_timestamp,bid,ask,midpoint,last,spread_percent,volume,open_interest,is_qualified,received_at)
            VALUES ('old','2026-10-26','2026-10-26',.18,.20,.19,.19,10,1500,2000,1,'2026-10-26')''')
        original=conn.execute('SELECT * FROM lottery_quote_snapshots').fetchall()
    alembic(db, 'upgrade', 'head')
    with sqlite3.connect(db) as conn:
        upgraded=conn.execute('SELECT * FROM lottery_quote_snapshots').fetchall()
        assert [row[:-1] for row in upgraded]==original
        assert upgraded[0][-1] is None


def test_equity_migration_preserves_existing_account_and_cash_events(tmp_path):
    db = tmp_path / "existing-ledger.db"
    alembic(db, "upgrade", "0014_forward_paper_account")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO forward_paper_accounts VALUES ('forward-cash-v1', '2026-10-12', '2026-10-14', 15, 4, '{\"starting_cash_cents\":200000}')")
        conn.execute("INSERT INTO forward_paper_events VALUES (1, 'forward-cash-v1', 'funding', '2026-10-12', 'FUNDING', 200000, 0, 0, 0, '{}')")
        original = conn.execute("SELECT * FROM forward_paper_events").fetchall()
        account = conn.execute("SELECT * FROM forward_paper_accounts").fetchall()
    alembic(db, "upgrade", "head")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT * FROM forward_paper_events").fetchall() == original
        assert conn.execute("SELECT * FROM forward_paper_accounts").fetchall() == account
        assert conn.execute("SELECT count(*) FROM forward_paper_equity_snapshots").fetchone()[0] == 0


def test_upgrade_from_0005_classifies_ambiguous_live_rows_unknown(tmp_path):
    db = tmp_path / "from_0005.db"
    alembic(db, "upgrade", "0005_signal_last_evaluated")
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            INSERT INTO signal_performance (
                signal_id, source, dedupe_key, ticker, direction, backend_status,
                setup_type, strategy_version, strategy_snapshot, condition_snapshot,
                trading_date, triggered_at, entry_price, stop_price, target_price,
                exit_reason, mfe_r, mae_r, score, user_entered, option_snapshot,
                conservative_same_candle, created_at, updated_at, last_evaluated_at, actionable
            ) VALUES (
                'legacy-live', 'LIVE', 'SPY:call:2026-08-04', 'SPY', 'CALL', 'BUY',
                'directional-liquidity', 'parlay-v1', '{}', '{}',
                '2026-08-04', '2026-08-04 14:00:00', 100, 99, 102,
                'OPEN', 0, 0, 90, 0, NULL, 0,
                '2026-08-04 14:00:00', '2026-08-04 14:00:00', '2026-08-04 14:00:00', 0
            )
            """
        )
    alembic(db, "upgrade", "head")
    with sqlite3.connect(db) as conn:
        source = conn.execute("SELECT source FROM signal_performance WHERE signal_id='legacy-live'").fetchone()[0]
    assert source == "UNKNOWN"


def test_lotto_upgrade_preserves_old_quotes_without_inventing_provenance(tmp_path):
    db = tmp_path / 'old-lotto.db'
    alembic(db, 'upgrade', '0015_forward_equity')
    with sqlite3.connect(db) as conn:
        # Initial bootstrap uses current metadata; recreate the pre-0016 shape.
        for table in ('lotto_trial_events','lotto_trial_positions','lotto_trial_accounts'):
            conn.execute(f'DROP TABLE {table}')
        for name in ('received_at','provider','data_mode'):
            conn.execute(f'ALTER TABLE lottery_quote_snapshots DROP COLUMN {name}')
        conn.execute('''INSERT INTO lottery_quote_snapshots
            (tracker_id,observed_at,quote_timestamp,bid,ask,midpoint,last,spread_percent,volume,open_interest,is_qualified)
            VALUES ('legacy','2026-10-01','2026-10-01',.18,.20,.19,.19,10,1500,2000,1)''')
        original = conn.execute('SELECT * FROM lottery_quote_snapshots').fetchall()
    alembic(db, 'upgrade', 'head')
    with sqlite3.connect(db) as conn:
        upgraded = conn.execute('SELECT * FROM lottery_quote_snapshots').fetchall()
        assert [row[:-3] for row in upgraded] == original
        assert upgraded[0][-3:] == (None,None,None)
        for table in ('lotto_trial_events','lotto_trial_positions','lotto_trial_accounts'):
            assert conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0


def test_unknown_audit_rows_do_not_change_live_metrics():
    from datetime import date, datetime, timezone

    from app.db.models import SignalPerformance
    from app.services.performance import metrics

    live = SignalPerformance(signal_id="live", source="LIVE", dedupe_key="live", ticker="SPY", direction="CALL",
        backend_status="BUY", setup_type="directional-liquidity", strategy_version="test", strategy_snapshot={},
        condition_snapshot={}, trading_date=date(2026, 8, 4), triggered_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
        entry_price=100, stop_price=99, target_price=102, exit_reason="TARGET", result_r=2, mfe_r=2, mae_r=.1,
        duration_minutes=10, score=90, user_entered=False, option_snapshot=None, conservative_same_candle=False,
        created_at=datetime(2026, 8, 4, tzinfo=timezone.utc), updated_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
        last_evaluated_at=datetime(2026, 8, 4, tzinfo=timezone.utc))
    unknown = SignalPerformance(signal_id="unknown", source="UNKNOWN", dedupe_key="unknown", ticker="IWN", direction="CALL",
        backend_status="BUY", setup_type="directional-liquidity", strategy_version="test", strategy_snapshot={},
        condition_snapshot={}, trading_date=date(2026, 8, 4), triggered_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
        entry_price=100, stop_price=99, target_price=102, exit_reason="STOP", result_r=-100, mfe_r=.1, mae_r=100,
        duration_minutes=10, score=90, user_entered=False, option_snapshot=None, conservative_same_candle=False,
        created_at=datetime(2026, 8, 4, tzinfo=timezone.utc), updated_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
        last_evaluated_at=datetime(2026, 8, 4, tzinfo=timezone.utc))

    live_metrics = metrics([row for row in [live, unknown] if row.source == "LIVE"])

    assert live_metrics["total_triggered_signals"] == 1
    assert live_metrics["win_rate"] == 100
    assert live_metrics["average_r"] == 2
    assert live_metrics["cumulative_r"] == 2
    assert live_metrics["maximum_drawdown_r"] == 0
