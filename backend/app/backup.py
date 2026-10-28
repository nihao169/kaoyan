"""Offline coordinated snapshots and restore verification. Never overwrites live data."""
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.engine import make_url
from .config import settings, ROOT


def checksum(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def new_directory(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT) or path == ROOT or path.exists():
        raise ValueError('Destination must be a NEW directory inside the project workspace')
    path.mkdir(parents=True)
    return path


def sqlite_snapshot(source, target):
    with sqlite3.connect(f'file:{Path(source).as_posix()}?mode=ro', uri=True) as src:
        with sqlite3.connect(target) as dest:
            src.backup(dest)


def validate(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    for relative, digest in manifest['files'].items():
        if Path(relative).is_absolute() or '..' in Path(relative).parts or Path(relative).drive:
            raise ValueError('Unsafe backup manifest path')
        path = (directory / relative).resolve()
        if not path.is_relative_to(directory) or not path.is_file() or checksum(path) != digest:
            raise ValueError('Backup file missing, changed, or unsafe: ' + relative)
    with sqlite3.connect(f'file:{(directory / "platform.db").as_posix()}?mode=ro', uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Database integrity verification failed')
        if db.execute('SELECT version_num FROM alembic_version').fetchone()[0] != manifest['migration']:
            raise ValueError('Migration version mismatch')
        for (file_key,) in db.execute('SELECT file_key FROM source_versions WHERE file_key IS NOT NULL'):
            if Path(file_key).name != file_key or f'files/{file_key}' not in manifest['files']:
                raise ValueError('Source original is not present in the manifest')
        if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='source_documents'").fetchone():
            for original, preview in db.execute('SELECT original_key, preview_key FROM source_documents'):
                for key in (original, preview):
                    if key and (Path(key).name != key or f'files/{key}' not in manifest['files']):
                        raise ValueError('Document original/preview missing from manifest')
    return manifest


def create(destination):
    url = make_url(settings.database_url)
    if url.get_backend_name() != 'sqlite':
        raise ValueError('This backup adapter only supports SQLite. PostgreSQL requires a matching database-native backup adapter.')
    target = new_directory(destination)
    sqlite_snapshot(Path(url.database).resolve(), target / 'platform.db')
    (target / 'files').mkdir()
    with sqlite3.connect(target / 'platform.db') as db:
        migration = db.execute('SELECT version_num FROM alembic_version').fetchone()[0]
        file_keys = {x[0] for x in db.execute('SELECT file_key FROM source_versions WHERE file_key IS NOT NULL')}
        if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='source_documents'").fetchone():
            for original, preview in db.execute('SELECT original_key, preview_key FROM source_documents'):
                file_keys.update(k for k in (original, preview) if k)
    for file_key in file_keys:
        if Path(file_key).name != file_key:
            raise ValueError('Unsafe stored file key')
        shutil.copy2(settings.data_dir / 'files' / file_key, target / 'files' / file_key)
    if (settings.data_dir / 'workflows.db').exists():
        sqlite_snapshot(settings.data_dir / 'workflows.db', target / 'workflows.db')
    files = {p.relative_to(target).as_posix(): checksum(p) for p in target.rglob('*') if p.is_file()}
    manifest = {'version': 1, 'created_at': datetime.now(timezone.utc).isoformat(), 'migration': migration,
                'files': files, 'secrets_included': False, 'requires_offline': True}
    (target / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    validate(target)
    return target


def restore(source, destination):
    source = Path(source).resolve()
    manifest = validate(source)
    target = new_directory(destination)
    for relative in manifest['files']:
        output = target / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, output)
    shutil.copy2(source / 'manifest.json', target / 'manifest.json')
    validate(target)
    return target


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Offline platform backup. Stop API and worker before create.')
    sub = parser.add_subparsers(dest='action', required=True)
    create_parser = sub.add_parser('create')
    create_parser.add_argument('destination')
    restore_parser = sub.add_parser('restore')
    restore_parser.add_argument('source')
    restore_parser.add_argument('destination')
    verify_parser = sub.add_parser('verify')
    verify_parser.add_argument('source')
    args = parser.parse_args()
    if args.action == 'create':
        print(create(args.destination))
    elif args.action == 'restore':
        print(restore(args.source, args.destination))
    else:
        validate(args.source)
        print('Integrity, migration, source files, and checksums verified.')


if __name__ == '__main__':
    main()
