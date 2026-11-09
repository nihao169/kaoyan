"""Native learning boundaries; all storage is the isolated fixture database."""
import json
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.db import SessionLocal
from app.v2 import models as m, project_learning as learning
from test_v2 import call


def create(student, scene='chapter'):
    return call(student, '/learning-projects', 'POST', {'title':'统计学项目', 'course_name':'统计学',
        'learning_goal':'理解抽样和估计', 'scenario':scene, **({'exam_year':2027} if scene=='kaoyan' else {})}, 201)


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


def test_intake_and_idempotent_native_delivery(clients, monkeypatch):
    student, _, _ = clients
    p=create(student)
    base='/learning-projects/'+p['id']
    sent=[]
    def native(owner, **body):
        sent.append((owner, body))
        return {'state':'running', 'messages':[], 'question':None}
    monkeypatch.setattr(learning, 'bridge', native)
    idem=str(uuid4())
    first=call(student, base+'/learning', 'POST', {'text':'我的数学基础比较薄弱'}, 202, idem)
    assert first==call(student, base+'/learning', 'POST', {'text':'我的数学基础比较薄弱'}, 202, idem)
    assert call(student, base+'/learning', 'POST', {'text':'不同请求'}, 409, idem)['code']=='IDEMPOTENCY_CONFLICT'
    assert learning.tick()
    assert len(sent)==1 and not sent[0][1]['ready'] and not sent[0][1]['sources']
    assert '学生第一次学习' in sent[0][1]['background']
    command_id=sent[0][1]['submission_id']
    with SessionLocal.begin() as db:
        run=db.get(m.AIRun, first['run_id']);run.state='failed'
    call(student, base+'/learning/retry', 'POST')
    assert learning.tick() and sent[-1][1]['submission_id']==command_id
    assert call(student, base+'/learning', 'POST', {'operation':'mode','mode':'study'}, 409)['code']=='MATERIAL_REQUIRED'


def test_scope_change_rejects_queued_command_and_keeps_history(clients, monkeypatch):
    student, teacher, _ = clients
    p=create(student);base='/learning-projects/'+p['id']
    first=call(student, base+'/learning', 'POST', {'text':'先聊目标'}, 202)
    call(student, base+'/materials', 'POST', {'title':'抽样', 'text':'随机抽样需要明确总体与样本。'}, 201)
    monkeypatch.setattr(learning, 'bridge', lambda *a, **k:pytest.fail('stale command must not reach tutor'))
    assert learning.tick()
    with SessionLocal() as db:
        run=db.get(m.AIRun, first['run_id'])
        assert run.state=='failed' and 'SCOPE_CHANGED' in run.error
        assert db.scalar(select(m.ProjectLearning).where(m.ProjectLearning.project_id==p['id']))
    assert call(student, base+'/learning')['state']=='not_started'
    call(teacher, base+'/learning', status=404)


def test_legacy_confirmation_preserves_evidence_and_reuses_path_on_goal_edit(clients, monkeypatch):
    student, _, _ = clients
    p=call(student,'/learning-projects','POST',{'title':'旧项目','exam_year':2027},201)
    base='/learning-projects/'+p['id']
    assert call(student,base+'/learning')['state']=='profile_required'
    p=call(student,base+'/learning-profile','PUT',{'revision':p['revision'],'scenario':'final','course_name':'统计学'})
    monkeypatch.setattr(learning,'bridge',lambda *a,**k:{'state':'idle','messages':[],'question':None})
    call(student,base+'/learning','POST',{'text':'请先了解我的目标'},202);assert learning.tick()
    p=call(student,base)
    call(student,base+'/learning-profile','PUT',{'revision':p['revision'],'scenario':'chapter','course_name':'统计学','learning_goal':'补充基础'})
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
