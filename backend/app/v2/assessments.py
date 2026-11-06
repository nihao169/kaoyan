from datetime import timedelta
from typing import Literal
from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select
from ..auth import context
from ..api_common import EnvelopeRoute, entity, idempotent
from ..db import get_db
from ..errors import fail
from . import models as m, service as s, tutor_practice
from .routes import Input, AnswerInput, create_run
from .exam_resources import load_resource

router = APIRouter(route_class=EnvelopeRoute)


class AssessmentInput(Input):
    project_id: str
    title: str = Field(min_length=1,max_length=200)
    mode: Literal['mock','practice'] = 'mock'
    question_ids: list[str] = Field(min_length=1,max_length=50)
    minutes: int = Field(default=30,ge=5,le=180)


class AssessmentDraftInput(Input):
    revision: int
    answers: dict[str, AnswerInput]


class SubmitInput(Input):
    answers: dict[str, AnswerInput]


class PastPaperInput(Input):
    project_id: str
    resource_id: str
    mode: Literal['mock','practice'] = 'mock'


def get_assessment(db, ctx, assessment_id, lock=False):
    a = db.get(m.Assessment, assessment_id)
    if not a:
        fail(404,'NOT_FOUND','测评不存在')
    s.project(db,ctx,a.project_id,lock=lock)
    return db.get(m.Assessment, assessment_id, populate_existing=True) if lock else a


@router.get('/learning-projects/{project_id}/question-bank')
def bank(project_id:str,ctx=Depends(context),db=Depends(get_db)):
    p=s.project(db,ctx,project_id)
    s.no_active_mock(db,p.id)
    allowed = {x.id: x for x in s.authorized_materials(db,ctx,p)}
    questions = [q for q in s.rows(db,m.Question,p.id) if q.material_id in allowed]
    if not tutor_practice.enabled(p.id):
        return [s.question_view(q) for q in questions]
    personal = [q for q in questions if tutor_practice.eligible(q, allowed[q.material_id])]
    db.commit()
    native = {q['id']: q for q in tutor_practice.call(tutor_practice.question_views(ctx.user.id, p.id, personal))}
    db.expire_all()
    p = s.project(db, ctx, project_id)
    s.no_active_mock(db, p.id)
    authorized = {x.id for x in s.authorized_materials(db, ctx, p)}
    return [native.get(q.id) or s.question_view(q) for q in questions if q.material_id in authorized]


@router.get('/assessments')
def assessments(ctx=Depends(context),db=Depends(get_db)):
    values=db.scalars(select(m.Assessment).join(m.Project).join(m.PersonalSpace).where(m.PersonalSpace.user_id==ctx.user.id).order_by(m.Assessment.created_at.desc()))
    return [entity(a,'id','project_id','title','mode','state','deadline_at') for a in values]


@router.post('/assessments',status_code=201)
def create(data:AssessmentInput,request:Request,ctx=Depends(context),db=Depends(get_db)):
    p=s.project(db,ctx,data.project_id,lock=True)
    s.authorized_materials(db,ctx,p)
    if len(set(data.question_ids))!=len(data.question_ids):
        fail(422,'DUPLICATE_QUESTION','同一测评不能重复选择题目')
    questions=[db.get(m.Question,qid) for qid in data.question_ids]
    if any(not q or q.project_id!=p.id for q in questions):
        fail(404,'NOT_FOUND','题目不属于当前学习项目')
    for q in questions:
        s.material_access(db,ctx,db.get(m.Material,q.material_id))
    def save():
        if db.scalar(select(m.Assessment.id).where(m.Assessment.project_id==p.id,m.Assessment.mode=='mock',m.Assessment.state=='active')):
            fail(409,'MOCK_ACTIVE','请先完成当前模考')
        return save_assessment(db,p,data.title,data.mode,data.minutes,questions,membership_id=ctx.membership.id)
    return idempotent(db,ctx,request,'v2.assessment.create',data.model_dump(),save)


def save_assessment(db, p, title, mode, minutes, questions, paper=None, membership_id=None):
    a=m.Assessment(project_id=p.id,title=title,mode=mode,deadline_at=(s.clock()+timedelta(minutes=minutes)).isoformat())
    db.add(a)
    db.flush()
    tasks=[]
    for index,q in enumerate(questions):
        payload = {'question_id':q.id,'knowledge':q.knowledge,'assessment_id':a.id,'membership_id':membership_id}
        if paper:
            payload.update(points=paper.contents['points'][q.id], resource_id=paper.id)
        t=s.add_task(db,p,'practice',f'{title[:180]} · 第{index+1}题',f'assessment:{a.id}:{q.id}',
                     '测评整组提交后查看反馈',q.material_id,payload)
        tasks.append(t.id)
    a.task_ids=tasks
    return {'id':a.id}


@router.post('/assessments/from-past-paper',status_code=201)
def from_past_paper(data:PastPaperInput,request:Request,ctx=Depends(context),db=Depends(get_db)):
    p=s.project(db,ctx,data.project_id,lock=True)
    paper=load_resource(db,ctx,p,data.resource_id,('past_paper','simulated_paper'))
    def save():
        s.no_active_mock(db,p.id)
        questions=[db.get(m.Question,qid) for qid in paper.contents['question_ids']]
        return save_assessment(db,p,f'{paper.year} · {paper.title} ({paper.edition})',data.mode,
                               paper.contents['minutes'],questions,paper,ctx.membership.id)
    return idempotent(db,ctx,request,'v2.assessment.past-paper',data.model_dump(),save)


@router.get('/assessments/{assessment_id}')
def detail(assessment_id:str,ctx=Depends(context),db=Depends(get_db)):
    a=get_assessment(db,ctx,assessment_id)
    p=s.project(db,ctx,a.project_id)
    if db.scalar(select(m.Assessment.id).where(m.Assessment.project_id==p.id, m.Assessment.mode=='mock',
            m.Assessment.state=='active', m.Assessment.id!=a.id)):
        s.no_active_mock(db,p.id)
    if a.state=='needs_review':
        return {**entity(a,'id','project_id','title','mode','state','deadline_at','revision','drafts'),
                'entries':[],'paper_objective_score':None,'server_now':s.clock().isoformat()}
    s.authorized_materials(db,ctx,p)
    entries=[]
    for task_id in a.task_ids:
        t=db.get(m.Task,task_id)
        q=db.get(m.Question,t.payload['question_id'])
        s.material_access(db,ctx,db.get(m.Material,q.material_id))
        attempt=db.scalar(select(m.Attempt).where(m.Attempt.task_id==t.id))
        entries.append({'task_id':t.id,'question':s.question_view(q,a.state!='active'),'points':t.payload.get('points'),
                        'result':attempt.result if attempt else None})
    objectives=[e for e in entries if e['points'] and e['question']['kind']!='essay']
    paper_score={'earned':sum(e['points'] for e in objectives if e['result'] and e['result'].get('correct')),
                 'possible':sum(e['points'] for e in objectives)} if objectives and a.state!='active' else None
    return {**entity(a,'id','project_id','title','mode','state','deadline_at','revision','drafts'),
            'entries':entries,'paper_objective_score':paper_score,'server_now':s.clock().isoformat()}


@router.put('/assessments/{assessment_id}/draft')
def draft(assessment_id:str,data:AssessmentDraftInput,ctx=Depends(context),db=Depends(get_db)):
    a=get_assessment(db,ctx,assessment_id,lock=True)
    if a.state!='active' or s.datetime.fromisoformat(a.deadline_at)<=s.clock():
        fail(409,'ASSESSMENT_CLOSED','测评已结束或已到截止时间，请交卷')
    if a.revision!=data.revision:
        fail(409,'REVISION_CONFLICT','作答已在其他页面变化，请刷新')
    validate_answers(db,a,data.answers)
    a.drafts={**a.drafts,**{tid:answer.model_dump() for tid,answer in data.answers.items()}}
    a.revision+=1
    return {'revision':a.revision}


@router.post('/assessments/{assessment_id}/submit')
def submit(assessment_id:str,data:SubmitInput,request:Request,ctx=Depends(context),db=Depends(get_db)):
    a=get_assessment(db,ctx,assessment_id,lock=True)
    p=s.project(db,ctx,a.project_id)
    s.authorized_materials(db,ctx,p)
    def save():
        if a.state=='submitted' and s.datetime.fromisoformat(a.deadline_at)<=s.clock():
            return {'id':a.id,'state':a.state,'used_saved_answers':True}
        if a.state!='active':
            fail(409,'ALREADY_SUBMITTED','测评已经提交')
        expired=s.datetime.fromisoformat(a.deadline_at)<=s.clock()
        answers=a.drafts if expired else {**a.drafts,**{tid:answer.model_dump() for tid,answer in data.answers.items()}}
        finish(db,ctx,p,a,answers)
        return {'id':a.id,'state':a.state,'used_saved_answers':expired}
    return idempotent(db,ctx,request,f'v2.assessment.submit:{a.id}',data.model_dump(),save)


def validate_answers(db,a,answers):
    for tid,value in answers.items():
        if tid not in a.task_ids:
            fail(422,'INVALID_TASK','作答不属于本次测评')
        q=db.get(m.Question,db.get(m.Task,tid).payload['question_id'])
        answer=value if isinstance(value, AnswerInput) else AnswerInput(**value)
        if (q.kind=='essay' and answer.answer) or (q.kind!='essay' and (
                answer.response_text or not set(answer.answer)<=q.options.keys() or
                len(set(answer.answer))!=len(answer.answer) or (q.kind=='single' and len(answer.answer)>1))):
            fail(422,'INVALID_ANSWER','答案不符合该题题型')


def finish(db,ctx,p,a,answers):
    validate_answers(db,a,answers)
    for tid in a.task_ids:
        t=db.get(m.Task,tid)
        q=db.get(m.Question,t.payload['question_id'])
        s.material_access(db,ctx,db.get(m.Material,q.material_id))
        value=AnswerInput(**answers.get(tid,{}))
        if not value.answer and not value.response_text.strip():
            attempt=m.Attempt(task_id=tid,answer=[],response_text='',confidence=value.confidence)
            db.add(attempt)
            db.flush()
            s.finish_answer(db,p,t,q,attempt,False,'本题未作答，建议回到资料检查。')
        else:
            attempt,_,_,_=s.submit_answer(db,ctx,tid,value,assessment=True)
            if q.kind=='essay':
                run=create_run(db,p,'evaluate','分析题AI训练评价',tid,ctx.membership.id)
                attempt.result={**attempt.result,'run_id':run.id}
    a.state='submitted'
    a.drafts=answers
    a.revision+=1


def close_expired(db,project_id,assessment_id):
    from .worker import context_for, tutor
    from fastapi import HTTPException
    p=db.scalar(select(m.Project).where(m.Project.id==project_id).with_for_update(skip_locked=True))
    if not p:
        return False
    a=db.get(m.Assessment,assessment_id,populate_existing=True)
    if not a or a.state!='active' or a.deadline_at>s.clock().isoformat():
        return False
    t=db.get(m.Task,a.task_ids[0])
    try:
        with db.begin_nested():
            ctx=context_for(db,p,t.payload.get('membership_id'))
            finish(db,ctx,p,a,a.drafts)
    except (HTTPException,tutor.TutorError):
        # Keep the saved draft for later review, but release the active mock restriction.
        a.state='needs_review'
        a.revision+=1
    return True
