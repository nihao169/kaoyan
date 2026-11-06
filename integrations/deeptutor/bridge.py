"""Loaded inside the pinned DeepTutor image; no modification of upstream source.

Each platform user/project/scope maps to an isolated native non-admin account.
Only a 60-second signed exchange is exposed to the private platform network.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from io import BytesIO
from typing import Literal
from fastapi import BackgroundTasks, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field
from deeptutor.api.main import app
from deeptutor.services.auth import AUTH_ENABLED, add_user, create_token, get_user_info, list_users
from deeptutor.multi_user.grants import empty_grant, save_grant
from deeptutor.multi_user.model_access import admin_catalog, is_owner_bound

_lock = threading.Lock()


class Assertion(BaseModel):
    principal: str = Field(min_length=1, max_length=200)
    expires: int
    audience: str


def check_assertion(data, signature):
    secret = os.environ.get('DEEPTUTOR_BRIDGE_SECRET', '')
    if not AUTH_ENABLED or len(secret) < 32:
        raise HTTPException(503, 'Bridge requires authentication and a 32-character secret')
    body = json.dumps(data.model_dump(), sort_keys=True, separators=(',', ':')).encode()
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature) or data.audience != 'zhixing-deeptutor' or not 0 < data.expires - time.time() <= 65:
        raise HTTPException(403, 'Invalid identity assertion')


def execution_user(principal):
    username = 'zx_' + hashlib.sha256(principal.encode()).hexdigest()[:40]
    with _lock:
        if not list_users():
            # Native bootstrap promotes the first account. Reserve it for operations.
            add_user('zx_service_admin', secrets.token_urlsafe(48), role='admin')
        user = get_user_info(username)
        if not user:
            add_user(username, secrets.token_urlsafe(48), role='user')
            user = get_user_info(username)
        if user.get('role') != 'user':
            raise HTTPException(503, 'Execution identity must not be admin')
        grant = empty_grant(user['id'])
        llm = admin_catalog().get('services', {}).get('llm', {})
        profile_id, model_id = llm.get('active_profile_id'), llm.get('active_model_id')
        profile = next((p for p in llm.get('profiles', []) if p.get('id') == profile_id), None)
        if not profile or is_owner_bound(profile) or not model_id:
            raise HTTPException(503, 'Configure a shareable active API-key model first')
        grant['models']['llm'] = [{'profile_id': profile_id, 'model_ids': [model_id]}]
        grant.update(enabled_tools=[], mcp_tools=[], cli_apps=[], exec_enabled=False)
        save_grant(user['id'], grant)
        return username, user['id']


@app.post('/internal/exchange')
def exchange(data: Assertion, x_zhixing_signature: str = Header(default='')):
    check_assertion(data, x_zhixing_signature)
    username, user_id = execution_user(data.principal)
    return {'token': create_token(username, role='user', user_id=user_id)}


class LearningRecord(BaseModel):
    id: str = Field(pattern=r'^[a-f0-9-]{32,36}$')
    kind: Literal['note', 'flashcard']
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=300000)
    material_id: str | None
    created_at: str


class ReviewEvidence(Assertion):
    scope_id: str = Field(pattern=r'^[a-f0-9-]{32,36}$')
    attempt_id: str = Field(pattern=r'^[a-f0-9-]{32,36}$')
    revision: int = Field(ge=1)
    objective_id: str = Field(pattern=r'^[a-f0-9-]{32,64}$')
    objective: str = Field(min_length=1, max_length=250)
    title: str = Field(min_length=1, max_length=250)
    knowledge_base: str = Field(pattern=r'^zx_[a-f0-9]{48}$')
    timestamp: float = Field(gt=0, allow_inf_nan=False)
    correct: bool


@app.post('/internal/mastery-evidence')
def mastery_evidence(data: ReviewEvidence, x_zhixing_signature: str = Header(default='')):
    from deeptutor.learning.models import (
        KnowledgePoint, KnowledgeType, LearningEvidence, LearningModule, QuizAttempt, TopicMetadata, TopicSource,
    )
    from deeptutor.learning.review_strategy import scheduler_for_progress
    from deeptutor.learning.service import LearningService
    from deeptutor.learning.storage import LearningStore
    from deeptutor.multi_user.models import CurrentUser
    from deeptutor.multi_user.paths import scope_for_user, user_context

    check_assertion(data, x_zhixing_signature)
    username, user_id = execution_user(data.principal)
    user = CurrentUser(id=user_id, username=username, role='user', scope=scope_for_user(user_id, is_admin=False))
    path_id = 'topic_zx_' + data.scope_id.replace('-', '')
    point_id = 'kp_zx_' + data.objective_id.replace('-', '')
    attempt_id = 'zx:' + data.attempt_id
    source_id = 'source_zx_' + data.scope_id.replace('-', '')
    source = TopicSource(id=source_id, kind='knowledge_base', source_id=data.knowledge_base, label=data.title)
    point = KnowledgePoint(id=point_id, name=data.objective, type=KnowledgeType.MEMORY,
                           module_id='zhixing', topic_source_ids=[source_id])
    with user_context(user):
        store = LearningStore()
        service = LearningService(store)

        def apply(tx):
            progress = tx.progress
            previous = next((e for e in progress.learning_evidence if e.question_id == attempt_id), None)
            if previous and int(previous.evidence_id.rsplit(':', 1)[1]) >= data.revision:
                return
            if previous and previous.knowledge_point_id != point_id:
                raise HTTPException(409, 'Evidence cannot move between objectives')
            if not progress.modules:
                progress.name = data.title
                tx.put_topic(TopicMetadata(path_id=path_id, goal=data.title), [source])
                service.replace_modules(progress, [
                    LearningModule(id='zhixing', name=data.title, order=0, knowledge_points=[point]),
                ])
                progress.current_module_id = 'zhixing'
            elif point_id not in progress.knowledge_types:
                module = progress.modules[0]
                module.knowledge_points.append(point)
                progress.knowledge_types[point_id] = point.type

            if previous:
                progress.quiz_attempts = [item for item in progress.quiz_attempts if item.question_id != attempt_id]
                progress.learning_evidence.remove(previous)
                progress.error_records = [item for item in progress.error_records if item.question_id != attempt_id]
            service.record_quiz_attempt(progress, QuizAttempt(
                question_id=attempt_id, knowledge_point_id=point_id, module_id='zhixing',
                is_correct=data.correct, timestamp=data.timestamp,
            ))
            progress.learning_evidence.append(LearningEvidence(
                evidence_id=f'{attempt_id}:{data.revision}', question_id=attempt_id,
                knowledge_point_id=point_id, timestamp=data.timestamp, source='zhixing',
                result='correct' if data.correct else 'incorrect', quality=1.0 if data.correct else 0.0,
            ))
            progress.quiz_attempts.sort(key=lambda item: (item.timestamp, item.question_id))
            progress.learning_evidence.sort(key=lambda item: (item.timestamp, item.evidence_id))
            service._recompute_objective_state(progress, point_id, scheduler_for_progress(progress))
            tx.emit('evidence.recorded', {'evidence_id': f'{attempt_id}:{data.revision}', 'source': 'zhixing'})

        store.mutate(path_id, apply, create=True)
    return {'path_id': path_id, 'revision': data.revision}


class ReviewSession(Assertion):
    path_id: str = Field(pattern=r'^topic_zx_[a-f0-9]{32}$')
    operation: Literal['status', 'start', 'answer']
    submission_id: str = Field(max_length=80)
    answer: str = Field(max_length=12000)
    expected_id: str = Field(max_length=150)
    answers: dict[str, str] = Field(max_length=4)


@app.post('/internal/mastery-review-session')
async def mastery_review_session(data: ReviewSession, x_zhixing_signature: str = Header(default='')):
    from deeptutor.api.routers.mastery_path import _read_projection, _review_queue
    from deeptutor.app.facade import DeepTutorApp
    from deeptutor.learning.pending import public_pending_question
    from deeptutor.learning.storage import LearningStore
    from deeptutor.multi_user.models import CurrentUser
    from deeptutor.multi_user.paths import scope_for_user, user_context
    from deeptutor.services.session import get_session_store
    from deeptutor.services.workspace.context import workspace_context

    check_assertion(data, x_zhixing_signature)
    username, user_id = execution_user(data.principal)
    user = CurrentUser(id=user_id, username=username, role='user', scope=scope_for_user(user_id, is_admin=False))
    session_id = 'zx_review_' + data.path_id.removeprefix('topic_zx_')
    command_id = hashlib.sha256(f'{session_id}:{data.submission_id}'.encode()).hexdigest()
    starter = '请按照当前 Mastery Path 的复习队列，发起一次到期知识点的复习检验。'
    with user_context(user), workspace_context(None):
        store = LearningStore()
        progress = store.load(data.path_id)
        native_topic = store.get_topic(data.path_id, progress=progress) if progress else None
        if not progress or not native_topic:
            raise HTTPException(404, 'Mastery Path unavailable')
        client = DeepTutorApp()
        session = await client.get_session(session_id)
        active = await client.get_active_turn(session_id)
        pending = progress.pending_question
        if data.operation == 'start' and not active and not pending:
            if not any(row['due'] for row in _review_queue(_read_projection(progress))):
                raise HTTPException(409, 'No native review is due')
            if not session:
                try:
                    await get_session_store().create_session('知行研学 · 复习', session_id=session_id)
                except sqlite3.IntegrityError:
                    if not await client.get_session(session_id):
                        raise
            await client.start_turn({
                'session_id': session_id, 'client_submission_id': command_id,
                'content': starter, 'capability': 'mastery_path', 'language': 'zh', 'auto_route': False,
                'mastery_path_id': data.path_id, 'workspace_mode': 'mastery_path', 'mastery_session_mode': 'review',
                'knowledge_bases': [source.source_id for source in native_topic.sources],
            })
        elif data.operation == 'answer':
            current = pending.question_id if pending else active['turn_id'] if active else ''
            if not current or current != data.expected_id or not (data.answer.strip() or data.answers):
                raise HTTPException(409, 'Review question changed')
            if active:
                if active['status'] != 'waiting_input':
                    raise HTTPException(409, 'Native review is still running')
                accepted = await client.turns.submit_user_reply(active['turn_id'], text=data.answer, command_id=command_id)
                if not accepted:
                    raise HTTPException(409, 'Native review is no longer waiting for a reply')
            else:
                if pending is None or bool(pending.questions) != bool(data.answers):
                    raise HTTPException(409, 'Review card answer format changed')
                children = {child.question_id for child in pending.questions}
                if not data.answers.keys() <= children or any(not value.strip() or len(value) > 8000 for value in data.answers.values()):
                    raise HTTPException(422, 'Invalid review card answers')
                answer = data.answer if not data.answers else '\n'.join(data.answers.values())
                await client.start_turn({
                    'session_id': session_id, 'client_submission_id': command_id,
                    'content': answer, 'capability': 'mastery_path', 'language': 'zh', 'auto_route': False,
                    'mastery_path_id': data.path_id, 'workspace_mode': 'mastery_path', 'mastery_session_mode': 'review',
                    'knowledge_bases': [source.source_id for source in native_topic.sources],
                    'mastery_answer': {'question_id': pending.question_id, 'text': answer, 'answers': data.answers or None},
                })
        active = await client.get_active_turn(session_id)
        progress = store.load(data.path_id)
        pending = progress.pending_question
        session = await client.get_session(session_id)
        messages = session.get('messages', []) if session else []
        feedback = ''
        if not active and not pending and messages and messages[-1].get('role') == 'assistant':
            latest_user = next((item for item in reversed(messages) if item.get('role') == 'user'), {})
            if latest_user.get('content') != starter:
                feedback = str(messages[-1].get('content', ''))[:20000]
        return {
            'state': active['status'] if active else 'question' if pending else 'idle',
            'request_id': pending.question_id if pending else active['turn_id'] if active else '',
            'question': public_pending_question(pending).to_dict() if pending else None,
            'feedback': feedback,
        }


class RecordsAssertion(Assertion):
    records: list[LearningRecord] = Field(max_length=25)
    listing: bool


@app.post('/internal/learning-records')
def learning_records(data: RecordsAssertion, x_zhixing_signature: str = Header(default='')):
    from deeptutor.co_writer.storage import CoWriterDocument, get_co_writer_storage
    from deeptutor.multi_user.models import CurrentUser
    from deeptutor.multi_user.paths import scope_for_user, user_context
    from deeptutor.notes.review import page_cards
    from deeptutor.services.notebook import notebook_manager

    check_assertion(data, x_zhixing_signature)
    username, user_id = execution_user(data.principal)
    user = CurrentUser(id=user_id, username=username, role='user', scope=scope_for_user(user_id, is_admin=False))
    with user_context(user):
        storage = get_co_writer_storage()
        # The per-owner file lock also serializes retries across bridge processes.
        with storage.locked():
            notebook = notebook_manager.get_or_create_notebook('知行研学')
            saved = {}
            for record in notebook['records']:
                meta = record.get('metadata', {}).get('zhixing')
                if meta:
                    saved[meta['id']] = {**meta, 'kind': 'note', 'title': record['title'], 'body': record['output']}
            for doc_id in storage.list_doc_ids():
                if not re.fullmatch(r'[a-f0-9]{32}', doc_id):
                    continue
                document = storage.load_document(doc_id)
                if not document or not document.blocks:
                    continue
                props = document.blocks[0].get('props', {})
                if props.get('kind') != 'flashcards':
                    continue
                meta = json.loads(props['data']).get('zhixing')
                if meta:
                    card, = page_cards(document)
                    saved[meta['id']] = {**meta, 'kind': 'flashcard', 'title': card['front'], 'body': card['back']}
            if data.listing:
                return {'items': list(saved.values())}

            items = []
            for record in data.records:
                item = record.model_dump()
                previous = saved.get(record.id)
                if previous:
                    if any(previous[key] != item[key] for key in item if key != 'created_at'):
                        raise HTTPException(409, 'Learning record id already has different content')
                    items.append(previous)
                    continue
                meta = {key: item[key] for key in ('id', 'material_id', 'created_at')}
                if record.kind == 'note':
                    result = notebook_manager.add_record([notebook['id']], 'co_writer', record.title, '', record.body,
                                                         metadata={'zhixing': meta})
                    if notebook['id'] not in result['added_to_notebooks']:
                        raise HTTPException(503, 'Notebook could not save this record')
                else:
                    doc_id = hashlib.sha256(record.id.encode()).hexdigest()[:32]
                    if storage.doc_exists(doc_id):
                        raise HTTPException(409, 'Flashcard document already exists')
                    content = {'zhixing': meta, 'cards': [{'front': record.title, 'back': record.body}]}
                    block = {'id': doc_id, 'type': 'learning', 'props': {'kind': 'flashcards',
                             'data': json.dumps(content, ensure_ascii=False)}, 'children': []}
                    storage._write(CoWriterDocument(id=doc_id, title=record.title, blocks=[block]))
                saved[record.id] = item
                items.append(item)
            return {'items': items}


class KnowledgeAssertion(Assertion):
    operation: Literal['create', 'status', 'search', 'delete', 'reader']
    name: str = Field(pattern=r'^zx_[0-9a-f]{48}$')
    data: dict[str, str]


@app.post('/internal/knowledge')
async def knowledge(data: KnowledgeAssertion, background: BackgroundTasks, x_zhixing_signature: str = Header(default='')):
    from deeptutor.api.routers import knowledge as native
    from deeptutor.api.routers import reading
    from deeptutor.multi_user.models import CurrentUser
    from deeptutor.multi_user.paths import scope_for_user, user_context
    from deeptutor.multi_user.knowledge_access import list_visible_knowledge_bases
    from deeptutor.tools.rag_tool import rag_search

    check_assertion(data, x_zhixing_signature)
    username, user_id = execution_user(data.principal)
    user = CurrentUser(id=user_id, username=username, role='user', scope=scope_for_user(user_id, is_admin=False))
    with user_context(user):
        exists = any(item.get('name') == data.name for item in list_visible_knowledge_bases())
        if data.operation == 'create':
            if exists:
                return {'state': 'indexing'}
            text = data.data.get('text', '')
            content = text.encode('utf-8')
            if not content or len(content) > 50 * 1024 * 1024:
                raise HTTPException(422, 'Unsupported source text size')
            # The upstream background initializer restores the owning user's context.
            # Keep PDF page boundaries when indexing extracted text. A short
            # final page must not be buried in the embedding of a previous page.
            pages = [part for part in re.split(r'(?=^\[第 \d+ 页\]\n)', text, flags=re.M) if part.strip()]
            uploads = [UploadFile(file=BytesIO(page.encode('utf-8')), filename=f'material-{i:04}.txt')
                       for i, page in enumerate(pages, 1)]
            try:
                try:
                    await native.create_knowledge_base(background, data.name, uploads, 'llamaindex',
                                                       '', '', None, '', '', None)
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
            finally:
                for upload in uploads:
                    await upload.close()
            return {'state': 'indexing'}
        if not exists:
            return {'state': 'missing'}
        if data.operation == 'reader':
            content = data.data.get('text', '').encode('utf-8')
            if not content or len(content) > 50 * 1024 * 1024:
                raise HTTPException(422, 'Unsupported reader text size')
            filename = data.name+'.md'
            for item in await reading.list_materials():
                if item.filename == filename:
                    return {'state': 'ready', 'material_id': item.material_id, 'revision': item.revision}
            upload = UploadFile(file=BytesIO(content), filename=filename)
            try:
                doc = await reading.upload_material(background, upload, False)
                return {'state': 'ready', 'material_id': doc.material_id, 'revision': doc.revision}
            finally:
                await upload.close()
        if data.operation == 'delete':
            for doc in await reading.list_materials():
                if doc.filename == data.name+'.md':
                    await reading.delete_material(doc.material_id)
            await native.delete_knowledge_base(data.name)
            return {'state': 'deleted'}
        if data.operation == 'status':
            progress = await native.get_indexing_run(data.name)
            state = (progress.get('run') or {}).get('state')
            if state == 'completed':
                return {'state': 'ready'}
            if state in {'failed', 'partial', 'cancelled'}:
                return {'state': 'failed'}
            # The native runner can briefly project "interrupted" while its
            # background process identity is being recorded. Check progress too.
            snapshot = await native.get_progress(data.name)
            if snapshot.get('stage') == 'error':
                return {'state': 'failed'}
            if state == 'interrupted':
                try:
                    stamp = datetime.fromisoformat(snapshot['timestamp'])
                    if stamp.tzinfo is None:
                        stamp = stamp.replace(tzinfo=timezone.utc)
                    if (datetime.now(timezone.utc) - stamp).total_seconds() > 300:
                        return {'state': 'failed'}
                except (KeyError, TypeError, ValueError):
                    return {'state': 'failed'}
            return {'state': 'indexing'}
        query = data.data.get('query', '').strip()
        if not query or len(query) > 8000:
            raise HTTPException(422, 'Invalid retrieval query')
        result = await rag_search(query=query, kb_name=data.name, rewrite=False, top_k=48)
        if result.get('error_type') or result.get('needs_reindex'):
            raise HTTPException(503, 'DeepTutor retrieval failed')
        passages = [item.get('evidence_text') or item.get('content', '') for item in result.get('sources', [])[:12]]
        # LlamaIndex may expose only a 200-character preview per text source.
        # Return the retrieved body too; the platform discards any span it cannot
        # match against the exact authorized version of the material.
        body = result.get('content', '')
        if isinstance(body, str):
            passages = [*body[:48000].split('\n\n'), *passages]
        return {'state': 'ready', 'passages': passages[:80]}
