import gzip
import hashlib
import importlib.util
import json
from datetime import datetime,timezone
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

spec=importlib.util.spec_from_file_location('maintenance',Path(__file__).parents[2]/'ops/parlay_maintenance.py')
maintenance=importlib.util.module_from_spec(spec)
spec.loader.exec_module(maintenance)


def test_restored_backup_requires_matching_checksum_and_valid_database(tmp_path):
    path=tmp_path/'fixture.sqlite'
    with sqlite3.connect(path) as db:db.execute('CREATE TABLE evidence (id INTEGER)')
    content=path.read_bytes();compressed=tmp_path/'fixture.gz'
    compressed.write_bytes(gzip.compress(content))
    maintenance.verified_archive(compressed,hashlib.sha256(content).hexdigest())
    with pytest.raises(ValueError,match='checksum'):
        maintenance.verified_archive(compressed,'wrong')
    assert not list(tmp_path.glob('parlay-restore-*'))


def test_local_reports_record_changes_once_and_backup_failures_stay_visible(tmp_path,monkeypatch):
    monkeypatch.setattr(maintenance,'remote',lambda *a,**kw:SimpleNamespace(stdout=json.dumps(
        {'status':'SLEEPING','problems':[]})))
    monkeypatch.setattr(maintenance,'backup',lambda *a,**kw:(_ for _ in ()).throw(ValueError('Synthetic failure')))
    now=datetime(2026,10,30,21,tzinfo=timezone.utc)
    result=maintenance.run('parlay','/fixture',tmp_path,now=now)
    assert result['status']=='ATTENTION' and 'Daily off-machine backup failed' in result['problems']
    maintenance.run('parlay','/fixture',tmp_path,now=now)
    assert len((tmp_path/'status-changes.jsonl').read_text().splitlines())==1


def test_retention_cannot_remove_manual_or_unverified_backups(tmp_path):
    manual=tmp_path/'manual.sqlite.gz';manual.write_bytes(b'preserve')
    for i in range(3):
        path=tmp_path/f'parlay-daily-2026102{i}T210000Z.sqlite.gz';path.write_bytes(b'fixture')
        manifest=tmp_path/path.name.removesuffix('.gz')
        manifest=manifest.with_suffix(manifest.suffix+'.json')
        manifest.write_text(json.dumps({'maintenance_owned':True,'restored_integrity':'ok','local_file':str(path)}))
    maintenance.retain_backups(tmp_path,keep=2)
    assert manual.read_bytes()==b'preserve'
    assert len(list(tmp_path.glob('parlay-daily-*.gz')))==2
