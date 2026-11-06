"""Native indexes for the activated source sections a teaching run can use."""
import hashlib
import time
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select
from .. import models as old
from ..auth import Context
from ..config import settings
from ..db import SessionLocal
from ..workflows import active_source
from . import models as m, service as s, tutor


def identity(membership_id):
    return 'teaching-knowledge:' + membership_id


def retrieve(ctx, version_id, chunks, query, authorize, name=None):
    name = name or ensure(ctx, version_id, chunks, authorize)
    authorize()
    response = tutor.knowledge_request(identity(ctx.membership.id), 'search', name, query=query[:8000])
    if response.get('state') != 'ready':
        raise tutor.TutorError('DEEPTUTOR_TEACHING_INDEX_NOT_READY')
    chosen = {}
    for snippet in response.get('passages', []):
        if not isinstance(snippet, str) or len(snippet) < 8:
            continue
        for chunk in chunks:
            if chunk['chunk_id'] in chosen:
                continue
            if snippet in chunk['text'] or chunk['text'] in snippet:
                start = max(0, chunk['text'].find(snippet) - 200)
                chosen[chunk['chunk_id']] = dict(chunk, text=chunk['text'][start:start+2200])
                if len(chosen) == 12:
                    return list(chosen.values())
    return list(chosen.values())


def ensure(ctx, version_id, chunks, authorize):
    # The subset is part of the version key: a chapter selection never gives
    # the model a knowledge base covering the rest of the book.
    text = '\n\n'.join(f'[第 {number} 页]\n{chunk["text"]}' for number, chunk in enumerate(chunks, 1))
    checksum = hashlib.sha256(text.encode()).hexdigest()
    owner = identity(ctx.membership.id)
    name = 'zx_' + hashlib.sha256(f'{owner}:{version_id}:{checksum}'.encode()).hexdigest()[:48]
    with SessionLocal.begin() as db:
        db.get(old.Membership, ctx.membership.id, with_for_update=True)
        row = db.scalar(select(m.TutorTeachingIndex).where(m.TutorTeachingIndex.membership_id == ctx.membership.id,
            m.TutorTeachingIndex.version_id == version_id, m.TutorTeachingIndex.sha256 == checksum))
        if row is None:
            row = m.TutorTeachingIndex(membership_id=ctx.membership.id, version_id=version_id,
                sha256=checksum, principal=owner, name=name, next_at=(s.clock() + timedelta(seconds=90)).isoformat())
            db.add(row)
        db.flush()
        row_id = row.id
    state = 'failed'
    try:
        authorize()
        state = tutor.knowledge_request(owner, 'status', name)['state']
        if state == 'failed':
            tutor.knowledge_request(owner, 'delete', name)
            state = 'missing'
        if state == 'missing':
            state = tutor.knowledge_request(owner, 'create', name, text=text)['state']
        deadline = time.monotonic()+90
        while state == 'indexing' and time.monotonic() < deadline:
            time.sleep(3)
            authorize()
            state = tutor.knowledge_request(owner, 'status', name)['state']
        if state != 'ready':
            raise tutor.TutorError('DEEPTUTOR_TEACHING_INDEX_NOT_READY：教师资料索引未就绪')
        return name
    finally:
        with SessionLocal.begin() as db:
            row = db.get(m.TutorTeachingIndex, row_id, with_for_update=True)
            if row.state != 'deleted':
                row.state = state
                row.next_at = (s.clock() + timedelta(seconds=60)).isoformat()


def tick():
    if not settings.deeptutor_url:
        return False
    with SessionLocal.begin() as db:
        row = db.scalar(select(m.TutorTeachingIndex).where(m.TutorTeachingIndex.state != 'deleted',
            m.TutorTeachingIndex.next_at <= s.clock().isoformat()).order_by(m.TutorTeachingIndex.next_at)
            .limit(1).with_for_update(skip_locked=True))
        if row is None:
            return False
        row.next_at = (s.clock() + timedelta(seconds=60)).isoformat()
        member = db.get(old.Membership, row.membership_id)
        user = db.get(old.User, member.user_id) if member else None
        if member and member.active and user and user.active:
            roles = list(db.scalars(select(old.RoleAssignment).where(old.RoleAssignment.membership_id == member.id)))
            if any(role.role in ('teacher', 'student') for role in roles):
                try:
                    active_source(db, Context(user, member, roles, None), row.version_id)
                    return True
                except HTTPException:
                    pass
        row_id, owner, name = row.id, row.principal, row.name
    try:
        tutor.knowledge_request(owner, 'delete', name)
    except tutor.TutorError:
        return True  # retry cleanup on the next poll
    with SessionLocal.begin() as db:
        row = db.get(m.TutorTeachingIndex, row_id, with_for_update=True)
        row.state = 'deleted'
    return True
