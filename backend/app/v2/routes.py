import json
from datetime import date
from typing import Literal
from fastapi import APIRouter, Depends, Request, UploadFile, File, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from .. import models as old
from ..auth import context
from ..api_common import EnvelopeRoute, entity, idempotent
from ..db import get_db
from ..errors import fail
from . import models as m, service as s, search

router = APIRouter(route_class=EnvelopeRoute)


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class ProjectInput(Input):
    title: str = Field(min_length=1, max_length=200)
    subject_id: str
    scenario: Literal['kaoyan'] = 'kaoyan'
    exam_year: int = Field(ge=2026, le=2100)
    daily_minutes: int = Field(default=45, ge=10, le=480)
    target_score: int | None = Field(default=None, ge=0, le=100)
    deadline: date | None = None


class PlanInput(Input):
    revision: int
    daily_minutes: int = Field(ge=10, le=480)
    target_score: int | None = Field(default=None, ge=0, le=100)
    deadline: date | None = None


class MaterialInput(Input):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=300000)


class LinkInput(Input):
    source_version_id: str


class StateInput(Input):
    state: Literal['todo', 'deferred']


class CheckpointInput(Input):
    revision: int
    text: str = Field(default='', max_length=30000)
    answer: list[str] = Field(default_factory=list, max_length=20)


class AnswerInput(Input):
    answer: list[str] = Field(default_factory=list, max_length=20)
    response_text: str = Field(default='', max_length=30000)
    confidence: Literal['low', 'normal', 'high'] = 'normal'


class NoteInput(MaterialInput):
    kind: Literal['note', 'flashcard'] = 'note'
    material_id: str | None = None


class AIInput(Input):
    kind: Literal['chat'] = 'chat'
    prompt: str = Field(min_length=1, max_length=10000)
    task_id: str | None = None


class PreparationInput(Input):
    kind: Literal['single', 'multiple', 'essay'] = 'single'


def project_view(p):
    return entity(p, 'id', 'title', 'scenario', 'subject_id', 'exam_year', 'daily_minutes', 'target_score',
                  'deadline', 'state', 'revision', 'scope_revision', 'policy')


def task_view(t):
    return entity(t, 'id', 'project_id', 'material_id', 'kind', 'title', 'reason', 'state', 'due_at', 'estimated_minutes')


def create_run(db, p, kind, prompt, task_id=None, membership_id=None):
    run = m.AIRun(project_id=p.id, task_id=task_id, scope_revision=p.scope_revision, kind=kind, prompt=prompt, membership_id=membership_id)
    db.add(run)
    db.flush()
    return run


@router.get('/scenarios')
def scenarios(ctx=Depends(context)):
    return [{'id': 'kaoyan', 'title': '考研复习', 'available': True},
            {'id': 'chapter', 'title': '章节学习', 'available': False},
            {'id': 'final', 'title': '期末备考', 'available': False}]


@router.get('/learning-projects')
def projects(ctx=Depends(context), db=Depends(get_db)):
    return [project_view(p) for p in db.scalars(select(m.Project).join(m.PersonalSpace).where(m.PersonalSpace.user_id == ctx.user.id).order_by(m.Project.created_at.desc()))]


@router.post('/learning-projects', status_code=201)
def new_project(data: ProjectInput, request: Request, ctx=Depends(context), db=Depends(get_db)):
    subject = db.get(old.Subject, data.subject_id)
    if not subject or subject.code != 'politics':
        fail(422, 'SUBJECT_NOT_READY', '首版支持考研政治')
    def save():
        p = m.Project(space_id=s.space(db, ctx.user.id).id, **data.model_dump(exclude={'deadline'}), deadline=data.deadline.isoformat() if data.deadline else None)
        db.add(p)
        db.flush()
        s.snapshot_plan(db, p, '用户确认第一份学习计划，等待选择学习资料')
        return project_view(p)
    return idempotent(db, ctx, request, 'v2.project.create', data.model_dump(mode='json'), save)


@router.get('/learning-projects/{project_id}')
def project_detail(project_id: str, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, active=False)
    return {**project_view(p), 'materials': [entity(x, 'id', 'title', 'state', 'source_version_id') for x in s.rows(db, m.Material, p.id)],
            'tasks': [task_view(x) for x in s.rows(db, m.Task, p.id) if not x.payload.get('assessment_id')], 'report': s.report(db, p)}


@router.get('/learning-projects/{project_id}/plans')
def plans(project_id: str, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, active=False)
    return [entity(x, 'id', 'number', 'daily_minutes', 'reason', 'scope', 'created_at') for x in s.rows(db, m.Plan, p.id)]


@router.post('/learning-projects/{project_id}/plans')
def change_plan(project_id: str, data: PlanInput, request: Request, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, lock=True)
    def save():
        if p.revision != data.revision:
            fail(409, 'REVISION_CONFLICT', '计划已变化，请刷新后调整')
        p.daily_minutes, p.target_score = data.daily_minutes, data.target_score
        p.deadline = data.deadline.isoformat() if data.deadline else None
        p.revision += 1
        s.snapshot_plan(db, p, '用户确认时间预算或目标调整，未完成任务按新预算安排')
        return project_view(p)
    return idempotent(db, ctx, request, f'v2.plan:{p.id}', data.model_dump(mode='json'), save)


@router.post('/learning-projects/{project_id}/archive')
def archive(project_id: str, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, active=False, lock=True)
    s.no_active_mock(db, p.id)
    p.state = 'archived'
    p.scope_revision += 1
    return project_view(p)


@router.get('/today')
def today(ctx=Depends(context), db=Depends(get_db)):
    return s.today(db, ctx)


@router.get('/course-materials')
def courses(ctx=Depends(context), db=Depends(get_db)):
    result = []
    for v in db.scalars(select(old.SourceVersion)):
        source = db.get(old.Source, v.source_id)
        enabled = v.status == 'published' or db.scalar(select(old.SourceActivation.id).where(old.SourceActivation.version_id == v.id))
        if v.status != 'withdrawn' and enabled and s.source_allowed(db, ctx, source):
            result.append({'id': v.id, 'title': source.title, 'version': v.number})
    return result


@router.post('/learning-projects/{project_id}/materials', status_code=201)
def add_material(project_id: str, data: MaterialInput, request: Request, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, lock=True)
    return idempotent(db, ctx, request, f'v2.material:{p.id}', data.model_dump(), lambda: entity(s.add_material(db, p, data.title, data.text), 'id', 'title', 'state'))


@router.post('/learning-projects/{project_id}/course-materials', status_code=201)
def link_material(project_id: str, data: LinkInput, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, lock=True)
    v = db.get(old.SourceVersion, data.source_version_id)
    if not v:
        fail(404, 'NOT_FOUND', '课程资料不存在')
    source = db.get(old.Source, v.source_id)
    candidate = m.Material(source_version_id=v.id)
    s.material_access(db, ctx, candidate)
    return entity(s.add_material(db, p, source.title, v.text, v.id), 'id', 'title', 'state')


@router.post('/learning-projects/{project_id}/uploads', status_code=201)
async def upload(project_id: str, file: UploadFile = File(), ctx=Depends(context), db=Depends(get_db)):
    s.project(db, ctx, project_id)
    db.commit()
    content = await file.read(20 * 1024 * 1024 + 1)
    if len(content) > 20 * 1024 * 1024:
        fail(422, 'FILE_TOO_LARGE', '资料最多 20 MB')
    name = file.filename or '学习资料'
    suffix = name.lower().rsplit('.', 1)[-1]
    from starlette.concurrency import run_in_threadpool
    from .documents import extract
    text = await run_in_threadpool(extract, content, suffix)
    if not text.strip() or len(text) > 300000:
        fail(422, 'MATERIAL_TEXT_INVALID', '未提取到正文，或正文超过30万字；扫描件请先进行 OCR')
    p = s.project(db, ctx, project_id, lock=True)
    item = s.add_material(db, p, name[:200], text, deduplicate=False)
    from pathlib import Path
    from ..config import settings
    path = settings.data_dir / 'v2-originals' / p.id
    path.mkdir(parents=True, exist_ok=True)
    with (path / f'{item.id}.{suffix}').open('xb') as original:
        original.write(content)
    return entity(item, 'id', 'title', 'state')


@router.delete('/learning-projects/{project_id}/materials/{material_id}')
def remove_material(project_id: str, material_id: str, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, lock=True)
    s.no_active_mock(db, p.id)
    material = db.get(m.Material, material_id)
    if not material or material.project_id != p.id:
        fail(404, 'NOT_FOUND', '资料不存在')
    material.state = 'revoked'
    p.scope_revision += 1
    p.revision += 1
    for t in s.rows(db, m.Task, p.id):
        if t.material_id == material.id and t.state != 'completed':
            t.state = 'cancelled'
    s.snapshot_plan(db, p, '移除资料，旧运行作用域停止使用')
    return {'removed': True}


@router.get('/learning-projects/{project_id}/material-search')
def search_materials(project_id: str, q: str = Query(min_length=1, max_length=500), ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, active=False)
    s.no_active_mock(db, p.id)
    materials = s.authorized_materials(db, ctx, p)
    return [{**search.location(x.material, x.start, x.end), 'quote': x.text} for x in search.retrieve(materials, q)]


def source_material(db, ctx, project_id, material_id):
    p = s.project(db, ctx, project_id, active=False)
    s.no_active_mock(db, p.id)
    material = db.get(m.Material, material_id)
    if not material or material.project_id != p.id:
        fail(404, 'NOT_FOUND', '资料不存在')
    return s.material_access(db, ctx, material)


@router.get('/learning-projects/{project_id}/materials/{material_id}/excerpt')
def excerpt(project_id: str, material_id: str, sha256: str, start: int, end: int, ctx=Depends(context), db=Depends(get_db)):
    material = source_material(db, ctx, project_id, material_id)
    if material.sha256 != sha256 or not (0 <= start < end <= len(material.text) and end-start <= 880):
        fail(422, 'INVALID_LOCATION', '无法在该资料版本中定位原文')
    return {**search.location(material, start, end), 'quote': material.text[start:end],
            'before': material.text[max(0, start-350):start], 'after': material.text[end:end+350]}


@router.get('/learning-projects/{project_id}/materials/{material_id}/original-pdf')
def original_pdf(project_id: str, material_id: str, ctx=Depends(context), db=Depends(get_db)):
    material = source_material(db, ctx, project_id, material_id)
    path = search.original_pdf(material)
    if not path:
        fail(404, 'NOT_FOUND', '此资料没有可查看的 PDF 原件')
    return FileResponse(path, media_type='application/pdf', headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/study-sessions/{task_id}')
def session(task_id: str, ctx=Depends(context), db=Depends(get_db)):
    t, p = s.task(db, ctx, task_id, active=False)
    s.no_active_mock(db, p.id)
    row = db.scalar(select(m.StudySession).where(m.StudySession.task_id == t.id))
    material = db.get(m.Material, t.material_id) if t.material_id else None
    material_view = entity(material, 'id', 'title', 'text') if material else None
    if material_view and t.payload.get('source_span'):
        start, end = t.payload['source_span']
        material_view['text'] = material.text[start:end]
    q = db.get(m.Question, t.payload['question_id']) if t.payload.get('question_id') else None
    attempt = db.scalar(select(m.Attempt).where(m.Attempt.task_id == t.id))
    latest_run = db.scalar(select(m.AIRun).where(m.AIRun.task_id == t.id, m.AIRun.kind.in_(['question', 'evaluate'])).order_by(m.AIRun.created_at.desc()))
    return {'task': task_view(t), 'project': project_view(p), 'material': material_view,
            'checkpoint': row.checkpoint if row else {}, 'revision': row.revision if row else 0,
            'question': s.question_view(q, bool(attempt and t.state == 'completed')) if q else None,
            'result': attempt.result if attempt else None, 'ai_run_id': latest_run.id if latest_run else None}


@router.put('/study-sessions/{task_id}/checkpoint')
def checkpoint(task_id: str, data: CheckpointInput, ctx=Depends(context), db=Depends(get_db)):
    t, p = s.task(db, ctx, task_id, lock=True)
    s.no_active_mock(db, p.id)
    if t.state in ('completed', 'cancelled'):
        fail(409, 'TASK_CLOSED', '任务已结束')
    row = db.scalar(select(m.StudySession).where(m.StudySession.task_id == t.id))
    if data.revision != (row.revision if row else 0):
        fail(409, 'REVISION_CONFLICT', '草稿已在其他页面修改')
    if not row:
        row = m.StudySession(task_id=t.id, revision=0)
        db.add(row)
    row.checkpoint = data.model_dump(exclude={'revision'})
    row.revision += 1
    t.state = 'in_progress'
    return {'revision': row.revision}


@router.post('/study-sessions/{task_id}/complete')
def complete(task_id: str, request: Request, ctx=Depends(context), db=Depends(get_db)):
    t, p = s.task(db, ctx, task_id, lock=True)
    s.no_active_mock(db, p.id)
    def save():
        if t.kind not in ('reading', 'remediation') or t.state in ('completed', 'cancelled'):
            fail(409, 'INVALID_TRANSITION', '当前任务不能重复完成或需要提交作答')
        t.state = 'completed'
        s.evidence(db, p, t, 'reading', t.payload.get('knowledge', t.title), source='learner')
        next_task = s.add_task(db, p, 'verification' if t.kind == 'remediation' else 'practice',
                               '独立检查理解', f'check:{t.id}', '阅读不是掌握证据，请独立尝试一道题', t.material_id,
                               {'knowledge': t.payload.get('knowledge', ''), 'focus': t.payload.get('focus'),
                                'source_span': t.payload.get('source_span'), 'exclude_question_id': t.payload.get('origin_question_id')})
        return {'next_task_id': next_task.id}
    return idempotent(db, ctx, request, f'v2.complete:{t.id}', {}, save)


@router.patch('/tasks/{task_id}')
def task_state(task_id: str, data: StateInput, ctx=Depends(context), db=Depends(get_db)):
    t, p = s.task(db, ctx, task_id, lock=True)
    if t.state in ('completed', 'cancelled'):
        fail(409, 'TASK_CLOSED', '任务已结束')
    t.state = data.state
    return task_view(t)


@router.post('/study-sessions/{task_id}/prepare', status_code=202)
def prepare(task_id: str, request: Request, data: PreparationInput | None = None, ctx=Depends(context), db=Depends(get_db)):
    t, p = s.task(db, ctx, task_id, lock=True)
    s.no_active_mock(db, p.id)
    if t.kind not in ('practice', 'verification', 'review') or t.state in ('completed', 'cancelled'):
        fail(409, 'INVALID_TRANSITION', '当前任务不能准备练习')
    if t.due_at and s.datetime.fromisoformat(t.due_at) > s.clock():
        fail(409, 'REVIEW_NOT_DUE', '延迟复习尚未到期')
    s.authorized_materials(db, ctx, p)
    def save():
        if t.payload.get('question_id') or db.scalar(select(m.AIRun.id).where(m.AIRun.task_id == t.id, m.AIRun.kind == 'question', m.AIRun.state.in_(['queued', 'running']))):
            fail(409, 'QUESTION_ALREADY_PREPARING', '题目已准备或正在准备，请查看当前状态')
        t.payload = {**t.payload, 'requested_kind': data.kind if data else 'single'}
        run = create_run(db, p, 'question', '生成一道有逐字原文依据的新题', t.id, ctx.membership.id)
        return {'run_id': run.id, 'state': run.state, 'status_url': f'/api/v2/ai-runs/{run.id}'}
    return idempotent(db, ctx, request, f'v2.prepare:{t.id}', data.model_dump() if data else {}, save)


@router.post('/study-sessions/{task_id}/hint')
def hint(task_id: str, ctx=Depends(context), db=Depends(get_db)):
    t, p = s.task(db, ctx, task_id, lock=True)
    s.no_active_mock(db, p.id)
    q = db.get(m.Question, t.payload.get('question_id'))
    if not q or t.state in ('completed', 'cancelled'):
        fail(409, 'QUESTION_REQUIRED', '当前没有可提示的练习')
    t.payload = {**t.payload, 'hint_used': True}
    return {'hint': '请回到这段原文核对：' + q.quote, 'counts_as_assisted': True}


@router.post('/study-sessions/{task_id}/submit')
def submit(task_id: str, data: AnswerInput, request: Request, ctx=Depends(context), db=Depends(get_db)):
    current, p = s.task(db, ctx, task_id)
    if current.payload.get('assessment_id'):
        fail(403, 'GROUP_SUBMISSION_REQUIRED', '测评必须整组交卷')
    def save():
        a, p, t, q = s.submit_answer(db, ctx, task_id, data)
        if q.kind == 'essay':
            run = create_run(db, p, 'evaluate', '按评分要点评价分析题，不形成正式成绩', t.id, ctx.membership.id)
            a.result = {**a.result, 'run_id': run.id}
        return {'attempt_id': a.id, 'result': a.result}
    return idempotent(db, ctx, request, f'v2.submit:{task_id}', data.model_dump(), save)


@router.get('/learning-projects/{project_id}/report')
def report(project_id: str, ctx=Depends(context), db=Depends(get_db)):
    return s.report(db, s.project(db, ctx, project_id, active=False))


@router.get('/learning-projects/{project_id}/notes')
def notes(project_id: str, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, active=False)
    s.no_active_mock(db, p.id)
    return [entity(n, 'id', 'title', 'body', 'kind', 'material_id', 'created_at') for n in s.rows(db, m.Note, p.id)]


@router.post('/learning-projects/{project_id}/notes', status_code=201)
def add_note(project_id: str, data: NoteInput, request: Request, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id)
    if data.material_id:
        material = db.get(m.Material, data.material_id)
        if not material or material.project_id != p.id:
            fail(404, 'NOT_FOUND', '资料不存在')
        s.material_access(db, ctx, material)
    def save():
        row = m.Note(project_id=p.id, title=data.title, body=data.text, kind=data.kind, material_id=data.material_id)
        db.add(row)
        db.flush()
        return entity(row, 'id', 'title', 'body', 'kind')
    return idempotent(db, ctx, request, f'v2.note:{p.id}', data.model_dump(), save)


@router.post('/learning-projects/{project_id}/ai-runs', status_code=202)
def ai(project_id: str, data: AIInput, request: Request, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, lock=True)
    s.no_active_mock(db, p.id)
    materials = s.authorized_materials(db, ctx, p)
    if not materials:
        fail(409, 'MATERIAL_REQUIRED', '请先选择课程或添加个人资料')
    if data.task_id:
        t, _ = s.task(db, ctx, data.task_id)
        if t.project_id != p.id:
            fail(404, 'NOT_FOUND', '任务不属于当前项目')
    def save():
        run = create_run(db, p, data.kind, data.prompt, data.task_id, ctx.membership.id)
        return {'run_id': run.id, 'state': run.state, 'status_url': f'/api/v2/ai-runs/{run.id}'}
    return idempotent(db, ctx, request, f'v2.ai:{p.id}', data.model_dump(), save)


def authorized_run(db, ctx, run_id):
    run = db.get(m.AIRun, run_id)
    if not run:
        fail(404, 'NOT_FOUND', '运行不存在')
    p = s.project(db, ctx, run.project_id, active=False)
    s.no_active_mock(db, p.id)
    if run.scope_revision != p.scope_revision:
        fail(403, 'SCOPE_CHANGED', '资料范围已变化，不能继续读取旧运行')
    s.authorized_materials(db, ctx, p)
    return run


@router.get('/ai-runs/{run_id}')
def ai_run(run_id: str, ctx=Depends(context), db=Depends(get_db)):
    return entity(authorized_run(db, ctx, run_id), 'id', 'state', 'kind', 'result', 'error', 'external_id')


@router.get('/ai-runs/{run_id}/events')
def events(run_id: str, request: Request, after: int = 0, ctx=Depends(context), db=Depends(get_db)):
    authorized_run(db, ctx, run_id)
    cursor = max(after, int(request.headers.get('Last-Event-ID', '0')) if request.headers.get('Last-Event-ID', '0').isdigit() else 0)
    records = list(db.scalars(select(m.AIEvent).where(m.AIEvent.run_id == run_id, m.AIEvent.seq > cursor).order_by(m.AIEvent.seq)))
    # A bounded durable snapshot closes normally; EventSource reconnects and reauthorizes.
    body = ''.join(f'id: {e.seq}\nevent: {e.kind}\ndata: {json.dumps(e.payload, ensure_ascii=False)}\n\n' for e in records)
    return StreamingResponse(iter([body or ': heartbeat\n\n']), media_type='text/event-stream', headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-cache'})


@router.post('/ai-runs/{run_id}/retry', status_code=202)
def retry(run_id: str, request: Request, ctx=Depends(context), db=Depends(get_db)):
    previous = authorized_run(db, ctx, run_id)
    p = s.project(db, ctx, previous.project_id, lock=True)
    if previous.state != 'failed':
        fail(409, 'RETRY_NOT_ALLOWED', '仅失败运行可以显式重试')
    def save():
        row = create_run(db, p, previous.kind, previous.prompt, previous.task_id, ctx.membership.id)
        return {'run_id': row.id, 'state': row.state}
    return idempotent(db, ctx, request, f'v2.retry:{previous.id}', {}, save)


@router.post('/ai-runs/{run_id}/cancel')
def cancel(run_id: str, ctx=Depends(context), db=Depends(get_db)):
    authorized_run(db, ctx, run_id)
    row = db.scalar(select(m.AIRun).where(m.AIRun.id==run_id).with_for_update().execution_options(populate_existing=True))
    if row.state == 'queued':
        row.state = 'cancelled'
    elif row.state == 'running':
        row.state = 'cancel_requested'
    return {'run_id': row.id, 'state': row.state}
