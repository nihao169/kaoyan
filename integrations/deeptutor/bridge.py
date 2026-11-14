"""Loaded inside the pinned DeepTutor integration image.

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


def check_assertion(data, signature, *, exclude_unset=False):
    secret = os.environ.get('DEEPTUTOR_BRIDGE_SECRET', '')
    if not AUTH_ENABLED or len(secret) < 32:
        raise HTTPException(503, 'Bridge requires authentication and a 32-character secret')
    body = json.dumps(data.model_dump(exclude_unset=exclude_unset), sort_keys=True, separators=(',', ':')).encode()
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


class ProjectLearningRequest(Assertion):
    path_id: str = Field(pattern=r'^topic_[a-zA-Z0-9_-]{1,130}$')
    session_id: str = Field(min_length=1, max_length=150)
    operation: Literal['status', 'message', 'answer', 'mode', 'read', 'notes', 'brief']
    submission_id: str = Field(default='', max_length=80)
    background: str = Field(max_length=6000)
    sources: list[dict[str, str]] = Field(default_factory=list, max_length=16)
    ready: bool
    text: str = Field(default='', max_length=12000)
    expected_id: str = Field(default='', max_length=150)
    answers: dict[str, str] = Field(default_factory=dict, max_length=4)
    mode: Literal['outline', 'study', 'review'] | None = None
    material_id: str | None = None
    note_ids: list[str] = Field(default_factory=list, max_length=20)
    notes: list[dict[str, str]] = Field(default_factory=list, max_length=20)
    reader: dict[str, str] | None = None
    guidance: str = Field(default='', max_length=16000)
    objective: str = Field(default='', max_length=150)
    teach: bool = False


async def learning_clarification(sessions, active):
    if not active or active['status'] != 'waiting_input':
        return None
    turn_id = active['turn_id']
    fallback = None
    for event in reversed(await sessions.get_turn_events(turn_id)):
        metadata = event.get('metadata') or {}
        ask = metadata.get('ask_user') or (metadata.get('tool_metadata') or {}).get('ask_user')
        if ask:
            return {'question_id': turn_id, 'prompt': ask.get('intro') or '请回答助教的问题',
                    'options': [], 'questions': [
                        {'question_id': q['id'], 'prompt': q['prompt'], 'clarification': True,
                         'options': [{'id': str(i), 'label': x['label'], 'body': x.get('description') or ''}
                                     for i, x in enumerate(q.get('options', [])) if x.get('label')]}
                        for q in ask.get('questions', [])]}
        if fallback is None and event.get('type') == 'wait_for_input' and event.get('content'):
            fallback = {'question_id': turn_id, 'prompt': str(event['content']), 'options': []}
    return fallback


@app.post('/internal/project-learning')
async def project_learning(data: ProjectLearningRequest, x_zhixing_signature: str = Header(default='')):
    """Expose native learning, never implement a second teaching engine."""
    from deeptutor.app.facade import DeepTutorApp
    from deeptutor.api.routers.mastery_path import _topic_payload
    from deeptutor.capabilities.mastery.mode import admission_error
    from deeptutor.learning.models import TopicMetadata, TopicSource
    from deeptutor.learning.pending import public_pending_question
    from deeptutor.learning.service import LearningService
    from deeptutor.learning.storage import LearningStore
    from deeptutor.runtime.request_contracts import MasteryPathRequestConfig
    from deeptutor.multi_user.models import CurrentUser
    from deeptutor.multi_user.paths import scope_for_user, user_context
    from deeptutor.services.session import get_session_store
    from deeptutor.services.workspace.context import workspace_context

    check_assertion(data, x_zhixing_signature, exclude_unset=True)
    bounded = 'zx_grade_only' in MasteryPathRequestConfig.model_fields
    if not bounded and (data.objective or data.operation == 'brief'):
        raise HTTPException(503, 'Rebuild the Zhixing DeepTutor integration image')
    username, user_id = execution_user(data.principal)
    user = CurrentUser(id=user_id, username=username, role='user', scope=scope_for_user(user_id, is_admin=False))
    with user_context(user), workspace_context(None):
        store, sessions, client = LearningStore(), get_session_store(), DeepTutorApp()
        progress = store.load(data.path_id)
        main = await sessions.get_session(data.session_id)
        # Reading and teaching share the project identity, not the same mutable interaction.
        prefs = (main or {}).get('preferences') or {}
        readers = prefs.get('zx_readers') or {}
        reader_key = prefs.get('zx_reader', '') if data.ready else ''
        if data.operation in ('mode', 'notes', 'brief'):
            reader_key = ''
        if data.operation != 'status':
            if not data.submission_id:
                raise HTTPException(422, 'A durable command identifier is required')
            if not data.ready and data.operation != 'message':
                raise HTTPException(409, 'Authorized indexed materials are required')
            if not main:
                try:
                    await sessions.create_session('知行研学 · 学习', session_id=data.session_id)
                except sqlite3.IntegrityError:
                    if not await client.get_session(data.session_id):
                        raise
            if data.ready and progress is None:
                sources = [TopicSource(id='source_' + str(i), kind='knowledge_base', source_id=x['name'],
                    label=x['label'], position=i) for i, x in enumerate(data.sources)]
                try:
                    progress = LearningService(store).create_topic(data.path_id, name='项目学习路径', modules=[],
                        metadata=TopicMetadata(path_id=data.path_id, goal=data.background), sources=sources)
                except ValueError:
                    progress = store.load(data.path_id)
                    if progress is None:
                        raise
            if data.ready and progress:
                topic = store.get_topic(data.path_id, progress=progress)
                if topic and topic.metadata.goal != data.background:
                    store.put_topic(topic.metadata.model_copy(update={'goal': data.background}), topic.sources)
            if data.operation == 'read':
                from deeptutor.api.routers import reading
                reader_key = data.reader['name']
                if reader_key not in readers:
                    filename = reader_key + '.md'
                    doc = next((x for x in await reading.list_materials() if x.filename == filename), None)
                    if doc is None:
                        upload = UploadFile(file=BytesIO(data.reader['text'].encode('utf-8')), filename=filename)
                        try:
                            doc = await reading.upload_material(BackgroundTasks(), upload, False)
                        finally:
                            await upload.close()
                    workspace = await reading.create_workspace(reading.WorkspaceCreateRequest(
                        title=data.reader['title'][:300], material_ids=[doc.material_id]))
                    workspace_id = workspace['workspace']['workspace_id']
                    native_session = await reading.create_reading_session(workspace_id,
                        reading.ReadingSessionCreateRequest(title='知行研学 · 精读', active_material_id=doc.material_id))
                    readers[reader_key] = {'session_id': native_session['session']['session_id'],
                        'reading_workspace_id': workspace_id, 'reading_material_id': doc.material_id,
                        'reading_material_revision': doc.revision}
                await sessions.update_session_preferences(data.session_id, {'zx_readers': readers, 'zx_reader': reader_key})
            elif data.operation in ('mode', 'notes', 'brief'):
                await sessions.update_session_preferences(data.session_id, {'zx_reader': ''})

        reading_context = readers.get(reader_key) if reader_key else None
        session_id = reading_context['session_id'] if reading_context else data.session_id
        session = await sessions.get_session(session_id)
        active = await client.get_active_turn(session_id) if session else None
        pending = progress.pending_question if progress and not reading_context and data.ready else None
        mode = ((session or {}).get('preferences') or {}).get('mastery_session_mode') or ('study' if progress and progress.modules else 'outline')
        followup = data.operation == 'message' and data.ready and (not reading_context or bool(active))
        followup_id = data.session_id + '_followup'
        followup_session = await sessions.get_session(followup_id)
        followup_active = await client.get_active_turn(followup_id) if followup_session else None
        recent_text = getattr(sessions, 'zx_recent_text', sessions.get_messages)
        feedback_id = prefs.get('zx_feedback_session')
        command_id = hashlib.sha256(f'{data.session_id}:{data.submission_id}'.encode()).hexdigest()
        prior = await sessions.submission_turn(command_id) if data.submission_id else None
        # Reply commands do not create a new turn. The native coordinator keeps
        # their identifiers, including after the waiter has already resumed.
        reply_turn = data.expected_id if data.operation == 'answer' else ''
        if reply_turn and not prior:
            commands = await client.turns.coordinator.read_commands(reply_turn)
            prior = next((command for _, command in commands if command.command_id == command_id), None)
        if data.operation != 'status' and prior is None:
            if followup_active or (active and active['status'] != 'waiting_input'):
                raise HTTPException(409, 'Native learning is still running')
            if data.operation == 'mode':
                refusal = admission_error(data.mode, has_outline=bool(progress and progress.modules))
                if refusal:
                    raise HTTPException(409, refusal)
                mode = data.mode
                if mode == 'review' and data.objective:
                    from deeptutor.api.routers.mastery_path import _read_projection
                    from deeptutor.learning.policy import due_reviews
                    if data.objective not in {item.knowledge_point_id for item in due_reviews(_read_projection(progress))}:
                        raise HTTPException(409, 'The selected objective is no longer due for review')
                await sessions.update_session_preferences(data.session_id, {'mastery_session_mode': mode})
            text = data.text.strip()
            extra = {}
            if data.operation == 'answer':
                expected = active['turn_id'] if active else pending.question_id if pending else ''
                if not expected or data.expected_id != expected:
                    raise HTTPException(409, 'The pending interaction has changed')
                if active:
                    accepted = await client.turns.submit_user_reply(active['turn_id'], text=text,
                        answers=[{'questionId': key, 'text': value} for key, value in data.answers.items()] or None,
                        command_id=command_id)
                    if not accepted:
                        raise HTTPException(409, 'No longer waiting for input')
                else:
                    children = {x.question_id for x in pending.questions}
                    if bool(children) != bool(data.answers) or not data.answers.keys() <= children:
                        raise HTTPException(422, 'Invalid card answer format')
                    if any(not x.strip() or len(x) > 8000 for x in data.answers.values()) or not (text or data.answers):
                        raise HTTPException(422, 'An answer is required')
                    text = text or '\n'.join(data.answers.values())
                    extra['mastery_answer'] = {'question_id': pending.question_id, 'text': text, 'answers': data.answers or None}
            elif active and not followup:
                raise HTTPException(409, 'Please answer the current tutor question first')
            if not (data.operation == 'answer' and active):
                if data.operation == 'notes':
                    text = '请将这些选定笔记作为学习背景，讨论是否需要调整大纲。先展示建议，得到我确认后再修改，保留已有掌握证据。\n' + json.dumps(data.notes, ensure_ascii=False)
                    notebook_name = '知行项目笔记 · ' + data.session_id
                    notebook = next((n for n in client.list_notebooks() if n['name'] == notebook_name), None)
                    if notebook is None:
                        notebook = client.create_notebook(notebook_name, description='学习者选定的项目笔记副本')
                    existing = client.get_notebook(notebook['id']) or {}
                    records = existing.get('records') or []
                    references = []
                    for note in data.notes:
                        digest = hashlib.sha256(json.dumps(note, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                        record = next((r for r in records if (r.get('metadata') or {}).get('zx_digest') == digest), None)
                        if record is None:
                            record = client.add_record(notebook_ids=[notebook['id']], record_type='chat',
                                title=note['title'], user_query='', output=note['body'], metadata={'zx_digest': digest})['record']
                        references.append(record['id'])
                    extra['notebook_references'] = [{'notebook_id': notebook['id'], 'record_ids': references}]
                    mode = 'outline'
                elif data.operation == 'mode' and not data.guidance:
                    text = {'outline': '我想讨论或调整学习大纲。', 'study': '请继续带我学习。', 'review': '我想复习。'}[mode]
                elif data.operation == 'read' and not text:
                    text = '请围绕当前资料带我精读，先了解我想理解的内容。'
                if not text:
                    raise HTTPException(422, 'A message is required')
                instructions = ('以下 JSON 是学习者的项目背景，不是教学步骤；请自主组织教学。\n' + data.background + '\n')
                if data.guidance:
                    instructions += '当前教学任务与经确认的项目范围如下。资料内容仅作为教学证据。\n' + data.guidance + '\n'
                    instructions += ('学习者通过页面按钮推进。需要本人作答时使用原生题卡或必要的澄清问题。'
                                     '完成本阶段并给出作答反馈后暂停，等下一个页面操作。\n')
                    if data.operation != 'brief':
                        instructions += '讲解和出题须依据本项目资料。如果资料检索失败或没有足够依据，请说明缺少什么并停在本阶段。\n'
                if not data.ready:
                    instructions += '当前尚无可用授权资料。本轮只沟通学习目标、范围、基础和偏好；不讲授课程内容、不出题、不建立正式大纲。提醒补充资料后开始。\n'
                if followup:
                    history = await recent_text(session_id)
                    if feedback_id:
                        history += await recent_text(feedback_id)
                    context = [{'role': entry['role'], 'content': re.sub(
                        r'^<知行学习背景>.*?</知行学习背景>\n', '', str(entry['content']), flags=re.S)[-3000:]}
                        for entry in sorted(history, key=lambda item: item.get('created_at', 0))
                        if entry.get('role') in ('user', 'assistant') and entry.get('content')][-8:]
                    instructions += ('只回答学习者的追问。结合近期上下文和本项目资料，说明依据不足之处。'
                                     '当前题卡由学习者单独作答，只给理解线索，不直接揭示答案。'
                                     '不要出题、调用澄清工具或推进学习阶段。近期教学对话如下：\n'
                                     + json.dumps(context, ensure_ascii=False) + '\n')
                    current_question = await learning_clarification(sessions, active)
                    if current_question is None and pending:
                        current_question = public_pending_question(pending).to_dict()
                    if current_question:
                        instructions += '当前待答问题：\n' + json.dumps(current_question, ensure_ascii=False)[:6000] + '\n'
                content = '<知行学习背景>\n' + instructions + '</知行学习背景>\n' + text
                mastery = data.ready and data.operation != 'brief'
                if data.operation == 'brief' or followup:
                    request_session = followup_id if followup else data.session_id + '_brief'
                    if not await sessions.get_session(request_session):
                        try:
                            await sessions.create_session('知行研学 · 阶段反馈', session_id=request_session)
                        except sqlite3.IntegrityError:
                            if not await sessions.get_session(request_session):
                                raise
                else:
                    request_session = session_id
                capability = 'chat'
                if data.operation != 'brief' and not followup:
                    capability = 'immersive_reading' if reading_context else 'mastery_path' if mastery else 'chat'
                request = {'session_id': request_session, 'client_submission_id': command_id, 'content': content,
                    'capability': capability,
                    'language': 'zh', 'auto_route': False, 'tools': [],
                    'knowledge_bases': [x['name'] for x in data.sources] if data.ready else []}
                if reading_context and data.operation != 'brief' and not followup:
                    request.update(workspace_mode='immersive_reading', reading_viewport={'locator': 0}, **reading_context)
                elif data.operation == 'brief' or followup:
                    request['config'] = {'zx_feedback_only': True}
                elif mastery:
                    request.update(workspace_mode='mastery_path', mastery_path_id=data.path_id, mastery_session_mode=mode)
                    if data.operation == 'answer' and pending and not active and not bounded:
                        raise HTTPException(503, 'Rebuild the Zhixing DeepTutor integration image')
                    if bounded:
                        request['config'] = {
                            'zx_grade_only': data.operation == 'answer' and bool(pending) and not active,
                            'zx_objective': data.objective,
                            'zx_teach': data.teach,
                        }
                _, started = await client.start_turn({**request, **extra})
                if data.operation == 'brief':
                    await sessions.update_session_preferences(data.session_id, {'zx_feedback_session': request_session})
                await sessions.update_session_preferences(request_session if followup else session_id, {
                    'zx_last_turn': started['turn_id'], 'zx_last_submission': data.submission_id,
                })
        elif prior and isinstance(prior, dict) and prior.get('turn_id'):
            target_session = followup_id if followup else session_id
            target_prefs = ((followup_session or {}).get('preferences') or {}) if followup else prefs
            previous_submission = target_prefs.get('zx_last_submission')
            if (not followup or prior.get('session_id') == target_session) and (
                    not previous_submission or previous_submission == data.submission_id):
                await sessions.update_session_preferences(target_session, {
                    'zx_last_turn': prior['turn_id'], 'zx_last_submission': data.submission_id,
                })

        progress = store.load(data.path_id) if data.ready else None
        session = await client.get_session(session_id)
        active = await client.get_active_turn(session_id) if session else None
        last_id = ((session or {}).get('preferences') or {}).get('zx_last_turn')
        last_turn = await sessions.get_turn(last_id) if last_id and not active else None
        if last_turn and last_turn.get('status') in ('created', 'running', 'recovering', 'waiting_input'):
            active = last_turn
        pending = progress.pending_question if progress and not reading_context else None
        messages = []
        transcript = await recent_text(session_id) if session else []
        if data.operation == 'brief':
            feedback_id = data.session_id + '_brief'
        if feedback_id:
            transcript += await recent_text(feedback_id)
        if followup or followup_session:
            transcript += await recent_text(followup_id)
        followup_active = await client.get_active_turn(followup_id) if followup or followup_session else None
        side_prefs = ((await sessions.get_session(followup_id) or {}).get('preferences') or {}
                      if followup or followup_session else {})
        side_turn_id = side_prefs.get('zx_last_turn')
        side_turn = await sessions.get_turn(side_turn_id) if side_turn_id and not followup_active else None
        if side_turn and side_turn.get('status') in ('created', 'running', 'recovering', 'waiting_input'):
            followup_active = side_turn
        for message in sorted(transcript, key=lambda item: item.get('created_at', 0))[-100:]:
            if message.get('role') in ('user', 'assistant') and isinstance(message.get('content'), str):
                content = re.sub(r'^<知行学习背景>.*?</知行学习背景>\n', '', message['content'], flags=re.S)
                if message['role'] == 'assistant':
                    content = re.sub(r'最后(?:一|1)(?:道)?题', '这道题', content)
                if content.strip():
                    messages.append({'role': message['role'], 'content': content[:30000]})
        curriculum = _topic_payload(store, data.path_id) if progress else None
        if curriculum:
            from deeptutor.api.routers.mastery_path import _read_projection
            from deeptutor.learning.policy import due_reviews
            eligible = {item.knowledge_point_id for item in due_reviews(_read_projection(progress))}
            curriculum['reviews'] = [{**item, 'can_start_review': item['knowledge_point_id'] in eligible}
                                     for item in curriculum['reviews']]
        clarification = await learning_clarification(sessions, active)
        failed = bool(last_turn and last_turn.get('status') in ('failed', 'cancelled'))
        evidence = [item for item in progress.learning_evidence if item.source == 'mastery_path'] if progress else []
        latest = evidence[-1] if evidence else None
        recent = [{'id': item.evidence_id or item.question_id, 'question_id': item.question_id,
                   'objective_id': item.knowledge_point_id, 'result': item.result,
                   'timestamp': item.timestamp, 'turn_id': item.turn_id}
                  for item in evidence[-100:]]
        side_failed = bool(side_turn and side_turn.get('status') in ('failed', 'cancelled'))
        side_status = followup_active['status'] if followup_active else ''
        if side_status == 'waiting_input':
            await client.cancel_turn(followup_active['turn_id'])
            side_status = 'cancel_requested'
        main_submission = ((session or {}).get('preferences') or {}).get('zx_last_submission')
        return {'state': side_status or (active['status'] if active else 'question' if pending else 'failed' if failed else 'idle'),
            'turn_id': active['turn_id'] if active else last_id,
            'submission_id': main_submission,
            'followup': {'state': side_status or ('failed' if side_failed else 'idle'), 'turn_id': side_turn_id,
                         'submission_id': side_prefs.get('zx_last_submission')} if side_turn_id else None,
            'error': '原生教学未完成，对话和已有证据已保留。可以重新执行当前步骤。' if failed else '',
            'intake': not data.ready, 'reading': bool(reading_context), 'mode': mode,
            'request_id': active['turn_id'] if active and active['status'] == 'waiting_input'
                          else pending.question_id if pending else active['turn_id'] if active else '',
            'question': clarification or (public_pending_question(pending).to_dict() if pending else None),
            'messages': messages, 'curriculum': curriculum,
            'question_objective': pending.knowledge_point_id if pending else '',
            'question_leaves': [item.question_id for item in pending.questions] if pending else [],
            'explained': list(progress.explained_objectives) if progress else [],
            'recent_evidence': recent,
            'evidence': {'count': len(evidence), 'result': latest.result if latest else None,
                         'hints': latest.hints_used if latest else None}}


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

class PersonalAttemptsRequest(Assertion):
    path_ids: list[str] = Field(max_length=200)


@app.post('/internal/personal-attempts')
async def personal_attempts(data: PersonalAttemptsRequest, x_zhixing_signature: str = Header(default='')):
    """Read immutable project attempts under the project's native identity."""
    from deeptutor.multi_user.models import CurrentUser
    from deeptutor.multi_user.paths import scope_for_user, user_context
    from deeptutor.services.session.sqlite_store import get_sqlite_session_store

    check_assertion(data, x_zhixing_signature)
    if not data.path_ids:
        return {'items': []}
    username, user_id = execution_user(data.principal)
    user = CurrentUser(id=user_id, username=username, role='user', scope=scope_for_user(user_id, is_admin=False))
    with user_context(user):
        store = get_sqlite_session_store()
        marks = ','.join('?' for _ in data.path_ids)
        with store._connect() as conn:
            rows = conn.execute(
                f"""SELECT a.attempt_id, a.occurred_at, a.assessment_json,
                           user_message.metadata_json AS request_metadata
                    FROM assessment_attempts a LEFT JOIN turns t ON t.id=a.turn_id AND t.session_id=a.session_id
                    LEFT JOIN messages reply ON reply.id=t.assistant_message_id AND reply.session_id=t.session_id
                    LEFT JOIN messages user_message ON user_message.id=reply.parent_message_id
                         AND user_message.session_id=t.session_id AND user_message.role='user'
                    WHERE a.mastery_path_id IN ({marks})""",
                data.path_ids,
            )
            items = []
            for row in rows:
                metadata = json.loads(row['request_metadata'] or '{}') or {}
                snapshot = metadata.get('request_snapshot') or metadata.get('requestSnapshot') or {}
                items.append({**json.loads(row['assessment_json']), 'id': 'check:' + row['attempt_id'],
                              'time': row['occurred_at'], 'category': 'guided',
                              'review_session': snapshot.get('masterySessionMode') == 'review'})
            has_reviews = conn.execute("SELECT 1 FROM sqlite_master WHERE name='practice_review_events'").fetchone()
            if has_reviews:
                reviews = conn.execute(
                    f"""SELECT e.*, n.question, n.question_type, n.options_json, n.correct_answer,
                               n.explanation, n.mastery_path_id
                        FROM practice_review_events e JOIN notebook_entries n ON n.id=e.entry_id
                        WHERE n.mastery_path_id IN ({marks})""", data.path_ids,
                )
                for row in reviews:
                    outcome = json.loads(row['outcome_json'])
                    items.append({'id': 'review:' + row['request_id'], 'time': row['reviewed_at'], 'category': 'legacy',
                                  'question': row['question'], 'question_type': row['question_type'],
                                  'options': json.loads(row['options_json'] or '{}'), 'user_answer': row['answer'],
                                  'correct_answer': row['correct_answer'], 'explanation': row['explanation'],
                                  'mastery_path_id': row['mastery_path_id'], 'is_correct': outcome.get('correct')})
    return {'items': items}
