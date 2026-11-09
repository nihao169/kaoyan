from datetime import timedelta
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from conftest import checked
from app.db import SessionLocal
from app.main import app
from app.v2 import models as m, service as s


def call(client, path, method='GET', body=None, status=200, idem=None):
    response = client.request(method, '/api/v2' + path, json=body, headers={'Idempotency-Key': idem or str(uuid4())})
    assert response.status_code == status, response.text
    return response.json().get('data') if status < 400 else response.json()['error']


def setup_project(student):
    subject = checked(student, '/catalog')['subjects'][0]['id']
    p = call(student, '/learning-projects', 'POST', {'title': '政治自主复习', 'subject_id': subject, 'exam_year': 2027, 'daily_minutes': 30}, 201)
    material = call(student, '/learning-projects/' + p['id'] + '/materials', 'POST', {'title': '认识与实践', 'text': '实践是认识的来源，实践是检验认识真理性的唯一标准。认识需要不断接受实践检验。'}, 201)
    detail = call(student, '/learning-projects/' + p['id'])
    return p, material, detail['tasks'][0]


def test_full_text_citation_and_revocation(clients, monkeypatch):
    import json
    from app.v2 import worker
    student, teacher, _ = clients
    p, _, reading = setup_project(student)
    base = '/learning-projects/' + p['id']
    quote = '认识需要接受量子灯塔试验的实际检验'
    material = call(student, base+'/materials', 'POST',
                    {'title':'尾部检索测试', 'text':('早期材料只谈进度与统计。\n'*1400)+quote+'。'}, 201)
    hits = call(student, base+'/material-search?q=量子灯塔试验')
    assert hits[0]['material_id'] == material['id'] and hits[0]['start'] > 12000
    assert quote in hits[0]['quote']
    async def execute(principal, prompt, capability, submission_id, on_event):
        assert quote in prompt
        return json.dumps({'text':'资料说明该试验用于检验认识。','citations':[
            {'material_id': material['id'], 'quote':quote}, {'material_id':material['id'], 'quote':'这条引文是模型捏造的，不存在于任何检索片段'}
        ]})
    monkeypatch.setattr(worker.tutor, 'execute', execute)
    run = call(student, base+'/ai-runs', 'POST', {'prompt':'量子灯塔试验的作用是什么？','task_id':reading['id']}, 202)
    assert worker.tick()
    result = call(student, '/ai-runs/'+run['run_id'])['result']
    assert result['citation_status'] == 'partial'
    citation, = result['citations']
    link = f"{base}/materials/{material['id']}/excerpt?start={citation['start']}&end={citation['end']}&sha256={citation['sha256']}"
    assert call(student, link)['quote'] == quote
    call(teacher, link, status=404)
    call(student, base+'/materials/'+material['id'], 'DELETE')
    call(student, link, status=403)
    call(student, '/ai-runs/'+run['run_id'], status=403)
    assert call(student, base+'/material-search?q=量子灯塔试验') == []


def test_native_index_uses_authorized_version_and_cleans_revoked_copy(clients, monkeypatch):
    import json
    from app.config import settings
    from app.v2 import tutor, tutor_index, worker

    student, teacher, _ = clients
    p, material, reading = setup_project(student)
    base = '/learning-projects/' + p['id']
    quote = '实践是检验认识真理性的唯一标准'
    copies = {}
    created = []

    def bridge(owner, op, name, **data):
        key = owner, name
        if op == 'status':
            return {'state': 'ready' if key in copies else 'missing'}
        if op == 'create':
            created.append(key)
            copies[key] = data['text']
            return {'state': 'indexing'}
        if op == 'search':
            assert quote in copies[key]
            return {'state': 'ready', 'passages': [quote, '未出现在授权原文的伪造内容']}
        assert op == 'delete'
        copies.pop(key, None)
        return {'state': 'deleted'}

    async def execute(principal, prompt, capability, submission_id, on_event):
        assert quote in prompt and '伪造内容' not in prompt
        return json.dumps({'text': '按讲义回答', 'citations': [{'material_id': material['id'], 'quote': quote}]})

    monkeypatch.setattr(settings, 'deeptutor_native_knowledge', True)
    monkeypatch.setattr(tutor, 'knowledge_request', bridge)
    monkeypatch.setattr(tutor, 'execute', execute)
    call(teacher, base+'/tutor-index', status=404)
    call(student, base+'/ai-runs', 'POST', {'prompt': '检验标准是什么'}, 409)
    for _ in range(2):
        call(student, base+'/tutor-index', 'POST', status=202)
    assert tutor_index.tick()
    assert call(student, base+'/tutor-index')['items'][0]['state'] == 'indexing'
    with SessionLocal.begin() as db:
        db.scalar(select(m.TutorIndex)).next_at = s.clock().isoformat()
    assert tutor_index.tick() and len(created) == 1
    assert call(student, base+'/tutor-index')['items'][0]['state'] == 'ready'
    run = call(student, base+'/ai-runs', 'POST', {'prompt': '检验标准是什么', 'task_id':reading['id']}, 202)
    assert worker.tick()
    result = call(student, '/ai-runs/'+run['run_id'])['result']
    assert result['citation_status'] == 'verified' and result['citations'][0]['quote'] == quote
    assert 'DeepTutor 原生知识库' in result['coverage_note']
    call(student, base+'/materials/'+material['id'], 'DELETE')
    call(student, '/ai-runs/'+run['run_id'], status=403)
    with SessionLocal.begin() as db:
        db.scalar(select(m.TutorIndex)).next_at = s.clock().isoformat()
    assert tutor_index.tick() and not copies


def test_expired_worker_subscribes_to_known_turn_without_resubmitting(clients, monkeypatch):
    from app.v2 import tutor, worker

    student, _, _ = clients
    p, _, reading = setup_project(student)
    run = call(student, f'/learning-projects/{p["id"]}/ai-runs', 'POST',
               {'prompt': '检验认识的标准是什么？', 'task_id': reading['id']}, 202)
    with SessionLocal.begin() as db:
        row = db.get(m.AIRun, run['run_id'])
        row.state = 'running'
        row.external_id = 'known-turn'
        row.lease_until = (s.clock()-timedelta(seconds=1)).isoformat()

    async def subscribe(principal, prompt, capability, submission_id, on_event, **options):
        assert options == {'resume_turn_id': 'known-turn'}
        return tutor.TurnResult('恢复原运行的答复', turn_id='known-turn')

    monkeypatch.setattr(tutor, 'execute_turn', subscribe)
    assert worker.tick()
    status = call(student, '/ai-runs/'+run['run_id'])
    assert status['state'] == 'succeeded' and status['result']['text'] == '恢复原运行的答复'


def test_native_reading_reuses_session_and_mastery_requires_acceptance(clients, monkeypatch):
    from app.config import settings
    from app.v2 import tutor, worker

    student, teacher, _ = clients
    p, material, reading = setup_project(student)
    base = '/learning-projects/' + p['id']
    quote = '实践是检验认识真理性的唯一标准'
    monkeypatch.setattr(settings, 'deeptutor_native_knowledge', True)
    monkeypatch.setattr(settings, 'deeptutor_native_lessons', True)
    with SessionLocal.begin() as db:
        row = db.get(m.Material, material['id'])
        member_id = db.get(m.Project, p['id']).space_id
        from app import models as old
        member_id = db.scalar(select(old.Membership.id).where(old.Membership.user_id == db.get(m.PersonalSpace, member_id).user_id))
        db.add(m.TutorIndex(material_id=row.id, membership_id=member_id, sha256=row.sha256, principal='owner',
                           name='kb', state='ready', next_at=(s.clock()+timedelta(days=1)).isoformat()))

    def knowledge(owner, op, name, **data):
        assert (owner, name) == ('owner', 'kb')
        return {'state': 'ready', 'passages': [quote], 'material_id': 'native-material', 'revision': 'r1'}

    sessions, turns = [], []

    async def reading_session(*args):
        sessions.append(args)
        return {'session_id': 'native-session', 'reading_workspace_id': 'native-workspace'}

    async def turn(principal, prompt, capability, submission_id, on_event, **context):
        turns.append((capability, context))
        return tutor.TurnResult('继续解释所学内容', session_id='native-study')

    async def draft(principal, body):
        assert body['sources'][0]['source_id'] == 'kb' and '2027' in body['goal']
        return {'modules': [{'name': '认识论', 'knowledge_points': [{'name': '实践标准'}]}]}

    async def create(principal, body):
        assert body['modules']
        return {'path_id': 'native-path'}

    monkeypatch.setattr(tutor, 'knowledge_request', knowledge)
    monkeypatch.setattr(tutor, 'reading_session', reading_session)
    monkeypatch.setattr(tutor, 'execute_turn', turn)
    monkeypatch.setattr(tutor, 'mastery_draft', draft)
    monkeypatch.setattr(tutor, 'mastery_create', create)

    def run(kind, task_id):
        result = call(student, base+'/ai-runs', 'POST', {'kind': kind, 'prompt': '实践的作用是什么？', 'task_id': task_id}, 202)
        assert worker.tick()
        status = call(student, '/ai-runs/'+result['run_id'])
        assert status['state'] == 'succeeded', status
        return status

    for _ in range(2):
        run('read', reading['id'])
    assert len(sessions) == 1 and [options['session_id'] for _, options in turns] == ['native-session']*2
    guide = run('guide', reading['id'])
    assert not call(student, base)['mastery_outline']
    call(teacher, '/ai-runs/'+guide['id']+'/accept-guide', 'POST', status=404)
    task = call(student, '/ai-runs/'+guide['id']+'/accept-guide', 'POST')['task_id']
    assert call(student, base)['mastery_outline'] == [{'name': '认识论', 'points': ['实践标准']}]
    assert call(student, '/ai-runs/'+guide['id']+'/accept-guide', 'POST')['task_id'] == task
    run('guide', task)
    run('guide', task)
    assert turns[-2][1]['mastery_path_id'] == 'native-path' and turns[-1][1]['session_id'] == 'native-study'
    assert not call(student, base+'/report')['evidence_count']
    call(student, base+'/materials/'+material['id'], 'DELETE')
    assert not call(student, base)['mastery_outline']
    call(student, '/ai-runs/'+guide['id'], status=403)


def test_pdf_citation_opens_correct_original_page(clients):
    import pymupdf
    student, teacher, _ = clients
    p, _, _ = setup_project(student)
    base = '/learning-projects/'+p['id']
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((72,72),'Page one introduction')
        pdf.new_page().insert_text((72,72),'Special immutable lighthouse citation')
        response = student.post('/api/v2'+base+'/uploads', files={'file':('proof.pdf',pdf.tobytes(),'application/pdf')})
    assert response.status_code == 201, response.text
    mid = response.json()['data']['id']
    hit = call(student, base+'/material-search?q=lighthouse')[0]
    # Search passage may cross page boundaries; the exact match resolves to page two.
    start = hit['start'] + hit['quote'].index('Special')
    loc = call(student, f"{base}/materials/{mid}/excerpt?sha256={hit['sha256']}&start={start}&end={start+36}")
    assert loc['page'] == 2
    url = f'/api/v2{base}/materials/{mid}/original-pdf'
    assert student.get(url).content.startswith(b'%PDF')
    assert teacher.get(url).status_code == 404


def test_annual_resources_and_offline_deadline(clients, monkeypatch):
    from app.v2 import maintenance
    student, teacher, _ = clients
    p, _, _ = setup_project(student)
    base = '/learning-projects/'+p['id']
    path = base+'/exam-resources'
    outline, paper = call(student, path+'/sample', 'POST', status=201)
    assert paper['kind']=='simulated_paper' and paper['question_count']==6 and paper['total_points']==30
    assert '模拟' in outline['title']
    assert call(student, path+'/sample', 'POST', status=201)[1]['id']==paper['id']
    assert len(call(student, path)['resources'])==2
    topic = outline['topics'][1]
    study = call(student, f"{path}/{outline['id']}/topics/{topic['code']}/study", 'POST')
    content = call(student, '/study-sessions/'+study['task_id'])['material']['text']
    assert topic['title'] in content and outline['topics'][0]['title'] not in content
    start_practice(student, {'id':study['task_id']})
    assert call(student,base+'/report')['syllabi'][0]['studied']==1
    call(teacher,path,status=404)
    exam = call(student,'/assessments/from-past-paper','POST',{'project_id':p['id'],'resource_id':paper['id']},201)
    exam_path = '/assessments/'+exam['id']
    details = call(student,exam_path)
    first = details['entries'][0]
    assert first['points']==2 and 'answer' not in first['question']
    call(student,'/study-sessions/'+first['task_id'],status=403)
    call(student,base+'/material-search?q=实践',status=403)
    call(student,exam_path+'/draft','PUT',{'revision':1,'answers':{first['task_id']:{'answer':['X']}}},422)
    call(student,exam_path+'/draft','PUT',{'revision':1,'answers':{first['task_id']:{'answer':['A']}}})
    future = s.clock()+timedelta(hours=1)
    monkeypatch.setattr(s,'clock',lambda:future)
    assert maintenance.tick()==1
    assert maintenance.tick()==0
    finished=call(student,exam_path)
    assert finished['state']=='submitted' and finished['paper_objective_score']=={'earned':2,'possible':10}
    assert call(student,exam_path+'/submit','POST',{'answers':{first['task_id']:{'answer':['B']}}})['used_saved_answers']


@pytest.mark.parametrize('cancel_while_silent', [False, True])
def test_deeptutor_stream_reconnects_or_cancels_without_new_submission(monkeypatch, cancel_while_silent):
    import asyncio
    import json
    from app.v2 import tutor
    monkeypatch.setattr(tutor.settings,'deeptutor_url','http://mock.invalid')
    monkeypatch.setattr(tutor.settings,'deeptutor_bridge_secret','x'*40)
    sent = []
    streams = [
        [{'type':'content','turn_id':'same-turn','seq':1,'content':'前半'}],
        [{'type':'content','turn_id':'same-turn','seq':1,'content':'前半'},
         {'type':'content','turn_id':'same-turn','seq':2,'content':'后半'},
         {'type':'done','turn_id':'same-turn','seq':3,'metadata':{'status':'completed'}}],
    ]
    if cancel_while_silent:
        streams = [[{'type':'content','turn_id':'same-turn','seq':1,'content':'前半'}, TimeoutError(),
                    {'type':'done','turn_id':'same-turn','seq':2,'metadata':{'status':'cancelled'}}]]
    class Exchange:
        status_code=200
        def json(self): return {'token':'fake'}
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): return Exchange()
    class Socket:
        def __init__(self, *args, **kwargs):
            self.events=iter(streams.pop(0))
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def send(self,value): sent.append(json.loads(value))
        async def recv(self):
            value = next(self.events, None)
            if value is None:
                raise OSError('connection interrupted')
            if isinstance(value, Exception):
                raise value
            return json.dumps(value)
    monkeypatch.setattr(tutor.httpx,'AsyncClient',Client)
    monkeypatch.setattr('websockets.asyncio.client.connect',Socket)
    result = asyncio.run(tutor.execute('example','question','chat','one-submit',
                                      lambda event: cancel_while_silent and event['type'] == 'heartbeat'))
    assert sent[0]['type']=='start_turn'
    assert len(sent) == 2
    if cancel_while_silent:
        assert result == ''
        assert sent[1] == {'type':'cancel_turn','turn_id':'same-turn','command_id':'one-submit:cancel','protocol_version':'2.0'}
    else:
        assert result == '前半后半'
        assert sent[1]=={'type':'subscribe_turn','turn_id':'same-turn','after_seq':1,'protocol_version':'2.0'}


def make_question(task_id, material, p, answer=None, essay=False):
    with SessionLocal.begin() as db:
        t = db.get(m.Task, task_id)
        q = m.Question(project_id=p['id'], material_id=material['id'], knowledge='实践与认识', kind='essay' if essay else 'single',
                       prompt='哪一项是检验认识真理性的标准？' + str(uuid4()), options={'A':'实践','B':'主观愿望'},
                       answer=answer or ['A'], explanation='必须接受实践检验。', quote='实践是检验认识真理性的唯一标准。',rubric=['实践标准'])
        db.add(q)
        db.flush()
        t.payload = {**t.payload, 'question_id': q.id, 'knowledge':'实践与认识'}
        return q.id


def start_practice(student, reading):
    return call(student, '/study-sessions/' + reading['id'] + '/complete', 'POST')['next_task_id']


def test_autonomous_loop_and_delayed_review(clients, monkeypatch):
    student, _, _ = clients
    p, material, reading = setup_project(student)
    practice = start_practice(student, reading)
    make_question(practice, material, p)
    result = call(student, f'/study-sessions/{practice}/submit', 'POST', {'answer':['B']})
    assert not result['result']['correct']
    detail = call(student, '/learning-projects/' + p['id'])
    remediation = next(t for t in detail['tasks'] if t['kind']=='remediation')
    verification = start_practice(student, remediation)
    make_question(verification, material, p)
    call(student, f'/study-sessions/{verification}/submit', 'POST', {'answer':['A']})
    detail = call(student, '/learning-projects/' + p['id'])
    review = next(t for t in detail['tasks'] if t['kind']=='review')
    make_question(review['id'], material, p)
    call(student, f'/study-sessions/{review["id"]}/submit', 'POST', {'answer':['A']}, 409)
    anchor = s.clock()
    monkeypatch.setattr(s, 'clock', lambda:anchor+timedelta(days=2))
    due = call(student, '/today')
    assert any(t['id']==review['id'] for t in due['tasks'])
    call(student, f'/study-sessions/{review["id"]}/submit', 'POST', {'answer':['B']})
    detail = call(student, '/learning-projects/' + p['id'])
    assert len([t for t in detail['tasks'] if t['kind']=='remediation']) == 2
    assert detail['report']['evidence_count'] >= 5


def test_idempotency_drafts_and_scope_isolation(clients):
    student, teacher, _ = clients
    p, material, reading = setup_project(student)
    call(teacher, '/learning-projects/'+p['id'], status=404)
    call(teacher, '/study-sessions/'+reading['id'], status=404)
    path=f'/study-sessions/{reading["id"]}/checkpoint'
    assert call(student,path,'PUT',{'revision':0,'text':'我的理解'})['revision']==1
    call(student,path,'PUT',{'revision':0,'text':'旧页面覆盖'},409)
    assert call(student,f'/study-sessions/{reading["id"]}')['checkpoint']['text']=='我的理解'
    token=str(uuid4())
    a=call(student,f'/study-sessions/{reading["id"]}/complete','POST',idem=token)
    b=call(student,f'/study-sessions/{reading["id"]}/complete','POST',idem=token)
    assert a==b
    assert len(call(student,'/learning-projects/'+p['id'])['tasks'])==2


def test_hint_does_not_grant_mastery(clients):
    student, _, _ = clients
    p, material, reading=setup_project(student)
    practice=start_practice(student,reading)
    make_question(practice,material,p)
    before=call(student,f'/study-sessions/{practice}')
    assert 'answer' not in before['question']
    assert call(student,f'/study-sessions/{practice}/hint','POST')['counts_as_assisted']
    call(student,f'/study-sessions/{practice}/submit','POST',{'answer':['A']})
    detail=call(student,'/learning-projects/'+p['id'])
    assert not any(t['kind']=='review' for t in detail['tasks'])
    assert any(t['kind']=='remediation' for t in detail['tasks'])


def test_budget_plan_history_and_future_scenarios(clients):
    student, _, _=clients
    p, material, reading=setup_project(student)
    current=call(student,'/learning-projects/'+p['id'])
    call(student,f'/learning-projects/{p["id"]}/plans','POST',{'revision':current['revision'],'daily_minutes':10})
    today=call(student,'/today')
    assert today['estimated_minutes']<=10
    assert today['deferred']
    plans=call(student,f'/learning-projects/{p["id"]}/plans')
    assert len(plans)==3
    call(student,f'/learning-projects/{p["id"]}/plans','POST',{'revision':1,'daily_minutes':20},409)
    assert [x['available'] for x in call(student,'/scenarios')]==[True,True,True]


def test_worker_real_failure_preserves_learning_and_no_fake_questions(clients, monkeypatch):
    from app.v2.worker import tick
    student, _, _=clients
    p, material, reading=setup_project(student)
    practice=start_practice(student,reading)
    queued=call(student,f'/study-sessions/{practice}/prepare','POST',status=202)
    from app.config import settings
    monkeypatch.setattr(settings,'deeptutor_url','')
    assert tick()
    result=call(student,'/ai-runs/'+queued['run_id'])
    assert result['state']=='failed' and 'NOT_CONFIGURED' in result['error']
    assert call(student,f'/study-sessions/{practice}')['question'] is None
    call(student,f'/learning-projects/{p["id"]}/materials/{material["id"]}','DELETE')
    call(student,'/ai-runs/'+queued['run_id'],status=403)
    call(student,f'/study-sessions/{practice}',status=403)


def test_worker_generated_question_validation_and_feedback(clients, monkeypatch):
    from app.v2 import tutor
    from app.v2.worker import tick
    import json
    student, _, _=clients
    p, material, reading=setup_project(student)
    practice=start_practice(student,reading)
    async def controlled(*args):
        if '请独立校验' in args[1]:
            return json.dumps({'valid':True,'reason':'受控测试校验通过'})
        return json.dumps({'material_id':material['id'],'knowledge':'实践与认识','kind':'single','prompt':'什么是认识的来源？','options':{'A':'实践','B':'猜想'},'answer':['A'],'explanation':'来源于实践','quote':'实践是认识的来源','rubric':[]})
    monkeypatch.setattr(tutor,'execute',controlled)
    queued=call(student,f'/study-sessions/{practice}/prepare','POST',status=202)
    assert tick()
    result=call(student,'/ai-runs/'+queued['run_id'])
    assert result['state']=='succeeded'
    question=call(student,f'/study-sessions/{practice}')['question']
    assert question and 'answer' not in question
    call(student,f'/study-sessions/{practice}/submit','POST',{'answer':['A']})
    assert call(student,f'/study-sessions/{practice}')['result']['correct']


@pytest.mark.parametrize('registration', [False, True])
def test_login_cookie_is_sent_after_session_commit(environment, registration):
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    committed = []
    observed = []

    async def capture(scope, receive, send):
        async def check_response(message):
            if message['type'] == 'http.response.start' and any(name == b'set-cookie' for name, _ in message['headers']):
                observed.append(bool(committed))
            await send(message)
        await app(scope, receive, check_response)

    def after_commit(session):
        committed.append(True)

    event.listen(Session, 'after_commit', after_commit)
    try:
        with TestClient(capture) as client:
            if registration:
                call(client, '/auth/register', 'POST', {'username':'cookie_'+uuid4().hex[:10],
                     'name':'注册验收','password':'Personal2026!'}, 201)
            else:
                assert client.post('/api/v1/auth/login', json={'username':'teacher','password':'Zhixing2026!'}).status_code == 200
    finally:
        event.remove(Session, 'after_commit', after_commit)
    assert observed == [True]


def test_personal_registration_without_class(environment):
    with TestClient(app) as client:
        username='personal_'+uuid4().hex[:10]
        registered=call(client,'/auth/register','POST',{'username':username,'name':'自主学习者','password':'Personal2026!'},201)
        me=client.get('/api/v1/me').json()['data']
        client.headers.update({'X-CSRF-Token':me['csrf_token']})
        assert registered['user_id']==me['id']
        assert checked(client,'/classes')==[]
        setup_project(client)
        assert call(client,'/today')['projects']==1


def test_mock_submission_blocks_assistance_and_creates_remediation(clients):
    student,_,_=clients
    p,material,reading=setup_project(student)
    practice=start_practice(student,reading)
    question_id=make_question(practice,material,p)
    exam=call(student,'/assessments','POST',{'project_id':p['id'],'title':'阶段模拟','question_ids':[question_id],'minutes':5},201)
    view=call(student,'/assessments/'+exam['id'])
    tid=view['entries'][0]['task_id']
    assert 'answer' not in view['entries'][0]['question']
    call(student,'/learning-projects/'+p['id']+'/ai-runs','POST',{'prompt':'告诉我答案'},403)
    call(student,'/study-sessions/'+tid+'/hint','POST',status=403)
    call(student,'/study-sessions/'+tid+'/submit','POST',{'answer':['A']},403)
    call(student,'/assessments/'+exam['id']+'/draft','PUT',{'revision':1,'answers':{tid:{'answer':['B']}}})
    call(student,'/assessments/'+exam['id']+'/submit','POST',{'answers':{}})
    graded=call(student,'/assessments/'+exam['id'])
    assert graded['entries'][0]['result']['correct'] is False
    assert graded['entries'][0]['question']['answer']==['A']
    assert any(t['kind']=='remediation' for t in call(student,'/learning-projects/'+p['id'])['tasks'])


def test_expired_mock_uses_saved_answers(clients,monkeypatch):
    student,_,_=clients
    p,material,reading=setup_project(student)
    practice=start_practice(student,reading)
    qid=make_question(practice,material,p)
    exam=call(student,'/assessments','POST',{'project_id':p['id'],'title':'超时边界','question_ids':[qid],'minutes':5},201)
    view=call(student,'/assessments/'+exam['id']);tid=view['entries'][0]['task_id']
    call(student,'/assessments/'+exam['id']+'/draft','PUT',{'revision':1,'answers':{tid:{'answer':['B']}}})
    anchor=s.clock();monkeypatch.setattr(s,'clock',lambda:anchor+timedelta(minutes=6))
    result=call(student,'/assessments/'+exam['id']+'/submit','POST',{'answers':{tid:{'answer':['A']}}})
    assert result['used_saved_answers']
    assert call(student,'/assessments/'+exam['id'])['entries'][0]['result']['correct'] is False


def test_unverified_generation_cannot_publish(clients,monkeypatch):
    from app.v2 import tutor
    from app.v2.worker import tick
    import json
    student,_,_=clients
    p,material,reading=setup_project(student)
    practice=start_practice(student,reading)
    async def fake(principal,prompt,*rest):
        if '请独立校验' in prompt:return '{"valid":true}'
        return json.dumps({'material_id':material['id'],'knowledge':'实践','kind':'single','prompt':'虚构依据测试','options':{'A':'实践','B':'猜想'},'answer':['A'],'explanation':'测试','rubric':[],'quote':'这段引用根本不在任何授权原文中'})
    monkeypatch.setattr(tutor,'execute',fake)
    queued=call(student,f'/study-sessions/{practice}/prepare','POST',status=202)
    assert tick()
    assert call(student,'/ai-runs/'+queued['run_id'])['state']=='failed'
    assert call(student,f'/study-sessions/{practice}')['question'] is None


def test_analysis_training_is_not_official_score(clients,monkeypatch):
    from app.v2 import tutor
    from app.v2.worker import tick
    from app import models as old
    import json
    student,_,_=clients
    p,material,reading=setup_project(student)
    practice=start_practice(student,reading)
    make_question(practice,material,p,essay=True)
    response=call(student,f'/study-sessions/{practice}/submit','POST',{'response_text':'需要根据实践效果检验认识，而不是仅凭主观愿望。'})
    assert response['result']['state']=='pending_ai'
    async def fake(*args):return json.dumps({'correct':True,'score':80,'feedback':'覆盖实践标准，应进一步结合材料。','quote':'实践是检验认识真理性的唯一标准'})
    monkeypatch.setattr(tutor,'execute',fake)
    assert tick()
    result=call(student,f'/study-sessions/{practice}')['result']
    assert result['training_score']==80
    assert result['evaluator']=='ai_training'
    with SessionLocal() as db:
        assert db.scalar(select(old.Evaluation.id)) is None
