from app.db.session import engine


def test_sqlite_uses_wal_and_waits_for_short_write_contention():
    if engine.dialect.name != "sqlite":
        return

    with engine.connect() as connection:
        journal_mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar_one()
        busy_timeout = connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one()

    assert journal_mode == "wal"
    assert busy_timeout >= 30_000
