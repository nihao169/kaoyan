import json
import hashlib
import asyncio
from datetime import date
from typing import Literal
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from .. import models as old
from ..auth import context
from ..config import settings
from ..api_common import EnvelopeRoute, entity, idempotent
from ..db import get_db
from ..errors import fail
from . import models as m, service as s, search, tutor, tutor_index, tutor_practice, tutor_records

router = APIRouter(route_class=EnvelopeRoute)


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class ProjectInput(Input):
    title: str = Field(min_length=1, max_length=200)
    subject_id: str | None = None
    scenario: Literal['chapter', 'final', 'kaoyan'] = 'kaoyan'
    exam_year: int | None = Field(default=None, ge=2026, le=2100)
    course_name: str = Field(default='', max_length=200)
    learning_goal: str = Field(default='', max_length=2000)
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
    kind: Literal['chat', 'solve', 'read', 'guide'] = 'chat'
    prompt: str = Field(min_length=1, max_length=10000)
    task_id: str | None = None


class PreparationInput(Input):
    kind: Literal['single', 'multiple', 'essay'] = 'single'


def project_view(p):
    return entity(p, 'id', 'title', 'scenario', 'subject_id', 'exam_year', 'daily_minutes', 'target_score',
                  'deadline', 'state', 'revision', 'scope_revision', 'policy', 'course_name', 'learning_goal', 'scene_confirmed')


def task_view(t):
    return entity(t, 'id', 'project_id', 'material_id', 'kind', 'title', 'reason', 'state', 'due_at', 'estimated_minutes')


def create_run(db, p, kind, prompt, task_id=None, membership_id=None, previous_backend=None):
    backend = {'solve': 'native_solve', 'read': 'native_read', 'guide': 'native_guide'}.get(kind, 'bounded_chat')
    if kind in ('chat', 'evaluate') and settings.deeptutor_native_knowledge:
        backend = 'native_knowledge'
    if kind == 'question' and settings.deeptutor_native_questions:
        backend = 'native_questions'
    run = m.AIRun(project_id=p.id, task_id=task_id, scope_revision=p.scope_revision, kind=kind, prompt=prompt,
                  membership_id=membership_id, backend=previous_backend or backend)
    db.add(run)
    db.flush()
    return run


@router.get('/scenarios')
def scenarios(ctx=Depends(context)):
    return [{'id': 'chapter', 'title': '首次学习', 'available': True},
            {'id': 'final', 'title': '期末复习', 'available': True},
            {'id': 'kaoyan', 'title': '考研学习', 'available': True}]


@router.get('/learning-projects')
def projects(ctx=Depends(context), db=Depends(get_db)):
    return [project_view(p) for p in db.scalars(select(m.Project).join(m.PersonalSpace).where(m.PersonalSpace.user_id == ctx.user.id).order_by(m.Project.created_at.desc()))]


@router.post('/learning-projects', status_code=201)
def new_project(data: ProjectInput, request: Request, ctx=Depends(context), db=Depends(get_db)):
    if data.scenario == 'kaoyan' and not data.exam_year:
        fail(422, 'EXAM_YEAR_REQUIRED', '请填写考研年份')
    subject = db.get(old.Subject, data.subject_id) if data.subject_id else None
    if data.subject_id and not subject:
        fail(422, 'SUBJECT_NOT_FOUND', '课程分类不存在')
    if not subject:
        subject = db.scalar(select(old.Subject).where(old.Subject.code == 'general'))
        if not subject:
            subject = old.Subject(code='general', name='通用课程')
            db.add(subject)
            db.flush()
    def save():
        fields = data.model_dump(exclude={'deadline', 'subject_id', 'exam_year'})
        p = m.Project(space_id=s.space(db, ctx.user.id).id, **fields, subject_id=subject.id,
                      exam_year=data.exam_year or date.today().year, scene_confirmed=bool(data.course_name),
                      policy='kaoyan-politics-v1' if data.course_name.strip() in ('政治', '考研政治') or (not data.course_name and subject.code == 'politics') else 'general-mastery-v1',
                      deadline=data.deadline.isoformat() if data.deadline else None)
        db.add(p)
        db.flush()
        s.snapshot_plan(db, p, '用户确认第一份学习计划，等待选择学习资料')
        return project_view(p)
    return idempotent(db, ctx, request, 'v2.project.create', data.model_dump(mode='json'), save)


@router.get('/learning-projects/{project_id}')
def project_detail(project_id: str, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, active=False)
    task, mastery = s.accepted_mastery(db, p)
    if task:
        try:
            s.no_active_mock(db, p.id)
            s.authorized_materials(db, ctx, p)
        except HTTPException as exc:
            if exc.status_code != 403:
                raise
            mastery = {}
    return {**project_view(p), 'materials': [entity(x, 'id', 'title', 'state', 'source_version_id') for x in s.rows(db, m.Material, p.id)],
            'tasks': [task_view(x) for x in s.rows(db, m.Task, p.id) if not x.payload.get('assessment_id')], 'report': s.report(db, p),
            'mastery_outline': mastery.get('outline', [])}


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
    def save():
        item = s.add_material(db, p, data.title, data.text)
        if settings.deeptutor_native_knowledge:
            tutor_index.enqueue(db, ctx, p, [item])
        return entity(item, 'id', 'title', 'state')
    return idempotent(db, ctx, request, f'v2.material:{p.id}', data.model_dump(), save)


@router.post('/learning-projects/{project_id}/course-materials', status_code=201)
def link_material(project_id: str, data: LinkInput, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, lock=True)
    v = db.get(old.SourceVersion, data.source_version_id)
    if not v:
        fail(404, 'NOT_FOUND', '课程资料不存在')
    source = db.get(old.Source, v.source_id)
    candidate = m.Material(source_version_id=v.id)
    s.material_access(db, ctx, candidate)
    item = s.add_material(db, p, source.title, v.text, v.id)
    if settings.deeptutor_native_knowledge:
        tutor_index.enqueue(db, ctx, p, [item])
    return entity(item, 'id', 'title', 'state')


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
    checksum = hashlib.sha256(content).hexdigest()
    existing = db.scalar(select(m.Material).where(m.Material.project_id == p.id, m.Material.state == 'ready',
                                                  m.Material.original_sha256 == checksum).limit(1))
    if existing:
        return entity(existing, 'id', 'title', 'state')
    item = s.add_material(db, p, name[:200], text, deduplicate=False)
    item.original_sha256 = checksum
    from pathlib import Path
    from ..config import settings
    path = settings.data_dir / 'v2-originals' / p.id
    path.mkdir(parents=True, exist_ok=True)
    with (path / f'{item.id}.{suffix}').open('xb') as original:
        original.write(content)
    if settings.deeptutor_native_knowledge:
        tutor_index.enqueue(db, ctx, p, [item])
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
    for index in db.scalars(select(m.TutorIndex).where(m.TutorIndex.material_id == material.id, m.TutorIndex.state != 'deleted')):
        index.next_at = s.clock().isoformat()
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
    if q:
        s.material_access(db, ctx, db.get(m.Material, q.material_id))
    attempt = db.scalar(select(m.Attempt).where(m.Attempt.task_id == t.id))
    latest_run = db.scalar(select(m.AIRun).where(m.AIRun.task_id == t.id, m.AIRun.scope_revision == p.scope_revision)
                           .order_by(m.AIRun.created_at.desc(), m.AIRun.id.desc()).limit(1))
    return {'task': task_view(t), 'project': project_view(p), 'material': material_view,
            'archived_review': p.scene_confirmed or (t.kind == 'review' and settings.deeptutor_mastery_reviews),
            'native_solve': settings.deeptutor_native_knowledge and settings.deeptutor_native_lessons,
            'native_lessons': settings.deeptutor_native_knowledge and settings.deeptutor_native_lessons,
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
    materials = s.authorized_materials(db, ctx, p)
    if settings.deeptutor_native_questions:
        if not settings.deeptutor_native_knowledge:
            fail(409, 'TUTOR_INDEX_DISABLED', '原生出题需要先启用知识库')
        require_ready_indexes(db, materials)
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
    s.material_access(db, ctx, db.get(m.Material, q.material_id))
    t.payload = {**t.payload, 'hint_used': True}
    return {'hint': '请回到这段原文核对：' + q.quote, 'counts_as_assisted': True}


@router.post('/study-sessions/{task_id}/submit')
def submit(task_id: str, data: AnswerInput, request: Request, ctx=Depends(context), db=Depends(get_db)):
    current, p = s.task(db, ctx, task_id, lock=True)
    s.no_active_mock(db, p.id)
    if current.payload.get('assessment_id'):
        fail(403, 'GROUP_SUBMISSION_REQUIRED', '测评必须整组交卷')
    question = db.get(m.Question, current.payload.get('question_id')) if current.payload.get('question_id') else None
    if question:
        s.material_access(db, ctx, db.get(m.Material, question.material_id))

    def grader(project, question, material, answer):
        if tutor_practice.eligible(question, material):
            return tutor_practice.call(tutor_practice.grade(ctx.user.id, project.id, question, answer)), 'deeptutor_practice'
        return set(answer) == set(question.answer), 'rule'

    use_native_grading = tutor_practice.enabled(p.id)

    def save():
        a, p, t, q = s.submit_answer(db, ctx, task_id, data, grader=grader if use_native_grading else None)
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
    if p.native_records:
        db.commit()
        records = tutor_records.native_records(ctx.user.id, p.id)
        db.expire_all()
        s.project(db, ctx, project_id, active=False)
        s.no_active_mock(db, project_id)
    else:
        records = tutor_records.local_records(db, p.id)
    return list(tutor_records.visible(db, ctx, project_id, records))


@router.post('/learning-projects/{project_id}/notes', status_code=201)
def add_note(project_id: str, data: NoteInput, request: Request, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, lock=True)
    s.no_active_mock(db, p.id)
    if data.material_id:
        material = db.get(m.Material, data.material_id)
        if not material or material.project_id != p.id:
            fail(404, 'NOT_FOUND', '资料不存在')
        s.material_access(db, ctx, material)
    def save():
        note_id = tutor_records.record_id(ctx, p.id, request.headers['Idempotency-Key'])
        if p.native_records:
            if not tutor_records.enabled(p.id):
                fail(503, 'RECORD_WRITES_PAUSED', '学习记录暂时停止写入，已有记录可查看')
            item = tutor_records.save_native(ctx, p.id, note_id, data)
            return {key: item[key] for key in ('id', 'title', 'body', 'kind')}
        fields = {'project_id': p.id, 'title': data.title, 'body': data.text, 'kind': data.kind,
                  'material_id': data.material_id}
        row = db.get(m.Note, note_id)
        if row and any(getattr(row, key) != value for key, value in fields.items()):
            fail(409, 'IDEMPOTENCY_CONFLICT', '相同幂等键不能提交不同内容')
        if not row:
            row = m.Note(id=note_id, **fields)
            db.add(row)
            db.flush()
        return entity(row, 'id', 'title', 'body', 'kind')
    return idempotent(db, ctx, request, f'v2.note:{p.id}', data.model_dump(), save)


@router.post('/learning-projects/{project_id}/notes/migrate')
def migrate_notes(project_id: str, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, lock=True)
    s.no_active_mock(db, p.id)
    if not tutor_records.enabled(p.id):
        fail(403, 'RECORD_MIGRATION_DISABLED', '此项目尚未开放学习记录迁移')
    if p.native_records:
        return {'backend': 'native'}
    return {'backend': 'native', 'count': tutor_records.migrate(db, ctx, p)}


@router.post('/learning-projects/{project_id}/notes/restore')
def restore_notes(project_id: str, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, active=False, lock=True)
    s.no_active_mock(db, p.id)
    if tutor_records.enabled(p.id):
        fail(409, 'RECORD_WRITES_ACTIVE', '请先暂停该项目的原生记录写入')
    if not p.native_records:
        return {'backend': 'local'}
    return {'backend': 'local', 'count': tutor_records.restore(db, ctx, p)}


def index_status(db, materials):
    found = tutor_index.mappings(db, materials)
    return {'enabled': True, 'items': [
        {'material_id': item.id, 'title': item.title, 'state': row.state, 'error': row.error}
        if (row := found.get(item.id)) else {'material_id': item.id, 'title': item.title, 'state': 'missing', 'error': ''}
        for item in materials]}


def require_ready_indexes(db, materials):
    found = tutor_index.mappings(db, materials)
    if not materials or any(item.id not in found or found[item.id].state != 'ready' for item in materials):
        fail(409, 'TUTOR_INDEX_NOT_READY', '请在项目的「课程与资料」中准备助教索引，再回来继续')


@router.get('/learning-projects/{project_id}/tutor-index')
def get_tutor_index(project_id: str, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id)
    s.no_active_mock(db, p.id)
    if not settings.deeptutor_native_knowledge:
        return {'enabled': False, 'items': []}
    return index_status(db, s.authorized_materials(db, ctx, p))


@router.post('/learning-projects/{project_id}/tutor-index', status_code=202)
def queue_tutor_index(project_id: str, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, lock=True)
    s.no_active_mock(db, p.id)
    if not settings.deeptutor_native_knowledge:
        fail(409, 'TUTOR_INDEX_DISABLED', '本环境未启用原生知识库')
    materials = s.authorized_materials(db, ctx, p)
    tutor_index.enqueue(db, ctx, p, materials)
    db.flush()
    return index_status(db, materials)


@router.post('/learning-projects/{project_id}/ai-runs', status_code=202)
def ai(project_id: str, data: AIInput, request: Request, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, lock=True)
    s.no_active_mock(db, p.id)
    materials = s.authorized_materials(db, ctx, p)
    if not materials:
        fail(409, 'MATERIAL_REQUIRED', '请先选择课程或添加个人资料')
    if data.kind == 'solve' and not (settings.deeptutor_native_knowledge and settings.deeptutor_native_lessons):
        fail(409, 'TUTOR_SOLVE_DISABLED', '本环境未启用原生讲题')
    if data.kind in ('read', 'guide') and not (settings.deeptutor_native_knowledge and settings.deeptutor_native_lessons):
        fail(409, 'TUTOR_LESSONS_DISABLED', '本环境未启用原生精读与引导学习')
    if settings.deeptutor_native_knowledge:
        require_ready_indexes(db, materials)
    if data.task_id:
        t, _ = s.task(db, ctx, data.task_id)
        if t.project_id != p.id:
            fail(404, 'NOT_FOUND', '任务不属于当前项目')
    if data.kind == 'solve' and (not data.task_id or t.state != 'completed' or not t.payload.get('question_id')):
        fail(409, 'SUBMIT_FIRST', '请先完成这道题，再打开讲解')
    if data.kind == 'read' and (not data.task_id or t.kind not in ('reading', 'remediation') or not t.material_id):
        fail(409, 'MATERIAL_REQUIRED', '请从含资料的阅读任务打开精读')
    def save():
        if data.kind in ('read', 'guide'):
            active = select(m.AIRun.id).where(m.AIRun.project_id == p.id, m.AIRun.scope_revision == p.scope_revision,
                m.AIRun.kind == data.kind, m.AIRun.state.in_(['queued', 'running', 'cancel_requested']))
            if data.kind == 'read':
                active = active.where(m.AIRun.task_id == data.task_id)
            if db.scalar(active.limit(1)):
                fail(409, 'AI_RUN_ACTIVE', '已有学习请求正在处理，请等待当前结果')
        if data.kind == 'guide' and not s.accepted_mastery(db, p)[0]:
            drafts = db.scalars(select(m.AIRun).where(m.AIRun.project_id == p.id, m.AIRun.scope_revision == p.scope_revision,
                m.AIRun.kind == 'guide', m.AIRun.state == 'succeeded').order_by(m.AIRun.created_at.desc(), m.AIRun.id.desc()))
            for draft in drafts:
                if draft.metrics.get('mastery') and draft.result.get('citations'):
                    return {'run_id': draft.id, 'state': draft.state, 'status_url': f'/api/v2/ai-runs/{draft.id}'}
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


@router.get('/learning-projects/{project_id}/chat-history')
def chat_history(project_id: str, offset: int = Query(0, ge=0), ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, active=False)
    s.no_active_mock(db, p.id)
    s.authorized_materials(db, ctx, p)
    runs = db.scalars(select(m.AIRun).where(m.AIRun.project_id == p.id, m.AIRun.kind == 'chat',
                     m.AIRun.state == 'succeeded', m.AIRun.scope_revision == p.scope_revision)
                     .order_by(m.AIRun.created_at.desc(), m.AIRun.id.desc()).offset(offset).limit(21)).all()
    return {'items': [{'id': run.id, 'title': run.prompt[:100], 'created_at': run.created_at} for run in runs[:20]],
            'next_offset': offset + 20 if len(runs) > 20 else None}


@router.get('/learning-projects/{project_id}/chat-history/{run_id}')
def chat_history_item(project_id: str, run_id: str, ctx=Depends(context), db=Depends(get_db)):
    run = authorized_run(db, ctx, run_id)
    if run.project_id != project_id or run.kind != 'chat' or run.state != 'succeeded':
        fail(404, 'NOT_FOUND', '未找到这次答疑')
    result = {key: run.result[key] for key in ('text', 'citations', 'coverage_note') if key in run.result}
    binding = run.metrics.get('chat_session')
    if binding and db.get(m.Project, project_id).native_records:
        db.commit()
        try:
            session = asyncio.run(tutor.native_request(binding['principal'], 'GET',
                                  '/api/sessions/' + quote(binding['id'], safe=''), timeout=8))
        except tutor.TutorError:
            fail(503, 'CHAT_HISTORY_UNAVAILABLE', '暂时无法读取答疑记录，请稍后重试')
        message = next((item for item in session.get('messages', [])
                        if item.get('role') == 'assistant' and (item.get('trace') or {}).get('turn_id') == run.external_id), None)
        if not message or not isinstance(message.get('content'), str):
            fail(503, 'CHAT_HISTORY_UNAVAILABLE', '暂时无法确认原生答疑记录')
        try:
            parsed = tutor.json_result(message['content'])
        except (ValueError, IndexError):
            parsed = None
        text = parsed.get('text') if isinstance(parsed, dict) else message['content']
        # Keep the original verified projection and reject a changed downstream answer.
        if text != result.get('text'):
            fail(503, 'CHAT_HISTORY_UNAVAILABLE', '原生答疑与已核对的结果不一致')
        result['text'] = text
        db.expire_all()
        authorized_run(db, ctx, run_id)
    return {'prompt': run.prompt, **result}


@router.get('/ai-runs/{run_id}')
def ai_run(run_id: str, ctx=Depends(context), db=Depends(get_db)):
    return entity(authorized_run(db, ctx, run_id), 'id', 'state', 'kind', 'backend', 'result', 'error')


@router.post('/ai-runs/{run_id}/accept-guide')
def accept_guide(run_id: str, ctx=Depends(context), db=Depends(get_db)):
    run = authorized_run(db, ctx, run_id)
    p = s.project(db, ctx, run.project_id, lock=True)
    s.no_active_mock(db, p.id)
    if run.kind != 'guide' or run.state != 'succeeded' or run.scope_revision != p.scope_revision or not run.result.get('citations'):
        fail(409, 'GUIDE_NOT_ACTIONABLE', '只有含已核对资料的引导建议可以加入计划')
    citation = run.result['citations'][0]
    material = s.material_access(db, ctx, db.get(m.Material, citation['material_id']))
    if material.sha256 != citation['sha256']:
        fail(403, 'SCOPE_CHANGED', '建议对应的原文版本已变化')
    path_id = run.metrics.get('mastery_path_id')
    if path_id:
        existing, binding = s.accepted_mastery(db, p)
        if existing:
            if binding['path_id'] != path_id:
                fail(409, 'GUIDE_ALREADY_ACCEPTED', '此资料范围已经有一份确认的学习路径')
            return {'task_id': existing.id}
    task = s.add_task(db, p, 'reading', '引导复习：'+material.title[:190], 'guide:'+(path_id or run.id),
        '先回到引导建议引用的原文，再完成独立检查', material.id,
        {'source_span':[citation['start'], citation['end']], **({'mastery_run_id': run.id} if path_id else {})}, minutes=10)
    return {'task_id': task.id}


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
    def save():
        db.refresh(previous)
        if previous.state != 'failed':
            fail(409, 'RETRY_NOT_ALLOWED', '仅失败运行可以显式重试')
        if settings.deeptutor_unified_execution and previous.error.startswith((
                'EXECUTION_UNCERTAIN', 'DEEPTUTOR_RECONNECT_FAILED', 'DEEPTUTOR_TIMEOUT', 'CANCEL_UNCERTAIN')):
            if (previous.external_id and previous.backend != 'bounded_chat' and
                    previous.kind in ('chat', 'read', 'solve', 'evaluate') and not previous.error.startswith('CANCEL_UNCERTAIN')):
                previous.state, previous.error, previous.lease_until = 'queued', '', None
                previous.metrics = {**previous.metrics, 'recovery_attempts': 1}
                return {'run_id': previous.id, 'state': previous.state}
            fail(409, 'EXECUTION_UNCERTAIN', '请先核对已有 DeepTutor 运行状态')
        row = create_run(db, p, previous.kind, previous.prompt, previous.task_id, ctx.membership.id,
                         None if settings.deeptutor_unified_execution else previous.backend)
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
