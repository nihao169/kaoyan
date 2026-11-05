"""Copy an existing SQLite database into an EMPTY migrated PostgreSQL database.

Source is opened read-only. IDs are preserved; no schema or source data changes.
Default is a read-only inventory. --apply requires a completely empty target.
"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from sqlalchemy import create_engine, select, func

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.db import Base
from app import models
from app.v2 import models as v2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--target-env', default='DATABASE_URL')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--source-data', type=Path)
    parser.add_argument('--target-data', type=Path)
    args = parser.parse_args()
    source_path = args.source.resolve(strict=True)
    import os
    source = create_engine('sqlite:///file:' + source_path.as_posix() + '?mode=ro&uri=true')
    report = {'source': str(source_path), 'applied': False, 'tables': {}}
    tables = [t for t in Base.metadata.sorted_tables if not t.name.startswith('v2_')]
    with source.connect() as connection:
        records = {t.name: [dict(row) for row in connection.execute(select(t)).mappings()] for t in tables}
    for name, rows in records.items():
        report['tables'][name] = {'count': len(rows), 'sha256': hashlib.sha256(json.dumps(sorted(rows, key=lambda x:x['id']), sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    file_keys = {row.get('file_key') for row in records.get('source_versions', []) if row.get('file_key')}
    for row in records.get('source_documents', []):
        file_keys.update(row.get(key) for key in ('original_key', 'preview_key') if row.get(key))
    file_hashes = {}
    if args.source_data:
        base = (args.source_data / 'files').resolve()
        for key in file_keys:
            path = (base / key).resolve()
            if not path.is_relative_to(base) or not path.is_file():
                raise RuntimeError('Missing or invalid source file in snapshot')
            file_hashes[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    report['files'] = file_hashes
    if args.apply:
        if file_keys and (not args.source_data or not args.target_data):
            raise SystemExit('Source has files; --source-data and --target-data are required.')
        if args.target_data and args.target_data.exists():
            raise SystemExit('Target data directory must be new; existing files will not be overwritten.')
        target_url = os.environ.get(args.target_env, '')
        if not target_url.startswith('postgresql'):
            raise SystemExit('Target must be a PostgreSQL URL supplied through the environment.')
        target = create_engine(target_url)
        with target.begin() as connection:
            for table in Base.metadata.sorted_tables:
                if connection.scalar(select(func.count()).select_from(table)):
                    raise SystemExit('Target is not empty. No records were imported.')
            for table in tables:
                if records[table.name]:
                    connection.execute(table.insert(), records[table.name])
                actual = [dict(row) for row in connection.execute(select(table)).mappings()]
                digest = hashlib.sha256(json.dumps(sorted(actual,key=lambda x:x['id']),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                if digest != report['tables'][table.name]['sha256']:
                    raise RuntimeError('Migration verification failed: ' + table.name)
            if args.target_data:
                target_files = args.target_data / 'files'
                target_files.mkdir(parents=True)
                for key, digest in file_hashes.items():
                    destination = target_files / key
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(args.source_data / 'files' / key, destination)
                    if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                        raise RuntimeError('File migration verification failed')
            # Historical projects carry provenance, never invented mastery.
            for user in connection.execute(select(models.User)).mappings():
                space_id = models.uid()
                connection.execute(v2.PersonalSpace.__table__.insert().values(id=space_id,user_id=user['id'],created_at=models.now()))
                member_ids = list(connection.scalars(select(models.Membership.id).where(models.Membership.user_id==user['id'])))
                for goal in connection.execute(select(models.Goal).where(models.Goal.membership_id.in_(member_ids))).mappings():
                    connection.execute(v2.Project.__table__.insert().values(id=models.uid(),space_id=space_id,title='历史学习项目',scenario='kaoyan',subject_id=goal['subject_id'],exam_year=goal['exam_year'],daily_minutes=goal['daily_minutes'],target_score=goal['target_score'],state='archived',revision=1,scope_revision=1,policy='legacy-import-v1',created_at=models.now()))
            report['applied'] = True
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Migration report saved; source was opened read-only.')


if __name__ == '__main__':
    main()
