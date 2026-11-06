import hashlib
from typing import Literal
from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from sqlalchemy import select, update, delete
from . import models as m
from . import schemas as s
from .auth import context, need, source_allowed, teacher_can_view
from .db import get_db
from .errors import fail, require
from . import content as c
from .api_common import entity, idempotent, no_active_diagnostic, EnvelopeRoute
from .config import settings
from .ports import LocalFileStore

router = APIRouter(route_class=EnvelopeRoute)


def editor(ctx=Depends(context)):
    if not (ctx.has('teacher') or ctx.has('admin')):
        fail(403, 'ROLE_REQUIRED', '需要内容管理角色')
    return ctx


@router.get('/content/sources', response_model=s.SourceListOutput)
def sources(page: int = 1, page_size: int = 20, ctx=Depends(editor), db=Depends(get_db)):
    if page < 1 or not 1 <= page_size <= 100:
        fail(422, 'INVALID_PAGE', '分页参数无效')
    result = []
    for version, source in db.execute(select(m.SourceVersion, m.Source).join(m.Source).where(m.Source.org_id == ctx.org_id).order_by(m.Source.created_at, m.SourceVersion.number.desc())):
        if source_allowed(db, ctx, source):
            latest_run=db.scalar(select(m.AgentRun).where(m.AgentRun.source_version_id==version.id,m.AgentRun.purpose=='content').order_by(m.AgentRun.created_at.desc()))
            result.append({**entity(version, 'id', 'number', 'status', 'revision', 'knowledge_id', 'review_note'),
                           **entity(source, 'title', 'rights', 'visibility'), 'source_id': source.id,
                           'enabled':bool(db.scalar(select(m.SourceActivation.id).where(m.SourceActivation.version_id==version.id))),
                           'generation_state':latest_run.state if latest_run else None})
    return {'items': result[(page-1)*page_size:page*page_size], 'total': len(result), 'page': page, 'page_size': page_size}


@router.post('/content/sources', status_code=202)
def add_source(data: s.SourceInput, ctx=Depends(editor), db=Depends(get_db)):
    version, job = c.create_source(db, ctx, data)
    return {'id': version.id, 'job_id': job.id}


@router.post('/content/sources/upload', status_code=202)
async def upload(file: UploadFile = File(...), knowledge_id: str | None = Form(None), rights: str = Form('教师提供，限本机构教学使用'), ctx=Depends(editor), db=Depends(get_db)):
    filename = file.filename or ''
    if not filename.lower().endswith(('.md', '.txt', '.pdf', '.docx')):
        fail(422, 'FILE_TYPE', '仅接受 PDF、DOCX、Markdown 和 TXT 文件')
    body = await file.read(50 * 1024 * 1024 + 1)
    if len(body) > 50 * 1024 * 1024:
        fail(413, 'FILE_TOO_LARGE', '文件不能超过 50 MB')
    if filename.lower().endswith(('.pdf', '.docx')):
        from .documents import store
        suffix = '.pdf' if filename.lower().endswith('.pdf') else '.docx'
        if not body or (suffix == '.pdf' and not body.startswith(b'%PDF-')) or (suffix == '.docx' and not body.startswith(b'PK')):
            fail(422, 'DOCUMENT_INVALID', '文件内容与扩展名不符')
        try:
            data = s.SourceInput(title=filename[:200], text='等待原文件解析', knowledge_id=knowledge_id, rights=rights)
        except ValueError:
            fail(422, 'FILE_CONTENT_INVALID', '请填写授权说明及有效知识点')
        version, job = c.create_source(db, ctx, data)
        db.add(m.SourceDocument(version_id=version.id, filename=filename[:200], original_key=store(body, suffix)))
        job.kind = 'document'
        return {'id': version.id, 'job_id': job.id}
    try:
        text = body.decode('utf-8-sig')
    except UnicodeDecodeError:
        fail(422, 'FILE_ENCODING', '请使用 UTF-8 编码')
    try:
        data = s.SourceInput(title=filename[:200], text=text, knowledge_id=knowledge_id, rights=rights)
    except ValueError:
        fail(422, 'FILE_CONTENT_INVALID', '资料正文不能为空，文件不超过50MB，授权说明不能为空')
    version, job = c.create_source(db, ctx, data)
    from .documents import store
    # Preserve exact uploaded bytes, including UTF-8 BOM and original newlines.
    version.file_key = store(body, '.md' if filename.lower().endswith('.md') else '.txt')
    return {'id': version.id, 'job_id': job.id}


@router.get('/sources/versions/{version_id}', response_model=s.SourceOutput, response_model_exclude_unset=True)
def source_detail(version_id: str, ctx=Depends(context), db=Depends(get_db)):
    no_active_diagnostic(db, ctx)
    version, source = c.source_preview_access(db, ctx, version_id)
    c.audit(db, ctx, 'source.read', version.id)
    cards = list(db.scalars(select(m.CardVersion).where(m.CardVersion.source_version_id == version.id)))
    data = {**entity(version, 'id', 'number', 'status', 'text', 'sha256', 'revision', 'knowledge_id', 'review_note'),
            **entity(source, 'title', 'rights', 'visibility'),
            'chunks': [entity(x, 'id', 'position', 'heading', 'text') for x in db.scalars(select(m.SourceChunk).where(m.SourceChunk.version_id == version.id).order_by(m.SourceChunk.position))],
            'cards': [entity(x, 'id', 'title', 'body', 'status', 'number') for x in cards]}
    from .documents import document_view
    doc = db.scalar(select(m.SourceDocument).where(m.SourceDocument.version_id == version.id))
    data['document_info'] = document_view(doc) if doc else None
    for item in data['cards']:
        rule = db.scalar(select(m.CardRule).where(m.CardRule.card_id == item['id']))
        item['causes'] = rule.causes if rule else []
    if ctx.has('teacher') or ctx.has('admin'):
        private_ids = select(m.GeneratedQuestion.question_version_id).where(m.GeneratedQuestion.owner_membership_id != None)
        data['questions'] = [entity(x, 'id', 'question_id', 'number', 'kind', 'prompt', 'options', 'answer', 'explanation', 'hints', 'rubric', 'max_score', 'status', 'source_version_id') for x in db.scalars(select(m.QuestionVersion).where(m.QuestionVersion.source_version_id == version.id, m.QuestionVersion.id.not_in(private_ids)))]
    if ctx.has('teacher'):
        affected = []
        for attempt in db.scalars(select(m.Attempt).join(m.QuestionVersion, m.Attempt.question_version_id == m.QuestionVersion.id).where(m.QuestionVersion.source_version_id == version.id)):
            if teacher_can_view(db, ctx, attempt.membership_id):
                member = db.get(m.Membership, attempt.membership_id)
                affected.append({'id': attempt.id, 'student': db.get(m.User, member.user_id).name, 'status': attempt.status})
        data['affected_attempts'] = affected
    return data


@router.patch('/content/sources/{version_id}')
def edit_source(version_id: str, data: s.SourceEdit, ctx=Depends(editor), db=Depends(get_db)):
    version, _ = c.version_access(db, ctx, version_id)
    if version.status != 'draft':
        fail(409, 'IMMUTABLE_VERSION', '仅可编辑草稿，发布内容请创建新版本')
    if db.scalar(select(m.SourceDocument.id).where(m.SourceDocument.version_id == version.id)):
        fail(409, 'ORIGINAL_IMMUTABLE', '原页资料请上传修订原文件，不可修改文字后保留不一致原页')
    file_key = LocalFileStore(settings.data_dir / 'files').put(data.text.encode())
    changed = db.execute(update(m.SourceVersion).where(m.SourceVersion.id == version.id, m.SourceVersion.revision == data.revision, m.SourceVersion.status == 'draft').values(text=data.text, revision=data.revision+1, sha256=hashlib.sha256(data.text.encode()).hexdigest(), file_key=file_key))
    if changed.rowcount != 1:
        fail(409, 'STALE_REVISION', '资料已变化，请重新读取')
    ids = select(m.SourceChunk.id).where(m.SourceChunk.version_id == version.id)
    db.execute(delete(m.ChunkEmbedding).where(m.ChunkEmbedding.chunk_id.in_(ids)))
    db.execute(delete(m.SourceChunk).where(m.SourceChunk.version_id == version.id))
    db.add(m.Job(org_id=ctx.org_id, owner_id=ctx.user.id, kind='parse', resource_id=version.id))
    return {'id': version.id, 'revision': data.revision+1}


@router.post('/content/sources/{version_id}/versions')
def new_version(version_id: str, ctx=Depends(editor), db=Depends(get_db)):
    version = c.new_version(db, ctx, version_id)
    return {'id': version.id, 'number': version.number}


@router.post('/content/sources/{version_id}/{action}')
def transition(version_id: str, action: str, data: s.PublishInput, request: Request, ctx=Depends(editor), db=Depends(get_db)):
    if action not in ('submit', 'publish', 'withdraw', 'reject'):
        fail(404, 'NOT_FOUND', '未知内容操作')
    def run():
        v = c.transition(db, ctx, version_id, action, data.note)
        return {'id': v.id, 'status': v.status}
    return idempotent(db, ctx, request, f'content-{action}:{version_id}', data.model_dump(), run)


def draft_source(db, ctx, version_id):
    version, _ = c.version_access(db, ctx, version_id)
    if version.status != 'draft':
        fail(409, 'IMMUTABLE_VERSION', '题目和知识卡仅可在草稿阶段编辑')
    return version


@router.post('/content/cards')
def card(data: s.CardInput, ctx=Depends(editor), db=Depends(get_db)):
    version = draft_source(db, ctx, data.source_version_id)
    card = m.CardVersion(org_id=ctx.org_id, source_version_id=version.id, knowledge_id=version.knowledge_id, title=data.title, body=data.body)
    db.add(card)
    db.flush()
    return {'id': card.id}


@router.put('/content/cards/{card_id}')
def edit_card(card_id: str, data: s.CardInput, ctx=Depends(editor), db=Depends(get_db)):
    card = require(db.get(m.CardVersion, card_id))
    draft_source(db, ctx, card.source_version_id)
    if data.source_version_id != card.source_version_id:
        fail(422, 'SOURCE_MISMATCH', '不能改变知识卡来源版本')
    card.title, card.body = data.title, data.body
    return {'id': card.id}


@router.post('/content/questions')
def question(data: s.QuestionInput, ctx=Depends(editor), db=Depends(get_db)):
    version = draft_source(db, ctx, data.source_version_id)
    policy = db.scalar(select(m.ScoringPolicyVersion).where(m.ScoringPolicyVersion.strategy == data.kind))
    if not policy:
        policy = m.ScoringPolicyVersion(strategy=data.kind)
        db.add(policy)
        db.flush()
    q = m.QuestionVersion(org_id=ctx.org_id, knowledge_id=version.knowledge_id, policy_id=policy.id, **data.model_dump())
    db.add(q)
    db.flush()
    return {'id': q.id}


@router.put('/content/questions/{question_id}')
def edit_question(question_id: str, data: s.QuestionInput, ctx=Depends(editor), db=Depends(get_db)):
    q = require(db.get(m.QuestionVersion, question_id))
    draft_source(db, ctx, q.source_version_id)
    if data.source_version_id != q.source_version_id or data.kind != q.kind:
        fail(422, 'QUESTION_IDENTITY', '不能改变题型或来源版本')
    for key, value in data.model_dump().items():
        setattr(q, key, value)
    return {'id': q.id}


@router.get('/retrieval', response_model=list[s.EvidenceOutput])
def retrieval(query: str = '', knowledge_id: str | None = None, mode: Literal['keyword', 'hybrid'] = 'keyword', ctx=Depends(context), db=Depends(get_db)):
    no_active_diagnostic(db, ctx)
    if len(query) > 1000:
        fail(422, 'QUERY_TOO_LONG', '查询过长')
    if mode == 'hybrid':
        if settings.native_teaching_pipeline:
            fail(409, 'NATIVE_RETRIEVAL_ENABLED', '资料可使用关键词查找，AI 答疑使用 DeepTutor 检索')
        from .search import hybrid, SearchUnavailable
        try:
            return hybrid(db, ctx, query, knowledge_id)
        except SearchUnavailable as exc:
            fail(503, str(exc), '真实混合检索尚未就绪，请检查本地模型和索引')
    return c.retrieve(db, ctx, query, knowledge_id)


@router.post('/attempts/{attempt_id}/tutor-runs', status_code=202)
def tutor(attempt_id: str, request: Request, ctx=Depends(context), db=Depends(get_db)):
    from .learning import owned_attempt, owned_task
    no_active_diagnostic(db, ctx)
    a = owned_attempt(db, ctx, attempt_id)
    task, q = owned_task(db, ctx, a.task_id)
    if task.mode == 'diagnostic':
        fail(403, 'DIAGNOSTIC_RESTRICTION', '诊断不允许 AI 辅导')
    if a.status == 'draft':
        fail(409, 'SUBMIT_FIRST', '请先独立提交作答，再获取 AI 分析')
    if settings.native_teaching_pipeline:
        fail(409, 'NATIVE_TUTOR_ENABLED', '请从当前作答的 AI 辅导入口发起，原有运行记录仍可查看')
    if not settings.model_api_key or not settings.model_name or not settings.model_base_url:
        fail(503, 'MODEL_NOT_CONFIGURED', 'AI 服务未配置；审核解析、来源资料和学习流程仍可使用')
    def run():
        workflow = m.WorkflowRun(attempt_id=a.id, model=settings.model_name)
        db.add(workflow)
        db.flush()
        job = m.Job(org_id=ctx.org_id, owner_id=ctx.user.id, kind='tutor', resource_id=workflow.id)
        db.add(job)
        db.flush()
        return {'run_id': workflow.id, 'job_id': job.id}
    return idempotent(db, ctx, request, f'tutor:{a.id}', {}, run)


@router.get('/jobs/{job_id}', response_model=s.JobOutput, response_model_exclude_unset=True)
def job(job_id: str, ctx=Depends(context), db=Depends(get_db)):
    job = require(db.get(m.Job, job_id))
    if job.org_id != ctx.org_id or job.owner_id != ctx.user.id:
        fail(404, 'NOT_FOUND', '任务不存在')
    data = entity(job, 'id', 'kind', 'state', 'attempts', 'error_code')
    if job.kind == 'tutor':
        no_active_diagnostic(db, ctx)
        run = db.get(m.WorkflowRun, job.resource_id)
        data['result'] = run.result
    return data
