"""Explicit pre-deployment SQLite backup, including committed WAL contents.

Never invoked by dashboard reads or by a trading scan. Copies all research, not
just successful trades. No credentials or environment values are exported.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


def archive_database(source: Path, destination: Path, *, revision: str) -> dict:
    source = source.resolve(strict=True)
    destination = destination.absolute()
    manifest = destination.with_suffix(destination.suffix + ".json")
    if source == destination or destination.exists() or manifest.exists():
        raise FileExistsError("Archive destination or manifest already exists; choose a new filename")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents overwriting any earlier archive, even on a race.
    with destination.open("xb"):
        pass
    destination.chmod(0o600)
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(destination)) as backup:
            original.backup(backup)
            integrity = backup.execute("PRAGMA integrity_check").fetchall()
            if integrity != [("ok",)]:
                raise RuntimeError("Archive integrity check failed; this file is not a verified archive")
            tables = [row[0] for row in backup.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            counts = {table: backup.execute('SELECT count(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0]
                      for table in tables}
    with destination.open("rb") as saved:
        digest = hashlib.file_digest(saved, "sha256").hexdigest()
    record = {"created_at": datetime.now(timezone.utc).isoformat(), "source": str(source),
              "archive": str(destination), "code_revision": revision, "sha256": digest,
              "integrity_check": "ok", "table_counts": counts,
              "scope": "All preserved research, including losses and unresolved positions; not a reset."}
    with manifest.open("x", encoding="utf-8") as saved_manifest:
        json.dump(record, saved_manifest, indent=2)
        saved_manifest.write("\n")
    destination.chmod(0o444)
    manifest.chmod(0o444)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--revision", required=True, help="Deployed code revision for provenance")
    args = parser.parse_args()
    print(json.dumps(archive_database(args.source, args.destination, revision=args.revision), indent=2))


if __name__ == "__main__":
    main()
