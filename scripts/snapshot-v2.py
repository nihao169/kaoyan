"""Offline PostgreSQL + files + DeepTutor snapshot with integrity verification.

Use backup-v2.ps1 to stop writers first. Restore always creates a new database
and a new output directory; it never overwrites an active database or files.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CONTAINER='zhixing-v2-postgres-1'


def extended_path(path):
    if os.name!='nt':
        return path
    absolute=str(path.absolute())
    if absolute.startswith('\\\\?\\'):
        return path
    if absolute.startswith('\\\\'):
        return Path('\\\\?\\UNC\\'+absolute[2:])
    return Path('\\\\?\\'+absolute)


def inventory(directory, version=2):
    directory=extended_path(directory)
    entries={}
    for p in sorted(directory.rglob('*')):
        if p.is_file() and p != directory/'manifest.json' and not (version==1 and p.name=='manifest.json'):
            with p.open('rb') as stream:
                entries[p.relative_to(directory).as_posix()] = hashlib.file_digest(stream,'sha256').hexdigest()
    return entries


def validate(directory):
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if inventory(directory,manifest['version'])!=manifest['files']:
        raise RuntimeError('Snapshot integrity mismatch; restore was refused')
    return manifest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['create','validate','restore'])
    parser.add_argument('snapshot',type=Path)
    parser.add_argument('--destination',type=Path)
    parser.add_argument('--database-name')
    parser.add_argument('--release',action='store_true',help='Snapshot the clean release DB and file namespace')
    args=parser.parse_args()
    snapshot=args.snapshot.resolve()
    if args.command=='create':
        source_db='zhixing_v2_release' if args.release else 'zhixing_v2'
        file_dir='v2-release' if args.release else 'v2'
        if snapshot.exists():
            raise RuntimeError('Destination already exists')
        if any((ROOT/'.runtime'/name).exists() for name in ('services-v2.json','services-v2-release.json')):
            raise RuntimeError('Stop V2 application writers first using backup-v2.ps1')
        state=subprocess.run(['docker','inspect','-f','{{.State.Running}}','zhixing-v2-deeptutor-1'],capture_output=True,text=True,check=True)
        if state.stdout.strip()=='true':
            raise RuntimeError('Stop DeepTutor before making a coordinated snapshot')
        snapshot.mkdir(parents=True)
        with (snapshot/'postgres.dump').open('wb') as output:
            subprocess.run(['docker','exec',CONTAINER,'pg_dump','-U','zhixing','-d',source_db,'-Fc'],stdout=output,stderr=subprocess.PIPE,check=True)
        for name in (file_dir,'v2-deeptutor'):
            source=ROOT/'data'/name
            if source.exists():
                shutil.copytree(extended_path(source),extended_path(snapshot/name))
        shutil.copy2(ROOT/'.runtime/v2-secrets.json',snapshot/'v2-secrets.json')
        (snapshot/'manifest.json').write_text(json.dumps({'version':2,'contains_secrets':True,'database':source_db,'files':inventory(snapshot)},ensure_ascii=False,indent=2),encoding='utf-8')
        validate(snapshot)
        print('Coordinated snapshot created and verified. Contains credentials; keep private.')
    elif args.command=='validate':
        validate(snapshot)
        print('Snapshot integrity verified.')
    else:
        validate(snapshot)
        if not args.destination or args.destination.exists():
            raise RuntimeError('Restore requires a new destination directory')
        if not args.database_name or not re.fullmatch(r'zhixing_v2_restore_[a-z0-9_]+',args.database_name):
            raise RuntimeError('Restore database name must start with zhixing_v2_restore_')
        subprocess.run(['docker','exec',CONTAINER,'createdb','-U','zhixing',args.database_name],check=True)
        with (snapshot/'postgres.dump').open('rb') as source:
            subprocess.run(['docker','exec','-i',CONTAINER,'pg_restore','-U','zhixing','--exit-on-error','-d',args.database_name],stdin=source,check=True)
        shutil.copytree(extended_path(snapshot),extended_path(args.destination))
        validate(args.destination)
        print('Restored to a new database and directory. Active V2 configuration was not changed.')


if __name__=='__main__':
    main()
