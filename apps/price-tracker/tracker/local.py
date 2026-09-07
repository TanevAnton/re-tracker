"""Local operations. All Git mutations are restricted to TanevAnton/re-tracker."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from .runtime import lock, backup
from .storage import connect

APP = Path(__file__).resolve().parents[1]
REPO = APP.parents[1]
DATA = APP/'.local'
DB = DATA/'prices.sqlite'
LABEL = 'bg.re-tech.price-tracker'
EXPORTS = ['README.md','summary.csv','summary.json','listings.csv','listings.json','review.csv',
           'history.csv','events.csv','source_status.csv','status.json','catalog.json','prices.sqlite']


def git(*args, **kwargs):
    return subprocess.run(['git',*args],cwd=REPO,check=True,capture_output=True,**kwargs).stdout


def verify_repository():
    remote = git('remote','get-url','origin',text=True).strip().removesuffix('.git')
    if remote not in ('https://github.com/TanevAnton/re-tracker','git@github.com:TanevAnton/re-tracker'):
        raise ValueError('Expected origin TanevAnton/re-tracker; no operation performed')


def validate_database(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('Database failed integrity check')
        for table in ('observations','runs'): db.execute('SELECT payload FROM '+table+' LIMIT 1').fetchall()


def merge_database(source, target):
    """Add remote rows, preserving local conflicts and archiving every observation."""
    validate_database(source)
    incoming = sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro',uri=True)
    destination = connect(target)
    try:
        with destination:
            for table in ('observations','runs'):
                columns = 5 if table=='observations' else 2
                for row in incoming.execute('SELECT * FROM '+table):
                    destination.execute('INSERT OR IGNORE INTO '+table+' VALUES('+','.join('?'*columns)+')',row)
                    if table=='observations':
                        payload=row[-1]
                        destination.execute('INSERT OR IGNORE INTO observation_events VALUES(?,?)',
                                            (hashlib.sha256(payload.encode()).hexdigest(),payload))
            if incoming.execute("SELECT 1 FROM sqlite_master WHERE name='observation_events'").fetchone():
                for row in incoming.execute('SELECT * FROM observation_events'):
                    destination.execute('INSERT OR IGNORE INTO observation_events VALUES(?,?)',row)
    finally:
        incoming.close();destination.close()


def restore():
    verify_repository()
    git('fetch','origin','price-data')
    ref = git('rev-parse','FETCH_HEAD',text=True).strip()
    DATA.mkdir(parents=True,exist_ok=True)
    backups=DATA/'backups';backups.mkdir(exist_ok=True)
    incoming=backups/('price-data-'+ref+'.sqlite')
    raw=git('show',ref+':prices.sqlite')
    if not incoming.exists(): incoming.write_bytes(raw)
    validate_database(incoming)
    with lock(DB):
        if DB.exists():
            with closing(sqlite3.connect(DB)) as old:
                backup(old,backups/('before-restore-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.sqlite'))
        merge_database(incoming,DB)
        (DATA/'restored.json').write_text(json.dumps({'ref':ref,'restored_at':datetime.now(timezone.utc).isoformat()}))
    with closing(sqlite3.connect(DB)) as db:
        print(json.dumps(dict(database=str(DB),observations=db.execute('SELECT count(*) FROM observations').fetchone()[0],runs=db.execute('SELECT count(*) FROM runs').fetchone()[0],source_commit=ref),indent=2))


def doctor():
    result=dict(os=platform.platform(),architecture=platform.machine(),python=sys.version.split()[0],
                executable=sys.executable,git=shutil.which('git'),launchctl=shutil.which('launchctl'),
                playwright=bool(importlib.util.find_spec('playwright')),vision=(DATA/'bin/vision-ocr').is_file(),
                interactive_computer_use='Codex session only; not callable by launchd',paid_vision_required=False)
    try:
        from .browser import Browser
        from .http import Client
        browser=Browser(Client(['desktop.bg']),{})
        browser.start();result['browser_launch']='ok';browser.close()
    except Exception as exc: result['browser_launch']=str(exc)
    print(json.dumps(result,indent=2))


def schedule(action,hour=7,minute=23):
    if platform.system() != 'Darwin': raise ValueError('The bundled scheduler targets macOS launchd')
    plist = Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
    domain=f'gui/{os.getuid()}'
    if action=='install':
        DATA.mkdir(exist_ok=True)
        logs=DATA/'logs';logs.mkdir(exist_ok=True)
        config=dict(Label=LABEL,ProgramArguments=[str(APP/'trackerctl'),'scheduled-run'],WorkingDirectory=str(APP),
                    StartCalendarInterval=dict(Hour=hour,Minute=minute),RunAtLoad=False,
                    ProcessType='Background',StandardOutPath=str(logs/'launchd.out.log'),StandardErrorPath=str(logs/'launchd.err.log'),
                    EnvironmentVariables=dict(PATH=os.environ.get('PATH','/usr/bin:/bin')))
        plist.parent.mkdir(parents=True,exist_ok=True)
        if plist.exists():
            old=plistlib.loads(plist.read_bytes())
            if old.get('ProgramArguments') != config['ProgramArguments']:
                raise ValueError('A scheduler with this label points elsewhere; inspect before replacing')
            subprocess.run(['launchctl','bootout',domain+'/'+LABEL],capture_output=True)
        plist.write_bytes(plistlib.dumps(config));plist.chmod(0o600)
        subprocess.run(['launchctl','bootstrap',domain,str(plist)],check=True)
        print(f'Installed {plist}: daily {hour:02}:{minute:02} in this Mac\'s local timezone')
    elif action=='remove':
        subprocess.run(['launchctl','bootout',domain+'/'+LABEL],capture_output=True)
        if plist.exists():
            if plistlib.loads(plist.read_bytes()).get('WorkingDirectory') != str(APP): raise ValueError('Scheduler belongs to a different checkout')
            archive=DATA/'backups';archive.mkdir(parents=True,exist_ok=True)
            plist.rename(archive/(LABEL+'-'+datetime.now().strftime('%Y%m%dT%H%M%S%f')+'.plist'))
        print('Scheduler unloaded; plist archived locally')
    elif action=='run-now': subprocess.run(['launchctl','kickstart',domain+'/'+LABEL],check=True)
    else: subprocess.run(['launchctl','print',domain+'/'+LABEL],check=True)


def scheduled_run():
    logs=DATA/'logs';logs.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    config=DATA/'schedule.json'
    extra=[]
    if config.exists():
        cfg=json.loads(config.read_text())
        if cfg.get('model'): extra+=['--model',cfg['model']]
        if cfg.get('source'): extra+=['--source',cfg['source']]
    path=logs/(stamp+'.log')
    try:
        with path.open('w') as output:
            result=subprocess.run([sys.executable,'-u','-m','tracker','--max-pages','1',*extra],cwd=APP,stdout=output,stderr=subprocess.STDOUT,timeout=3*3600)
        code=result.returncode
    except subprocess.TimeoutExpired:
        code=124
    result=dict(finished_at=datetime.now(timezone.utc).isoformat(),exit_code=code,log=str(path))
    (DATA/'last-scheduled.json').write_text(json.dumps(result,indent=2))
    # Bounded automatic log retention (explicitly runtime logs, never price history).
    for old in sorted(logs.glob('20*.log'))[:-30]: old.unlink()
    print(json.dumps(result),flush=True)
    return code


def publish(approve_run=None):
    verify_repository()
    snapshot=(DATA/'output').resolve(strict=True)
    run=json.loads((snapshot/'status.json').read_text())
    if run['mode']!='live': raise ValueError('Fixture exports cannot be published')
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(run['finished_at'])).total_seconds()
    if not -300 <= age <= 36*3600: raise ValueError('Exports are stale; collect before publishing')
    hashes={name:hashlib.sha256((snapshot/name).read_bytes()).hexdigest() for name in EXPORTS}
    manifest=json.loads((snapshot/'manifest.json').read_text())
    if manifest['run_id'] != run['run_id'] or any(manifest['sha256'].get(k)!=v for k,v in hashes.items()):
        raise ValueError('Snapshot changed after collection; collect and review a new snapshot')
    print(json.dumps(dict(run_id=run['run_id'],snapshot=str(snapshot),health=run['health'],files=hashes),indent=2))
    if approve_run != run['run_id']:
        if approve_run: raise ValueError('Approval does not match the current snapshot')
        print('Review the files and source reuse permissions. Publish with: ./trackerctl publish --approve-run '+run['run_id'])
        return
    git('fetch','origin','price-data')
    ref=git('rev-parse','FETCH_HEAD',text=True).strip()
    if run.get('price_data_base') != ref:
        raise ValueError('Remote price-data changed or was not restored. Restore, collect, and review a new snapshot before publishing')
    # A detached temporary worktree preserves the code checkout and branch history.
    with tempfile.TemporaryDirectory(prefix='publish-',dir=DATA) as tmp:
        checkout=Path(tmp)/'checkout'
        git('worktree','add','--detach',str(checkout),ref)
        try:
            for name in EXPORTS: shutil.copy2(snapshot/name,checkout/name)
            def workgit(*args): return subprocess.run(['git',*args],cwd=checkout,check=True,capture_output=True,text=True).stdout
            workgit('add','--',*EXPORTS)
            workgit('commit','-m','Publish approved local observations '+run['run_id'])
            workgit('push','origin','HEAD:price-data')
            print('Published '+workgit('rev-parse','HEAD').strip())
        finally: git('worktree','remove','--force',str(checkout))


def main():
    os.chdir(APP)
    p=argparse.ArgumentParser(description='Re-Tech local development and scheduling')
    sub=p.add_subparsers(dest='command',required=True)
    for name in ('doctor','restore','report','scheduled-run'): sub.add_parser(name)
    s=sub.add_parser('schedule');s.add_argument('action',choices=['install','status','run-now','remove']);s.add_argument('--hour',type=int,default=7);s.add_argument('--minute',type=int,default=23)
    s=sub.add_parser('publish');s.add_argument('--approve-run')
    args=p.parse_args()
    try:
        if args.command=='doctor':doctor()
        elif args.command=='restore':restore()
        elif args.command=='schedule':
            if not 0<=args.hour<=23 or not 0<=args.minute<=59: raise ValueError('Invalid hour/minute')
            schedule(args.action,args.hour,args.minute)
        elif args.command=='scheduled-run':return scheduled_run()
        elif args.command=='publish':publish(args.approve_run)
        else:
            path=DATA/'output/README.md'
            print(path.read_text())
            print('Files: '+str(path.parent))
        return 0
    except (ValueError,OSError,subprocess.SubprocessError) as exc:
        print(str(exc),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
