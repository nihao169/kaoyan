"""Native learning boundaries; all storage is the isolated fixture database."""
import json
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.db import SessionLocal
from app.v2 import models as m, project_learning as learning
from app.v2 import annual_drafts
from test_v2 import call


def create(student, scene='chapter'):
    return call(student, '/learning-projects', 'POST', {'title':'统计学项目', 'course_name':'统计学',
        'learning_goal':'理解抽样和估计', 'scenario':scene, **({'exam_year':2027} if scene=='kaoyan' else {})}, 201)


def mark_indexed(student, material_id):
    membership = student.get('/api/v1/me').json()['data']['membership_id']
    with SessionLocal.begin() as db:
        material = db.get(m.Material, material_id)
        db.add(m.TutorIndex(material_id=material.id, membership_id=membership, sha256=material.sha256,
            principal='test', name='zx_'+uuid4().hex, state='ready', next_at=''))


def ready_book(student, base):
    material = call(student, base+'/materials', 'POST', {'title':'抽样', 'text':'# 抽样与总体\n随机抽样需要明确总体与样本。'}, 201)
    mark_indexed(student, material['id'])
    return material


@pytest.mark.parametrize('scene', ['chapter', 'final', 'kaoyan'])
def test_scene_and_course_persist_without_politics(clients, scene):
    student, _, _ = clients
    p=create(student, scene)
    assert p['scene_confirmed'] and p['scenario']==scene and p['policy']=='general-mastery-v1'
    base='/learning-projects/'+p['id']
    call(student, base+'/materials', 'POST', {'title':'抽样', 'text':'随机抽样需要明确总体与样本。'}, 201)
    assert call(student, base)['tasks']==[]
    assert call(student, base)['course_name']=='统计学'
    resources=call(student,base+'/exam-resources')
    assert not resources['references'] and not resources['sample_available']
    call(student,base+'/exam-resources/sample','POST',status=422)


def test_preparation_gate_and_idempotent_native_delivery(clients, monkeypatch):
    student, _, _ = clients
    p=create(student)
    base='/learning-projects/'+p['id']
    sent=[]
    state = {'state':'idle', 'messages':[], 'question':None}
    def native(owner, **body):
        if body['operation'] != 'status':
            sent.append((owner, body))
        return dict(state)
    monkeypatch.setattr(learning, 'bridge', native)
    idem=str(uuid4())
    assert call(student, base+'/learning', 'POST', {'text':'我的数学基础比较薄弱'}, 409)['code']=='MATERIAL_REQUIRED'
    ready_book(student, base)
    start = {'operation':'guided', 'action_id':'chapter_outline'}
    first=call(student, base+'/learning', 'POST', start, 202, idem)
    assert first==call(student, base+'/learning', 'POST', start, 202, idem)
    assert call(student, base+'/learning', 'POST', {'text':'不同请求'}, 409, idem)['code']=='IDEMPOTENCY_CONFLICT'
    assert learning.tick()
    assert len(sent)==1 and sent[0][1]['ready'] and sent[0][1]['sources']
    assert '前置概念' in sent[0][1]['guidance']
    assert '学生第一次学习' in sent[0][1]['background']
    command_id=sent[0][1]['submission_id']
    with SessionLocal.begin() as db:
        run=db.get(m.AIRun, first['run_id']);run.state='failed'
    call(student, base+'/learning/retry', 'POST')
    assert learning.tick() and sent[-1][1]['submission_id']==command_id
    assert call(student, base+'/learning', 'POST', {'operation':'guided','action_id':'final_retest'}, 409)['code']=='ACTION_NOT_READY'
    state['curriculum'] = {'map':{'modules':[{'id':'sampling'}]},'reviews':[]}
    for action in ('chapter_start', 'chapter_check'):
        call(student, base+'/learning', 'POST', {'operation':'guided','action_id':action}, 202)
        assert learning.tick()
    state['evidence'] = {'count':1,'result':'incorrect','hints':0}
    assert call(student, base+'/learning')['workflow']['actions'][0]['id'] == 'chapter_reteach'
    call(student, base+'/learning', 'POST', {'operation':'guided','action_id':'chapter_reteach'}, 202)
    assert learning.tick()
    state['evidence'] = {'count':2,'result':'correct','hints':0}
    assert call(student, base+'/learning')['workflow']['actions'][0]['id'] == 'chapter_next'


def test_scope_change_rejects_queued_command_and_keeps_history(clients, monkeypatch):
    student, teacher, _ = clients
    p=create(student);base='/learning-projects/'+p['id']
    book = ready_book(student, base)
    first=call(student, base+'/learning', 'POST', {'text':'先聊目标'}, 202)
    call(student, base+'/materials', 'POST', {'title':'抽样', 'text':'随机抽样需要明确总体与样本。'}, 201)
    monkeypatch.setattr(learning, 'bridge', lambda *a, **k:pytest.fail('stale command must not reach tutor'))
    assert learning.tick()
    with SessionLocal() as db:
        run=db.get(m.AIRun, first['run_id'])
        assert run.state=='failed' and 'SCOPE_CHANGED' in run.error
        assert db.scalar(select(m.ProjectLearning).where(m.ProjectLearning.project_id==p['id']))
    assert call(student, base+'/learning')['state']=='preparing'
    [history] = call(student, base+'/learning-history')
    monkeypatch.setattr(learning, 'bridge', lambda *a, **k:{'curriculum':{'map':{'modules':[]}},'evidence':{'count':0}})
    assert call(student, base+'/learning-history/'+history['id'])['evidence']['count'] == 0
    call(student, base+'/materials/'+book['id'], 'DELETE')
    assert call(student, base+'/learning-history') == []
    call(student, base+'/learning-history/'+history['id'], status=404)
    call(teacher, base+'/learning', status=404)


def test_saved_learning_is_readable_while_index_recovers(clients, monkeypatch):
    from app.config import settings
    from app.v2 import tutor_index

    student, _, _ = clients
    project = create(student)
    base = '/learning-projects/' + project['id']
    ready_book(student, base)
    state = {'state': 'question', 'messages': [{'role': 'assistant', 'content': '已有讲解'}],
             'question': {'question_id': 'saved-card'}, 'request_id': 'saved-card',
             'curriculum': {'map': {'modules': [{'id': 'm', 'knowledge_points': [
                 {'id': 'p', 'name': '样本'},
             ]}]}}}
    requests = []

    def bridge(owner, **fields):
        requests.append(fields)
        return state

    monkeypatch.setattr(learning, 'bridge', bridge)
    call(student, base+'/learning', 'POST', {'operation': 'guided', 'action_id': 'chapter_outline'}, 202)
    assert learning.tick()
    with SessionLocal.begin() as db:
        index = db.scalar(select(m.TutorIndex))
        index.state = 'failed'
        index.error = 'DEEPTUTOR_KNOWLEDGE_UNAVAILABLE：无法访问知识库服务'
    snapshot = call(student, base+'/learning')
    assert not snapshot['preparation']['ready'] and not snapshot['writable']
    assert snapshot['messages'] == state['messages'] and snapshot['question'] == state['question']
    assert snapshot['curriculum'] == state['curriculum'] and snapshot['daily_plan'] is None
    assert requests[-1]['ready'] and requests[-1]['sources'] == []
    call(student, base+'/learning', 'POST', {'operation': 'answer', 'expected_id': 'saved-card', 'text': 'A'}, 409)
    monkeypatch.setattr(settings, 'deeptutor_native_knowledge', True)

    def knowledge(owner, operation, name):
        assert operation == 'status'
        return {'state': 'ready'}

    monkeypatch.setattr(learning.tutor, 'knowledge_request', knowledge)
    assert tutor_index.tick()
    snapshot = call(student, base+'/learning')
    assert snapshot['preparation']['ready'] and snapshot['writable']
    assert snapshot['request_id'] == 'saved-card'


def test_legacy_confirmation_preserves_evidence_and_reuses_path_on_goal_edit(clients, monkeypatch):
    student, _, _ = clients
    p=call(student,'/learning-projects','POST',{'title':'旧项目','exam_year':2027},201)
    base='/learning-projects/'+p['id']
    assert call(student,base+'/learning')['state']=='profile_required'
    p=call(student,base+'/learning-profile','PUT',{'revision':p['revision'],'scenario':'final','course_name':'统计学'})
    monkeypatch.setattr(learning,'bridge',lambda *a,**k:{'state':'idle','messages':[],'question':None})
    book=ready_book(student, base)
    p=call(student,base)
    assert call(student,base+'/learning')['preparation']['checks'][1]['state']=='missing'
    call(student,base+'/study-scope','PUT',{'revision':p['revision'],'sections':[{'material_id':book['id'],'title':'抽样与总体'}]})
    call(student,base+'/learning','POST',{'text':'请先了解我的目标'},202);assert learning.tick()
    p=call(student,base)
    call(student,base+'/learning-profile','PUT',{'revision':p['revision'],'scenario':'final','course_name':'统计学','learning_goal':'补充基础'})
    assert call(student,base+'/learning')['state']=='idle'
    call(student,base+'/learning','POST',{'text':'请调整大纲，保留已有证据'},202);assert learning.tick()
    with SessionLocal() as db:
        bindings=list(db.scalars(select(m.ProjectLearning).where(m.ProjectLearning.project_id==p['id'])))
        assert len(bindings)==2 and len({row.path_id for row in bindings})==1
    call(student,base+'/archive','POST')
    assert call(student,base+'/learning')['state']=='idle'
    call(student,base+'/learning','POST',{'text':'归档后不能继续教学'},409)


def test_ready_sources_and_authorized_note_selection(clients, monkeypatch):
    student, _, _=clients
    p=create(student);base='/learning-projects/'+p['id']
    material=call(student,base+'/materials','POST',{'title':'抽样','text':'随机抽样需要明确总体与样本。'},201)
    with SessionLocal.begin() as db:
        db.add(m.TutorIndex(material_id=material['id'], membership_id=student.get('/api/v1/me').json()['data']['membership_id'],
            sha256=db.get(m.Material,material['id']).sha256,principal='test',name='zx_'+'a'*48,state='ready',next_at=''))
    note=call(student,base+'/notes','POST',{'title':'我的理解','text':'样本不是总体','kind':'note'},201)
    monkeypatch.setattr(learning,'bridge',lambda owner,**fields:{'received':fields,'state':'idle','messages':[],'question':None})
    run=call(student,base+'/learning','POST',{'operation':'notes','note_ids':[note['id']]},202)
    assert learning.tick()
    with SessionLocal() as db:
        body=db.get(m.AIRun,run['run_id']).result['received']
        assert body['ready'] and body['sources'][0]['label']=='抽样' and body['notes'][0]['title']=='我的理解'
    call(student,base+'/learning','POST',{'operation':'notes','note_ids':[str(uuid4())]},404)
    records=call(student,base+'/notes')
    with SessionLocal.begin() as db:
        db.get(m.Project,p['id']).native_records=True
    monkeypatch.setattr(learning.tutor_records,'native_records',lambda *args:records)
    call(student,base+'/learning','POST',{'operation':'notes','note_ids':[note['id']]},202)
    assert learning.tick()


def test_native_practice_hides_keys_and_rejects_other_paths(clients, monkeypatch):
    student, _, _=clients
    p=create(student);base='/learning-projects/'+p['id']
    monkeypatch.setattr(learning,'bridge',lambda *a,**k:{'state':'idle','messages':[],'question':None})
    ready_book(student, base)
    call(student,base+'/learning','POST',{'text':'目标讨论'},202);assert learning.tick()
    with SessionLocal() as db:
        path=db.scalar(select(m.ProjectLearning).where(m.ProjectLearning.project_id==p['id'])).path_id
    entry={'id':1,'question':'选出总体','question_type':'single','options':{'A':'总体'},
           'mastery_path_id':path,'correct_answer':'A','explanation':'参考解释'}
    sent=[]
    def native(owner,method,url,**kwargs):
        sent.append((method,url,kwargs))
        if url.endswith('/entries'):
            return {'items':[entry,{**entry,'id':2,'mastery_path_id':'other'}],'total':2}
        if url.endswith('/check'): return {'correct':True}
        if url.endswith('/review'): return {'state':{'version':1}}
        return {'entry':entry,'state':{'version':0}}
    monkeypatch.setattr(learning,'native_call',native)
    listed=call(student,base+'/learning/practice')
    assert len(listed['items'])==1 and 'correct_answer' not in listed['items'][0]
    question=call(student,base+'/learning/practice/1')
    assert 'correct_answer' not in question['entry'] and question['version']==0
    result=call(student,base+'/learning/practice/1','POST',{'answer':'A','version':0})
    assert result['correct_answer']=='A' and not result['updates_mastery_path']
    assert sent[-1][2]['body']['rating']=='good'
    entry['mastery_path_id']='other'
    call(student,base+'/learning/practice/1',status=404)


def test_kaoyan_requires_syllabus_and_book_then_real_paper_without_rebinding(clients, monkeypatch):
    student, _, _ = clients
    p = create(student, 'kaoyan')
    base = '/learning-projects/' + p['id']
    ready_book(student, base)
    syllabus = {'kind':'syllabus', 'year':2027, 'edition':'v1', 'title':'统计考试范围', 'source_title':'验收资料',
        'rights_confirmed':True, 'topics':[{'code':'sample','chapter':'抽样','title':'总体与样本','text':'区分总体与样本。'}]}
    call(student, base+'/learning', 'POST', {'operation':'guided','action_id':'kaoyan_outline'}, 409)
    resource = call(student, base+'/exam-resources', 'POST', syllabus, 201)
    mark_indexed(student, resource['material_id'])
    assert call(student, base+'/learning')['workflow']['actions'][0]['id'] == 'kaoyan_outline'
    sent = []

    def bridge(owner, **body):
        sent.append(body)
        return {'state':'idle', 'messages':[], 'question':None}

    monkeypatch.setattr(learning, 'bridge', bridge)
    call(student, base+'/learning', 'POST', {'operation':'guided','action_id':'kaoyan_outline'}, 202)
    assert learning.tick()
    assert '目标年度考纲' in sent[-1]['guidance']
    with SessionLocal() as db:
        before = db.get(m.Project, p['id']).scope_revision
        binding = db.scalar(select(m.ProjectLearning).where(m.ProjectLearning.project_id == p['id'])).path_id
    paper = {'year':2026,'edition':'v1','title':'抽样试卷','source_title':'验收试卷','rights_confirmed':True,
        'minutes':5,'questions':[{'number':1,'kind':'single','knowledge':'总体','prompt':'哪项描述总体？',
        'options':{'A':'全体','B':'一部分'},'answer':['A'],'explanation':'总体是所研究对象的全体。','points':2}]}
    call(student, base+'/exam-resources', 'POST', {**paper,'kind':'simulated_paper'}, 201)
    assert call(student, base+'/learning')['preparation']['papers'] == []
    exam_resource = call(student, base+'/exam-resources', 'POST', {**paper,'kind':'past_paper'}, 201)
    assert call(student, base+'/learning')['preparation']['papers'][0]['id'] == exam_resource['id']
    assert call(student, base)['scope_revision'] == before
    assert sent[-1]['path_id'] == binding and len(sent[-1]['sources']) == 2
    request = {'project_id':p['id'],'resource_id':exam_resource['id']}
    call(student, '/assessments/from-past-paper', 'POST', {**request,'mode':'mock'}, 409)
    practice = call(student, '/assessments/from-past-paper', 'POST', {**request,'mode':'practice'}, 201)
    path = '/assessments/' + practice['id']
    task = call(student, path)['entries'][0]['task_id']
    call(student, path+'/submit', 'POST', {'answers':{task:{'answer':['B']}}})
    call(student, base+'/learning', 'POST', {'operation':'guided','action_id':'kaoyan_analyze'}, 202)
    assert learning.tick()
    assert sent[-1]['operation'] == 'brief' and '客观题正确' in sent[-1]['guidance']
    result = call(student, '/assessments/from-past-paper', 'POST', {**request,'mode':'mock'}, 201)
    assert 'answer' not in call(student, '/assessments/'+result['id'])['entries'][0]['question']
    call(student, base+'/learning', status=403)
    call(student, base+'/annual-drafts', status=403)


def test_annual_document_extract_edit_and_confirm(clients, monkeypatch):
    student, teacher, _ = clients
    p = create(student, 'kaoyan')
    base = '/learning-projects/' + p['id']
    path = base + '/annual-drafts'
    response = student.post('/api/v2' + path, data={'kind':'past_paper'},
        files={'file':('paper.txt','2026 模拟验收材料，题目一：总体是什么？'.encode(),'text/plain'),
               'answer':('answer.txt','第1题：A。总体是所研究对象的全体。'.encode(),'text/plain')})
    assert response.status_code == 202, response.text
    draft_path = path + '/' + response.json()['data']['id']
    call(teacher, draft_path, status=404)
    responses = iter([{'year':2026,'minutes':5,'questions':[{'number':1,'kind':'single','knowledge':'抽样',
        'prompt':'总体是什么？','options':{'A':'全体','B':'一部分'},'points':2}]},
        {'questions':[{'number':1,'answer':['A'],'explanation':'总体是所研究对象的全体。'}]}])

    async def extract(*args, **kwargs):
        return next(responses)

    monkeypatch.setattr(annual_drafts.tutor, 'structured_chat', extract)
    assert annual_drafts.tick() and annual_drafts.tick()
    detail = call(student, draft_path)
    assert detail['state'] == 'succeeded' and detail['draft']['questions'][0]['answer'] == ['A']
    assert call(student, draft_path+'/confirm', 'POST', status=422)['code'] == 'DRAFT_INVALID'
    assert student.get('/api/v2'+draft_path+'/files/1').content.startswith('第1题'.encode())
    call(student, draft_path, 'PUT', {'revision':detail['revision'],'resource':{**detail['draft'],'rights_confirmed':True}})
    resource = call(student, draft_path+'/confirm', 'POST', status=201)
    assert call(student, draft_path)['resource_id'] == resource['id']
    assert call(student, draft_path+'/confirm', 'POST', status=201)['id'] == resource['id']

    second = student.post('/api/v2' + path, data={'kind':'past_paper'},
        files={'file':('second.txt','2026 第二份验收材料，题目一：样本是什么？'.encode(),'text/plain')})
    assert second.status_code == 202, second.text
    second_path = path + '/' + second.json()['data']['id']

    async def extract_second(*args, **kwargs):
        return {'year':2026,'minutes':5,'questions':[{'number':1,'kind':'single','knowledge':'抽样',
            'prompt':'样本是什么？','options':{'A':'全体','B':'一部分'},'points':2,
            'answer':['B'],'explanation':'样本是从总体中选出的一部分。'}]}

    monkeypatch.setattr(annual_drafts.tutor, 'structured_chat', extract_second)
    assert annual_drafts.tick()
    detail = call(student, second_path)
    call(student, second_path, 'PUT', {'revision':detail['revision'],'resource':{**detail['draft'],'rights_confirmed':True}})
    second_resource = call(student, second_path+'/confirm', 'POST', status=201)
    assert second_resource['edition'] != resource['edition']
    assert {row['id'] for row in call(student, base+'/exam-resources')['resources']} == {resource['id'], second_resource['id']}


def test_final_advances_from_native_diagnostic_to_retest(clients, monkeypatch):
    student, _, _ = clients
    p = create(student, 'final')
    base = '/learning-projects/' + p['id']
    ready_book(student, base)
    call(student, base+'/learning', 'POST', {'operation':'guided','action_id':'final_outline'}, 409)
    call(student, base+'/study-scope', 'PUT', {'revision':call(student, base)['revision'],'text':'抽样与总体'})
    native = {'state':'idle','messages':[],'question':None,'evidence':{'count':0}}
    commands = []

    def bridge(owner, **body):
        if body['operation'] != 'status':
            commands.append(body)
        return dict(native)

    monkeypatch.setattr(learning, 'bridge', bridge)

    def run(action):
        state = call(student, base+'/learning')
        assert action in {item['id'] for item in state['workflow']['actions']}
        call(student, base+'/learning', 'POST', {'operation':'guided','action_id':action}, 202)
        assert learning.tick()
        assert '抽样与总体' in commands[-1]['guidance']

    run('final_outline')
    native['curriculum'] = {'map':{'modules':[{'id':'sampling'}]},'reviews':[]}
    run('final_diagnose')
    call(student, base+'/learning', 'POST', {'operation':'guided','action_id':'final_weakness'}, 409)
    native['evidence'] = {'count':1,'result':'incorrect'}
    run('final_weakness')
    run('final_remediate')
    run('final_retest')
    native['evidence'] = {'count':2,'result':'correct'}
    run('final_checklist')
    assert len({entry['guidance'] for entry in commands}) == len(commands)


def test_daily_plan_resumes_and_finishes_without_extra_cards(clients, monkeypatch):
    student, _, _ = clients
    p = create(student)
    base = '/learning-projects/' + p['id'] + '/learning'
    ready_book(student, base.removesuffix('/learning'))
    state = {'state': 'idle', 'messages': [], 'question': None, 'recent_evidence': []}
    teaching = []

    def native(owner, **body):
        if body['operation'] == 'mode' and body.get('objective'):
            objective = body['objective']
            teaching.append(objective)
            state.update(state='question', request_id='q-' + objective, question_objective=objective,
                         explained=[objective], question={'question_id': 'q-' + objective})
        elif body['operation'] == 'answer':
            qid = body['expected_id']
            state['recent_evidence'].append({'id': qid, 'question_id': qid, 'objective_id': qid[2:], 'result': 'incorrect'})
            state.update(state='idle', question=None, request_id='')
        return dict(state)

    async def plan(*args, **kwargs):
        return {'items': [{'id': 'sample', 'minutes': 5}, {'id': 'population', 'minutes': 5}]}

    monkeypatch.setattr(learning, 'bridge', native)
    monkeypatch.setattr(learning.tutor, 'structured_chat', plan)
    call(student, base, 'POST', {'operation': 'guided', 'action_id': 'chapter_outline'}, 202)
    assert learning.tick()
    state['curriculum'] = {'map': {'modules': [{'id': 'sampling', 'name': '抽样', 'knowledge_points': [
        {'id': 'sample', 'name': '样本'}, {'id': 'population', 'name': '总体'},
    ]}]}, 'reviews': [{'due': True, 'knowledge_point_id': 'population'}]}
    assert call(student, base)['daily_plan']['state'] == 'planning'
    assert learning.tick()
    daily = call(student, base)['daily_plan']
    assert daily['state'] == 'ready' and daily['items'][0]['id'] == 'population'
    assert call(student, base)['daily_plan']['id'] == daily['id']
    call(student, base, 'POST', {'operation': 'guided', 'action_id': 'chapter_continue'}, 202)
    assert learning.tick()
    assert call(student, base)['request_id'] == 'q-population'
    call(student, base, 'POST', {'operation': 'message', 'text': '可以解释一下总体吗？'}, 202)
    assert learning.tick()
    after_question = call(student, base)
    assert after_question['request_id'] == 'q-population' and after_question['daily_plan']['completed'] == 0
    call(student, base, 'POST', {'operation': 'guided', 'action_id': 'chapter_summary'}, 202)
    paused = call(student, base)
    assert paused['daily_plan']['state'] == 'paused' and paused['request_id'] == 'q-population'

    async def practice(*args, **kwargs):
        return [{'kind': 'single', 'prompt': '什么是样本？', 'options': {'A': '总体的一部分', 'B': '所有对象'},
                 'answer': ['A'], 'explanation': '样本来自总体。', 'rubric': [],
                 'quote': '随机抽样需要明确总体与样本。'}]

    monkeypatch.setattr(learning.tutor, 'generate_questions', practice)
    call(student, base, 'POST', {'operation': 'guided', 'action_id': 'chapter_practice',
                                'chapter_id': 'sampling', 'counts': {'single': 1}}, 202)
    assert learning.tick()
    value = call(student, base)
    assert value['request_id'] == 'q-population'
    assessment = call(student, '/assessments/' + value['chapter_practice_id'])
    assert len(assessment['entries']) == 1 and 'answer' not in assessment['entries'][0]['question']
    call(student, base, 'POST', {'operation': 'guided', 'action_id': 'chapter_continue'}, 202)
    for objective in ('population', 'sample'):
        idem = uuid4().hex
        body = {'operation': 'answer', 'expected_id': 'q-' + objective, 'text': 'A'}
        first = call(student, base, 'POST', body, 202, idem)
        assert call(student, base, 'POST', body, 202, idem) == first
        assert learning.tick()
        result = call(student, base)
        if objective == 'population':
            assert result['daily_plan']['completed'] == 1
            assert not learning.tick()
            call(student, base, 'POST', {'operation': 'guided', 'action_id': 'chapter_continue'}, 202)
            assert learning.tick()
            assert call(student, base)['daily_plan']['last_question']
    assert result['daily_plan']['state'] == 'completed'
    assert result['daily_plan']['completed'] == 2
    assert result['question'] is None and teaching == ['population', 'sample']
    assert not learning.tick()


def test_final_stage_counts_only_its_assigned_cards(clients, monkeypatch):
    student, _, _ = clients
    project = create(student, 'final')
    base = '/learning-projects/' + project['id']
    ready_book(student, base)
    call(student, base + '/study-scope', 'PUT', {
        'revision': call(student, base)['revision'], 'text': '抽样与总体',
    })
    path = base + '/learning'
    state = {'state': 'idle', 'messages': [], 'question': None, 'recent_evidence': []}
    issued = []

    def bridge(owner, **body):
        if objective := body.get('objective'):
            issued.append(objective)
            state.update(state='question', request_id='check-' + objective, question_objective=objective,
                         question={'question_id': 'check-' + objective})
        elif body['operation'] == 'answer':
            qid = body['expected_id']
            state['recent_evidence'].append({'id': qid, 'question_id': qid,
                                             'objective_id': qid.removeprefix('check-'), 'result': 'correct'})
            state.update(state='idle', question=None, request_id='')
        return dict(state)

    monkeypatch.setattr(learning, 'bridge', bridge)
    call(student, path, 'POST', {'operation': 'guided', 'action_id': 'final_outline'}, 202)
    assert learning.tick()
    state['curriculum'] = {'map': {'modules': [{'id': 'sampling', 'name': '抽样', 'knowledge_points': [
        {'id': 'one', 'name': '总体'}, {'id': 'two', 'name': '随机抽样'}, {'id': 'three', 'name': '样本'},
        {'id': 'outside', 'name': '二次积分'},
    ]}]}, 'reviews': []}
    assert call(student, path)['stage_sizes']['final_diagnose'] == 3
    call(student, path, 'POST', {'operation': 'guided', 'action_id': 'final_diagnose'}, 202)
    for index, objective in enumerate(('one', 'two', 'three'), 1):
        assert learning.tick()
        value = call(student, path)
        assert value['request_id'] == 'check-' + objective
        assert value['stage']['last_question'] is (index == 3)
        call(student, path, 'POST', {'operation': 'answer', 'text': 'A', 'expected_id': value['request_id']}, 202)
        assert learning.tick()
        value = call(student, path)
        assert value['stage']['completed'] == index
        if index < 3:
            assert not learning.tick()
            assert value['workflow']['actions'][0]['label'] == '继续当前检查'
            call(student, path, 'POST', {'operation': 'message', 'text': '能再解释上一题吗？'}, 202)
            assert learning.tick()
            assert call(student, path)['stage']['completed'] == index
            assert not learning.tick()
            call(student, path, 'POST', {'operation': 'guided', 'action_id': 'final_diagnose'}, 202)
    assert value['stage']['state'] == 'completed'
    assert value['workflow']['actions'][0]['id'] == 'final_weakness'
    assert issued == ['one', 'two', 'three'] and not learning.tick()


def test_budget_stops_next_card_and_previous_task_carries_into_new_day(clients, monkeypatch):
    student, _, _ = clients
    p = create(student)
    base = '/learning-projects/' + p['id'] + '/learning'
    ready_book(student, base.removesuffix('/learning'))
    date = '2026-11-14'
    monkeypatch.setattr(learning.batches, 'day', lambda: date)
    state = {'state': 'idle', 'messages': [], 'question': None}
    monkeypatch.setattr(learning, 'bridge', lambda *args, **kwargs: dict(state))
    call(student, base, 'POST', {'operation': 'guided', 'action_id': 'chapter_outline'}, 202)
    assert learning.tick()
    state['curriculum'] = {'map': {'modules': [{'id': 'm', 'knowledge_points': [
        {'id': 'p', 'name': '样本', 'status': 'learning'},
    ]}]}}

    async def plan(*args, **kwargs):
        return {'items': [{'id': 'p', 'minutes': 5}]}

    monkeypatch.setattr(learning.tutor, 'structured_chat', plan)
    assert call(student, base)['daily_plan']['state'] == 'planning'
    assert learning.tick()
    with SessionLocal.begin() as db:
        batch = db.scalar(select(m.LearningBatch).where(m.LearningBatch.project_id == p['id']))
        batch.data = {**batch.data, 'state': 'active', 'seconds': 45 * 60}
    assert call(student, base)['daily_plan']['state'] == 'budget_reached'
    assert not learning.tick()
    date = '2026-11-15'
    assert call(student, base)['daily_plan']['state'] == 'planning'
    with SessionLocal() as db:
        queued = db.scalar(select(m.AIRun).where(m.AIRun.project_id == p['id'], m.AIRun.state == 'queued'))
        assert json.loads(queued.prompt)['priority'] == ['p']


def test_kaoyan_topic_ends_after_one_check(clients, monkeypatch):
    student, _, _ = clients
    project = create(student, 'kaoyan')
    base = '/learning-projects/' + project['id']
    ready_book(student, base)
    resource = call(student, base + '/exam-resources', 'POST', {
        'kind': 'syllabus', 'year': 2027, 'edition': 'v1', 'title': '统计考试范围',
        'source_title': '验收资料', 'rights_confirmed': True,
        'topics': [{'code': 'sample', 'chapter': '抽样', 'title': '总体与样本', 'text': '区分总体与样本。'}],
    }, 201)
    mark_indexed(student, resource['material_id'])
    path = base + '/learning'
    state = {'state': 'idle', 'messages': [], 'question': None, 'recent_evidence': []}
    issued = []

    def bridge(owner, **body):
        if objective := body.get('objective'):
            issued.append(objective)
            state.update(state='question', request_id='check', question_objective=objective,
                         question={'question_id': 'check'})
        elif body['operation'] == 'answer':
            state.update(state='idle', question=None, request_id='', recent_evidence=[
                {'id': 'grade', 'question_id': 'check', 'objective_id': issued[-1], 'result': 'incorrect'},
            ])
        return dict(state)

    monkeypatch.setattr(learning, 'bridge', bridge)
    call(student, path, 'POST', {'operation': 'guided', 'action_id': 'kaoyan_outline'}, 202)
    assert learning.tick()
    state['curriculum'] = {'map': {'modules': [{'id': 'm', 'knowledge_points': [
        {'id': 'sample', 'name': '样本'}, {'id': 'population', 'name': '总体'},
    ]}]}, 'next': {'knowledge_point_id': 'sample'}}
    assert call(student, path)['stage_sizes']['kaoyan_start'] == 1
    call(student, path, 'POST', {'operation': 'guided', 'action_id': 'kaoyan_start'}, 202)
    assert learning.tick()
    assert call(student, path)['stage']['last_question']
    call(student, path, 'POST', {'operation': 'message', 'text': '这个专题的概念怎么区分？'}, 202)
    assert learning.tick()
    assert call(student, path)['request_id'] == 'check'
    call(student, path, 'POST', {'operation': 'answer', 'text': 'A', 'expected_id': 'check'}, 202)
    assert learning.tick()
    result = call(student, path)
    assert result['stage']['state'] == 'completed'
    assert {'kaoyan_next', 'kaoyan_coverage'} <= {action['id'] for action in result['workflow']['actions']}
    assert issued == ['sample'] and not learning.tick()


def test_invalid_daily_plan_retry_generates_a_new_native_turn(clients, monkeypatch):
    student, _, _ = clients
    project = create(student)
    base = '/learning-projects/' + project['id']
    ready_book(student, base)
    path = base + '/learning'
    state = {'state': 'idle', 'messages': [], 'question': None}
    monkeypatch.setattr(learning, 'bridge', lambda *args, **kwargs: dict(state))
    call(student, path, 'POST', {'operation': 'guided', 'action_id': 'chapter_outline'}, 202)
    assert learning.tick()
    state['curriculum'] = {'map': {'modules': [{'id': 'm', 'knowledge_points': [{'id': 'p', 'name': '样本'}]}]}}
    submissions = []

    async def plan(owner, prompt, submission, on_event):
        submissions.append(submission)
        return {'items': [{'id': 'invalid' if len(submissions) == 1 else 'p', 'minutes': 5}]}

    monkeypatch.setattr(learning.tutor, 'structured_chat', plan)
    assert call(student, path)['daily_plan']['state'] == 'planning'
    assert learning.tick()
    assert call(student, path)['daily_plan']['state'] == 'failed'
    call(student, path + '/retry', 'POST')
    assert learning.tick()
    assert call(student, path)['daily_plan']['state'] == 'ready'
    assert len(set(submissions)) == 2

@pytest.mark.parametrize('scene', ['chapter', 'final', 'kaoyan'])
def test_project_due_review_starts_and_reports_only_review_attempts(clients, monkeypatch, scene):
    from app.v2 import personal_learning
    student, _, _ = clients
    project = create(student, scene)
    base = '/learning-projects/' + project['id']
    book = ready_book(student, base)
    if scene == 'final':
        revision = call(student, base)['revision']
        call(student, base+'/study-scope', 'PUT', {'revision':revision, 'material_ids':[book['id']]})
    if scene == 'kaoyan':
        syllabus = call(student, base+'/exam-resources', 'POST', {
            'kind':'syllabus', 'year':2027, 'edition':'v1', 'title':'统计考纲', 'source_title':'测试',
            'rights_confirmed':True, 'topics':[{'code':'sample','chapter':'抽样','title':'抽样',
                'text':'随机抽样需要区别总体与样本。'}]}, 201)
        mark_indexed(student, syllabus['material_id'])
    with SessionLocal.begin() as db:
        p = db.get(m.Project, project['id'])
        materials = list(db.scalars(select(m.Material).where(m.Material.project_id == p.id)))
        db.add(m.ProjectLearning(project_id=p.id, scope_revision=p.scope_revision, plan_revision=p.revision,
            path_id='topic_review_test', session_id='zx_learning_test', context={'source_ids':[x.id for x in materials]}))
        if scene == 'chapter':
            db.add(m.LearningBatch(project_id=p.id, scope_revision=p.scope_revision, key=learning.batches.day(),
                action='chapter_continue', data={'items':[{'id':'planned','name':'样本','review':True}], 'state':'ready'}))
    state = {'state':'idle', 'messages':[], 'question':None, 'curriculum':{
        'map':{'modules':[{'id':'sampling','knowledge_points':[{'id':key,'name':name} for key,name in
            [('chosen','总体'),('planned','样本'),('future','估计')]]}]},
        'reviews':[{'due':due,'knowledge_point_id':key} for key,due in [('chosen',True),('planned',True),('future',False)]]}}

    def bridge(owner, **body):
        if body['operation'] == 'mode':
            assert body['mode'] == 'review' and body['objective'] == 'chosen'
            state.update(state='question',mode='review',request_id='review-card',question={'question_id':'review-card'})
        elif body['operation'] == 'answer':
            assert body['expected_id'] == 'review-card'
            state.update(state='idle',question=None,turn_id='review-answer',request_id='')
            state['curriculum']['reviews'].pop(0)
        return dict(state)

    monkeypatch.setattr(learning, 'bridge', bridge)
    path = base+'/learning'
    due = call(student, path)['due_reviews']
    assert [item['id'] for item in due] == ['chosen','planned']
    assert due[1]['in_daily_plan'] is (scene == 'chapter')
    def start(objective, status):
        return call(student,path,'POST',{'operation':'guided','action_id':'due_review','review_objective':objective},status)
    start('future',409)
    if scene == 'chapter':
        start('planned',409)
    start('chosen',202)
    assert learning.tick()
    assert call(student,path)['request_id'] == 'review-card'
    start('planned',409)
    call(student,path,'POST',{'operation':'answer','expected_id':'review-card','text':'A'},202)
    assert learning.tick()
    assert [item['id'] for item in call(student,path)['due_reviews']] == ['planned']
    snapshot = {'question':'什么是总体？','options':{'A':'全体'},'question_type':'single_choice',
                'correct_answer':'A','user_answer':'A','is_correct':True,
                'category':'guided','assessment_type':'review','mastery_path_id':'topic_review_test'}
    monkeypatch.setattr(personal_learning,'native_history',lambda *_:[
        {**snapshot,'id':'check:1','time':1700000000,'question_id':'review-card','turn_id':'review-answer'},
        {**snapshot,'id':'check:2','time':1700000001,'question_id':'other','turn_id':'other'},
        {**snapshot,'id':'check:3','time':1700000002,'question_id':'old','review_session':True}])
    assert [x['id'] for x in call(student,base+'/attempt-history?source=review')['items']] == ['check:3','check:1']
    assert [x['id'] for x in call(student,base+'/attempt-history?source=guided')['items']] == ['check:2']
    call(student, base+'/archive', 'POST')
    start('planned',409)
    assert len(call(student,base+'/attempt-history?source=review')['items']) == 2
