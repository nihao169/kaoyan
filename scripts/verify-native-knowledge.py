"""Run the native knowledge and citation acceptance against an isolated tutor."""
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

import pymupdf
import httpx
from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[1]
preview = Path(sys.argv[1]).resolve()
if not preview.is_relative_to(root / '.runtime') or not preview.name.startswith('tutor-native-preview-'):
    raise SystemExit('Pass the isolated tutor-native-preview-* directory under .runtime')
data = preview / ('platform-' + uuid4().hex)
data.mkdir()
acceptance_url = os.environ.get('ZX_NATIVE_ACCEPTANCE_DATABASE_URL', 'sqlite:///' + (data / 'acceptance.db').as_posix())
if 'ZX_NATIVE_ACCEPTANCE_DATABASE_URL' in os.environ:
    url = make_url(acceptance_url)
    if (url.get_backend_name() != 'postgresql' or url.host not in ('127.0.0.1', 'localhost') or
            not (url.database or '').startswith('zhixing_tutor_native_')):
        raise SystemExit('Use a dedicated local PostgreSQL database named zhixing_tutor_native_*')
os.environ.update(DATABASE_URL=acceptance_url, DATA_DIR=str(data),
                  DEEPTUTOR_URL='http://127.0.0.1:18012', DEEPTUTOR_NATIVE_KNOWLEDGE='true',
                  DEEPTUTOR_NATIVE_LESSONS='true', DEEPTUTOR_TIMEOUT='240',
                  DEEPTUTOR_BRIDGE_SECRET=(preview / 'bridge.key').read_text(encoding='utf-8-sig').strip(),
                  NO_PROXY='127.0.0.1,localhost')
os.environ['DEEPTUTOR_NATIVE_QUESTIONS'] = 'true' if '--student' in sys.argv else 'false'
sys.path.insert(0, str(root / 'backend'))

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.db import SessionLocal
from app.main import app
from app.seed import seed
from app.v2 import models as m, service as s, tutor, tutor_index, worker

until = time.monotonic() + 45
with httpx.Client(trust_env=False, timeout=2) as connection:
    while time.monotonic() < until:
        try:
            if connection.get(os.environ['DEEPTUTOR_URL']+'/health/ready').is_success:
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    else:
        raise SystemExit('Isolated DeepTutor preview did not become ready')

command.upgrade(Config(str(root / 'backend' / 'alembic.ini')), 'head')
seed(include_demo_content=False)


def login(username):
    client = TestClient(app)
    response = client.post('/api/v1/auth/login', json={'username': username, 'password': 'Zhixing2026!'})
    response.raise_for_status()
    client.headers['X-CSRF-Token'] = client.get('/api/v1/me').json()['data']['csrf_token']
    return client


def call(path, method='GET', body=None, client=None, expected=200, **kwargs):
    response = (client or student).request(method, '/api/v2' + path, json=body,
        headers={'Idempotency-Key': str(uuid4())}, **kwargs)
    if response.status_code != expected:
        raise RuntimeError(f'{method} {path}: {response.status_code} {response.text[:600]}')
    return response.json().get('data') if expected < 400 else None


def process(run):
    for _ in range(30):
        worker.tick()
        result = call('/ai-runs/'+run['run_id'])
        if result['state'] in ('succeeded', 'failed', 'cancelled'):
            return result
        time.sleep(1)
    raise TimeoutError('Platform run was not processed')


def wait_index(base):
    call(base+'/tutor-index', 'POST', expected=202)
    until = time.monotonic() + 180
    while time.monotonic() < until:
        tutor_index.tick()
        items = call(base+'/tutor-index')['items']
        if items and all(item['state'] == 'ready' for item in items):
            return
        errors = [item['error'] for item in items if item['state'] == 'failed']
        if errors:
            raise RuntimeError(errors)
        time.sleep(2)
    raise TimeoutError('Native index did not become ready')


student, other = login('student'), login('teacher')
try:
    subject = student.get('/api/v1/catalog').json()['data']['subjects'][0]['id']
    project = call('/learning-projects', 'POST', {'title':'原生知识库验收', 'subject_id':subject,
                                                  'exam_year':2027, 'daily_minutes':30}, expected=201)
    base = '/learning-projects/' + project['id']
    call(base+'/tutor-index', client=other, expected=404)
    quote = '海岬试验的验收标记是蓝色铜铃。'
    with pymupdf.open() as pdf:
        for _ in range(20):
            page = pdf.new_page()
            for line in range(30):
                page.insert_text((40, 45 + 19 * line), '本页仅记录测试用的时间、样本与数据分布。', fontname='china-s')
        page = pdf.new_page()
        page.insert_text((40, 45), quote, fontname='china-s')
        content = pdf.tobytes()
    material = call(base+'/uploads', 'POST', files={'file': ('long.pdf', content, 'application/pdf')}, expected=201)
    duplicate = call(base+'/uploads', 'POST', files={'file': ('same.pdf', content, 'application/pdf')}, expected=201)
    assert duplicate['id'] == material['id']
    print('Waiting for native DeepTutor LlamaIndex.', flush=True)
    wait_index(base)
    run = call(base+'/ai-runs', 'POST', {'prompt':'海岬试验的验收标记是什么？请完整逐字引用一句原文。'}, expected=202)
    result = process(run)
    if result['state'] != 'succeeded':
        raise RuntimeError(result['error'])
    citation = next(c for c in result['result']['citations'] if c['quote'] in quote and '蓝色铜铃' in c['quote'])
    assert citation['page'] == 21 and citation['start'] > 12000
    source = base+'/materials/'+material['id']
    excerpt = f"{source}/excerpt?sha256={citation['sha256']}&start={citation['start']}&end={citation['end']}"
    assert call(excerpt)['quote'] == citation['quote']
    call(excerpt, client=other, expected=404)
    if '--lessons' in sys.argv:
        reading, = [task for task in call(base)['tasks'] if task['material_id'] == material['id'] and task['kind'] == 'reading']
        for kind in ('read', 'guide', 'solve'):
            task_id = reading['id']
            if kind == 'solve':
                with SessionLocal.begin() as db:
                    p = db.get(m.Project, project['id'])
                    q = m.Question(project_id=p.id, material_id=material['id'], knowledge='海岬试验', kind='single',
                        prompt='海岬试验的验收标记是什么？', options={'A':'蓝色铜铃','B':'纸灯'},
                        answer=['A'], explanation=quote, quote=quote)
                    db.add(q)
                    db.flush()
                    task = s.add_task(db, p, 'practice', '讲题验收', 'solve-preview', '已提交测试题', material['id'], {'question_id':q.id})
                    task.state = 'completed'
                    db.add(m.Attempt(task_id=task.id, answer=['A']))
                    task_id = task.id
            lesson = call(base+'/ai-runs', 'POST', {'kind':kind, 'task_id':task_id,
                'prompt':'围绕海岬试验的验收标记给出一条学习说明并逐字引用原文。'}, expected=202)
            state = process(lesson)
            if state['state'] != 'succeeded':
                raise RuntimeError(kind+': '+str(state['error']))
            assert state['result']['text'].strip(), kind
            if kind == 'guide':
                accepted = call('/ai-runs/'+lesson['run_id']+'/accept-guide', 'POST')
                assert call('/ai-runs/'+lesson['run_id']+'/accept-guide', 'POST') == accepted
            print('PASS: real DeepTutor', kind, flush=True)
    call(source, 'DELETE')
    call('/ai-runs/'+run['run_id'], expected=403)
    with SessionLocal.begin() as db:
        row = db.scalar(select(m.TutorIndex))
        row.next_at = s.clock().isoformat()
        owner, name = row.principal, row.name
    tutor_index.tick()
    assert tutor.knowledge_request(owner, 'status', name)['state'] == 'missing'
    print('PASS: real native retrieval, model answer, PDF page 21, scope isolation and deletion.', flush=True)
    if '--student' in sys.argv:
        study = call('/learning-projects', 'POST', {'title':'考研练习验收', 'subject_id':subject,
                                                   'exam_year':2027, 'daily_minutes':30}, expected=201)
        path = '/learning-projects/'+study['id']
        source_text = ('实践是认识的来源，是认识发展的动力，是检验认识真理性的唯一标准，也是认识的目的。'
                       '正确的认识能够促进实践，错误的认识会阻碍实践。认识过程具有反复性和无限性。真理是具体的、有条件的。')
        notes = call(path+'/materials', 'POST', {'title':'实践与认识', 'text':source_text}, expected=201)
        wait_index(path)
        for kind in ('single', 'multiple', 'essay'):
            with SessionLocal.begin() as db:
                project_row = db.get(m.Project, study['id'])
                task = s.add_task(db, project_row, 'practice', '原生出题：'+kind, 'preview:'+kind, '验收练习', notes['id'],
                                  {'knowledge':'实践与认识'})
                session_path = '/study-sessions/'+task.id
            state = process(call(session_path+'/prepare', 'POST', {'kind':kind}, expected=202))
            if state['state'] != 'succeeded':
                raise RuntimeError(kind+': '+str(state['error']))
            with SessionLocal() as db:
                question = db.get(m.Question, state['result']['question_id'])
                assert question.kind == kind and question.quote in source_text
                answer = question.answer
            submitted = call(session_path+'/submit', 'POST', {'answer':answer, 'response_text':source_text if kind == 'essay' else '',
                                                               'confidence':'normal'})['result']
            if kind == 'essay':
                assert submitted['state'] == 'pending_ai'
                evaluation = process(submitted)
                assert evaluation['state'] == 'succeeded' and evaluation['result']['label'] == 'AI训练评价，不是正式成绩', evaluation
            else:
                assert submitted['correct'] is True, submitted
            print('PASS: real student question and submission', kind, flush=True)
finally:
    student.close()
    other.close()
