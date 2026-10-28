from pathlib import Path
from uuid import uuid4
import json
import sqlite3
import pytest
from app.backup import create, restore, validate
from app.config import ROOT
from app.db import SessionLocal
from app import models as m
from sqlalchemy import select, func
from conftest import checked, publish_all


def test_snapshot_restore_and_tamper_detection(clients):
    student, teacher, _ = clients
    publish_all(teacher)
    base = ROOT / '.runtime' / 'backup-tests' / str(uuid4())
    base.mkdir(parents=True)
    snapshot = create(base / 'snapshot')
    restored = restore(snapshot, base / 'restored')
    assert validate(restored)['secrets_included'] is False
    with sqlite3.connect(restored / 'platform.db') as db:
        assert db.execute('SELECT count(*) FROM users').fetchone()[0] == 3
        assert db.execute("SELECT count(*) FROM question_versions WHERE status='published'").fetchone()[0] == 60
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    with pytest.raises(ValueError):
        restore(snapshot, restored)
    manifest = json.loads((snapshot / 'manifest.json').read_text())
    original = next(name for name in manifest['files'] if name.startswith('files/'))
    (snapshot / original).write_text('altered', encoding='utf-8')
    with pytest.raises(ValueError, match='changed'):
        validate(snapshot)
