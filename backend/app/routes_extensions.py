from pathlib import Path
from fastapi import APIRouter, Depends, Request, UploadFile, File
from fastapi.responses import FileResponse, Response
from sqlalchemy import select, or_
from pydantic import BaseModel, Field
from . import models as m, schemas as s
from .auth import context, need, teacher_can_view
from .db import get_db, SessionLocal
from .errors import fail, require
from .api_common import EnvelopeRoute, idempotent, no_active_diagnostic, entity
from .content import version_access, source_preview_access, audit
from .learning import owned_attempt
from .ai_services import AIInput, TUTOR_CHAT, advisory_completion, advisory_model, configured, completion, evidence_access, CAUSES
from .ai import WorkflowError
from .config import settings
from .documents import document_view
from .search import build_index, SearchUnavailable

router = APIRouter(route_class=EnvelopeRoute)


class CardCauses(BaseModel):
    causes: list[str] = Field(max_length=6)


@router.put('/content/cards/{card_id}/causes')
def card_causes(card_id: str, data: CardCauses, ctx=Depends(context), db=Depends(get_db)):
    need(ctx, 'teacher')
    card = require(db.get(m.CardVersion, card_id))
    version, _ = version_access(db, ctx, card.source_version_id)
    if version.status != 'draft':
        fail(409, 'IMMUTABLE_VERSION', '请先创建修订草稿')
    if any(c not in CAUSES for c in data.causes) or len(set(data.causes)) != len(data.causes):
        fail(422, 'INVALID_CAUSE', '请选择有效且不重复的错因')
    rule = db.scalar(select(m.CardRule).where(m.CardRule.card_id == card_id))
    if not rule:
        rule = m.CardRule(card_id=card_id)
        db.add(rule)
    rule.causes = data.causes
    audit(db, ctx, 'card.causes', card_id, {'causes': data.causes})
    return {'causes': data.causes}


@router.post('/documents/{version_id}/original', status_code=202)
async def replace_original(version_id: str, file: UploadFile = File(...), ctx=Depends(context), db=Depends(get_db)):
    need(ctx, 'teacher')
    version, _ = version_access(db, ctx, version_id)
    if version.status != 'draft':
        fail(409, 'IMMUTABLE_VERSION', '请先创建修订草稿')
    doc = require(db.scalar(select(m.SourceDocument).where(m.SourceDocument.version_id == version_id)))
    pending = db.scalar(select(m.Job.id).where(m.Job.resource_id == version_id, m.Job.kind == 'document', m.Job.state.in_(['queued', 'running'])))
    if pending:
        fail(409, 'DOCUMENT_BUSY', '已有解析任务，请稍后再替换')
    name = file.filename or ''
    suffix = Path(name).suffix.lower()
    body = await file.read(50*1024*1024+1)
    if suffix not in ('.pdf', '.docx') or not body or len(body)>50*1024*1024:
        fail(422, 'FILE_CONTENT_INVALID', '请上传不超过50MB的PDF或DOCX')
    if (suffix=='.pdf' and not body.startswith(b'%PDF-')) or (suffix=='.docx' and not body.startswith(b'PK')):
        fail(422, 'DOCUMENT_INVALID', '文件内容与扩展名不符')
    from .documents import store
    doc.original_key, doc.filename, doc.state = store(body, suffix), name[:200], 'queued'
    doc.preview_key, doc.pages, doc.confirmed, doc.error_code = None, [], False, ''
    from sqlalchemy import delete
    ids = select(m.SourceChunk.id).where(m.SourceChunk.version_id == version_id)
    db.execute(delete(m.ChunkEmbedding).where(m.ChunkEmbedding.chunk_id.in_(ids)))
    db.execute(delete(m.SourceChunk).where(m.SourceChunk.version_id == version_id))
    job = m.Job(org_id=ctx.org_id, owner_id=ctx.user.id, kind='document', resource_id=version_id)
    db.add(job)
    db.flush()
    return {'job_id': job.id}


@router.get('/sources/versions/{version_id}/document')
def document(version_id: str, ctx=Depends(context), db=Depends(get_db)):
    no_active_diagnostic(db, ctx)
    source_preview_access(db, ctx, version_id)
    row = db.scalar(select(m.SourceDocument).where(m.SourceDocument.version_id == version_id))
    return document_view(row) if row else None


@router.get('/sources/versions/{version_id}/{file_kind}')
def original(version_id: str, file_kind: str, ctx=Depends(context), db=Depends(get_db)):
    no_active_diagnostic(db, ctx)
    version, source = source_preview_access(db, ctx, version_id)
    if file_kind not in ('original', 'preview'):
        fail(404, 'NOT_FOUND', '文件不存在')
    row = db.scalar(select(m.SourceDocument).where(m.SourceDocument.version_id == version_id))
    if not row:
        key = version.file_key
        if file_kind != 'original' or not key or Path(key).name != key:
            fail(404,'NOT_FOUND','原始文本不存在')
        return FileResponse(settings.data_dir/'files'/key,media_type='text/plain; charset=utf-8',
                            filename=source.title,content_disposition_type='attachment')
    key = row.original_key if file_kind == 'original' else row.preview_key
    if not key or Path(key).name != key:
        fail(404, 'NOT_FOUND', '预览尚未生成')
    return FileResponse(settings.data_dir / 'files' / key, media_type='application/pdf' if key.endswith('.pdf') else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                        filename=row.filename if file_kind == 'original' else 'preview.pdf', content_disposition_type='inline')


@router.get('/sources/versions/{version_id}/pages/{page}')
def page_image(version_id: str, page: int, chunk: str = '', ctx=Depends(context), db=Depends(get_db)):
    no_active_diagnostic(db, ctx)
    source_preview_access(db, ctx, version_id)
    row = require(db.scalar(select(m.SourceDocument).where(m.SourceDocument.version_id == version_id)))
    if not row.preview_key or not 1 <= page <= len(row.pages):
        fail(404, 'NOT_FOUND', '原页尚未生成')
    import pymupdf as fitz
    with fitz.open(settings.data_dir / 'files' / row.preview_key) as pdf:
        original = pdf[page-1]
        if chunk:
            c = require(db.get(m.SourceChunk, chunk))
            if c.version_id != version_id or c.position != page:
                fail(404, 'NOT_FOUND', '引用不属于此页')
            for block in row.pages[page-1]['blocks']:
                original.add_highlight_annot(fitz.Rect(block['bbox']))
        return Response(original.get_pixmap(matrix=fitz.Matrix(1.4, 1.4)).tobytes('png'), media_type='image/png')


@router.post('/documents/{version_id}/confirm')
def confirm_document(version_id: str, ctx=Depends(context), db=Depends(get_db)):
    need(ctx, 'teacher')
    version, _ = version_access(db, ctx, version_id)
    doc = require(db.scalar(select(m.SourceDocument).where(m.SourceDocument.version_id == version_id)))
    if version.status != 'draft' or doc.state != 'parsed':
        fail(409, 'DOCUMENT_NOT_READY', '请先完成解析并核对草稿原页')
    doc.confirmed = True
    audit(db, ctx, 'document.confirm', version_id)
    return document_view(doc)


@router.post('/documents/{version_id}/retry')
def retry_document(version_id: str, ctx=Depends(context), db=Depends(get_db)):
    need(ctx, 'teacher')
    version, _ = version_access(db, ctx, version_id)
    doc = require(db.scalar(select(m.SourceDocument).where(m.SourceDocument.version_id == version_id)))
    if version.status != 'draft' or doc.state != 'failed':
        fail(409, 'INVALID_STATE', '仅失败的草稿解析可重试')
    doc.state, doc.error_code = 'queued', ''
    job = m.Job(org_id=ctx.org_id, owner_id=ctx.user.id, kind='document', resource_id=version_id)
    db.add(job)
    db.flush()
    return {'job_id': job.id}


@router.post('/content/indexes/{version_id}/rebuild')
def rebuild(version_id: str, ctx=Depends(context), db=Depends(get_db)):
    if not (ctx.has('teacher') or ctx.has('admin')):
        fail(403, 'ROLE_REQUIRED', '需要内容管理角色')
    version_access(db, ctx, version_id)
    if settings.native_teaching_pipeline:
        fail(409, 'NATIVE_INDEX_MANAGED', 'DeepTutor 在出题时为选定资料建立索引，可重试失败的生成任务')
    job = m.Job(org_id=ctx.org_id, owner_id=ctx.user.id, kind='index', resource_id=version_id)
    db.add(job)
    db.flush()
    return {'job_id': job.id}


@router.get('/content/indexes/{version_id}')
def index_status(version_id: str, ctx=Depends(context), db=Depends(get_db)):
    if not (ctx.has('teacher') or ctx.has('admin')):
        fail(403, 'ROLE_REQUIRED', '需要内容管理角色')
    version_access(db, ctx, version_id)
    from .search import fingerprint
    ids = list(db.scalars(select(m.SourceChunk.id).where(m.SourceChunk.version_id == version_id)))
    if settings.native_teaching_pipeline:
        return {'backend': 'deeptutor', 'chunks': len(ids), 'indexed': 0, 'state': 'ready' if ids else 'not_ready'}
    indexed = len(list(db.scalars(select(m.ChunkEmbedding.id).where(m.ChunkEmbedding.chunk_id.in_(ids), m.ChunkEmbedding.model_revision == fingerprint()))))
    return {'model_revision': fingerprint(), 'chunks': len(ids), 'indexed': indexed,
            'state': 'ready' if ids and len(ids) == indexed else 'not_ready'}


@router.get('/ai/status')
def ai_status(ctx=Depends(context)):
    need(ctx, 'admin')
    model = advisory_model('lesson')
    native = model == TUTOR_CHAT
    return {'configured': configured(model), 'model': model, 'provider': 'DeepTutor' if native else 'DeepSeek',
            'key_present': False if native else bool(settings.model_api_key),
            'price_version': None if native else settings.model_price_version}


@router.post('/ai/connection-test')
def connection_test(ctx=Depends(context), db=Depends(get_db)):
    need(ctx, 'admin')
    model = advisory_model('lesson')
    native = model == TUTOR_CHAT
    if not configured(model):
        fail(503, 'MODEL_NOT_CONFIGURED', '请配置 DeepTutor 服务和内部连接' if native else
             '请在服务端 .env 填写 MODEL_API_KEY 后重启服务')
    # Authentication read the session using this request's DB transaction.
    # Release it before the external provider call as well.
    db.commit()
    metrics = {}
    try:
        prompt = [{'role': 'system', 'content': '只返回JSON {"ok":true}'}, {'role': 'user', 'content': '测试连接'}]
        result = (advisory_completion(model, f'v1:health:{ctx.user.id}', m.uid(), prompt, metrics)
                  if native else completion(prompt, metrics))
    except WorkflowError as exc:
        with SessionLocal.begin() as log_db:
            audit(log_db, ctx, 'ai.connection_test', ctx.user.id, {'error_code': exc.code, 'metrics': metrics})
        fail(503, exc.code, ('DeepTutor' if native else 'DeepSeek') + ' 连接测试失败，请核对服务配置或网络')
    with SessionLocal.begin() as log_db:
        audit(log_db, ctx, 'ai.connection_test', ctx.user.id, {'connected': result.get('ok') is True, 'metrics': metrics})
    return {'connected': result.get('ok') is True, 'metrics': metrics, 'model': model}


@router.post('/ai/requests', status_code=202)
def create_ai(data: AIInput, request: Request, ctx=Depends(context), db=Depends(get_db)):
    if data.purpose == 'lesson':
        need(ctx, 'teacher')
        require(db.get(m.KnowledgePoint, data.knowledge_id))
    else:
        need(ctx, 'student')
        no_active_diagnostic(db, ctx)
        a = owned_attempt(db, ctx, data.attempt_id)
        task = db.get(m.LearningTask, a.task_id)
        if task.mode == 'diagnostic':
            fail(403, 'DIAGNOSTIC_RESTRICTION', '诊断期间不允许 AI')
        if data.purpose in ('cause', 'evaluation') and a.status == 'draft':
            fail(409, 'SUBMIT_FIRST', '请先独立提交作答')
        if data.purpose == 'evaluation' and db.get(m.QuestionVersion, a.question_version_id).kind != 'essay':
            fail(422, 'OBJECTIVE_RULE_ONLY', '客观题由规则判分')
        if data.purpose == 'hint' and (a.status != 'draft' or data.level > a.hint_level + 1):
            fail(409, 'HINT_ORDER', '请在作答期间逐级查看提示')
    model = advisory_model(data.purpose)
    if not configured(model):
        fail(503, 'MODEL_NOT_CONFIGURED', '请配置当前 AI 服务；当前没有真实模型结果')
    def create():
        if data.purpose != 'lesson':
            if data.purpose in ('hint', 'question') and a.status == 'draft':
                db.add(m.LearningEvent(attempt_id=a.id, kind='ai_requested', event_key=m.uid(), payload={'purpose': data.purpose, 'level': data.level}))
        payload = data.model_dump()
        payload['draft'] = data.purpose != 'lesson' and a.status == 'draft'
        payload['_native_retrieval'] = model == TUTOR_CHAT and settings.deeptutor_native_knowledge
        row = m.AIRequest(org_id=ctx.org_id, owner_id=ctx.user.id, membership_id=ctx.membership.id,
            attempt_id=data.attempt_id if data.purpose != 'lesson' else None, knowledge_id=data.knowledge_id,
            purpose=data.purpose, input=payload, model=model)
        db.add(row)
        db.flush()
        db.add(m.Job(org_id=ctx.org_id, owner_id=ctx.user.id, kind='ai_request', resource_id=row.id))
        return {'id': row.id, 'state': row.state}
    return idempotent(db, ctx, request, 'ai:create', data.model_dump(), create)


def advisory_available(db, ctx, row):
    if row.model != TUTOR_CHAT or row.state != 'succeeded':
        return True
    try:
        for version_id in row.metrics.get('authorized_versions', [item['version_id'] for item in row.result.get('sources', [])]):
            evidence_access(db, ctx, version_id)
    except WorkflowError:
        return False
    return True


def ai_view(row):
    result = entity(row, 'id', 'purpose', 'attempt_id', 'knowledge_id', 'state', 'model', 'result', 'error_code', 'metrics', 'created_at')
    result['metrics'] = {key: value for key, value in row.metrics.items() if key not in ('external_id', 'authorized_versions')}
    return result


@router.get('/ai/requests')
def list_ai(attempt_id: str | None = None, ctx=Depends(context), db=Depends(get_db)):
    if ctx.has('student'):
        no_active_diagnostic(db, ctx)
    stmt = select(m.AIRequest).where(m.AIRequest.owner_id == ctx.user.id, m.AIRequest.org_id == ctx.org_id)
    if attempt_id:
        stmt = stmt.where(m.AIRequest.attempt_id == attempt_id)
    return [ai_view(r) for r in db.scalars(stmt.order_by(m.AIRequest.created_at.desc()).limit(100)) if advisory_available(db, ctx, r)]


@router.post('/ai/requests/{run_id}/retry')
def retry_ai(run_id: str, ctx=Depends(context), db=Depends(get_db)):
    row = require(db.get(m.AIRequest, run_id))
    if row.owner_id != ctx.user.id or row.org_id != ctx.org_id:
        fail(404, 'NOT_FOUND', '任务不存在')
    if ctx.has('student'):
        no_active_diagnostic(db, ctx)
    if row.state != 'failed':
        fail(409, 'INVALID_STATE', '仅失败任务可重试')
    if not configured(row.model):
        fail(503, 'MODEL_NOT_CONFIGURED', '请配置该任务使用的模型服务')
    from sqlalchemy import update
    changed = db.execute(update(m.AIRequest).where(m.AIRequest.id == row.id, m.AIRequest.state == 'failed').values(state='queued', error_code=''))
    if changed.rowcount != 1:
        fail(409, 'INVALID_STATE', '任务已被重试')
    db.refresh(row)
    db.add(m.Job(org_id=ctx.org_id, owner_id=ctx.user.id, kind='ai_request', resource_id=row.id))
    return ai_view(row)


class Note(BaseModel):
    text: str = Field(min_length=1, max_length=10000)


@router.post('/attempts/{attempt_id}/referrals')
def refer(attempt_id: str, data: Note, ctx=Depends(context), db=Depends(get_db)):
    need(ctx, 'student')
    no_active_diagnostic(db, ctx)
    a = owned_attempt(db, ctx, attempt_id)
    if db.get(m.LearningTask, a.task_id).mode == 'diagnostic':
        fail(403, 'DIAGNOSTIC_RESTRICTION', '诊断中不能申请辅导')
    row = db.scalar(select(m.TeachingReferral).where(m.TeachingReferral.attempt_id == a.id, m.TeachingReferral.state == 'open'))
    if not row:
        row = m.TeachingReferral(attempt_id=a.id, reason=data.text)
        db.add(row)
        db.flush()
    return {'id': row.id, 'state': row.state}


@router.get('/teaching/referrals')
def referrals(ctx=Depends(context), db=Depends(get_db)):
    if ctx.has('student'):
        no_active_diagnostic(db, ctx)
    result = []
    for r in db.scalars(select(m.TeachingReferral).order_by(m.TeachingReferral.created_at.desc())):
        a = db.get(m.Attempt, r.attempt_id)
        if a.membership_id == ctx.membership.id or teacher_can_view(db, ctx, a.membership_id):
            result.append({**entity(r, 'id', 'attempt_id', 'reason', 'state', 'response', 'created_at'),
                'prompt': db.get(m.QuestionVersion, a.question_version_id).prompt})
    return result


@router.post('/teaching/referrals/{referral_id}/resolve')
def resolve_referral(referral_id: str, data: Note, ctx=Depends(context), db=Depends(get_db)):
    need(ctx, 'teacher')
    r = require(db.get(m.TeachingReferral, referral_id))
    a = db.get(m.Attempt, r.attempt_id)
    if not teacher_can_view(db, ctx, a.membership_id):
        fail(404, 'NOT_FOUND', '转办不存在')
    if r.state != 'open':
        fail(409, 'INVALID_STATE', '此转办已处理')
    r.state, r.response, r.teacher_id = 'resolved', data.text, ctx.user.id
    audit(db, ctx, 'referral.resolve', r.id)
    return {'id': r.id, 'state': r.state}


@router.get('/teacher/lessons')
def lessons(ctx=Depends(context), db=Depends(get_db)):
    need(ctx, 'teacher')
    return [entity(r, 'id', 'request_id', 'body', 'revision') for r in db.scalars(select(m.LessonDraft).where(m.LessonDraft.owner_id == ctx.user.id))
            if advisory_available(db, ctx, db.get(m.AIRequest, r.request_id))]


class LessonEdit(Note):
    revision: int


@router.put('/teacher/lessons/{lesson_id}')
def edit_lesson(lesson_id: str, data: LessonEdit, ctx=Depends(context), db=Depends(get_db)):
    need(ctx, 'teacher')
    row = require(db.get(m.LessonDraft, lesson_id))
    if row.owner_id != ctx.user.id:
        fail(404, 'NOT_FOUND', '教案不存在')
    if not advisory_available(db, ctx, db.get(m.AIRequest, row.request_id)):
        fail(403, 'ACCESS_REVOKED', '教案引用的资料已撤回')
    from sqlalchemy import update
    result = db.execute(update(m.LessonDraft).where(m.LessonDraft.id == row.id, m.LessonDraft.revision == data.revision).values(body=data.text, revision=data.revision+1))
    if result.rowcount != 1:
        fail(409, 'STALE_REVISION', '教案已变化，请刷新')
    return {'id': row.id, 'revision': data.revision+1}


@router.get('/knowledge/status')
def knowledge_status(ctx=Depends(context), db=Depends(get_db)):
    need(ctx, 'student')
    no_active_diagnostic(db, ctx)
    from .learning import current_evaluation
    result = []
    for kp in db.scalars(select(m.KnowledgePoint).where(or_(m.KnowledgePoint.org_id==None,m.KnowledgePoint.org_id==ctx.org_id))):
        attempts = list(db.scalars(select(m.Attempt).join(m.QuestionVersion).where(m.Attempt.membership_id == ctx.membership.id,
            m.QuestionVersion.knowledge_id == kp.id, m.Attempt.status != 'draft').order_by(m.Attempt.created_at.desc())))
        state = '待诊断'
        if attempts:
            a = attempts[0]
            ev = current_evaluation(db, a.id)
            state = '待验证' if not ev else '已有独立正确证据' if ev['score'] == db.get(m.QuestionVersion, a.question_version_id).max_score and a.hint_level == 0 else '存在薄弱线索'
            remediation = db.scalar(select(m.Remediation).where(m.Remediation.attempt_id == a.id))
            if state == '存在薄弱线索' and remediation and remediation.verification_task_id:
                pending = db.scalar(select(m.Attempt.id).where(m.Attempt.task_id == remediation.verification_task_id, m.Attempt.status != 'draft'))
                if not pending:
                    state = '待验证'
        result.append({'id': kp.id, 'name': kp.name, 'state': state,
            'requires': list(db.scalars(select(m.Prerequisite.requires_id).where(m.Prerequisite.knowledge_id == kp.id)))})
    return result


@router.post('/teacher/remediations/{remediation_id}/cause')
def teacher_cause(remediation_id: str, data: s.CauseInput, ctx=Depends(context), db=Depends(get_db)):
    need(ctx, 'teacher')
    r = require(db.get(m.Remediation, remediation_id))
    a = db.get(m.Attempt, r.attempt_id)
    if not teacher_can_view(db, ctx, a.membership_id):
        fail(404, 'NOT_FOUND', '补学记录不存在')
    from .learning import change_cause
    change_cause(db, ctx, r, data.cause)
    return {'confirmed': True}


@router.get('/teacher/attempts/{attempt_id}/learning-chain')
def learning_chain(attempt_id: str, ctx=Depends(context), db=Depends(get_db)):
    need(ctx, 'teacher')
    original = require(db.get(m.Attempt, attempt_id))
    if not teacher_can_view(db, ctx, original.membership_id):
        fail(404, 'NOT_FOUND', '作答不存在')
    remediation = db.scalar(select(m.Remediation).where(m.Remediation.attempt_id == original.id))
    related = [original.id]
    verification = None
    if remediation and remediation.verification_task_id:
        verification = db.scalar(select(m.Attempt).where(m.Attempt.task_id == remediation.verification_task_id))
        if verification:
            related.append(verification.id)
    from .workflows import visible_agents, grading_view
    practices = []
    from .learning import current_evaluation
    for practice in db.scalars(select(m.TargetedPractice).where(m.TargetedPractice.origin_attempt_id==original.id)):
        entries = []
        for link in db.scalars(select(m.PracticeTask).where(m.PracticeTask.practice_id==practice.id).order_by(m.PracticeTask.position)):
            attempt = db.scalar(select(m.Attempt).where(m.Attempt.task_id==link.task_id))
            related.append(attempt.id)
            entries.append({**entity(attempt,'id','status','answer','response_text','hint_level'),
                            **grading_view(db,ctx,attempt),'evaluation':current_evaluation(db,attempt.id)})
        practices.append({'id':practice.id,'state':practice.state,'attempts':entries})
    reviews = list(db.scalars(select(m.ReviewSchedule).where(m.ReviewSchedule.attempt_id.in_(related))))
    return {'remediation': entity(remediation, 'id', 'cause', 'cause_status') if remediation else None,
            'agents': visible_agents(db, ctx, db.scalars(select(m.AgentRun).where(m.AgentRun.attempt_id==original.id).order_by(m.AgentRun.created_at))),
            'practices': practices,
            'verification': entity(verification, 'id', 'status', 'answer', 'response_text', 'hint_level') if verification else None,
            'reviews': [entity(r, 'stage', 'due_at', 'state', 'task_id') for r in reviews],
            'ai': [ai_view(r) for r in db.scalars(select(m.AIRequest).where(m.AIRequest.attempt_id.in_(related))) if advisory_available(db, ctx, r)],
            'events': [entity(e, 'kind', 'payload', 'created_at') for e in db.scalars(select(m.LearningEvent).where(m.LearningEvent.attempt_id.in_(related)).order_by(m.LearningEvent.created_at))]}
