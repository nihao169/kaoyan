"""Disposable API-to-DeepTutor acceptance. Uses real model calls and fees.

All platform records live under .runtime. DeepTutor uses isolated native accounts.
The output records generated content for human review, never provider secrets.
"""
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
directory=ROOT/'.runtime'/('v2-real-'+uuid4().hex)
directory.mkdir(parents=True)
os.environ['DATABASE_URL']='sqlite:///'+(directory/'acceptance.db').as_posix()
os.environ['DATA_DIR']=str(directory)
os.environ['PYTHONUTF8']='1'
os.environ['DEEPTUTOR_URL']='http://127.0.0.1:18001'
secrets=json.loads((ROOT/'.runtime/v2-secrets.json').read_text(encoding='utf-8-sig'))
os.environ['DEEPTUTOR_BRIDGE_SECRET']=secrets['bridge_secret']
sys.path.insert(0,str(ROOT/'backend'))
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from app.main import app
from app.seed import seed
from app.db import SessionLocal
from app.v2 import models as m
from app.v2.worker import tick

command.upgrade(Config(str(ROOT/'backend/alembic.ini')),'head')
seed(include_demo_content=False)
client=TestClient(app)
response=client.post('/api/v1/auth/login',json={'username':'student','password':'Zhixing2026!'})
assert response.status_code==200,response.text
me=client.get('/api/v1/me').json()['data']
client.headers.update({'X-CSRF-Token':me['csrf_token']})

def call(path,method='GET',body=None):
    response=client.request(method,'/api/v2'+path,json=body,headers={'Idempotency-Key':str(uuid4())})
    if not response.is_success:
        raise RuntimeError(response.text)
    return response.json()['data']

subject=client.get('/api/v1/catalog').json()['data']['subjects'][0]['id']
p=call('/learning-projects','POST',{'title':'真实服务验收专用','subject_id':subject,'exam_year':2027,'daily_minutes':45})
material=call('/learning-projects/'+p['id']+'/materials','POST',{'title':'原创验收材料：实践与认识','text':'实践是认识的来源，是认识发展的动力，是检验认识真理性的唯一标准，也是认识的目的。认识对实践具有反作用，正确的认识促进实践，错误的认识阻碍实践。真理具有客观性，同时是具体的、有条件的，必须坚持一切从实际出发。对某项政策进行评价，应检查实际条件、实施过程与效果，不能只依据主观愿望。'})
reading=call('/learning-projects/'+p['id'])['tasks'][0]
practice=call('/study-sessions/'+reading['id']+'/complete','POST')['next_task_id']
record={'provider':'real DeepTutor / DeepSeek','database':str(directory/'acceptance.db'),'runs':[],'questions':[],'human_review':'required'}
try:
    tail_quote = '海岬试验的验收标记是蓝色铜铃。'
    tail = call('/learning-projects/'+p['id']+'/materials','POST',{
        'title':'全文检索验收资料',
        'text':('本页仅记录测试用的时间、样本与数据分布。\n'*820)+tail_quote})
    search = call('/learning-projects/'+p['id']+'/material-search?q=海岬试验验收标记')
    assert search[0]['material_id']==tail['id'] and search[0]['start']>12000
    queued = call('/learning-projects/'+p['id']+'/ai-runs','POST',{'prompt':'海岬试验的验收标记是什么？请用完整的一句话逐字引述原文。'})
    print('Executing real question answering with a citation beyond 12,000 characters.',flush=True)
    assert tick()
    chat = call('/ai-runs/'+queued['run_id'])
    record['runs'].append(chat)
    assert chat['state']=='succeeded',chat['error']
    match = next(ref for ref in chat['result']['citations'] if ref['material_id']==tail['id'])
    assert match['start']>12000 and match['quote'] in tail_quote and '蓝色铜铃' in chat['result']['text']
    path = '/learning-projects/'+p['id']+'/materials/'+tail['id']
    excerpt = call(f"{path}/excerpt?sha256={match['sha256']}&start={match['start']}&end={match['end']}")
    assert excerpt['quote']==match['quote']
    call(path,'DELETE')
    for cycle in range(2):
        queued=call('/study-sessions/'+practice+'/prepare','POST')
        print('Executing real question generation and independent review, cycle',cycle+1,flush=True)
        assert tick()
        run=call('/ai-runs/'+queued['run_id'])
        record['runs'].append(run)
        if run['state']!='succeeded':
            raise RuntimeError(run['error'])
        session=call('/study-sessions/'+practice)
        with SessionLocal() as db:
            question=db.get(m.Question,session['question']['id'])
            correct=list(question.answer)
            wrong=next((k for k in question.options if k not in correct),None)
            record['questions'].append({'prompt':question.prompt,'answer':correct,'quote':question.quote,'explanation':question.explanation})
        if not correct or wrong is None:
            raise RuntimeError('Acceptance requires an objective question with a wrong alternative')
        call('/study-sessions/'+practice+'/submit','POST',{'answer':[wrong] if cycle==0 else correct})
        if cycle==0:
            detail=call('/learning-projects/'+p['id'])
            remediate=next(t for t in detail['tasks'] if t['kind']=='remediation')
            practice=call('/study-sessions/'+remediate['id']+'/complete','POST')['next_task_id']
    detail=call('/learning-projects/'+p['id'])
    assert any(t['kind']=='review' for t in detail['tasks'])
    record.update(status='passed',report=detail['report'])
    print('Real source-grounded generation, remediation and review scheduling passed.',flush=True)
finally:
    (ROOT/'.runtime/v2-real-acceptance.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    client.close()
