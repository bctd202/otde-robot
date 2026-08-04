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


def test_clean_upgrade_through_0006(tmp_path):
    db = tmp_path / "clean.db"
    alembic(db, "upgrade", "head")
    assert "0006_contract_provenance" in alembic(db, "current")


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
