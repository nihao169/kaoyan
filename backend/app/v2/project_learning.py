"""Project authorization and durable commands for the native tutor.

Native turns own teaching and mastery. Platform transactions only authorize,
version bindings and enqueue commands; HTTP executes outside those transactions.
"""
import hashlib
import asyncio
import json
from datetime import timedelta
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select

from .. import models as old
from ..api_common import EnvelopeRoute, idempotent
from ..auth import context
from ..config import settings
from ..db import get_db, SessionLocal
from ..errors import fail
from . import models as m, service as s, tutor, tutor_index, tutor_records
from .routes import Input, project_view

router = APIRouter(route_class=EnvelopeRoute)
SCENES = {'chapter': '学生第一次学习这门课程。', 'final': '学生已经学过这门课程，现在准备期末考试。',
          'kaoyan': '学生准备考研，请结合目标与已提供的考试范围开展学习。'}


class LearningProfile(Input):
    revision: int
    scenario: Literal['chapter', 'final', 'kaoyan']
    course_name: str = Field(min_length=1, max_length=200)
    learning_goal: str = Field(default='', max_length=2000)
    exam_year: int | None = Field(default=None, ge=2026, le=2100)


class LearningCommand(Input):
    operation: Literal['message', 'answer', 'mode', 'read', 'notes'] = 'message'
    text: str = Field(default='', max_length=12000)
    expected_id: str = Field(default='', max_length=150)
    answers: dict[str, str] = Field(default_factory=dict, max_length=4)
    mode: Literal['outline', 'study', 'review'] | None = None
    material_id: str | None = None
    note_ids: list[str] = Field(default_factory=list, max_length=20)


def access(db, ctx, project_id, *, active=True):
    p = s.project(db, ctx, project_id, active=active)
    s.no_active_mock(db, p.id)
    materials = s.authorized_materials(db, ctx, p)
    return p, materials


def binding(db, p, *, current_only=False):
    current = db.scalar(select(m.ProjectLearning).where(m.ProjectLearning.project_id == p.id,
        m.ProjectLearning.scope_revision == p.scope_revision, m.ProjectLearning.plan_revision == p.revision))
    if current or current_only:
        return current
    # A goal/budget edit keeps the existing learning scene visible. Archiving
    # increments the scope once without changing its authorized materials.
    scope = p.scope_revision - 1 if p.state == 'archived' else p.scope_revision
    return db.scalar(select(m.ProjectLearning).where(m.ProjectLearning.project_id == p.id,
        m.ProjectLearning.scope_revision == scope).order_by(m.ProjectLearning.created_at.desc()))


def background(p):
    return json.dumps({'学习背景': SCENES[p.scenario], '课程': p.course_name, '目标': p.learning_goal,
        '考试年份': p.exam_year if p.scenario == 'kaoyan' else None, '目标日期': p.deadline,
        '每日分钟': p.daily_minutes, '目标分': p.target_score,
        '评价范围': '政治专项训练' if p.policy == 'kaoyan-politics-v1' else '通用课程训练，不代表官方考试评分'}, ensure_ascii=False)


def ensure_binding(db, ctx, p, materials):
    row = binding(db, p, current_only=True)
    if row:
        return row
    previous = db.scalar(select(m.ProjectLearning).where(m.ProjectLearning.project_id == p.id,
        m.ProjectLearning.scope_revision == p.scope_revision).order_by(m.ProjectLearning.created_at.desc()))
    _, legacy = s.accepted_mastery(db, p)
    token = hashlib.sha256(f'{p.id}:{p.scope_revision}'.encode()).hexdigest()[:32]
    path_id = previous.path_id if previous else legacy.get('path_id') or 'topic_zxp_' + token
    # Plan edits use the same path: outline revision preserves valid evidence.
    row = m.ProjectLearning(project_id=p.id, scope_revision=p.scope_revision, plan_revision=p.revision,
        path_id=path_id, session_id=previous.session_id if previous else legacy.get('session_id') or 'zx_learning_' + token,
        context={'background': background(p)})
    db.add(row)
    db.flush()
    return row


def bridge(principal, **fields):
    tutor.require_configuration()
    payload, signature = tutor.signed_assertion(principal, **fields)
    try:
        with httpx.Client(timeout=45, trust_env=False) as client:
            response = client.post(settings.deeptutor_url.rstrip('/') + '/internal/project-learning',
                json=payload, headers={'X-Zhixing-Signature': signature})
        if response.status_code in (404, 409, 422):
            fail(response.status_code, 'NATIVE_LEARNING_CONFLICT', '学习状态已变化或请求不适用，请刷新后继续')
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError('invalid tutor state')
        return result
    except (httpx.HTTPError, ValueError, tutor.TutorError):
        fail(503, 'NATIVE_LEARNING_UNAVAILABLE', 'DeepTutor 暂时不可用，学习现场已保留，请重试')


def native_call(owner, method, path, **kwargs):
    try:
        return asyncio.run(tutor.native_request(owner, method, path, **kwargs))
    except tutor.TutorError:
        fail(503, 'NATIVE_PRACTICE_UNAVAILABLE', '原生练习暂不可用，请刷新后重试')


def public_entry(item):
    return {key: item.get(key) for key in ('id', 'question', 'question_type', 'options', 'mastery_path_id')}


@router.get('/learning-projects/{project_id}/learning/practice')
def practice_list(project_id: str, ctx=Depends(context), db=Depends(get_db)):
    p, _ = access(db, ctx, project_id)
    row = binding(db, p)
    if not row:
        return {'items': [], 'total': 0}
    revision, scope, path_id = p.revision, p.scope_revision, row.path_id
    owner = tutor_index.principal(ctx.user.id, p.id)
    db.commit()
    result = native_call(owner, 'GET', '/api/question-notebook/entries',
        params={'mastery_path_id': path_id, 'limit': 100})
    db.expire_all()
    current, _ = access(db, ctx, project_id)
    if (current.revision, current.scope_revision) != (revision, scope):
        fail(409, 'SCOPE_CHANGED', '项目范围已变化，请刷新')
    items = [public_entry(item) for item in result.get('items', []) if item.get('mastery_path_id') == path_id]
    return {'items': items, 'total': result.get('total', len(items))}


class PracticeAnswer(Input):
    answer: str = Field(min_length=1, max_length=12000)
    version: int = Field(ge=0)
    rating: Literal['again', 'hard', 'good', 'easy'] = 'good'
    self_report: bool = False


def practice_entry(db, ctx, project_id, entry_id):
    p, _ = access(db, ctx, project_id)
    row = binding(db, p)
    if not row:
        fail(404, 'NOT_FOUND', '当前路径没有这道练习')
    path_id, revision, scope = row.path_id, p.revision, p.scope_revision
    owner = tutor_index.principal(ctx.user.id, p.id)
    db.commit()
    item = native_call(owner, 'GET', f'/api/question-notebook/practice/questions/{entry_id}')
    db.expire_all()
    p, _ = access(db, ctx, project_id)
    if (p.revision, p.scope_revision) != (revision, scope) or item['entry'].get('mastery_path_id') != path_id:
        fail(404, 'NOT_FOUND', '练习不属于当前资料范围')
    db.commit()
    return owner, item, revision, scope


@router.get('/learning-projects/{project_id}/learning/practice/{entry_id}')
def get_practice(project_id: str, entry_id: int, ctx=Depends(context), db=Depends(get_db)):
    _, item, _, _ = practice_entry(db, ctx, project_id, entry_id)
    return {'entry': public_entry(item['entry']), 'version': item['state'].get('version', 0)}


@router.post('/learning-projects/{project_id}/learning/practice/{entry_id}')
def answer_practice(project_id: str, entry_id: int, data: PracticeAnswer, request: Request,
                    ctx=Depends(context), db=Depends(get_db)):
    idem = request.headers.get('Idempotency-Key', '')
    if not idem or len(idem) > 150:
        fail(422, 'IDEMPOTENCY_KEY_REQUIRED', '请提供有效提交标识')
    owner, item, revision, scope = practice_entry(db, ctx, project_id, entry_id)
    if not data.self_report:
        verdict = native_call(owner, 'POST', f'/api/question-notebook/practice/questions/{entry_id}/check', body={'answer': data.answer})
        if verdict.get('correct') is None:
            fail(422, 'SELF_REPORT_REQUIRED', '此题需要自评，不能自动判定掌握')
        rating = 'good' if verdict['correct'] else 'again'
    else:
        rating = data.rating
    result = native_call(owner, 'POST', f'/api/question-notebook/practice/questions/{entry_id}/review',
        body={'answer': data.answer, 'version': data.version, 'rating': rating, 'self_report': data.self_report,
              'request_id': hashlib.sha256(f'{project_id}:{idem}'.encode()).hexdigest()})
    db.expire_all()
    p, _ = access(db, ctx, project_id)
    if (p.revision, p.scope_revision) != (revision, scope):
        fail(409, 'SCOPE_CHANGED', '资料范围已变化，请刷新')
    return {**result, 'correct_answer': item['entry'].get('correct_answer', ''),
            'explanation': item['entry'].get('explanation', ''), 'updates_mastery_path': False}


@router.put('/learning-projects/{project_id}/learning-profile')
def profile(project_id: str, data: LearningProfile, request: Request, ctx=Depends(context), db=Depends(get_db)):
    p, _ = access(db, ctx, project_id)
    def save():
        db.refresh(p, with_for_update=True)
        if p.revision != data.revision:
            fail(409, 'REVISION_CONFLICT', '项目信息已更新，请刷新')
        if data.scenario == 'kaoyan' and not data.exam_year:
            fail(422, 'EXAM_YEAR_REQUIRED', '请填写考研年份')
        p.scenario, p.course_name, p.learning_goal = data.scenario, data.course_name, data.learning_goal
        if data.exam_year:
            p.exam_year = data.exam_year
        p.policy = 'kaoyan-politics-v1' if data.course_name.strip() in ('政治', '考研政治') else 'general-mastery-v1'
        p.scene_confirmed = True
        p.revision += 1
        s.snapshot_plan(db, p, '确认学习背景，由 DeepTutor 组织教学；旧记录保留')
        return project_view(p)
    return idempotent(db, ctx, request, f'learning.profile:{p.id}', data.model_dump(), save)


def payload(db, ctx, p, materials, row):
    indexes = tutor_index.mappings(db, materials)
    ready = bool(materials) and all(x.id in indexes and indexes[x.id].state == 'ready' for x in materials)
    return {'path_id': row.path_id, 'session_id': row.session_id, 'background': background(p),
        'sources': [{'name': indexes[x.id].name, 'label': x.title} for x in materials] if ready else [],
        'ready': ready}


@router.get('/learning-projects/{project_id}/learning')
def status(project_id: str, ctx=Depends(context), db=Depends(get_db)):
    p, materials = access(db, ctx, project_id, active=False)
    if not p.scene_confirmed:
        return {'state': 'profile_required', 'messages': [], 'question': None}
    row = binding(db, p)
    if not row:
        return {'state': 'not_started', 'messages': [], 'question': None, 'has_materials': bool(materials)}
    fields = payload(db, ctx, p, materials, row)
    ids = (row.id, p.scope_revision, p.revision)
    command = db.scalar(select(m.AIRun).where(m.AIRun.project_id == p.id, m.AIRun.backend == 'project_learning',
        m.AIRun.scope_revision == p.scope_revision,
        m.AIRun.metrics['plan_revision'].as_integer() == p.revision).order_by(m.AIRun.created_at.desc(), m.AIRun.id.desc()))
    command_view = {'id': command.id, 'state': command.state, 'error': command.error} if command else None
    owner = tutor_index.principal(ctx.user.id, p.id)
    db.commit()
    result = bridge(owner, operation='status', **fields)
    db.expire_all()
    current, _ = access(db, ctx, project_id, active=False)
    if (current.scope_revision, current.revision) != ids[1:]:
        fail(409, 'SCOPE_CHANGED', '资料或学习背景已变化，请刷新')
    return {**result, 'command': command_view, 'has_materials': bool(materials), 'writable': current.state == 'active'}


@router.post('/learning-projects/{project_id}/learning', status_code=202)
def command(project_id: str, data: LearningCommand, request: Request, ctx=Depends(context), db=Depends(get_db)):
    p, materials = access(db, ctx, project_id)
    if not p.scene_confirmed:
        fail(409, 'PROFILE_REQUIRED', '请先确认学习场景、课程和目标')
    if len(materials) > 16:
        fail(422, 'TOO_MANY_SOURCES', '每条学习路径最多选择16份资料，请先整理项目资料')
    if data.operation == 'mode' and data.mode is None:
        fail(422, 'MODE_REQUIRED', '请选择大纲、学习或复习模式')
    native_notes = None
    if data.operation == 'notes' and p.native_records:
        version = (p.revision, p.scope_revision)
        note_owner = ctx.user.id
        db.commit()
        native_notes = tutor_records.native_records(note_owner, project_id)
        db.expire_all()
        p, materials = access(db, ctx, project_id)
        if (p.revision, p.scope_revision) != version:
            fail(409, 'SCOPE_CHANGED', '项目范围已变化，请刷新')
    def save():
        db.refresh(p, with_for_update=True)
        if db.scalar(select(m.AIRun.id).where(m.AIRun.project_id == p.id, m.AIRun.backend == 'project_learning',
                m.AIRun.state.in_(['queued', 'running'])).limit(1)):
            fail(409, 'LEARNING_BUSY', '上一条请求正在处理，请稍候')
        row = ensure_binding(db, ctx, p, materials)
        fields = payload(db, ctx, p, materials, row)
        body = data.model_dump()
        if data.operation != 'message' and not fields['ready']:
            fail(409, 'MATERIAL_REQUIRED', '请先添加资料并完成助教索引')
        if data.operation == 'message' and not data.text.strip():
            fail(422, 'MESSAGE_REQUIRED', '请填写发给助教的话')
        if data.operation == 'notes':
            records = native_notes if native_notes is not None else tutor_records.local_records(db, p.id)
            visible = {x['id']: x for x in tutor_records.visible(db, ctx, p.id, records)}
            if not data.note_ids or any(note_id not in visible for note_id in data.note_ids):
                fail(404, 'NOTE_NOT_FOUND', '请选择当前项目可访问的笔记')
            body['notes'] = [{'title': visible[n]['title'], 'body': visible[n]['body'][:4000]} for n in data.note_ids]
        if data.operation == 'read':
            material = next((x for x in materials if x.id == data.material_id), None)
            if not material:
                fail(404, 'MATERIAL_NOT_FOUND', '请选择当前项目可访问的资料')
        run = m.AIRun(project_id=p.id, membership_id=ctx.membership.id, scope_revision=p.scope_revision,
            kind='learning', backend='project_learning', prompt=json.dumps(body, ensure_ascii=False),
            metrics={'binding_id': row.id, 'plan_revision': p.revision})
        db.add(run)
        db.flush()
        return {'run_id': run.id}
    return idempotent(db, ctx, request, f'learning.command:{p.id}', data.model_dump(), save)


@router.post('/learning-projects/{project_id}/learning/retry')
def retry(project_id: str, ctx=Depends(context), db=Depends(get_db)):
    p, _ = access(db, ctx, project_id)
    run = db.scalar(select(m.AIRun).where(m.AIRun.project_id == p.id, m.AIRun.backend == 'project_learning')
        .order_by(m.AIRun.created_at.desc(), m.AIRun.id.desc()).with_for_update())
    if not run or run.state != 'failed' or run.scope_revision != p.scope_revision or run.metrics['plan_revision'] != p.revision:
        fail(409, 'RETRY_NOT_ALLOWED', '当前没有可恢复的学习请求')
    run.state, run.error = 'queued', ''
    db.commit()
    return {'run_id': run.id}


def tick():
    """Replay only the same downstream command identifier after uncertain delivery."""
    from .worker import context_for
    with SessionLocal.begin() as db:
        for run in db.scalars(select(m.AIRun).where(m.AIRun.backend == 'project_learning',
                m.AIRun.state == 'running', m.AIRun.lease_until < s.clock().isoformat()).with_for_update(skip_locked=True)):
            run.state = 'queued'
        run = db.scalar(select(m.AIRun).where(m.AIRun.backend == 'project_learning', m.AIRun.state == 'queued')
            .order_by(m.AIRun.created_at).with_for_update(skip_locked=True).limit(1))
        if not run:
            return False
        run.state, run.lease_until = 'running', (s.clock() + timedelta(seconds=120)).isoformat()
        run_id = run.id
    try:
        with SessionLocal() as db:
            run = db.get(m.AIRun, run_id)
            p = db.get(m.Project, run.project_id)
            ctx = context_for(db, p, run.membership_id)
            p, materials = access(db, ctx, p.id)
            if p.scope_revision != run.scope_revision or p.revision != run.metrics['plan_revision']:
                raise tutor.TutorError('SCOPE_CHANGED：资料或学习背景已变化')
            row = db.get(m.ProjectLearning, run.metrics['binding_id'])
            fields = payload(db, ctx, p, materials, row)
            body = json.loads(run.prompt)
            owner = tutor_index.principal(ctx.user.id, p.id)
            if body['operation'] == 'read':
                material = next(x for x in materials if x.id == body['material_id'])
                index = tutor_index.mappings(db, [material])[material.id]
                fields['reader'] = {'name': index.name, 'title': material.title, 'text': material.text}
            db.commit()
        result = bridge(owner, submission_id=run_id, **fields, **body)
        with SessionLocal.begin() as db:
            run = db.get(m.AIRun, run_id, with_for_update=True)
            run.state, run.result, run.error = 'succeeded', result, ''
    except Exception as exc:
        from fastapi import HTTPException
        with SessionLocal.begin() as db:
            run = db.get(m.AIRun, run_id, with_for_update=True)
            detail = exc.detail if isinstance(exc, HTTPException) else None
            run.state, run.error = 'failed', (detail.get('message', '') if isinstance(detail, dict) else str(exc))[:1000]
    return True
