from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.v2 import models as m, service as s, tutor, tutor_records
from test_v2 import call, setup_project


def test_native_practice_checks_only_at_submission(clients, monkeypatch):
    student, teacher, _ = clients
    project, material, _ = setup_project(student)
    base = '/learning-projects/' + project['id']
    with SessionLocal.begin() as db:
        p = db.get(m.Project, project['id'])
        q = m.Question(project_id=p.id, material_id=material['id'], kind='multiple', knowledge='实践',
                       prompt='哪些说法正确？', options={'A': '甲', 'B': '乙', 'C': '丙'},
                       answer=['A', 'C'], explanation='保密解析', quote='实践是认识的来源')
        db.add(q)
        db.flush()
        task = s.add_task(db, p, 'verification', '补学练习', 'native-test', '独立完成', material['id'],
                          {'question_id': q.id})
        task_id = task.id
    monkeypatch.setattr(settings, 'deeptutor_practice_projects', project['id'])
    entries = {}
    checks = []
    unavailable = True

    async def request(owner, method, path, *, body=None, params=None, **_):
        assert owner.endswith(f":{project['id']}:practice")
        if method == 'GET':
            return entries.get(params['question_id'], {})
        if path.endswith('/upsert'):
            entry = {'id': 123, **body}
            entries[body['question_id']] = entry
            return entry
        assert path.endswith('/practice/questions/123/check')
        checks.append(body['answer'])
        if unavailable:
            raise tutor.TutorError('unavailable')
        return {'correct': set(body['answer'].split(',')) == {'A', 'C'}}

    monkeypatch.setattr(tutor, 'native_request', request)
    call(teacher, base + '/question-bank', status=404)
    question, = call(student, base + '/question-bank')
    assert set(question).isdisjoint({'answer', 'explanation', 'quote', 'rubric'})
    session = '/study-sessions/' + task_id
    assert set(call(student, session)['question']) == set(question)
    assert not checks
    answer = {'answer': ['C', 'A']}
    call(student, session + '/submit', 'POST', answer, 503, idem='retry')
    with SessionLocal() as db:
        assert db.scalar(select(m.Attempt).where(m.Attempt.task_id == task_id)) is None
    unavailable = False
    result = call(student, session + '/submit', 'POST', answer, idem='retry')
    assert result['result']['correct'] and result['result']['evaluator'] == 'deeptutor_practice'
    assert call(student, session + '/submit', 'POST', answer, idem='retry') == result
    assert len(checks) == 2
    call(student, base + '/materials/' + material['id'], 'DELETE')
    assert call(student, base + '/question-bank') == []
    call(student, session, status=403)


def test_records_migrate_without_double_write_and_restore_new_notes(clients, monkeypatch):
    student, teacher, _ = clients
    project, material, _ = setup_project(student)
    base = '/learning-projects/' + project['id']
    path = base + '/notes'
    old = call(student, path, 'POST', {'title': '正面', 'text': '背面', 'kind': 'flashcard',
                                      'material_id': material['id']}, 201)
    original = call(student, path)
    call(student, path + '/migrate', 'POST', status=403)
    monkeypatch.setattr(settings, 'deeptutor_records_projects', project['id'])
    remote = {}
    lost_response = True

    def records(user_id, project_id, items=None):
        assert project_id == project['id']
        if items is None:
            return list(remote.values())
        saved = [remote.setdefault(item['id'], item) for item in items]
        if lost_response and items[0]['id'] != old['id']:
            tutor_records.fail(503, 'TUTOR_RECORDS_UNAVAILABLE', 'response lost')
        return saved

    monkeypatch.setattr(tutor_records, 'native_records', records)
    call(teacher, path + '/migrate', 'POST', status=404)
    assert call(student, path + '/migrate', 'POST')['count'] == 1
    assert call(student, path) == original
    body = {'title': '新笔记', 'text': '实践'}
    call(student, path, 'POST', body, 503, idem='retry')
    lost_response = False
    new = call(student, path, 'POST', body, 201, idem='retry')
    assert len(remote) == 2 and new['id'] in remote
    with SessionLocal() as db:
        assert db.get(m.Note, new['id']) is None
    pending = {'title': '保存结果不明', 'text': '需要核对'}
    lost_response = True
    call(student, path, 'POST', pending, 503, idem='during-rollback')
    monkeypatch.setattr(settings, 'deeptutor_records_projects', '')
    call(student, path, 'POST', body, 503)
    assert len(call(student, path)) == 3
    assert call(student, path + '/restore', 'POST')['count'] == 3
    restored = call(student, path, 'POST', pending, 201, idem='during-rollback')
    assert restored['id'] in remote
    call(student, base + '/materials/' + material['id'], 'DELETE')
    assert {item['id'] for item in call(student, path)} == {new['id'], restored['id']}


def test_chat_history_reads_bound_turn_and_never_returns_upstream_trace(clients, monkeypatch):
    student, teacher, _ = clients
    project, material, _ = setup_project(student)
    base = '/learning-projects/' + project['id']
    with SessionLocal.begin() as db:
        p = db.get(m.Project, project['id'])
        p.native_records = True
        run = m.AIRun(project_id=p.id, scope_revision=p.scope_revision, kind='chat', state='succeeded',
                      prompt='实践与认识是什么关系？', result={'text': '实践是认识的来源'},
                      external_id='turn-a', metrics={'chat_session': {'principal': 'bound-owner', 'id': 'session-a'}})
        db.add(run)
        db.flush()
        run_id = run.id
    requested = []

    async def session(owner, method, path, **_):
        requested.append(path)
        assert (owner, method, path) == ('bound-owner', 'GET', '/api/sessions/session-a')
        return {'messages': [
            {'role': 'user', 'content': '下游内部提示词'},
            {'role': 'assistant', 'content': '{"text":"实践是认识的来源"}',
             'trace': {'turn_id': 'turn-a'}, 'events': [{'content': '内部执行记录'}]},
        ]}

    monkeypatch.setattr(tutor, 'native_request', session)
    history = base + '/chat-history'
    assert call(student, history)['items'][0]['id'] == run_id
    call(teacher, history + '/' + run_id, status=404)
    assert call(student, history + '/' + run_id) == {'prompt': '实践与认识是什么关系？', 'text': '实践是认识的来源'}
    call(student, base + '/materials/' + material['id'], 'DELETE')
    assert not call(student, history)['items']
    call(student, history + '/' + run_id, status=403)
    assert len(requested) == 1
