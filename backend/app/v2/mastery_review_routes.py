"""Platform authorization for the native review queue and review session."""
import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..api_common import EnvelopeRoute
from ..auth import context, need
from ..config import settings
from ..db import get_db
from ..errors import fail
from . import mastery_reviews as reviews, models as m, tutor
from . import service as s

router = APIRouter(route_class=EnvelopeRoute)


class ReviewAction(BaseModel):
    operation: Literal['start', 'answer']
    submission_id: str = Field(min_length=8, max_length=80)
    answer: str = Field(default='', max_length=12000)
    expected_id: str = Field(default='', max_length=150)
    answers: dict[str, str] = Field(default_factory=dict, max_length=4)


@router.get('/mastery-reviews')
def queue(ctx=Depends(context), db=Depends(get_db)):
    need(ctx, 'student')
    if not settings.deeptutor_mastery_reviews:
        return {'enabled': False, 'items': [], 'history': [], 'pending': 0, 'unavailable': False}
    bindings = []
    scope_ids = []
    for scope in db.scalars(select(m.MasteryReviewScope).where(m.MasteryReviewScope.owner_id == ctx.user.id)
                            .order_by(m.MasteryReviewScope.created_at, m.MasteryReviewScope.id)):
        try:
            principal, title, _ = reviews.scope_access(db, ctx, scope, study=True)
        except HTTPException:
            continue
        scope_ids.append(scope.id)
        if scope.path_id:
            bindings.append((scope.id, principal, scope.path_id, title))
    pending = db.scalar(select(func.count()).select_from(m.MasteryReviewEvent).where(
        m.MasteryReviewEvent.scope_id.in_(scope_ids), m.MasteryReviewEvent.state == 'queued'))
    db.commit()
    results = asyncio.run(reviews.collect(bindings))
    current = reviews.owner_context(db, ctx.membership.id)
    need(current, 'student')
    items = []
    for binding, result in zip(bindings, results, strict=True):
        try:
            reviews.scope_access(db, current, db.get(m.MasteryReviewScope, binding[0]), study=True)
        except HTTPException:
            continue
        items.extend(result or [])
    items.sort(key=lambda row: not row['due'])
    history = []
    for task in db.scalars(select(m.Task).join(m.Project).join(m.PersonalSpace).where(
            m.PersonalSpace.user_id == ctx.user.id, m.Task.kind == 'review').order_by(m.Task.created_at.desc())):
        try:
            s.task(db, current, task.id, active=False)
            s.no_active_mock(db, task.project_id)
        except HTTPException:
            continue
        history.append({'id': task.id, 'title': task.title, 'due_at': task.due_at, 'state': task.state})
    return {'enabled': True, 'items': items, 'history': history, 'pending': pending,
            'unavailable': any(r is None for r in results)}


def session(db, ctx, scope_id, operation='status', **fields):
    need(ctx, 'student')
    if not settings.deeptutor_mastery_reviews:
        fail(404, 'NOT_FOUND', '原生复习尚未启用')
    scope = db.get(m.MasteryReviewScope, scope_id)
    principal, _, _ = reviews.scope_access(db, ctx, scope, study=True)
    if not scope.path_id:
        fail(409, 'REVIEW_PENDING', '学习证据正在同步')
    path_id = scope.path_id
    db.commit()
    try:
        result = reviews.session_request(principal, path_id, operation, **fields)
    except tutor.TutorError:
        fail(503, 'DEEPTUTOR_REVIEW_UNAVAILABLE', 'DeepTutor 复习暂不可用，请稍后重试')
    current = reviews.owner_context(db, ctx.membership.id)
    need(current, 'student')
    reviews.scope_access(db, current, db.get(m.MasteryReviewScope, scope_id), study=True)
    return result


@router.get('/mastery-reviews/{scope_id}/session')
def session_status(scope_id: str, ctx=Depends(context), db=Depends(get_db)):
    return session(db, ctx, scope_id)


@router.post('/mastery-reviews/{scope_id}/session')
def session_action(scope_id: str, data: ReviewAction, ctx=Depends(context), db=Depends(get_db)):
    return session(db, ctx, scope_id, **data.model_dump())
