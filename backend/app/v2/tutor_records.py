"""Project-owned learning records. The native backend is chosen once per cutover."""
import hashlib

import httpx
from fastapi import HTTPException

from ..api_common import entity
from ..config import settings
from ..errors import fail
from . import models as m, service as s, tutor


FIELDS = ('id', 'title', 'body', 'kind', 'material_id', 'created_at')


def enabled(project_id):
    return project_id in settings.deeptutor_records_projects.split()


def native_records(user_id, project_id, records=None):
    try:
        tutor.require_configuration()
        payload, signature = tutor.signed_assertion(f'{user_id}:{project_id}:records',
                                                    records=records or [], listing=records is None)
        with httpx.Client(timeout=10, trust_env=False) as client:
            response = client.post(settings.deeptutor_url.rstrip('/') + '/internal/learning-records',
                                   json=payload, headers={'X-Zhixing-Signature': signature})
        if response.status_code == 409:
            fail(409, 'RECORD_CONFLICT', '学习记录标识已绑定其他内容')
        response.raise_for_status()
        items = response.json()['items']
        if not isinstance(items, list) or any(not isinstance(item, dict) or set(item) != set(FIELDS) for item in items):
            raise ValueError('Invalid learning records response')
        return items
    except (httpx.HTTPError, KeyError, TypeError, ValueError, tutor.TutorError):
        fail(503, 'TUTOR_RECORDS_UNAVAILABLE', '暂时无法确认学习记录状态，请稍后重试')


def local_records(db, project_id):
    return [entity(row, *FIELDS) for row in s.rows(db, m.Note, project_id)]


def visible(db, ctx, project_id, items):
    for item in sorted(items, key=lambda record: (record['created_at'], record['id'])):
        if item['material_id']:
            material = db.get(m.Material, item['material_id'])
            if not material or material.project_id != project_id:
                continue
            try:
                s.material_access(db, ctx, material)
            except HTTPException as exc:
                if exc.status_code != 403:
                    raise
                continue
        yield item


def record_id(ctx, project_id, key):
    identity = f'{project_id}:{ctx.membership.id}:{key}'
    return hashlib.sha256(identity.encode()).hexdigest()[:32]


def save_native(ctx, project_id, note_id, data):
    item = {'id': note_id, 'title': data.title, 'body': data.text,
            'kind': data.kind, 'material_id': data.material_id, 'created_at': s.clock().isoformat()}
    saved = native_records(ctx.user.id, project_id, [item])
    if len(saved) != 1 or any(saved[0][key] != item[key] for key in FIELDS if key != 'created_at'):
        fail(503, 'TUTOR_RECORDS_UNAVAILABLE', '暂时无法确认学习记录状态，请稍后重试')
    return saved[0]


def migrate(db, ctx, project):
    records = local_records(db, project.id)
    for start in range(0, len(records), 25):
        native_records(ctx.user.id, project.id, records[start:start + 25])
    imported = native_records(ctx.user.id, project.id)
    if sorted(records, key=lambda item: item['id']) != sorted(imported, key=lambda item: item['id']):
        fail(409, 'RECORD_MIGRATION_MISMATCH', '学习记录核对未通过，项目继续使用原存储')
    project.native_records = True
    return len(imported)


def restore(db, ctx, project):
    existing = {item['id']: item for item in local_records(db, project.id)}
    records = native_records(ctx.user.id, project.id)
    for item in records:
        previous = existing.get(item['id'])
        if previous is None:
            db.add(m.Note(project_id=project.id, **item))
        elif previous != item:
            fail(409, 'RECORD_MIGRATION_MISMATCH', '学习记录核对未通过，项目继续使用原生读取')
    if existing.keys() - {item['id'] for item in records}:
        fail(409, 'RECORD_MIGRATION_MISMATCH', '旧记录未全部找到，项目继续使用原生读取')
    project.native_records = False
    return len(records)
