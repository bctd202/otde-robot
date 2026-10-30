"""Main-Mac local reports and verified off-machine backups. No broker endpoints.

Run every five minutes with launchd. Back up once after 16:20 Eastern on weekdays.
No email, webhook, automatic restart or financial/account repair is performed.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import fcntl
from pathlib import Path
import plistlib
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo


def atomic_json(path, data):
    temporary=path.with_suffix(path.suffix+'.part')
    with temporary.open('w') as stream:
        json.dump(data,stream,indent=2);stream.write('\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def remote(server, command, **kwargs):
    return subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',server,command],
        check=True,timeout=kwargs.pop('timeout',90),**kwargs)


def verified_archive(compressed, expected_hash):
    """Restore to an isolated temporary directory and verify bytes and database."""
    with tempfile.TemporaryDirectory(prefix='parlay-restore-',dir=compressed.parent) as folder:
        restored=Path(folder)/'restore.sqlite';digest=hashlib.sha256()
        with gzip.open(compressed,'rb') as source, restored.open('xb') as target:
            while chunk:=source.read(1024*1024):
                digest.update(chunk);target.write(chunk)
        if digest.hexdigest()!=expected_hash:raise ValueError('Backup checksum mismatch')
        with sqlite3.connect(restored.as_uri()+'?mode=ro',uri=True) as db:
            if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('Restored database check failed')


def retain_backups(output, keep=30):
    """Only this runner's verified copies; never touch manual/pinned archives."""
    owned=[]
    for path in sorted(output.glob('parlay-daily-*.sqlite.json')):
        try:manifest=json.loads(path.read_text())
        except (ValueError,OSError):continue
        compressed=output/(path.name[:-5]+'.gz')
        if (manifest.get('maintenance_owned') is True and manifest.get('restored_integrity')=='ok'
                and manifest.get('local_file')==str(compressed) and compressed.is_file()):
            owned.append((path,compressed))
    for manifest,compressed in owned[:-keep]:
        compressed.unlink();manifest.unlink()


def backup(server, project, output, now):
    stamp=now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    name=f'parlay-daily-{stamp}.sqlite'
    path='/data/backups/'+name
    code=("from datetime import datetime,timezone; from pathlib import Path; import json; "
          "from app.services.market_calendar import market_session; "
          "from app.services.research_archive import archive_database; "
          "assert market_session(datetime.now(timezone.utc)) != 'regular'; "
          f"print(json.dumps(archive_database(Path('/data/liquidity_hunter.db'),Path({path!r}),revision=REVISION)))")
    # Revision is resolved on the source checkout, never supplied by an old report.
    code=code.replace('revision=REVISION',"revision=__import__('os').environ['PARLAY_BACKUP_REVISION']")
    prefix='export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin; cd '+shlex.quote(project)+' && '
    command=prefix+'docker compose exec -T -e PARLAY_BACKUP_REVISION="$(git rev-parse HEAD)" backend python -c '+shlex.quote(code)
    manifest=json.loads(remote(server,command,capture_output=True,text=True,timeout=300).stdout)
    if not re.fullmatch(r'[0-9a-f]{64}',str(manifest.get('sha256',''))):
        raise ValueError('Source backup manifest has no valid checksum')
    final=output/(name+'.gz');partial=output/(name+'.gz.part')
    if final.exists() or partial.exists():raise FileExistsError('Never overwrite a backup')
    compress=("import gzip,shutil,sys; "
              f"s=open({path!r},'rb'); z=gzip.GzipFile(fileobj=sys.stdout.buffer,mode='wb'); "
              "shutil.copyfileobj(s,z); z.close(); s.close()")
    with partial.open('xb') as stream:
        remote(server,prefix+'docker compose exec -T backend python -c '+shlex.quote(compress),
               stdout=stream,stderr=subprocess.PIPE,timeout=300)
    partial.chmod(0o600)
    verified_archive(partial,manifest['sha256'])
    partial.rename(final)
    manifest.update(local_file=str(final),restored_integrity='ok',copied_at=now.isoformat(),maintenance_owned=True)
    atomic_json(output/(name+'.json'),manifest)
    atomic_json(output/'last-verified-backup.json',manifest)
    # The verified compressed copy and manifest are now on the other machine.
    # Remove only the two intermediates created by this exact invocation.
    cleanup=f"from pathlib import Path; Path({path!r}).unlink(); Path({(path+'.json')!r}).unlink()"
    remote(server,prefix+'docker compose exec -T backend python -c '+shlex.quote(cleanup),capture_output=True)
    retain_backups(output)
    return manifest


def run(server, project, output, *, backup_now=False, now=None):
    now=now or datetime.now(timezone.utc)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@-]*',server):raise ValueError('Invalid SSH destination')
    output=output.expanduser().resolve()
    if output in (Path('/'),Path.home()):raise ValueError('Use a dedicated report directory')
    output.mkdir(parents=True,exist_ok=True,mode=0o700)
    previous_path=output/'status.json'
    previous=json.loads(previous_path.read_text()) if previous_path.exists() else {}
    try:
        response=remote(server,'curl --max-time 30 -fsS http://localhost:8000/api/readiness',capture_output=True,text=True)
        status=json.loads(response.stdout)
        if status.get('status') not in {'ATTENTION','SLEEPING','COLLECTING'}:
            raise ValueError('Invalid readiness response')
    except (subprocess.SubprocessError,ValueError,OSError) as exc:
        status={'status':'UNREACHABLE','problems':['Server readiness check unavailable'],
                'error_type':type(exc).__name__}
    status['checked_at']=now.isoformat()
    local=now.astimezone(ZoneInfo('America/New_York'))
    saved=output/'last-verified-backup.json'
    prior_backup=json.loads(saved.read_text()) if saved.exists() else {}
    backup_day=datetime.fromisoformat(prior_backup['copied_at']).astimezone(local.tzinfo).date() if prior_backup else None
    due=local.weekday()<5 and (local.hour,local.minute)>=(16,20) and backup_day!=local.date()
    if backup_now or due:
        try:prior_backup=backup(server,project,output,now)
        except (subprocess.SubprocessError,ValueError,OSError,sqlite3.Error) as exc:
            status.setdefault('problems',[]).append('Daily off-machine backup failed')
            status['backup_error_type']=type(exc).__name__
    status['last_verified_backup_at']=prior_backup.get('copied_at')
    if prior_backup:
        age=(now-datetime.fromisoformat(prior_backup['copied_at'])).total_seconds()
        if age>4*86400:status.setdefault('problems',[]).append('Verified backup is more than four days old')
    else:status.setdefault('problems',[]).append('No verified off-machine backup recorded by this runner')
    if status.get('problems'):status['status']='ATTENTION' if status['status']!='UNREACHABLE' else 'UNREACHABLE'
    if (status.get('status'),status.get('problems')) != (previous.get('status'),previous.get('problems')):
        with (output/'status-changes.jsonl').open('a') as stream:
            stream.write(json.dumps({'at':now.isoformat(),'status':status['status'],'problems':status.get('problems',[])})+'\n')
    atomic_json(previous_path,status)
    return status


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server',default='parlay')
    parser.add_argument('--project',default='/Users/bctd/otde-robot')
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--backup-now',action='store_true')
    parser.add_argument('--print-launch-agent',action='store_true')
    args=parser.parse_args()
    folder=args.output.expanduser().resolve()
    if args.print_launch_agent:
        job={'Label':'com.parlay.maintenance','RunAtLoad':True,'StartInterval':300,
             'ProgramArguments':[sys.executable,str(Path(__file__).resolve()),'--server',args.server,
                 '--project',args.project,'--output',str(folder)],
             'StandardOutPath':str(folder/'runner.log'),'StandardErrorPath':str(folder/'runner-errors.log')}
        sys.stdout.buffer.write(plistlib.dumps(job))
    else:
        folder.mkdir(parents=True,exist_ok=True)
        with (folder/'runner.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            print(json.dumps(run(args.server,args.project,folder,backup_now=args.backup_now)))
