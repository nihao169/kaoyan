"""Real native bridge acceptance using an isolated preview, never production data.

Usage: python scripts/verify-project-learning.py .runtime/tutor-native-preview-...
The preview's configured model and embedding service must already be available.
"""
import os
from pathlib import Path
import sys
import time
from uuid import uuid4
import hashlib

root=Path(__file__).resolve().parents[1]
preview=Path(sys.argv[1]).resolve()
if not preview.is_relative_to(root/'.runtime') or not preview.name.startswith('tutor-native-preview-'):
    raise SystemExit('Use an isolated preview directory under .runtime')
os.environ.update(DEEPTUTOR_URL='http://127.0.0.1:18012',
    DEEPTUTOR_BRIDGE_SECRET=(preview/'bridge.key').read_text(encoding='utf-8-sig').strip())
sys.path.insert(0,str(root/'backend'))
from app.v2 import project_learning as learning, tutor

token=uuid4().hex
results=[]
contexts=[]
def call(owner,fields,operation='status',**body):
    return learning.bridge(owner,operation=operation,**fields,**body)

def settle(owner,fields):
    until=time.monotonic()+240
    while time.monotonic()<until:
        result=call(owner,fields)
        if result['state'] not in ('queued','running','created','recovering'):
            return result
        time.sleep(2)
    raise TimeoutError('Native model turn did not settle within 240 seconds')

def submit(owner,fields,operation,**body):
    sid=uuid4().hex
    call(owner,fields,operation,submission_id=sid,**body)
    # Replay the exact delivery identifier before waiting for the model.
    call(owner,fields,operation,submission_id=sid,**body)
    return settle(owner,fields)

for scene,description in learning.SCENES.items():
    if '--teaching' in sys.argv and scene != 'chapter':
        continue
    owner='acceptance-project-learning:'+token+':'+scene
    fields={'path_id':'topic_zxp_'+uuid4().hex,'session_id':'zx_learning_'+uuid4().hex,
        'background':description+' 课程：统计学。目标：理解总体与样本。每日30分钟。', 'ready':False,'sources':[]}
    result=submit(owner,fields,'message',text='请先了解我的目标。我尚未提供资料，请不要开始正式教学。')
    assert result['intake'] and not result['curriculum'] and result['messages']
    assert all('<知行学习背景>' not in x['content'] for x in result['messages'])
    print(scene,'intake:',result['state'],flush=True)
    contexts.append((owner,fields,result))

owner,fields,result=contexts[0]
name='zx_'+hashlib.sha256((token+':material').encode()).hexdigest()[:48]
text='统计学学习资料\n总体是所研究对象的全体。样本是从总体中抽取的一部分。统计推断通过样本了解总体，但样本统计量不等同于总体参数。随机抽样有助于减小选择偏差。'
tutor.knowledge_request(owner,'create',name,text=text,title='总体与样本')
until=time.monotonic()+180
while time.monotonic()<until:
    indexed=tutor.knowledge_request(owner,'status',name)
    if indexed['state']=='ready':break
    if indexed['state']=='failed':raise RuntimeError('Native indexing failed: '+str(indexed))
    time.sleep(2)
else:raise TimeoutError('Native index not ready')
fields.update(ready=True,sources=[{'name':name,'label':'总体与样本'}])
if result['state']=='waiting_input':
    result=submit(owner,fields,'answer',expected_id=result['request_id'],text='我希望理解总体、样本的区别，基础较弱，先讨论大纲。')
else:
    result=submit(owner,fields,'message',text='资料已经准备好，请先依据资料与我讨论大纲，待我确认再修改。')
assert result['curriculum'] and not result['intake']
print('indexed native path:',result['state'],flush=True)
if '--teaching' in sys.argv:
    confirmation='我确认学习范围：一个模块“统计入门”，两个知识点“总体与样本”和“随机抽样”。请使用原生工具保存大纲，保留已有证据。'
    for attempt in range(3):
        if result['state']=='waiting_input':
            result=submit(owner,fields,'answer',expected_id=result['request_id'],text=confirmation)
        else:
            result=submit(owner,fields,'message',text=confirmation)
        if result['curriculum']['map']['counts']['total']>0:break
    assert result['curriculum']['map']['counts']['total']>0, 'No native outline was saved'
    print('native outline saved:',result['curriculum']['map']['counts']['total'],flush=True)
    if result['state']=='waiting_input':
        result=submit(owner,fields,'answer',expected_id=result['request_id'],text='确认，开始总体与样本的学习。')
    result=submit(owner,fields,'mode',mode='study')
    for attempt in range(3):
        if result['state']=='question':break
        if result['state']=='waiting_input':
            result=submit(owner,fields,'answer',expected_id=result['request_id'],text='我已经理解刚才的讲解，请检查理解。')
        else:
            result=submit(owner,fields,'message',text='请依据原文用理解检查题卡检验当前知识点，不要仅靠我的自评判定掌握。')
    assert result['state']=='question' and result['question'], 'Native tutor did not present a check card'
    question=result['question']
    answer='总体是研究对象的全体，样本是从总体中抽取的部分，随机抽样有助于减小选择偏差。'
    result=submit(owner,fields,'answer',expected_id=result['request_id'],text=answer,
        answers={q['question_id']:answer for q in question.get('questions',[])})
    assert result['curriculum']
    print('native check card answered; mastered:',result['curriculum']['map']['counts']['mastered'],flush=True)
if result['state']=='waiting_input':
    result=submit(owner,fields,'answer',expected_id=result['request_id'],text='请先保留当前建议，我接下来想精读原文。')
if result['state'] not in ('waiting_input','question'):
    result=submit(owner,fields,'notes',notes=[{'title':'我的理解','body':'样本来自总体，但不能直接将样本比例当成总体参数。'}])
    print('native notebook references:',result['state'],flush=True)
if result['state']=='waiting_input':
    result=submit(owner,fields,'answer',expected_id=result['request_id'],text='暂不修改大纲，先保留笔记。')
if result['state'] not in ('waiting_input','question'):
    result=submit(owner,fields,'read',reader={'name':name,'title':'总体与样本','text':text})
    assert result['reading']
    print('native immersive reading:',result['state'],flush=True)
else:
    print('native tutor has a pending interaction; session preserved for manual continuation',flush=True)
print('Real acceptance complete; isolated principal prefix:',token,flush=True)
