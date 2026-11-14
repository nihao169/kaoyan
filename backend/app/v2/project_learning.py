"""Project authorization and durable commands for the native tutor.

Native turns own teaching and mastery. Platform transactions only authorize,
version bindings and enqueue commands; HTTP executes outside those transactions.
"""
import asyncio
import hashlib
import json
import logging
from datetime import timedelta
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select

from .. import models as old
from ..api_common import EnvelopeRoute, idempotent
from ..auth import context, need
from ..config import settings
from ..db import get_db, SessionLocal
from ..errors import fail
from . import learning_batches as batches, learning_guide as guide, models as m, search, service as s, tutor, tutor_index, tutor_records
from .routes import Input, project_view
from .validation import QuestionCandidate

router = APIRouter(route_class=EnvelopeRoute)
logger = logging.getLogger(__name__)
SCENES = {'chapter': '学生第一次学习这门课程。', 'final': '学生已经学过这门课程，现在准备期末考试。',
          'kaoyan': '学生准备考研，请结合目标与已提供的考试范围开展学习。'}


class LearningProfile(Input):
    revision: int
    scenario: Literal['chapter', 'final', 'kaoyan']
    course_name: str = Field(min_length=1, max_length=200)
    learning_goal: str = Field(default='', max_length=2000)
    exam_year: int | None = Field(default=None, ge=2026, le=2100)


class LearningCommand(Input):
    operation: Literal['message', 'answer', 'mode', 'read', 'notes', 'guided'] = 'message'
    text: str = Field(default='', max_length=12000)
    expected_id: str = Field(default='', max_length=150)
    answers: dict[str, str] = Field(default_factory=dict, max_length=4)
    mode: Literal['outline', 'study', 'review'] | None = None
    material_id: str | None = None
    note_ids: list[str] = Field(default_factory=list, max_length=20)
    action_id: str = Field(default='', max_length=60)
    review_objective: str = Field(default='', max_length=150)
    chapter_id: str = Field(default='', max_length=150)
    counts: dict[Literal['single', 'multiple', 'essay'], int] = Field(default_factory=dict)


class ScopeSection(Input):
    material_id: str
    title: str = Field(min_length=1, max_length=160)


class StudyScope(Input):
    revision: int
    text: str = Field(default='', max_length=2000)
    sections: list[ScopeSection] = Field(default_factory=list, max_length=30)
    material_ids: list[str] = Field(default_factory=list, max_length=16)
    file_id: str | None = None


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
        context={'background': background(p), 'source_ids': [x.id for x in materials]})
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
    except (httpx.HTTPError, ValueError, tutor.TutorError) as exc:
        logger.warning('DeepTutor learning bridge failed for %s: %s', fields.get('operation'), type(exc).__name__)
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
        if p.scenario != data.scenario or p.course_name != data.course_name or (data.exam_year and p.exam_year != data.exam_year):
            p.scope_revision += 1
            p.study_scope = {}
        p.scenario, p.course_name, p.learning_goal = data.scenario, data.course_name, data.learning_goal
        if data.exam_year:
            p.exam_year = data.exam_year
        p.policy = 'kaoyan-politics-v1' if data.course_name.strip() in ('政治', '考研政治') else 'general-mastery-v1'
        p.scene_confirmed = True
        p.revision += 1
        s.snapshot_plan(db, p, '确认学习背景，由 DeepTutor 组织教学；旧记录保留')
        return project_view(p)
    return idempotent(db, ctx, request, f'learning.profile:{p.id}', data.model_dump(), save)


@router.put('/learning-projects/{project_id}/study-scope')
def update_scope(project_id: str, data: StudyScope, request: Request, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, lock=True)
    s.no_active_mock(db, p.id)

    def save():
        if p.scenario != 'final' or p.revision != data.revision:
            fail(409, 'REVISION_CONFLICT', '请刷新期末项目后再确认考试范围')
        if sum((bool(data.text.strip()), bool(data.sections or data.material_ids), bool(data.file_id))) != 1:
            fail(422, 'SCOPE_REQUIRED', '请选择已上传的资料或其中的章节')
        materials = s.authorized_materials(db, ctx, p)
        annual_ids = {r.material_id for r in guide.annual_rows(db, p, materials)}
        books = [x for x in materials if x.id not in annual_ids]
        options = {(x['id'], title) for x in guide.scope_options(books) for title in x['sections']}
        book_ids = {x.id for x in books}
        if (data.file_id and data.file_id not in book_ids) or not set(data.material_ids) <= book_ids:
            fail(422, 'SCOPE_FILE_REQUIRED', '请选择本项目中已导入的资料')
        if any((x.material_id, x.title) not in options for x in data.sections):
            fail(422, 'SCOPE_SECTION_INVALID', '请从当前讲义选择章节')
        if len(set(data.material_ids) | {x.material_id for x in data.sections}) > 16:
            fail(422, 'SCOPE_TOO_MANY_MATERIALS', '考试范围最多选择 16 份资料')
        value = {key: value for key, value in payload.items() if key != 'revision'}
        value['text'] = data.text.strip()
        if p.study_scope != value:
            p.study_scope = value
            p.revision += 1
            p.scope_revision += 1
            s.snapshot_plan(db, p, '确认期末考试范围')
        return project_view(p)

    payload = data.model_dump(exclude={'material_ids'} if not data.material_ids else None)
    return idempotent(db, ctx, request, f'learning.scope:{p.id}', payload, save)


def payload(db, ctx, p, materials, row):
    prep, sources = guide.preparation(db, p, materials)
    indexes = tutor_index.mappings(db, sources)
    ready = prep['ready']
    return {'path_id': row.path_id, 'session_id': row.session_id, 'background': background(p),
        'sources': [{'name': indexes[x.id].name, 'label': x.title} for x in sources] if ready else [],
        'ready': ready}


def guided_runs(db, p, row, native):
    if not row:
        return {}
    found = {}
    for run in db.scalars(select(m.AIRun).where(m.AIRun.project_id == p.id, m.AIRun.backend == 'project_learning',
            m.AIRun.scope_revision == row.scope_revision, m.AIRun.state == 'succeeded',
            m.AIRun.metrics['action_id'].as_string().is_not(None)).order_by(m.AIRun.created_at.desc(), m.AIRun.id.desc())):
        if native.get('state') == 'failed' and native.get('turn_id') and native['turn_id'] == run.result.get('turn_id'):
            continue
        found.setdefault(run.metrics['action_id'], run)
    return found


def due_items(native, daily=None):
    planned = {item['id'] for item in daily.data['items'] if item.get('review') and not item.get('result')} \
        if daily and daily.data['state'] in ('ready', 'active', 'paused') else set()
    items = {}
    for review in (native.get('curriculum') or {}).get('reviews', []):
        objective = review.get('knowledge_point_id')
        if objective and review.get('due'):
            items.setdefault(objective, {
                'id': objective, 'name': review.get('knowledge_point_name') or
                batches.objectives(native).get(objective, {}).get('name', objective),
                'in_daily_plan': objective in planned,
                'can_start': review.get('can_start_review', True),
            })
    return list(items.values())


def guided_view(db, p, prep, row, result):
    exams = guide.paper_attempts(db, p, {paper['id'] for paper in prep['papers']})
    runs = guided_runs(db, p, row, result)
    stage = batches.stage(db, p) if p.scenario != 'chapter' else None
    flow = guide.workflow(p, prep, result, runs, exams, stage=stage)
    if stage and stage.data['state'] in ('active', 'paused') and result.get('state') in ('idle', 'failed'):
        flow['actions'] = [{'id': stage.action, 'label': '继续当前检查'}]
    if prep['ready'] and p.scenario == 'chapter' and batches.objectives(result):
        flow['actions'] = [{'id': action, 'label': guide.ACTIONS[action][0]}
                           for action in ('chapter_continue', 'chapter_practice', 'chapter_summary')]
        daily = batches.today(db, p)
        flow['step'] = 3 if daily and daily.data['state'] in ('completed', 'budget_reached') else 2
        if not daily:
            flow['actions'] = []
    return flow


def history_bindings(db, p, materials):
    allowed = {material.id for material in materials}
    found = {}
    for row in db.scalars(select(m.ProjectLearning).where(m.ProjectLearning.project_id == p.id,
            m.ProjectLearning.scope_revision != p.scope_revision).order_by(m.ProjectLearning.created_at.desc())):
        source_ids = row.context.get('source_ids')
        if source_ids and set(source_ids) <= allowed:
            found.setdefault(row.path_id, row)
    return found


@router.get('/learning-projects/{project_id}/learning-history')
def history(project_id: str, ctx=Depends(context), db=Depends(get_db)):
    p, materials = access(db, ctx, project_id, active=False)
    return [{'id': row.id, 'created_at': row.created_at} for row in history_bindings(db, p, materials).values()]


@router.get('/learning-projects/{project_id}/learning-history/{binding_id}')
def history_detail(project_id: str, binding_id: str, ctx=Depends(context), db=Depends(get_db)):
    p, materials = access(db, ctx, project_id, active=False)
    def permitted(rows):
        return next((row for row in rows.values() if row.id == binding_id), None)

    row = permitted(history_bindings(db, p, materials))
    if not row:
        fail(404, 'NOT_FOUND', '此学习路径不在当前授权资料范围内')
    fields = {'path_id': row.path_id, 'session_id': row.session_id, 'background': '',
              'ready': True, 'sources': []}
    owner = tutor_index.principal(ctx.user.id, p.id)
    db.commit()
    result = bridge(owner, operation='status', **fields)
    db.expire_all()
    p, materials = access(db, ctx, project_id, active=False)
    if not permitted(history_bindings(db, p, materials)):
        fail(404, 'NOT_FOUND', '此学习路径不在当前授权资料范围内')
    curriculum = result.get('curriculum') or {}
    return {'map': curriculum.get('map'), 'evidence': result.get('evidence')}


@router.get('/learning-projects/{project_id}/learning')
def status(project_id: str, ctx=Depends(context), db=Depends(get_db)):
    p, materials = access(db, ctx, project_id, active=False)
    if not p.scene_confirmed:
        return {'state': 'profile_required', 'messages': [], 'question': None}
    row = binding(db, p)
    prep, sources = guide.preparation(db, p, materials)
    allowed_sources = {material.id for material in materials}
    if not row or not set(row.context.get('source_ids') or []) <= allowed_sources:
        return {'state': 'not_started' if prep['ready'] else 'preparing', 'messages': [], 'question': None,
                'preparation': prep, 'workflow': guided_view(db, p, prep, row, {})}
    fields = payload(db, ctx, p, materials, row)
    # The bridge also uses this flag to expose saved path state. An authorized
    # status read needs no live retrieval, even while its indexes are offline.
    fields['ready'] = True
    ids = (row.id, p.scope_revision, p.revision)
    bound_sources = set(row.context.get('source_ids') or [])
    command = db.scalar(select(m.AIRun).where(m.AIRun.project_id == p.id, m.AIRun.backend == 'project_learning',
        m.AIRun.scope_revision == p.scope_revision,
        m.AIRun.metrics['plan_revision'].as_integer() == p.revision).order_by(m.AIRun.created_at.desc(), m.AIRun.id.desc()))
    command_view = {'id': command.id, 'state': command.state, 'error': command.error,
                    'label': guide.ACTIONS.get(command.metrics.get('action_id'), ('学习请求',))[0]} if command else None
    owner = tutor_index.principal(ctx.user.id, p.id)
    db.commit()
    result = bridge(owner, operation='status', **fields)
    if command_view and (result.get('followup') or {}).get('submission_id') == command_view['id']:
        command_view['label'] = '助教追问'
    if command_view and any(turn.get('submission_id') == command_view['id'] and turn.get('turn_id')
                            for turn in (result, result.get('followup') or {})):
        if command_view['state'] == 'failed':
            db.scalar(select(m.Project.id).where(m.Project.id == project_id).with_for_update())
            recovered = db.get(m.AIRun, command_view['id'], with_for_update=True)
            if recovered.state == 'failed' and recovered.error.startswith('DeepTutor 暂时不可用'):
                recovered.state, recovered.result, recovered.error = 'succeeded', result, ''
                command_view.update(state='succeeded', error='')
                db.commit()
    db.expire_all()
    current, current_materials = access(db, ctx, project_id, active=False)
    if (current.scope_revision, current.revision) != ids[1:]:
        fail(409, 'SCOPE_CHANGED', '资料或学习背景已变化，请刷新')
    if not bound_sources <= {material.id for material in current_materials}:
        fail(403, 'MATERIAL_REVOKED', '学习记录所用的资料已不可访问')
    prep, sources = guide.preparation(db, current, current_materials)
    daily = stage = None
    practice = db.scalar(select(m.AIRun).where(m.AIRun.project_id == current.id,
        m.AIRun.backend == 'project_learning', m.AIRun.scope_revision == current.scope_revision,
        m.AIRun.metrics['action_id'].as_string() == 'chapter_practice', m.AIRun.state == 'succeeded'
    ).order_by(m.AIRun.created_at.desc(), m.AIRun.id.desc()).limit(1)) if current.scenario == 'chapter' else None
    if not prep['ready']:
        daily = batches.today(db, current) if current.scenario == 'chapter' else None
        stage = batches.stage(db, current) if current.scenario != 'chapter' else None
    elif batches.objectives(result):
        db.refresh(current, with_for_update=True)
        if (current.scope_revision, current.revision) != ids[1:]:
            fail(409, 'SCOPE_CHANGED', '资料或学习背景已变化，请刷新')
        busy = db.scalar(select(m.AIRun.id).where(m.AIRun.project_id == current.id,
            m.AIRun.backend == 'project_learning', m.AIRun.state.in_(['queued', 'running'])).limit(1))
        if current.scenario == 'chapter':
            daily = batches.today(db, current)
            if daily and daily.data['state'] == 'failed' and not busy and current.state == 'active':
                planner = db.scalar(select(m.AIRun).where(m.AIRun.project_id == current.id,
                    m.AIRun.backend == 'project_learning', m.AIRun.metrics['batch_id'].as_string() == daily.id
                ).order_by(m.AIRun.created_at.desc(), m.AIRun.id.desc()).limit(1))
                if planner and planner.metrics['plan_revision'] != current.revision:
                    db.delete(daily)
                    db.flush()
                    daily = None
            if not daily or result.get('recent_evidence'):
                old = batches.previous_day(db, current)
                if old and old.data['state'] == 'active':
                    old.data = {**old.data, 'state': 'paused', 'activity_at': None}
                if old:
                    batches.sync(db, current, row, old, result, True)
            if not daily and not busy and current.state == 'active':
                daily = batches.create_today(db, current, row, ctx.membership.id, result)
            if current.state == 'active':
                batches.sync(db, current, row, daily, result, busy or result.get('reading'), advance=False)
        else:
            stage = batches.stage(db, current)
            if current.state == 'active':
                batches.sync(db, current, row, stage, result, busy, advance=False)
        if busy and (not command_view or command_view['id'] != busy):
            command_view = {'id': busy, 'state': 'queued', 'error': '', 'label': '学习请求'}
        db.commit()
    supported = batches.supported_objectives(result, sources, prep['scope']) if current.scenario == 'final' else None
    return {**result, 'command': command_view, 'preparation': prep,
            'daily_plan': batches.batch_view(daily), 'stage': batches.batch_view(stage),
            'due_reviews': due_items(result, daily) if current.state == 'active' and prep['ready'] else [],
            'chapter_practice_id': practice.result.get('assessment_id') if practice else None,
            'stage_sizes': {key: len(batches.targets(result, key, supported)) for key in batches.STAGES},
            'workflow': guided_view(db, current, prep, row, result),
            'writable': current.state == 'active' and prep['ready']}


@router.post('/learning-projects/{project_id}/learning/activity')
def study_activity(project_id: str, ctx=Depends(context), db=Depends(get_db)):
    p, _ = access(db, ctx, project_id)
    db.refresh(p, with_for_update=True)
    batch = batches.today(db, p)
    if p.scenario == 'chapter' and batch and batch.data['state'] == 'active':
        latest = db.scalar(select(m.AIRun).where(m.AIRun.project_id == p.id,
            m.AIRun.backend == 'project_learning').order_by(m.AIRun.created_at.desc(), m.AIRun.id.desc()).limit(1))
        if latest and latest.state in ('queued', 'running'):
            batch.data = {**batch.data, 'activity_at': None}
        else:
            batches.activity(batch)
        db.commit()
    return {'reached': bool(batch and batch.data.get('budget')
                           and batch.data.get('seconds', 0) >= batch.data['budget'] * 60)}


@router.post('/learning-projects/{project_id}/learning', status_code=202)
def command(project_id: str, data: LearningCommand, request: Request, ctx=Depends(context), db=Depends(get_db)):
    p, materials = access(db, ctx, project_id)
    if not p.scene_confirmed:
        fail(409, 'PROFILE_REQUIRED', '请先确认学习场景、课程和目标')
    idem = request.headers.get('Idempotency-Key')
    operation = f'learning.command:{p.id}'
    if idem and db.scalar(select(old.IdempotencyRecord.id).where(
            old.IdempotencyRecord.membership_id == ctx.membership.id,
            old.IdempotencyRecord.operation == operation, old.IdempotencyRecord.key == idem)):
        return idempotent(db, ctx, request, operation, data.model_dump(), lambda: None)
    prep, sources = guide.preparation(db, p, materials)
    if not prep['ready']:
        fail(409, 'MATERIAL_REQUIRED', '请先补齐当前场景的必备资料并完成索引')
    if data.operation == 'mode' and data.mode is None:
        fail(422, 'MODE_REQUIRED', '请选择大纲、学习或复习模式')
    snapshot = (p.revision, p.scope_revision)
    native = {}
    existing = binding(db, p)
    local_pause = data.operation == 'guided' and data.action_id in ('chapter_pause', 'chapter_summary') and p.scenario == 'chapter'
    if data.operation in ('guided', 'answer') and existing and not local_pause:
        fields = payload(db, ctx, p, materials, existing)
        owner = tutor_index.principal(ctx.user.id, p.id)
        db.commit()
        native = bridge(owner, operation='status', **fields)
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
        s.no_active_mock(db, p.id)
        if (p.revision, p.scope_revision) != snapshot or p.state != 'active':
            fail(409, 'SCOPE_CHANGED', '资料或学习背景已变化，请刷新')
        busy = db.scalar(select(m.AIRun.id).where(m.AIRun.project_id == p.id, m.AIRun.backend == 'project_learning',
                m.AIRun.state.in_(['queued', 'running'])).limit(1))
        batch = batches.today(db, p) if p.scenario == 'chapter' else batches.stage(db, p)
        action = data.action_id if data.operation == 'guided' else ''
        if action in batches.CHAPTER and p.scenario == 'chapter' and (batches.objectives(native) or (local_pause and batch)):
            if action == 'chapter_pause':
                if batch and batch.data['state'] == 'active':
                    batch.data = {**batch.data, 'state': 'paused', 'activity_at': None}
                return {'paused': True}
            if action == 'chapter_summary':
                if batch and batch.data['state'] == 'active':
                    batch.data = {**batch.data, 'state': 'paused', 'activity_at': None}
                return {'summary': batches.batch_view(batch)}
            if busy:
                fail(409, 'LEARNING_BUSY', '上一条请求正在处理，请稍候')
            row = ensure_binding(db, ctx, p, sources)
            if action == 'chapter_practice':
                chapter = next((x for x in batches.modules(native) if x['id'] == data.chapter_id), None)
                if not chapter or not 1 <= sum(data.counts.values()) <= 10 or any(x < 0 for x in data.counts.values()):
                    fail(422, 'PRACTICE_SELECTION', '请选择章节并设置合计 1–10 道题')
                if batch and batch.data['state'] == 'active':
                    batch.data = {**batch.data, 'state': 'paused', 'activity_at': None}
                run = batches.queue(db, p, row, ctx.membership.id, {
                    'operation': 'chapter_practice', 'topic': chapter['name'], 'counts': data.counts,
                    'points': [item['name'] for item in chapter.get('knowledge_points', [])],
                }, action_id=action)
                return {'run_id': run.id}
            if not batch or batch.data['state'] not in ('ready', 'active', 'paused'):
                fail(409, 'DAILY_PLAN_NOT_READY', '当前没有可继续的今日任务')
            if native.get('reading'):
                fail(409, 'READING_ACTIVE', '请先返回引导学习，再继续今日任务')
            batch.data = {**batch.data, 'state': 'active', 'activity_at': None, 'error': ''}
            queued = batches.sync(db, p, row, batch, native, False, resume=True)
            return {'run_id': queued.id} if queued else {'continued': True}
        if busy:
            fail(409, 'LEARNING_BUSY', '上一条请求正在处理，请稍候')
        row = ensure_binding(db, ctx, p, sources)
        body = data.model_dump(exclude={'action_id', 'chapter_id', 'counts', 'review_objective'})
        metrics = {}
        if data.operation == 'guided':
            flow = guided_view(db, p, prep, row, native)
            available = {x['id'] for x in flow['actions']}
            if action == 'due_review':
                due = [item for item in due_items(native, batch if p.scenario == 'chapter' else None)
                       if not item['in_daily_plan'] and item['can_start']]
                selected = next((item for item in due if not data.review_objective or item['id'] == data.review_objective), None)
                if not selected or native.get('reading') or (batch and p.scenario != 'chapter'
                        and batch.data['state'] in ('active', 'paused')):
                    fail(409, 'REVIEW_NOT_READY', '请先完成当前学习步骤，或从今日任务开始复习')
                available.add(action)
                body['objective'] = selected['id']
                metrics['review_objective'] = selected['id']
                if p.scenario == 'chapter' and batch and batch.data['state'] == 'active':
                    batch.data = {**batch.data, 'state':'paused', 'activity_at':None}
            if native.get('state') not in (None, 'idle', 'failed') or action not in available:
                fail(409, 'ACTION_NOT_READY', '请完成当前题卡或阶段，再继续')
            label, mode, prompt = guide.ACTIONS[data.action_id]
            if flow['confirm_outline'] and mode == 'outline':
                label, prompt = '确认并保存大纲', '我确认刚才的大纲。请通过原生大纲工具保存已确认方案。'
            scope = prep['scope']
            context_text = json.dumps({'已确认考试范围': scope,
                '考试范围文件': next((x.title for x in sources if x.id == scope.get('file_id')), None),
                '纳入范围的整份资料': [x.title for x in sources if x.id in scope.get('material_ids', [])],
                '可用资料': [x.title for x in sources]}, ensure_ascii=False)[:5000]
            operation = 'mode'
            if action in batches.STAGES and batches.objectives(native):
                if batch and batch.action == action and batch.data['state'] in ('active', 'paused'):
                    batch.data = {**batch.data, 'state': 'active', 'error': ''}
                    queued = batches.sync(db, p, row, batch, native, False, resume=True)
                    return {'run_id': queued.id} if queued else {'continued': True}
                supported = batches.supported_objectives(native, sources, scope) if p.scenario == 'final' else None
                items = batches.targets(native, action, supported)
                batch = batches.create_stage(db, p, ctx.membership.id, action, context_text, items)
                queued = batches.sync(db, p, row, batch, native, False)
                if not queued:
                    fail(409, 'ACTION_NOT_READY', '请等待助教结束当前操作')
                return {'run_id': queued.id}
            if action in ('final_weakness', 'final_remediate', 'final_checklist', 'kaoyan_coverage', 'chapter_summary'):
                operation = 'brief'
                context_text += '\n学习大纲：' + json.dumps([
                    {'id': point['id'], 'name': point['name'], 'status': point.get('status')}
                    for point in batches.objectives(native).values()
                ], ensure_ascii=False)[:5000]
                context_text += '\n当前学习进展：' + json.dumps(native.get('recent_evidence', [])[-30:], ensure_ascii=False)
                if p.scenario == 'final':
                    context_text += '\n最近完成的摸底和复测：' + json.dumps(
                        batches.stage_results(db, p, ('final_diagnose', 'final_retest')), ensure_ascii=False)
            if data.action_id in ('kaoyan_analyze', 'kaoyan_review'):
                exams = guide.paper_attempts(db, p, {paper['id'] for paper in prep['papers']})
                exam = exams['practice' if data.action_id == 'kaoyan_analyze' else 'mock']
                context_text += '\n已交卷作答摘要：' + guide.assessment_evidence(db, exam)
                operation = 'brief'
                metrics['assessment_id'] = exam.id
            body.update(operation=operation, mode=mode, text=label, guidance=(prompt + '\n' + context_text)[:16000])
            metrics.update(action_id=data.action_id, evidence_count=(native.get('evidence') or {}).get('count', 0))
        if data.operation == 'message' and not data.text.strip():
            fail(422, 'MESSAGE_REQUIRED', '请填写发给助教的话')
        if data.operation == 'notes':
            records = native_notes if native_notes is not None else tutor_records.local_records(db, p.id)
            visible = {x['id']: x for x in tutor_records.visible(db, ctx, p.id, records)}
            if not data.note_ids or any(note_id not in visible for note_id in data.note_ids):
                fail(404, 'NOTE_NOT_FOUND', '请选择当前项目可访问的笔记')
            body['notes'] = [{'title': visible[n]['title'], 'body': visible[n]['body'][:4000]} for n in data.note_ids]
        if data.operation == 'read':
            material = next((x for x in sources if x.id == data.material_id), None)
            if not material:
                fail(404, 'MATERIAL_NOT_FOUND', '请选择当前项目可访问的资料')
            if batch and batch.action == 'chapter_continue' and batch.data['state'] == 'active':
                batch.data = {**batch.data, 'state': 'paused', 'activity_at': None}
        if data.operation == 'answer':
            if native.get('mode') == 'review':
                metrics['review_answer'] = True
            elif batch and any(item.get('review') and item.get('question_id') == data.expected_id
                               for item in batch.data['items']):
                metrics['review_answer'] = True
        if data.operation == 'answer' and batch:
            if batch.action == 'chapter_continue' and batch.data['state'] == 'paused' and any(
                    item.get('question_id') == data.expected_id and not item.get('result') for item in batch.data['items']):
                fail(409, 'LEARNING_PAUSED', '请先继续学习，再提交当前题卡')
            metrics['batch_id'] = batch.id
        run = batches.queue(db, p, row, ctx.membership.id, body, **metrics)
        return {'run_id': run.id}
    db.refresh(p, with_for_update=True)
    return idempotent(db, ctx, request, operation, data.model_dump(), save)


@router.post('/learning-projects/{project_id}/learning/retry')
def retry(project_id: str, ctx=Depends(context), db=Depends(get_db)):
    p, materials = access(db, ctx, project_id)
    db.refresh(p, with_for_update=True)
    if not guide.preparation(db, p, materials)[0]['ready']:
        fail(409, 'MATERIAL_REQUIRED', '请先补齐当前场景的必备资料并完成索引')
    run = db.scalar(select(m.AIRun).where(m.AIRun.project_id == p.id, m.AIRun.backend == 'project_learning')
        .order_by(m.AIRun.created_at.desc(), m.AIRun.id.desc()).with_for_update())
    if not run or run.state != 'failed' or run.scope_revision != p.scope_revision or run.metrics['plan_revision'] != p.revision:
        fail(409, 'RETRY_NOT_ALLOWED', '当前没有可恢复的学习请求')
    run.state, run.error = 'queued', ''
    batch = db.get(m.LearningBatch, run.metrics['batch_id']) if run.metrics.get('batch_id') else None
    if batch and json.loads(run.prompt)['operation'] == 'daily_plan':
        if batch.key != batches.day():
            fail(409, 'DAILY_PLAN_EXPIRED', '该计划已过期，请刷新查看今天的安排')
        batch.data = {**batch.data, 'state': 'planning', 'error': ''}
        if run.metrics.get('regenerate_plan'):
            run.metrics = {**run.metrics, 'regenerate_plan': False,
                           'plan_attempt': run.metrics.get('plan_attempt', 0) + 1}
    elif batch and run.metrics.get('objective') and batch.action == 'chapter_continue':
        if batch.key != batches.day() or batch.data['state'] in ('completed', 'budget_reached'):
            fail(409, 'DAILY_PLAN_EXPIRED', '该任务已经收尾，请刷新学习页')
        batch.data = {**batch.data, 'state': 'active', 'error': '', 'activity_at': None}
    db.commit()
    return {'run_id': run.id}


def tick():
    """Replay only the same downstream command identifier after uncertain delivery."""
    from .worker import context_for
    from . import personal_learning as personal
    with SessionLocal.begin() as db:
        for run in db.scalars(select(m.AIRun).where(m.AIRun.backend.in_(['project_learning', personal.BACKEND]),
                m.AIRun.state == 'running', m.AIRun.lease_until < s.clock().isoformat()).with_for_update(skip_locked=True)):
            run.state = 'queued'
        run = db.scalar(select(m.AIRun).where(m.AIRun.backend.in_(['project_learning', personal.BACKEND]), m.AIRun.state == 'queued')
            .order_by(m.AIRun.created_at).with_for_update(skip_locked=True).limit(1))
        if not run:
            return False
        lease_seconds = max(120, settings.deeptutor_timeout + 30)
        run.state, run.lease_until = 'running', (s.clock() + timedelta(seconds=lease_seconds)).isoformat()
        run_id = run.id
        lease = run.lease_until
    try:
        with SessionLocal() as db:
            run = db.get(m.AIRun, run_id)
            p = db.get(m.Project, run.project_id)
            project_id = p.id
            run_membership = run.membership_id
            ctx = context_for(db, p, run_membership)
            if run.kind == 'diagnose_practice' and run.backend == personal.BACKEND:
                p = s.project(db, ctx, p.id)
                s.no_active_mock(db, p.id)
                materials = []
            else:
                p, materials = access(db, ctx, p.id)
            if p.scope_revision != run.scope_revision or (run.kind != 'diagnose_practice' and p.revision != run.metrics['plan_revision']):
                raise tutor.TutorError('SCOPE_CHANGED：资料或学习背景已变化')
            if run.backend == personal.BACKEND:
                need(ctx, 'student')
                output = personal.execute(db, ctx, p, materials, run)
                with SessionLocal.begin() as write:
                    if run.kind == 'diagnose_practice':
                        current = s.project(write, ctx, project_id, lock=True)
                        s.no_active_mock(write, current.id)
                    else:
                        current, _ = personal.access(write, ctx, project_id, lock=True)
                    job = write.get(m.AIRun, run_id, with_for_update=True)
                    if job.state != 'running' or job.lease_until != lease:
                        return True
                    if current.scope_revision != job.scope_revision or (job.kind == 'generate_practice' and current.revision != job.metrics['plan_revision']):
                        raise tutor.TutorError('资料或学习计划已变化，请重新发起')
                    job.result = personal.publish(write, ctx, current, job, output)
                    job.state, job.error = 'succeeded', ''
                return True
            row = db.get(m.ProjectLearning, run.metrics['binding_id'])
            fields = payload(db, ctx, p, materials, row)
            if not fields['ready']:
                raise tutor.TutorError('MATERIAL_REQUIRED：必备资料或索引已变化')
            body = json.loads(run.prompt)
            plan_attempt = run.metrics.get('plan_attempt', 0)
            owner = tutor_index.principal(ctx.user.id, p.id)
            batch = db.get(m.LearningBatch, run.metrics['batch_id']) if run.metrics.get('batch_id') else None
            if (batch and run.metrics.get('objective') and p.scenario == 'chapter'
                    and (batch.key != batches.day() or batch.data['state'] in ('paused', 'budget_reached', 'completed'))):
                run.state, run.error = 'cancelled', ''
                db.commit()
                return True
            exercise_materials = None
            if body['operation'] == 'chapter_practice':
                _, exercise_materials = guide.preparation(db, p, materials)
            if body['operation'] == 'read':
                material = next(x for x in materials if x.id == body['material_id'])
                index = tutor_index.mappings(db, [material])[material.id]
                fields['reader'] = {'name': index.name, 'title': material.title, 'text': material.text}
            db.commit()
        if body['operation'] == 'daily_plan':
            submission = run_id if not plan_attempt else f'{run_id}:plan:{plan_attempt}'
            result = {'items': batches.generate_plan(owner, body, submission)}
        elif body['operation'] == 'chapter_practice':
            prompt, hits = batches.practice_prompt(exercise_materials, body['topic'], body.get('points', []))
            result = {'questions': asyncio.run(tutor.generate_questions(
                owner, prompt, body['counts'], run_id, lambda _: False,
                knowledge_bases=[source['name'] for source in fields['sources']]))}
            for question in result['questions']:
                citation = search.verify(hits, exercise_materials, question['quote'])
                if not citation:
                    raise tutor.TutorError('生成题缺少可核对的章节原文')
                question['material_id'] = citation['material_id']
            if not result['questions']:
                raise tutor.TutorError('助教没有返回可用的章节练习')
        else:
            result = bridge(owner, submission_id=run_id, **fields, **body)
        with SessionLocal.begin() as db:
            p = db.scalar(select(m.Project).where(m.Project.id == project_id).with_for_update())
            if body['operation'] == 'chapter_practice':
                ctx = context_for(db, p, run_membership)
                p, _ = access(db, ctx, project_id)
            run = db.get(m.AIRun, run_id, with_for_update=True)
            if run.state != 'running' or run.lease_until != lease:
                return True
            if body['operation'] in ('daily_plan', 'chapter_practice') and (
                    p.scope_revision != run.scope_revision or p.revision != run.metrics['plan_revision']):
                raise tutor.TutorError('SCOPE_CHANGED：资料或学习计划已变化')
            if body['operation'] == 'daily_plan':
                batch = db.get(m.LearningBatch, run.metrics['batch_id'])
                batch.data = {**batch.data, 'items': result['items'], 'state': 'ready', 'error': '',
                              'previous_cards': body.get('previous_cards', [])}
            elif run.metrics.get('objective') and run.metrics.get('batch_id'):
                batch = db.get(m.LearningBatch, run.metrics['batch_id'])
                batches.remember_question(batch, result, run.metrics['objective'])
            elif body['operation'] == 'chapter_practice':
                from .assessments import save_assessment
                questions = []
                for item in result['questions']:
                    s.material_access(db, ctx, db.get(m.Material, item['material_id']))
                    candidate = QuestionCandidate(**item, knowledge=body['topic'][:200])
                    question = m.Question(project_id=p.id, origin='chapter_practice', **candidate.model_dump())
                    db.add(question)
                    questions.append(question)
                db.flush()
                result = {'assessment_id': save_assessment(db, p, '章节练习 · ' + body['topic'][:180],
                    'practice', 180, questions, membership_id=ctx.membership.id)['id']}
            run.state, run.result, run.error = 'succeeded', result, ''
    except Exception as exc:
        from fastapi import HTTPException
        with SessionLocal.begin() as db:
            run = db.get(m.AIRun, run_id, with_for_update=True)
            if run.state != 'running' or run.lease_until != lease:
                return True
            detail = exc.detail if isinstance(exc, HTTPException) else None
            run.state, run.error = 'failed', (detail.get('message', '') if isinstance(detail, dict) else str(exc))[:1000]
            if run.metrics.get('batch_id') and json.loads(run.prompt)['operation'] == 'daily_plan':
                if isinstance(exc, batches.InvalidPlan):
                    run.metrics = {**run.metrics, 'regenerate_plan': True}
                batch = db.get(m.LearningBatch, run.metrics['batch_id'])
                batch.data = {**batch.data, 'state': 'failed', 'error': run.error}
    return True
