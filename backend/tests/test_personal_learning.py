from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models as classroom
from app.db import SessionLocal
from app.main import app
from app.v2 import maintenance, models as m, personal_learning as personal, project_learning, service
from test_project_learning import create, mark_indexed, ready_book
from test_v2 import call


QUOTE = '随机抽样需要明确总体与样本。'


@pytest.mark.parametrize('scene', ['chapter', 'final', 'kaoyan'])
def test_generate_private_practice_and_review(clients, monkeypatch, scene):
    student, teacher, _ = clients
    project = create(student, scene)
    base = '/learning-projects/' + project['id']
    if scene == 'final':
        book = call(student, base+'/materials', 'POST', {'title':'抽样', 'text':
            f'# 抽样与总体\n{QUOTE}\n# 排除章节\n这是不能用于期末出题的材料。'}, 201)
        mark_indexed(student, book['id'])
        revision = call(student, base)['revision']
        call(student, base+'/study-scope', 'PUT', {'revision':revision,
            'sections':[{'material_id':book['id'], 'title':'抽样与总体'}]})
    else:
        book = ready_book(student, base)
    if scene == 'kaoyan':
        syllabus = call(student, base+'/exam-resources', 'POST', {
            'kind':'syllabus','year':2027,'edition':'v1','title':'统计考纲','source_title':'测试资料',
            'rights_confirmed':True,'topics':[{'code':'sample','chapter':'抽样','title':'抽样与总体',
                'text':'随机抽样需要区别总体与样本。'}]}, 201)
        mark_indexed(student, syllabus['material_id'])
    config = base+'/concentrated-practice'
    assert call(student, config)['ready']
    assert call(teacher, config, status=403)['code'] == 'ROLE_REQUIRED'
    call(student, config, 'POST', {'single':10,'multiple':1}, 422)
    call(student, config, 'POST', {'single':1,'scope_id':'not-in-project'}, 422)
    options = call(student, config)['options']
    assert scene == 'chapter' or options
    calls = []

    async def generate(owner, prompt, counts, token, callback):
        calls.append(token)
        assert QUOTE in prompt
        assert '不能用于期末出题' not in prompt
        return [
            {'kind':kind,'prompt':'抽样题 '+kind,'options':{} if kind=='essay' else {'A':'总体','B':'样本','C':'调查'},
             'answer':[] if kind=='essay' else ['A','B'] if kind=='multiple' else ['A'],
             'explanation':'区分总体、样本和抽样过程。','quote':QUOTE,
             'rubric':['解释总体与样本'] if kind=='essay' else [],'reference_answer':'先说明总体范围' if kind=='essay' else ''}
            for kind,count in counts.items() for _ in range(count)
        ]

    monkeypatch.setattr(personal.tutor, 'generate_questions', generate)
    body = {'single':1,'multiple':1,'essay':1, **({'scope_id':options[0]['id']} if options else {})}
    idem = uuid4().hex
    job = call(student, config, 'POST', body, 202, idem)
    assert call(student, config, 'POST', body, 202, idem) == job
    assert project_learning.tick()
    status = call(student, base+'/personal-runs/'+job['run_id'])
    assert status['state'] == 'succeeded', status
    assert len(calls) == 1
    path = '/assessments/'+status['result']['assessment_id']
    exam = call(student, path)
    assert exam['deadline_at'] is None
    assert all('answer' not in x['question'] for x in exam['entries'])
    assert not call(student, base+'/attempt-history')['items']
    task_ids = {x['question']['kind']:x['task_id'] for x in exam['entries']}
    answers = {task_ids['single']:{'answer':['B']}, task_ids['essay']:{'response_text':'错误示例'}}
    call(student, path+'/draft', 'PUT', {'revision':exam['revision'], 'answers':answers})
    now = service.clock()
    monkeypatch.setattr(service, 'clock', lambda:now+timedelta(days=3))
    assert maintenance.tick() == 0
    assert call(student, path)['drafts'][task_ids['single']]['answer'] == ['B']
    call(student, path+'/submit', 'POST', {'answers':{}})
    history = base+'/attempt-history'
    assert {x['state'] for x in call(student, history)['items']} == {'incorrect','unanswered','pending'}
    call(teacher, history, status=403)
    with SessionLocal.begin() as db:
        essay = db.scalar(select(m.Attempt).where(m.Attempt.task_id == task_ids['essay']))
        run = db.get(m.AIRun, essay.result['run_id'])
        run.state = 'failed'
    assert 'evaluation_failed' in {x['state'] for x in call(student, history)['items']}
    assert len(call(student, history+'?mistakes=true')['items']) == 1
    with SessionLocal.begin() as db:
        essay = db.scalar(select(m.Attempt).where(m.Attempt.task_id == task_ids['essay']))
        essay.result = {'correct':False,'evaluator':'ai_training','feedback':'缺少总体范围'}
    mistakes = call(student, history+'?mistakes=true')['items']
    assert len(mistakes) == 2 and all(x['source']=='concentrated' for x in mistakes)

    async def diagnose_model(owner, prompt, token, callback):
        assert '随机抽样' in prompt
        if not token.endswith('-1'):
            raise personal.tutor.TutorError('模拟诊断暂不可用')
        return {'diagnosis':'复习总体与样本的区别。'}

    monkeypatch.setattr(personal.tutor, 'structured_chat', diagnose_model)
    attempt = next(x for x in mistakes if x['kind']=='single')
    reply = call(student, base+'/attempt-diagnoses', 'POST', {'attempt_id':attempt['id']},202)
    run_path = base+'/personal-runs/'+reply['run_id']
    assert project_learning.tick()
    assert call(student, run_path)['state'] == 'failed'
    call(student, run_path+'/retry', 'POST', status=202)
    assert project_learning.tick()
    assert call(student, run_path)['result']['diagnosis']
    with TestClient(app) as other:
        username = 'private_' + uuid4().hex[:12]
        call(other, '/auth/register', 'POST', {'username':username,'name':'另一位学生','password':'Personal2026!'},201)
        assert other.post('/api/v1/auth/login', json={'username':username,'password':'Personal2026!'}).is_success
        call(other, history, status=404)
        call(other, run_path, status=404)
        call(other, path, status=404)
    with SessionLocal() as db:
        assert not db.scalars(select(classroom.Attempt)).all()
        question_id = exam['entries'][0]['question']['id']
    mock = call(student, '/assessments', 'POST', {'project_id':project['id'],'title':'限时模考',
        'mode':'mock','minutes':5,'question_ids':[question_id]},201)
    call(student, history, status=403)
    call(student, run_path, status=403)
    call(student, path, status=403)
    call(student, '/assessments/'+mock['id']+'/submit','POST',{'answers':{}})
    call(student, base+'/materials/'+book['id'], 'DELETE')
    assert not call(student, history+'?mistakes=true')['items']
    call(student, run_path, status=409)


def test_report_keeps_distinct_native_attempts_and_degrades(clients, monkeypatch):
    student, _, _ = clients
    p = create(student)
    base = '/learning-projects/'+p['id']
    book = ready_book(student, base)
    with SessionLocal.begin() as db:
        project = db.get(m.Project,p['id'])
        db.add(m.ProjectLearning(project_id=p['id'],scope_revision=project.scope_revision,
            plan_revision=project.revision, path_id='topic_test',session_id='test',
            context={'source_ids':[book['id']]}))
    snapshot = {'question':'总体与样本？','question_type':'single_choice','options':{'A':'正确','B':'错误'},
        'correct_answer':'A','mastery_path_id':'topic_test','category':'guided'}
    monkeypatch.setattr(personal,'native_history',lambda *_:[
        {**snapshot,'id':'check:1','time':1700000000,'user_answer':'B','is_correct':False},
        {**snapshot,'id':'check:2','time':1700000001,'user_answer':'A','is_correct':True}])
    history = base+'/attempt-history'
    assert [x['answer'] for x in call(student, history+'?source=guided')['items']] == ['A','B']
    assert [x['id'] for x in call(student, history+'?mistakes=true')['items']] == ['check:1']

    def missing(*args):
        raise personal.HistoryUnavailable

    monkeypatch.setattr(personal,'native_history',missing)
    assert call(student, history)['partial'] is True

def test_generation_rejects_invalid_output_and_stale_scope(clients, monkeypatch):
    student, _, _ = clients
    p = create(student)
    base = '/learning-projects/'+p['id']
    ready_book(student, base)
    endpoint = base+'/concentrated-practice'
    result = []

    async def generated(*args):
        return result

    monkeypatch.setattr(personal.tutor, 'generate_questions', generated)
    first = call(student, endpoint, 'POST', {'single':1}, 202)
    assert project_learning.tick()
    url = base+'/personal-runs/'+first['run_id']
    assert call(student, url)['state'] == 'failed'
    assert not call(student, '/assessments')

    result.append({'kind':'single','prompt':'统计题','options':{'A':'甲','B':'乙'},'answer':['A'],
                   'explanation':'原文不支持这道题。','quote':'这条引文不存在于授权资料。','rubric':[]})
    call(student, url+'/retry', 'POST', status=202)
    assert project_learning.tick()
    assert call(student, url)['state'] == 'failed'
    assert not call(student, '/assessments')

    stale = call(student, endpoint, 'POST', {'single':1}, 202)
    call(student, base+'/materials', 'POST', {'title':'另一份讲义','text':'分层抽样先把总体按特征划分为层。'}, 201)
    assert project_learning.tick()
    call(student, base+'/personal-runs/'+stale['run_id'], status=409)
    assert not call(student, '/assessments')
