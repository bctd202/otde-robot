import hashlib
import json
import sqlite3

import pytest

from app.services.research_archive import archive_database


def test_archive_includes_committed_wal_and_preserves_source_and_unresolved_rows(tmp_path):
    source, destination = tmp_path / "live.sqlite", tmp_path / "archives" / "legacy.sqlite"
    with sqlite3.connect(source) as original:
        original.execute("PRAGMA journal_mode=WAL")
        original.execute("CREATE TABLE evidence (id INTEGER PRIMARY KEY, state TEXT, pnl INTEGER)")
        original.executemany("INSERT INTO evidence VALUES (?, ?, ?)", [(1, "LOSS", -100), (2, "UNPRICED", None)])
        original.commit()
        before = original.execute("SELECT * FROM evidence").fetchall()
        result = archive_database(source, destination, revision="test-revision")
        assert original.execute("SELECT * FROM evidence").fetchall() == before
    with sqlite3.connect(destination.as_uri() + "?mode=ro", uri=True) as saved:
        assert saved.execute("SELECT * FROM evidence").fetchall() == before
    assert result["table_counts"] == {"evidence": 2}
    assert result["sha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert json.loads(destination.with_suffix(".sqlite.json").read_text())["code_revision"] == "test-revision"
    assert destination.stat().st_mode & 0o222 == 0
    with pytest.raises(FileExistsError):
        archive_database(source, destination, revision="overwrite-attempt")
    assert result["sha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()
