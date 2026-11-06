"""The new lifecycle uses controlled provider responses here; live acceptance is separate."""
import json
import pytest
from sqlalchemy import select, func
from app import models as m
from app.db import SessionLocal
from app.config import settings
from app.worker import tick
from app.workflow_schemas import GenerationSettings
from conftest import checked


def drain():
    for _ in range(100):
        if not tick():
            return
    raise AssertionError('job queue did not drain')


@pytest.fixture
def provider(monkeypatch):
    state={'count':0,'bad':False,'calls':0,'withdraw':None}
    monkeypatch.setattr(settings,'model_api_key','explicit-controlled-test-key')
    monkeypatch.setattr(settings,'model_name','controlled-teaching-provider')

    def complete(messages,metrics,max_tokens=4096):
        state['calls']+=1
        metrics['calls']=metrics.get('calls',0)+1
        metrics['total_tokens']=metrics.get('total_tokens',0)+50
        data=json.loads(messages[-1]['content'])
        if 'artifact' in data:
            if state['withdraw']:
                with SessionLocal.begin() as db:
                    db.get(m.SourceVersion,state['withdraw']).status='withdrawn'
                state['withdraw']=None
            return {'accepted':True,'conflict':False,'issues':[]}
        evidence=data['evidence'][0]
        cite={'chunk_id':evidence['chunk_id'],'quote':evidence['text'][:60]}
        if 'expected_kinds' in data:
            questions=[]
            settings_=data['expected_kinds']
            scenarios=['社区走访改变服务安排','粮食试验修订种植方案','交通调查完善路口管理','课堂观察改进教学节奏','企业访谈调整培训内容','体育测试调整训练强度','医院随访改进预约流程','工厂试运行修订操作方案','图书馆访谈改变开放时段','居民实测检验节能措施','研究者实地调研修正假设','志愿者观察重新安排活动','团队检验比较实际效果','小组采样核对认识依据','农户实验检查技术条件','车间观察排查生产故障']
            for kind in settings_:
                state['count']+=1
                scenario=scenarios[state['count']%len(scenarios)]
                q={'kind':kind,'knowledge_name':data['topics'][0],'prompt':f'原创情境：{scenario}。这一行为与实践推动认识发展的联系是什么？',
                    'options':{'A':f'{scenario}无需关注客观条件','B':f'{scenario}需要通过实践检验和修正认识','C':f'{scenario}只需凭个人猜测','D':f'{scenario}可以不看实际反馈'},
                    'answer':['B'] if kind=='single' else ['A','B'],'explanation':'实践提供认识的来源并检验认识，应结合实际条件分析。',
                    'hints':['先回忆实践与认识的关系','关注检验和反馈','结合材料中的变化分析','实践推动认识的发展，注意适用条件'],
                    'rubric':[],'max_score':2 if kind=='single' else 4,'option_analysis':{k:'结合原文中的实践与认识关系辨析此项。' for k in 'ABCD'},'evidence':[cite]}
                if kind=='essay':
                    q.update(options={},answer=[],option_analysis={},max_score=10,rubric=[{'label':'原理阐述','score':4},{'label':'联系材料','score':6}])
                elif kind=='multiple':
                    q['options']['A']=f'{scenario}需要核对实践条件'
                if state['bad']:
                    q['evidence']=[{'chunk_id':'invented','quote':'并不存在的原文引用'}]
                questions.append(q)
            return {'questions':questions}
        if 'original' not in data:
            return {'topics':[{'name':'实践与认识','section':'原文核心知识','card':'实践为认识提供来源，认识需要通过实践检验和修正。','evidence':[cite]}],'coverage':'本批只覆盖提供原文中的实践与认识关系。'}
        if 'parts' in messages[0]['content']:
            return {'parts':[2,3],'feedback':'原理有所涉及，但结合具体材料的论证尚不充分，建议补充。','evidence':[cite]}
        return {'explanation':'你选中的干扰项忽略了实践检验。过程证据有限，尚不能确定心理错因。',
            'candidate_cause':'可能混淆了认识与实践检验','option_analysis':{k:'本项应结合实践检验的原文条件分析。' for k in 'ABCD'},
            'knowledge_gaps':['实践检验认识的条件'],'learning_advice':['先阅读相关原文，区分经验与检验标准。'],
            'clarifying_questions':['你当时为什么选择这一项？'],'evidence':[cite]}

    monkeypatch.setattr('app.ai_services.completion',complete)
    return state


def material(teacher,config=None):
    created=checked(teacher,'/content/sources','POST',{'title':'教师新上传测试资料','text':'# 实践与认识\n\n实践是认识的来源，实践检验认识的真理性。分析认识的发展时，应联系具体的实践过程、条件和反馈。','rights':'原创验收资料'},status=202)
    drain()
    run=checked(teacher,f'/content/sources/{created["id"]}/enable','POST',config or {'single':1,'multiple':1,'essay':1},status=202)
    drain()
    run=checked(teacher,'/agent-runs/'+run['id'])
    return created['id'],run


def assign(teacher,question_ids):
    cls=checked(teacher,'/classes')[0]['id']
    return checked(teacher,'/teacher/assignments','POST',{'title':'原文生成班级作业','class_id':cls,'question_ids':question_ids},status=201)


def fill(student,group):
    for entry in group['entries']:
        a=entry['attempt']
        q=a['question']
        checked(student,'/attempts/'+a['id']+'/draft','PATCH',{'answer':[] if q['kind']=='essay' else ['C'],
            'response_text':'实践需要联系具体情况检验认识。' if q['kind']=='essay' else '',
            'process':'我对选项的适用条件尚未区分清楚。','duration_seconds':35,'revision':a['revision']})


def test_default_generation_and_settings():
    assert GenerationSettings().model_dump()['single']==6
    with pytest.raises(ValueError):
        GenerationSettings(single=30,multiple=1,essay=0)


def test_native_teacher_can_queue_generation_without_legacy_index(clients, monkeypatch):
    _, teacher, admin = clients
    for flag in ('deeptutor_native_knowledge', 'deeptutor_native_teacher_questions', 'deeptutor_structured_teacher'):
        monkeypatch.setattr(settings, flag, True)
    monkeypatch.setattr(settings, 'deeptutor_url', 'http://native.invalid')
    monkeypatch.setattr(settings, 'deeptutor_bridge_secret', 'x'*40)
    source = checked(teacher, '/content/sources', 'POST', {'title':'原生出题资料',
        'text':'实践是认识的来源，认识必须接受实践检验。', 'rights':'测试资料'}, status=202)
    drain()
    index = checked(teacher, f'/content/indexes/{source["id"]}')
    assert index['state'] == 'ready' and index['backend'] == 'deeptutor'
    with SessionLocal() as db:
        assert not db.scalar(select(m.Job.id).where(m.Job.kind == 'index', m.Job.resource_id == source['id']))
    run = checked(teacher, f'/content/sources/{source["id"]}/enable', 'POST', {'single':1,'multiple':0,'essay':0}, status=202)
    assert run['model'] == 'deeptutor:deep-question'
    with SessionLocal() as db:
        assert db.get(m.AgentRun, run['id']).input['_native_retrieval'] is True
    def native_ping(model, principal, request_id, prompt, metrics):
        assert model == 'deeptutor:structured-chat' and principal.startswith('v1:health:')
        return {'ok': True}

    monkeypatch.setattr('app.routes_extensions.advisory_completion', native_ping)
    assert checked(admin, '/ai/status')['provider'] == 'DeepTutor'
    assert checked(admin, '/ai/connection-test', 'POST')['connected'] is True


@pytest.mark.parametrize('acknowledged', [True, False])
def test_native_teacher_retries_original_turn_only(clients, monkeypatch, acknowledged):
    _, teacher, _ = clients
    monkeypatch.setattr(settings, 'deeptutor_native_teacher_questions', True)
    monkeypatch.setattr(settings, 'deeptutor_url', 'http://native.invalid')
    monkeypatch.setattr(settings, 'deeptutor_bridge_secret', 'x'*40)
    submissions = []

    async def chat(principal, prompt, submission, record, *, resume_turn_id=None):
        submissions.append((submission, resume_turn_id))
        if len(submissions) == 1:
            if acknowledged:
                record({'type':'turn_started', 'turn_id':'native-extract'})
            raise TimeoutError()
        if resume_turn_id == 'native-extract':
            evidence = json.loads(prompt.rsplit('\n', 1)[-1])['evidence'][0]
            record({'type':'done', 'turn_id':resume_turn_id,
                    'metadata':{'usage_summary':{'total_calls':1}}})
            return {'topics':[{'name':'实践与认识','section':'讲义','card':'实践是认识的来源，也是检验认识的标准。',
                               'evidence':[{'chunk_id':evidence['chunk_id'],'quote':'实践是认识的来源'}]}],
                    'coverage':'覆盖实践与认识的关系'}
        raise TimeoutError()  # Stop at the next distinct step.

    monkeypatch.setattr('app.v2.tutor.structured_chat', chat)
    _, failed = material(teacher, {'single':1,'multiple':0,'essay':0})
    assert failed['error_code'] == 'DEEPTUTOR_TIMEOUT'
    assert '_native_turns' not in failed['metrics']
    retried = checked(teacher, '/agent-runs/'+failed['id']+'/retry', 'POST', {},
                      status=202 if acknowledged else 409)
    drain()
    if acknowledged:
        assert submissions[1] == (submissions[0][0], 'native-extract')
        assert len(submissions) == 3 and submissions[2][0].endswith(':verify')
        assert checked(teacher, '/agent-runs/'+failed['id'])['metrics']['total_calls'] == 1
    else:
        assert retried['code'] == 'EXECUTION_UNCERTAIN'
        assert len(submissions) == 1
    assert checked(teacher, '/teaching/questions') == []


def test_native_teacher_retries_only_terminal_chat_step(clients, monkeypatch):
    _, teacher, _ = clients
    monkeypatch.setattr(settings, 'deeptutor_native_teacher_questions', True)
    monkeypatch.setattr(settings, 'deeptutor_url', 'http://native.invalid')
    monkeypatch.setattr(settings, 'deeptutor_bridge_secret', 'x'*40)
    from app.v2.tutor import TutorError
    calls = []

    async def chat(principal, prompt, submission, record):
        calls.append(submission)
        record({'type':'turn_started', 'turn_id':f'turn-{len(calls)}'})
        raise TutorError('DEEPTUTOR_PROVIDER_TRANSPORT')

    monkeypatch.setattr('app.v2.tutor.structured_chat', chat)
    _, failed = material(teacher, {'single':1,'multiple':0,'essay':0})
    assert failed['error_code'] == 'DEEPTUTOR_PROVIDER_TRANSPORT'
    assert len(calls) == 2 and calls[1] == calls[0] + ':transport-retry'
    assert checked(teacher, '/teaching/questions') == []


def test_teacher_agent_assignment_manual_diagnosis_and_private_practice(clients,provider):
    student,teacher,admin=clients
    vid,generated=material(teacher)
    assert generated['state']=='succeeded',generated
    assert len(generated['output']['question_ids'])==3
    assert generated['metrics']['calls']>=4
    # Repeated enable does not produce another task, even with a new HTTP idempotency key.
    again=checked(teacher,f'/content/sources/{vid}/enable','POST',{'single':1,'multiple':1,'essay':1},status=202)
    assert again['id']==generated['id']
    assert checked(teacher,f'/content/sources/{vid}/enable','POST',{'single':2,'multiple':1,'essay':1},status=202)['id']==generated['id']
    bank=checked(teacher,'/teaching/questions')
    assert len(bank)==3 and all(q['sources'] for q in bank)
    assignment=assign(teacher,[q['id'] for q in bank])
    start_url = '/assignments/'+assignment['id']+'/start'
    if settings.database_url.startswith('postgresql'):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        start_gate = Barrier(2)

        def start_group():
            start_gate.wait(timeout=5)
            return checked(student, start_url, 'POST')

        with ThreadPoolExecutor(max_workers=2) as pool:
            requests = [pool.submit(start_group) for _ in range(2)]
            group, duplicate = [request.result(timeout=15) for request in requests]
        assert group == duplicate
    else:
        group = checked(student, start_url, 'POST')
    assert group['state']=='draft'
    assert all(e['attempt']['question'].get('answer') is None for e in group['entries'])
    incomplete=checked(student,'/assignments/'+assignment['id']+'/submit','POST',status=422)
    assert incomplete['code']=='INCOMPLETE_ASSIGNMENT'
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(m.Evaluation))==0
    fill(student,group)
    first=group['entries'][0]['attempt']
    assert checked(student,'/attempts/'+first['id']+'/submit','POST',status=409)['code']=='GROUP_SUBMISSION_REQUIRED'
    submitted=checked(student,'/assignments/'+assignment['id']+'/submit','POST')
    assert submitted['state']=='submitted'
    repeated=checked(student,'/assignments/'+assignment['id']+'/submit','POST')
    assert repeated['state']=='submitted'
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(m.Evaluation))==2
        assert db.scalar(select(func.count()).select_from(m.AgentRun).where(m.AgentRun.purpose=='diagnosis'))==0
        assert db.scalar(select(func.count()).select_from(m.AgentRun).where(m.AgentRun.purpose=='targeted'))==0
    drain()
    essay=next(e['attempt'] for e in submitted['entries'] if e['attempt']['question']['kind']=='essay')
    preliminary=checked(student,'/attempts/'+essay['id'])
    assert preliminary['evaluation'] is None
    assert preliminary['grading_state']=='AI初评待教师确认'
    assert preliminary['ai_suggestion']['score']==5
    teacher_detail=checked(teacher,'/teacher/attempts/'+essay['id'])
    assert teacher_detail['ai_suggestion']['score']==5
    confirmed=checked(teacher,'/teacher/attempts/'+essay['id']+'/confirm-ai-evaluation','POST',{})
    assert confirmed['score']==5 and confirmed['method']=='teacher'
    assert checked(student,'/attempts/'+essay['id'])['grading_state']=='教师已确认'
    mistakes=checked(student,'/mistake-diagnoses')
    wrong=next(r for r in mistakes if r['kind']=='multiple')
    assert wrong['selected']==['C'] and wrong['wrong_options']==['C'] and set(wrong['missing_options'])=={'A','B'}
    assert wrong['sources'] and wrong['cards'] and wrong['group_url'].endswith(assignment['id'])
    assert wrong['diagnosis'] is None
    checked(student,'/remediations/'+wrong['id']+'/practice-generations','POST',status=404)
    diagnosis=checked(student,'/remediations/'+wrong['id']+'/diagnose','POST',status=202)
    drain()
    analyzed=checked(student,'/agent-runs/'+diagnosis['id'])
    assert analyzed['state']=='succeeded' and analyzed['output']['learning_advice']
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(m.TargetedPractice))==0
    targeted=checked(student,'/remediations/'+wrong['id']+'/practice-generations','POST',status=202)
    assert checked(student,'/remediations/'+wrong['id']+'/practice-generations','POST',status=202)['id']==targeted['id']
    drain()
    personal=checked(student,'/agent-runs/'+targeted['id'])
    assert personal['state']=='succeeded',personal
    assert len(personal['output']['question_ids'])==3
    assert 'questions' not in personal['output']  # Progress must not leak exercise answers.
    practice_id=personal['output']['practice_id']
    practice=checked(student,'/practice-groups/'+practice_id+'/open','POST')
    for entry in practice['entries']:
        a=entry['attempt']
        assert a['question'].get('answer') is None
        checked(student,'/attempts/'+a['id']+'/draft','PATCH',{'answer':['A','B'],
            'response_text':'','process':'核对实践条件和检验作用后作答。','duration_seconds':45,'revision':a['revision']})
    finished=checked(student,'/practice-groups/'+practice_id+'/submit','POST')
    assert all(e['attempt']['evaluation']['score']==4 for e in finished['entries'])
    assert checked(student,'/practice-groups/'+practice_id+'/submit','POST')['state']=='submitted'
    updated=next(r for r in checked(student,'/mistake-diagnoses') if r['id']==wrong['id'])
    assert updated['resolved'] and updated['practice_results'][0]['independent_correct']==3
    chain=checked(teacher,'/teacher/attempts/'+wrong['attempt_id']+'/learning-chain')
    assert len(chain['practices'][0]['attempts'])==3 and len(chain['reviews'])==3
    # Public bank and source management must never expose student-private generated questions.
    assert len(checked(teacher,'/teaching/questions'))==3
    assert len(checked(teacher,'/sources/versions/'+vid)['questions'])==3
    cls=checked(admin,'/classes')[0]['id']
    checked(admin,'/admin/users','POST',{'name':'另一学生','username':'student_two','password':'Example2026!','roles':['student'],'class_id':cls})
    from conftest import login_client
    other=login_client('student')  # Start with a distinct HTTP session, then replace it below.
    other.post('/api/v1/auth/logout',headers={'X-CSRF-Token':checked(other,'/me')['csrf_token']})
    response=other.post('/api/v1/auth/login',json={'username':'student_two','password':'Example2026!'})
    assert response.status_code==200
    other.headers.update({'X-CSRF-Token':checked(other,'/me')['csrf_token']})
    checked(other,'/agent-runs/'+targeted['id'],status=404)
    checked(other,'/practice-groups/'+personal['output']['practice_id']+'/open','POST',status=404)
    checked(other,'/attempts/'+wrong['attempt_id'],status=404)
    other.close()


def test_invalid_agent_output_is_not_published_and_can_be_retried(clients,provider):
    _,teacher,_=clients
    provider['bad']=True
    vid,failed=material(teacher,{'single':1,'multiple':0,'essay':0})
    assert failed['state']=='failed' and failed['error_code']=='GENERATION_VALIDATION_FAILED'
    assert checked(teacher,'/teaching/questions')==[]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(m.GeneratedQuestion))==0
    provider['bad']=False
    checked(teacher,'/agent-runs/'+failed['id']+'/retry','POST',{},status=202)
    drain()
    assert checked(teacher,'/agent-runs/'+failed['id'])['state']=='succeeded'


def test_source_revoke_during_model_call_stops_delivery(clients,provider):
    _,teacher,_=clients
    source=checked(teacher,'/content/sources','POST',{'title':'调用期间撤回','text':'实践是认识的来源，也是检验认识真理性的标准，需核对具体条件。','rights':'原创'},status=202)
    drain()
    run=checked(teacher,'/content/sources/'+source['id']+'/enable','POST',{'single':1,'multiple':0,'essay':0},status=202)
    provider['withdraw']=source['id']
    drain()
    assert checked(teacher,'/agent-runs/'+run['id'])['error_code']=='CONTENT_UNAVAILABLE'
    assert checked(teacher,'/teaching/questions')==[]


def test_default_twelve_questions_and_assignment_version_snapshot(clients,provider):
    student,teacher,_=clients
    _,run=material(teacher,GenerationSettings().model_dump())
    assert run['state']=='succeeded',run
    bank=checked(teacher,'/teaching/questions')
    assert {k:sum(q['kind']==k for q in bank) for k in ('single','multiple','essay')}=={'single':6,'multiple':4,'essay':2}
    original=next(q for q in bank if q['kind']=='single')
    assignment=assign(teacher,[original['id']])
    revised={k:original[k] for k in ('source_version_id','kind','prompt','options','answer','explanation','hints','rubric','max_score')}
    revised['prompt']='教师修订后的另一情境：调查反馈为什么能够推动认识的发展？'
    checked(teacher,'/teaching/questions/'+original['id'],'PUT',revised)
    group=checked(student,'/assignments/'+assignment['id']+'/start','POST')
    assert group['entries'][0]['attempt']['question']['id']==original['id']
    assert group['entries'][0]['attempt']['question']['prompt']==original['prompt']


def test_native_teacher_bank_respects_organization_and_role(clients, provider, monkeypatch):
    from app.auth import passwords
    from app.v2 import tutor
    from conftest import login_client

    student, teacher, _ = clients
    _, run = material(teacher, {'single': 1, 'multiple': 0, 'essay': 0})
    assert run['state'] == 'succeeded'
    with SessionLocal.begin() as db:
        original_user = db.scalar(select(m.User).where(m.User.username == 'teacher'))
        original_org = db.scalar(select(m.Membership).where(m.Membership.user_id == original_user.id)).org_id
        foreign = m.Organization(name='隔离机构')
        db.add(foreign)
        db.flush()
        for username, org in [('peer-teacher', original_org), ('foreign-teacher', foreign.id)]:
            user = m.User(username=username, name=username, password_hash=passwords.hash('Zhixing2026!'))
            db.add(user)
            db.flush()
            membership = m.Membership(user_id=user.id, org_id=org)
            db.add(membership)
            db.flush()
            db.add(m.RoleAssignment(membership_id=membership.id, role='teacher'))
    monkeypatch.setattr(settings, 'deeptutor_teacher_bank_orgs', original_org)
    stored = {}

    async def request(owner, method, path, *, body=None, params=None, **_):
        assert owner == f'{original_org}:teacher-bank'
        if method == 'GET':
            return stored.get(params['question_id'], {})
        assert path.endswith('/entries/upsert')
        item = {'id': 1, **body}
        stored[body['question_id']] = item
        return item

    monkeypatch.setattr(tutor, 'native_request', request)
    with login_client('peer-teacher') as peer, login_client('foreign-teacher') as outsider:
        assert checked(peer, '/teaching/questions') == checked(teacher, '/teaching/questions')
        assert len(stored) == 1
        assert checked(outsider, '/teaching/questions') == []
        checked(student, '/teaching/questions', status=403)


def test_malformed_json_uses_bounded_repair(clients,provider,monkeypatch):
    from app.ai import WorkflowError
    from app import ai_services
    original=ai_services.completion
    malformed=[True]
    def once(messages,metrics,max_tokens=4096):
        if malformed[0]:
            malformed[0]=False
            raise WorkflowError('MODEL_OUTPUT_INVALID')
        return original(messages,metrics,max_tokens)
    monkeypatch.setattr(ai_services,'completion',once)
    _,run=material(clients[1],{'single':1,'multiple':0,'essay':0})
    assert run['state']=='succeeded',run


def test_uploaded_text_original_bytes_are_preserved(clients):
    teacher=clients[1]
    body=b'\xef\xbb\xbf# Original\r\n\r\nTeacher authored source, with original line endings.\r\n'
    response=teacher.post('/api/v1/content/sources/upload',files={'file':('original.md',body,'text/markdown')})
    assert response.status_code==202,response.text
    vid=response.json()['data']['id']
    drain()
    raw=teacher.get('/api/v1/sources/versions/'+vid+'/original')
    assert raw.status_code==200 and raw.content==body


def test_interrupted_verification_resumes_checkpoint(clients,provider,monkeypatch):
    from app.ai import WorkflowError
    from app import ai_services
    original=ai_services.completion
    state={'interrupted':False,'extractions':0}
    def interrupt_once(messages,metrics,max_tokens=4096):
        payload=json.loads(messages[-1]['content'])
        if 'artifact' in payload and not state['interrupted']:
            state['interrupted']=True
            raise WorkflowError('MODEL_TIMEOUT',True)
        if 'original' not in payload and 'artifact' not in payload:
            state['extractions']+=1
        return original(messages,metrics,max_tokens)
    monkeypatch.setattr(ai_services,'completion',interrupt_once)
    _,run=material(clients[1],{'single':1,'multiple':0,'essay':0})
    assert run['state']=='succeeded',run
    assert state['extractions']==1  # Resume verification, don't generate duplicate artifacts.
    assert len(checked(clients[1],'/teaching/questions'))==1


def test_teacher_modified_initial_evaluation_is_formal(clients,provider):
    student,teacher,_=clients
    _,generated=material(teacher,{'single':0,'multiple':0,'essay':1})
    assignment=assign(teacher,generated['output']['question_ids'])
    group=checked(student,'/assignments/'+assignment['id']+'/start','POST')
    fill(student,group)
    checked(student,'/assignments/'+assignment['id']+'/submit','POST')
    drain()
    aid=group['entries'][0]['attempt']['id']
    checked(teacher,'/teacher/attempts/'+aid+'/evaluations','POST',{'parts':[4,6],
        'feedback':'教师核对材料后修改分项，正式确认此答案完整。','expected_revision':0})
    result=checked(student,'/attempts/'+aid)
    assert result['grading_state']=='教师已确认'
    assert result['evaluation']['score']==10
    assert result['ai_suggestion']['confirmed'] is True and result['ai_suggestion']['score']==5
