import hashlib
import re
from sqlalchemy import select, func, delete, or_
from . import models as m
from .auth import need, source_allowed
from .errors import fail, require
from .config import settings
from .ports import LocalFileStore


def audit(db, ctx, action, resource_id, detail=None):
    db.add(m.AuditEvent(org_id=ctx.org_id, actor_id=ctx.user.id, action=action, resource_id=resource_id, detail=detail or {}))


def version_access(db, ctx, version_id, published=False):
    version = require(db.get(m.SourceVersion, version_id))
    source = require(db.get(m.Source, version.source_id))
    if not source_allowed(db, ctx, source):
        fail(404, 'NOT_FOUND', '资料不存在或无权访问')
    if version.status in ('draft', 'pending') and not (ctx.has('teacher') or ctx.has('admin')):
        fail(404, 'NOT_FOUND', '资料尚未发布')
    if published and version.status != 'published':
        fail(409, 'CONTENT_UNAVAILABLE', '内容尚未发布或已撤回')
    return version, source


def source_preview_access(db, ctx, version_id):
    return version_access(db, ctx, version_id, published=not (ctx.has('teacher') or ctx.has('admin')))


def parse_chunks(db, version):
    if db.scalar(select(m.SourceChunk.id).where(m.SourceChunk.version_id == version.id)):
        return
    heading, paragraphs, sections = '正文', [], []
    for paragraph in re.split(r'\n\s*\n', version.text.strip()):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if paragraph.startswith('#'):
            if paragraphs:
                sections.append((heading, '\n\n'.join(paragraphs)))
            lines = paragraph.split('\n', 1)
            heading = lines[0].lstrip('# ').strip()[:250]
            paragraphs = [lines[1]] if len(lines) > 1 and lines[1].strip() else []
        else:
            paragraphs.append(paragraph)
    if paragraphs:
        sections.append((heading, '\n\n'.join(paragraphs)))
    for index, (title, body) in enumerate(sections, 1):
        db.add(m.SourceChunk(version_id=version.id, position=index, heading=title, text=body))


def create_source(db, ctx, data):
    if not (ctx.has('teacher') or ctx.has('admin')):
        fail(403, 'ROLE_REQUIRED', '需要内容管理权限')
    if data.knowledge_id:
        knowledge = require(db.get(m.KnowledgePoint, data.knowledge_id), '知识点不存在')
        if knowledge.org_id and knowledge.org_id != ctx.org_id:
            fail(404, 'NOT_FOUND', '知识点不存在')
    else:
        module = db.scalar(select(m.Module).where(m.Module.name == '教师资料'))
        if not module:
            subject = require(db.scalar(select(m.Subject).where(m.Subject.code == 'politics')))
            module = m.Module(subject_id=subject.id, name='教师资料', position=100)
            db.add(module)
            db.flush()
        knowledge = db.scalar(select(m.KnowledgePoint).where(m.KnowledgePoint.module_id == module.id,
                              m.KnowledgePoint.org_id == ctx.org_id, m.KnowledgePoint.name == '待提取知识'))
        if not knowledge:
            knowledge = m.KnowledgePoint(module_id=module.id, org_id=ctx.org_id, name='待提取知识')
            db.add(knowledge)
            db.flush()
    if data.visibility == 'class':
        cls = require(db.get(m.TeachingClass, data.class_id))
        if cls.org_id != ctx.org_id or not (ctx.has('admin') or any(r.role == 'teacher' and (r.class_id is None or r.class_id == cls.id) for r in ctx.roles)):
            fail(404, 'NOT_FOUND', '班级不存在或无权访问')
    text = data.text
    file_key = LocalFileStore(settings.data_dir / 'files').put(text.encode('utf-8'))
    source = m.Source(org_id=ctx.org_id, owner_id=ctx.user.id, title=data.title, visibility=data.visibility, class_id=data.class_id, rights=data.rights)
    db.add(source)
    db.flush()
    version = m.SourceVersion(source_id=source.id, text=text, sha256=hashlib.sha256(text.encode()).hexdigest(), file_key=file_key, knowledge_id=knowledge.id)
    db.add(version)
    db.flush()
    job = m.Job(org_id=ctx.org_id, owner_id=ctx.user.id, kind='parse', resource_id=version.id)
    db.add(job)
    db.flush()
    audit(db, ctx, 'source.create', version.id)
    return version, job


def transition(db, ctx, version_id, action, note):
    need(ctx, 'teacher')
    version, _ = version_access(db, ctx, version_id)
    if action == 'submit':
        if version.status != 'draft':
            fail(409, 'INVALID_STATE', '只有草稿可以提交审核')
        doc = db.scalar(select(m.SourceDocument).where(m.SourceDocument.version_id == version.id))
        if doc and (doc.state != 'parsed' or not doc.confirmed):
            fail(409, 'DOCUMENT_REVIEW_REQUIRED', '请等待解析成功并确认原页核对')
        parse_chunks(db, version)
        db.flush()
        ensure_index(db, version.id)
        version.status = 'pending'
    elif action == 'publish':
        if version.status != 'pending':
            fail(409, 'INVALID_STATE', '需要先提交审核')
        ensure_index(db, version.id)
        cards = list(db.scalars(select(m.CardVersion).where(m.CardVersion.source_version_id == version.id)))
        questions = list(db.scalars(select(m.QuestionVersion).where(m.QuestionVersion.source_version_id == version.id)))
        if not cards or not questions:
            fail(422, 'INCOMPLETE_CONTENT', '发布需至少一张知识卡和一道已核对题目')
        parse_chunks(db, version)
        # Older versions remain readable for history; only latest is used for new work.
        version.status = 'published'
        for obj in cards + questions:
            obj.status = 'published'
    elif action == 'withdraw':
        if version.status != 'published':
            fail(409, 'INVALID_STATE', '只有发布版本可以撤回')
        version.status = 'withdrawn'
        for cls in (m.CardVersion, m.QuestionVersion):
            for obj in db.scalars(select(cls).where(cls.source_version_id == version.id)):
                obj.status = 'withdrawn'
    elif action == 'reject':
        if version.status != 'pending':
            fail(409, 'INVALID_STATE', '只有待审核内容可以退回')
        version.status = 'draft'
    version.review_note = note
    version.revision += 1
    db.add(m.ContentReview(org_id=ctx.org_id, version_id=version.id, reviewer_id=ctx.user.id, action=action, note=note))
    audit(db, ctx, f'content.{action}', version.id, {'note': note})
    return version


def ensure_index(db, version_id):
    from .search import fingerprint
    ids = list(db.scalars(select(m.SourceChunk.id).where(m.SourceChunk.version_id == version_id)))
    if settings.native_teaching_pipeline and ids:
        return  # DeepTutor indexes the authorized chapter selection when its teaching run begins.
    indexed = len(list(db.scalars(select(m.ChunkEmbedding.id).where(m.ChunkEmbedding.chunk_id.in_(ids), m.ChunkEmbedding.model_revision == fingerprint()))))
    if not ids or indexed != len(ids):
        fail(409, 'INDEX_NOT_READY', '请等待后台索引完成，或点击重建索引后再提交审核')


def new_version(db, ctx, version_id):
    need(ctx, 'teacher')
    old, _ = version_access(db, ctx, version_id)
    if old.status not in ('published', 'withdrawn'):
        fail(409, 'INVALID_STATE', '未发布内容请直接编辑草稿')
    number = db.scalar(select(func.max(m.SourceVersion.number)).where(m.SourceVersion.source_id == old.source_id)) + 1
    version = m.SourceVersion(source_id=old.source_id, number=number, text=old.text, sha256=old.sha256, file_key=old.file_key, knowledge_id=old.knowledge_id)
    db.add(version)
    db.flush()
    original = db.scalar(select(m.SourceDocument).where(m.SourceDocument.version_id == old.id))
    if original:
        db.add(m.SourceDocument(version_id=version.id, filename=original.filename, original_key=original.original_key,
            preview_key=original.preview_key, state=original.state, pages=original.pages, confirmed=False))
        for c in db.scalars(select(m.SourceChunk).where(m.SourceChunk.version_id == old.id)):
            db.add(m.SourceChunk(version_id=version.id, position=c.position, heading=c.heading, text=c.text))
    for card in db.scalars(select(m.CardVersion).where(m.CardVersion.source_version_id == old.id)):
        copy = m.CardVersion(card_id=card.card_id, number=number, org_id=card.org_id, source_version_id=version.id, knowledge_id=card.knowledge_id, title=card.title, body=card.body)
        db.add(copy)
        db.flush()
        rule = db.scalar(select(m.CardRule).where(m.CardRule.card_id == card.id))
        if rule:
            db.add(m.CardRule(card_id=copy.id, causes=rule.causes))
    for q in db.scalars(select(m.QuestionVersion).where(m.QuestionVersion.source_version_id == old.id)):
        db.add(m.QuestionVersion(question_id=q.question_id, number=number, org_id=q.org_id, source_version_id=version.id, knowledge_id=q.knowledge_id, policy_id=q.policy_id, kind=q.kind, prompt=q.prompt, options=q.options, answer=q.answer, explanation=q.explanation, rubric=q.rubric, hints=q.hints, max_score=q.max_score))
    audit(db, ctx, 'content.new_version', version.id)
    parse_chunks(db, version)
    if not settings.native_teaching_pipeline:
        db.add(m.Job(org_id=ctx.org_id, owner_id=ctx.user.id, kind='index', resource_id=version.id))
    return version


def available_questions(db, ctx, knowledge_id=None):
    stmt = select(m.QuestionVersion).where(m.QuestionVersion.org_id == ctx.org_id, m.QuestionVersion.status == 'published')
    if knowledge_id:
        stmt = stmt.where(m.QuestionVersion.knowledge_id == knowledge_id)
    result = []
    for q in db.scalars(stmt.order_by(m.QuestionVersion.created_at, m.QuestionVersion.id)):
        generated = db.scalar(select(m.GeneratedQuestion).where(m.GeneratedQuestion.question_version_id == q.id))
        if generated and (generated.disabled or (generated.owner_membership_id and generated.owner_membership_id != ctx.membership.id)):
            continue
        v = db.get(m.SourceVersion, q.source_version_id)
        source = db.get(m.Source, v.source_id)
        latest = db.scalar(select(func.max(m.SourceVersion.number)).where(m.SourceVersion.source_id == v.source_id, m.SourceVersion.status == 'published'))
        if source_allowed(db, ctx, source) and v.status == 'published' and v.number == latest:
            result.append(q)
    return result


def retrieve(db, ctx, query='', knowledge_id=None, version_id=None, limit=5):
    stmt = select(m.SourceChunk, m.SourceVersion, m.Source).join(m.SourceVersion, m.SourceChunk.version_id == m.SourceVersion.id).join(m.Source, m.SourceVersion.source_id == m.Source.id).where(m.Source.org_id == ctx.org_id)
    if version_id:
        statuses = ['published', 'withdrawn'] if ctx.has('teacher') or ctx.has('admin') else ['published']
        stmt = stmt.where(m.SourceVersion.id == version_id, m.SourceVersion.status.in_(statuses))
    else:
        stmt = stmt.where(m.SourceVersion.status == 'published')
    if knowledge_id:
        stmt = stmt.where(or_(m.SourceVersion.knowledge_id == knowledge_id,
            select(m.SourceKnowledge.id).where(m.SourceKnowledge.version_id == m.SourceVersion.id,
                m.SourceKnowledge.knowledge_id == knowledge_id).exists()))
    tokens = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{2,}', query.lower())
    pairs = [t[i:i+2] for t in tokens for i in range(len(t)-1)]
    results = []
    for chunk, version, source in db.execute(stmt):
        if not source_allowed(db, ctx, source):
            continue
        latest = db.scalar(select(func.max(m.SourceVersion.number)).where(m.SourceVersion.source_id == source.id, m.SourceVersion.status == 'published'))
        if not version_id and version.number != latest:
            continue
        score = sum(1 for t in pairs if t in chunk.text.lower()) + (4 if knowledge_id else 0)
        if score or not query:
            results.append({'chunk_id': chunk.id, 'version_id': version.id, 'source_title': source.title,
                            'version': version.number, 'position': chunk.position, 'heading': chunk.heading,
                            'text': chunk.text, 'score': score, 'page': chunk.position if db.scalar(select(m.SourceDocument.id).where(m.SourceDocument.version_id == version.id)) else None,
                            'url': f'/sources/{version.id}?page={chunk.position}&chunk={chunk.id}'})
    ordered = sorted(results, key=lambda x: -x['score'])
    return ordered if limit is None else ordered[:limit]
