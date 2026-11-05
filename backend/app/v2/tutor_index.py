"""Versioned, project-scoped copies for DeepTutor's native retrieval."""
import hashlib
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select
from .. import models as old
from ..auth import Context
from ..config import settings
from ..db import SessionLocal
from . import models as m, search, service as s, tutor


def principal(user_id, project_id):
    return f'{user_id}:{project_id}:knowledge'


def mappings(db, materials):
    versions = {item.id: item.sha256 for item in materials}
    if not versions:
        return {}
    rows = db.scalars(select(m.TutorIndex).where(m.TutorIndex.material_id.in_(versions)))
    return {row.material_id: row for row in rows if versions[row.material_id] == row.sha256}


def enqueue(db, ctx, project, materials):
    found = mappings(db, materials)
    owner = principal(ctx.user.id, project.id)
    for material in materials:
        row = found.get(material.id)
        if row is None:
            name = 'zx_' + hashlib.sha256(f'{owner}:{material.id}:{material.sha256}'.encode()).hexdigest()[:48]
            row = m.TutorIndex(material_id=material.id, membership_id=ctx.membership.id,
                               sha256=material.sha256, principal=owner, name=name,
                               state='queued', next_at=s.clock().isoformat(), error='')
            db.add(row)
        elif row.state in ('failed', 'deleted'):
            row.membership_id = ctx.membership.id
            row.state, row.next_at, row.error = 'queued', s.clock().isoformat(), ''


def allowed(db, row, material):
    if not material or material.state != 'ready' or material.sha256 != row.sha256:
        return False
    project = db.get(m.Project, material.project_id)
    member = db.get(old.Membership, row.membership_id)
    if not project or project.state != 'active' or not member or not member.active:
        return False
    owner = db.get(m.PersonalSpace, project.space_id)
    user = db.get(old.User, member.user_id)
    if not user or not user.active or not owner or user.id != owner.user_id:
        return False
    roles = list(db.scalars(select(old.RoleAssignment).where(old.RoleAssignment.membership_id == member.id)))
    try:
        s.material_access(db, Context(user=user, membership=member, roles=roles, session=None), material)
        return True
    except HTTPException:
        return False


def tick():
    if not settings.deeptutor_native_knowledge and not settings.deeptutor_url:
        return False
    with SessionLocal.begin() as db:
        now = s.clock()
        row = db.scalar(select(m.TutorIndex).where(m.TutorIndex.state != 'deleted', m.TutorIndex.next_at <= now.isoformat())
                        .order_by(m.TutorIndex.next_at, m.TutorIndex.id).limit(1).with_for_update(skip_locked=True))
        if row is None:
            return False
        material = db.get(m.Material, row.material_id)
        remove = not allowed(db, row, material)
        row_id, owner, name, previous = row.id, row.principal, row.name, row.state
        text = material.text if not remove else ''
        row.next_at = (now + timedelta(seconds=90)).isoformat()
    state, error = previous, ''
    delay = 60
    try:
        if remove:
            tutor.knowledge_request(owner, 'delete', name)
            state = 'deleted'
        elif settings.deeptutor_native_knowledge and previous in ('queued', 'indexing', 'ready'):
            state = tutor.knowledge_request(owner, 'status', name)['state']
            if previous == 'queued' and state == 'failed':
                tutor.knowledge_request(owner, 'delete', name)
                state = 'missing'
            if state == 'missing':
                state = tutor.knowledge_request(owner, 'create', name, text=text)['state']
            if state == 'indexing':
                delay = 4
            elif state == 'failed':
                error = 'DeepTutor 索引未完成，请重试。'
    except (KeyError, tutor.TutorError) as exc:
        state = previous if remove else 'failed'
        error = str(exc) if isinstance(exc, tutor.TutorError) else '知识库返回了无效状态。'
    with SessionLocal.begin() as db:
        row = db.get(m.TutorIndex, row_id, with_for_update=True)
        if row.state == previous:
            row.state = state
            if previous != 'failed' or error:
                row.error = error
            row.next_at = (s.clock() + timedelta(seconds=delay)).isoformat()
    return True


def retrieve(indexed, query):
    hits = []
    terms = set(search.terms(query))
    seen = set()
    for material, owner, name in indexed:
        result = tutor.knowledge_request(owner, 'search', name, query=query[:8000])
        if result.get('state') != 'ready':
            raise tutor.TutorError('DEEPTUTOR_INDEX_NOT_READY：资料索引未就绪，请返回项目检查索引状态')
        for snippet in result.get('passages', [])[:80]:
            if isinstance(snippet, str) and len(snippet.strip()) >= 8:
                snippet = snippet.strip()
                start = material.text.find(snippet)
                key = (material.id, start, len(snippet))
                if start >= 0 and key not in seen:
                    hits.append(search.Passage(material, start, start + len(snippet)))
                    seen.add(key)
    # Rank only results returned by DeepTutor. This never searches the
    # platform corpus for extra candidates or bypasses native retrieval.
    hits.sort(key=lambda hit: -sum(len(term) for term in terms.intersection(search.terms(hit.text))))
    return hits[:12]
