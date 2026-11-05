import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def test_migration_inventory_is_read_only(environment,tmp_path):
    if os.environ.get('V2_TEST_DATABASE_URL'):
        return  # SQLite snapshot inventory is exercised by the ordinary isolated suite.
    source=environment/'test.db'
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    report=tmp_path/'migration-report.json'
    root=Path(__file__).resolve().parents[2]
    result=subprocess.run([sys.executable,str(root/'scripts/migrate-v2.py'),'--source',str(source),'--report',str(report)],cwd=root,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    data=json.loads(report.read_text(encoding='utf-8'))
    assert not data['applied']
    assert data['tables']['users']['count']==3
    assert data['tables']['question_versions']['count']==60
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before
