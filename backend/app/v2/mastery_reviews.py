"""Deliver verified Zhixing evidence and read the native review queue."""
import asyncio
import hashlib
import logging
from datetime import timedelta

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from .. import models as old
from ..auth import Context
from ..config import settings
from ..db import SessionLocal
from ..errors import fail
from . import models as m, service as s, tutor, tutor_index, tutor_teaching_index

logger = logging.getLogger(__name__)


def owner_context(db, membership_id):
    member = db.get(old.Membership, membership_id)
    user = db.get(old.User, member.user_id) if member else None
    if not member or not member.active or not user or not user.active:
        fail(403, 'REVIEW_SCOPE_REVOKED', '复习资料权限已撤回')
    roles = list(db.scalars(select(old.RoleAssignment).where(old.RoleAssignment.membership_id == member.id)))
    return Context(user=user, membership=member, roles=roles, session=None)


def enqueue(db, ctx, kind, resource_id, attempt_id, revision, objective_id, objective, occurred_at, correct):
    # A learner row serializes scope creation across imports and simultaneous submissions.
    db.execute(select(old.User.id).where(old.User.id == ctx.user.id).with_for_update()).scalar_one()
    scope = db.scalar(select(m.MasteryReviewScope).where(m.MasteryReviewScope.owner_id == ctx.user.id,
        m.MasteryReviewScope.kind == kind, m.MasteryReviewScope.resource_id == resource_id))
    if scope is None:
        scope = m.MasteryReviewScope(owner_id=ctx.user.id, membership_id=ctx.membership.id, kind=kind,
                                    resource_id=resource_id)
        db.add(scope)
        db.flush()
    row = db.scalar(select(m.MasteryReviewEvent).where(m.MasteryReviewEvent.scope_id == scope.id,
        m.MasteryReviewEvent.attempt_id == attempt_id).with_for_update())
    if row and row.revision >= revision:
        return 'unchanged'
    payload = {'objective_id': objective_id, 'objective': objective, 'correct': correct,
               'timestamp': s.datetime.fromisoformat(occurred_at).timestamp()}
    if row is None:
        row = m.MasteryReviewEvent(scope_id=scope.id, attempt_id=attempt_id)
        db.add(row)
    row.revision, row.payload, row.state, row.next_at = revision, payload, 'queued', s.clock().isoformat()
    return 'staged'


def enqueue_v1(db, ctx, attempt, question, evaluation):
    task = db.get(old.LearningTask, attempt.task_id)
    point = db.get(old.KnowledgePoint, question.knowledge_id)
    if not point or not attempt.submitted_at:
        return 'missing_evidence'
    if attempt.hint_level or task.mode == 'diagnostic':
        return 'assisted_or_diagnostic'
    from ..workflows import active_source
    try:
        active_source(db, ctx, question.source_version_id)
    except HTTPException:
        return 'unauthorized'
    return enqueue(db, ctx, 'v1', question.source_version_id, attempt.id, evaluation['revision'],
                   point.id, point.name, attempt.submitted_at, evaluation['score'] == question.max_score)


def enqueue_v2(db, project, task, question, attempt, correct, membership_id=None):
    member_id = membership_id or task.payload.get('membership_id')
    owner = db.get(m.PersonalSpace, project.space_id)
    if not member_id:
        material = db.get(m.Material, question.material_id)
        index = tutor_index.mappings(db, [material]).get(material.id) if material else None
        member_id = index.membership_id if index else None
    if not member_id:
        member_id = db.scalar(select(old.Membership.id).join(old.RoleAssignment)
            .where(old.Membership.user_id == owner.user_id, old.Membership.active,
                   old.RoleAssignment.role == 'student').order_by(old.Membership.created_at, old.Membership.id).limit(1))
    if not member_id or not question.knowledge.strip():
        return 'unmapped'
    if attempt.hint_used or question.kind == 'essay':
        return 'assisted_or_training'
    try:
        ctx = owner_context(db, member_id)
        material = s.material_access(db, ctx, db.get(m.Material, question.material_id))
    except HTTPException:
        return 'unauthorized'
    if ctx.user.id != owner.user_id or material.project_id != project.id or project.state != 'active':
        return 'unauthorized'
    key = hashlib.sha256(' '.join(question.knowledge.split()).casefold().encode()).hexdigest()
    return enqueue(db, ctx, 'v2', question.material_id, attempt.id, 1, key,
                   question.knowledge, attempt.created_at, correct)


def scope_access(db, ctx, scope, *, study=False):
    if not scope or scope.owner_id != ctx.user.id or (scope.kind == 'v1' and scope.membership_id != ctx.membership.id):
        fail(404, 'NOT_FOUND', '复习范围不存在')
    if scope.kind == 'v1':
        from ..workflows import active_source
        if study:
            from ..learning import no_active_diagnostic
            no_active_diagnostic(db, ctx)
        version, source = active_source(db, ctx, scope.resource_id)
        return tutor_teaching_index.identity(ctx.membership.id), source.title, version
    material = s.material_access(db, ctx, db.get(m.Material, scope.resource_id))
    p = s.project(db, ctx, material.project_id)
    if study:
        s.no_active_mock(db, p.id)
    return tutor_index.principal(ctx.user.id, p.id), material.title, material


def teaching_chunks(db, version):
    return [{'chunk_id': chunk.id, 'text': chunk.text} for chunk in db.scalars(
        select(old.SourceChunk).where(old.SourceChunk.version_id == version.id).order_by(old.SourceChunk.position))]


def evidence_request(principal, **claims):
    tutor.require_configuration()
    payload, signature = tutor.signed_assertion(principal, **claims)
    try:
        with httpx.Client(timeout=12, trust_env=False) as client:
            response = client.post(settings.deeptutor_url.rstrip('/') + '/internal/mastery-evidence',
                                   json=payload, headers={'X-Zhixing-Signature': signature})
        response.raise_for_status()
        result = response.json()
        if result != {'path_id': 'topic_zx_' + claims['scope_id'].replace('-', ''),
                      'revision': claims['revision']}:
            raise ValueError('unexpected evidence acknowledgement')
        return result['path_id']
    except (httpx.HTTPError, ValueError) as exc:
        raise tutor.TutorError('DEEPTUTOR_REVIEW_SYNC_FAILED') from exc


def tick(*, replay=False):
    if not (settings.deeptutor_mastery_reviews or replay):
        return False
    with SessionLocal.begin() as db:
        now = s.clock()
        event = db.scalar(select(m.MasteryReviewEvent).where(m.MasteryReviewEvent.state == 'queued',
            m.MasteryReviewEvent.next_at <= now.isoformat()).order_by(m.MasteryReviewEvent.next_at,
            m.MasteryReviewEvent.created_at, m.MasteryReviewEvent.id).limit(1).with_for_update(skip_locked=True))
        if event is None:
            return False
        scope = db.get(m.MasteryReviewScope, event.scope_id)
        event_id, revision, scope_id = event.id, event.revision, scope.id
        claims = {**event.payload, 'attempt_id': event.attempt_id, 'revision': revision, 'scope_id': scope_id}
        event.next_at = (now + timedelta(minutes=3)).isoformat()
        try:
            ctx = owner_context(db, scope.membership_id)
            principal, title, material = scope_access(db, ctx, scope)
        except HTTPException:
            event.state = 'skipped'
            return True
        if scope.kind == 'v2':
            index = tutor_index.mappings(db, [material]).get(material.id)
            if index is None or index.state in ('failed', 'deleted'):
                tutor_index.enqueue(db, ctx, db.get(m.Project, material.project_id), [material])
            if index is None or index.state != 'ready':
                event.next_at = (now + timedelta(seconds=15)).isoformat()
                return True
            name = index.name
            chunks = []
        else:
            name = None
            chunks = teaching_chunks(db, material)
            if not chunks:
                event.state = 'skipped'
                return True
        membership_id, version_id = scope.membership_id, material.id

    def authorize():
        with SessionLocal() as db:
            scope_access(db, owner_context(db, membership_id), db.get(m.MasteryReviewScope, scope_id))

    try:
        if name is None:
            name = tutor_teaching_index.ensure(ctx, version_id, chunks, authorize)
        authorize()
        path_id = evidence_request(principal, **claims, title=title, knowledge_base=name)
    except HTTPException:
        state, path_id = 'skipped', None
    except tutor.TutorError:
        logger.warning('mastery_review_sync_failed event=%s', event_id)
        state, path_id = 'queued', None
    else:
        state = 'synced'
    with SessionLocal.begin() as db:
        event = db.get(m.MasteryReviewEvent, event_id, with_for_update=True)
        if event.revision == revision:
            event.state = state
            if path_id:
                db.get(m.MasteryReviewScope, scope_id).path_id = path_id
    return True


def topic(principal, path_id):
    return tutor.native_request(principal, 'GET', '/api/mastery-paths/topics/' + path_id, timeout=8)


async def collect(bindings):
    limit = asyncio.Semaphore(4)

    async def read(scope_id, principal, path_id, title):
        async with limit:
            try:
                data = await topic(principal, path_id)
                next_step = data.get('next') or {}
                return [{'scope_id': scope_id, 'title': title, 'knowledge': row['knowledge_point_name'],
                         'due_at': row['due_at'], 'due': row['due'], 'reason': row['reason'],
                         'priority': row['priority'], 'id': row['id'],
                         'next_step': next_step.get('action') if next_step.get('knowledge_point_id') == row.get('knowledge_point_id') else None}
                        for row in data['reviews']]
            except (tutor.TutorError, KeyError, TypeError):
                return None

    return await asyncio.gather(*(read(*binding) for binding in bindings))


def session_request(principal, path_id, operation, submission_id='', answer='', expected_id='', answers=None):
    tutor.require_configuration()
    payload, signature = tutor.signed_assertion(principal, path_id=path_id, operation=operation,
        submission_id=submission_id, answer=answer, expected_id=expected_id, answers=answers or {})
    try:
        with httpx.Client(timeout=15, trust_env=False) as client:
            response = client.post(settings.deeptutor_url.rstrip('/') + '/internal/mastery-review-session', json=payload,
                                   headers={'X-Zhixing-Signature': signature})
        if response.status_code == 409:
            fail(409, 'REVIEW_STATE_CHANGED', '复习状态已变化，请刷新后继续')
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError('invalid native review session')
        return result
    except (httpx.HTTPError, ValueError) as exc:
        raise tutor.TutorError('DEEPTUTOR_REVIEW_UNAVAILABLE') from exc
