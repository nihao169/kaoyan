import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, func
from . import models as m, schemas as s, workflows as w, workflow_schemas as ws
from .auth import context, need, teacher_can_view, source_allowed
from .db import get_db
from .errors import fail, require
from .api_common import EnvelopeRoute, idempotent, entity
from .content import version_access, parse_chunks, ensure_index, audit
from .ai_services import configured
from .learning import owned_attempt, current_evaluation
from .config import settings

router=APIRouter(route_class=EnvelopeRoute)


@router.get('/content/sources/{version_id}/processing')
def processing(version_id: str,ctx=Depends(context),db=Depends(get_db)):
    if not (ctx.has('teacher') or ctx.has('admin')):
        fail(403,'ROLE_REQUIRED','需要内容管理角色')
    version,_=version_access(db,ctx,version_id)
    doc=db.scalar(select(m.SourceDocument).where(m.SourceDocument.version_id==version_id))
    runs=list(db.scalars(select(m.AgentRun).where(m.AgentRun.source_version_id==version_id,m.AgentRun.purpose=='content').order_by(m.AgentRun.created_at.desc())))
    activation=db.scalar(select(m.SourceActivation).where(m.SourceActivation.version_id==version_id))
    return {'enabled':bool(activation),'parsed':not doc or doc.state=='parsed','document_state':doc.state if doc else 'parsed',
        'chapters':[entity(c,'position','heading') for c in db.scalars(select(m.SourceChunk).where(m.SourceChunk.version_id==version_id).order_by(m.SourceChunk.position))],
        'runs':[w.agent_view(r) for r in runs],'version_status':version.status}


def enable_material(db,ctx,version_id,data,request,additional=False):
    need(ctx,'teacher')
    version,_=version_access(db,ctx,version_id)
    if version.status=='withdrawn':
        fail(409,'CONTENT_UNAVAILABLE','资料已撤回，请创建修订版本')
    doc=db.scalar(select(m.SourceDocument).where(m.SourceDocument.version_id==version_id))
    if doc and doc.state!='parsed':
        fail(409,'DOCUMENT_NOT_READY','请等待文件解析成功')
    parse_chunks(db,version)
    db.flush()
    positions=set(db.scalars(select(m.SourceChunk.position).where(m.SourceChunk.version_id==version_id)))
    if not set(data.chapters).issubset(positions):
        fail(422,'INVALID_CHAPTER','章节或页段不存在')
    ensure_index(db,version_id)
    for vid in data.supplement_ids:
        if vid==version_id:
            fail(422,'INVALID_SUPPLEMENT','原资料无需重复作为补充资料')
        w.active_source(db,ctx,vid)
    if not configured():
        fail(503,'MODEL_NOT_CONFIGURED','尚未配置真实模型，不能生成题目')
    activation=db.scalar(select(m.SourceActivation).where(m.SourceActivation.version_id==version_id))
    if activation and not additional:
        existing=db.scalar(select(m.AgentRun).where(m.AgentRun.source_version_id==version_id,
            m.AgentRun.purpose=='content').order_by(m.AgentRun.created_at))
        if existing:
            return w.agent_view(existing)
    if not activation:
        db.add(m.SourceActivation(version_id=version_id,org_id=ctx.org_id,teacher_id=ctx.user.id))
        version.status='published'
        version.review_note='教师一次启用原文；生成内容由Agent校验，不表示逐题人工审核'
        version.revision+=1
        if doc:
            doc.confirmed=True
        audit(db,ctx,'source.enable',version_id)
    payload=data.model_dump()
    key=version_id+':'+json.dumps(payload,sort_keys=True)
    if additional:
        key+=':'+request.headers.get('Idempotency-Key','')
    return w.agent_view(w.new_run(db,ctx,'content',key,payload,version_id))


@router.post('/content/sources/{version_id}/enable',response_model=ws.AgentRunOutput,status_code=202)
def enable(version_id: str,data: ws.GenerationSettings,request: Request,ctx=Depends(context),db=Depends(get_db)):
    return idempotent(db,ctx,request,'source-enable:'+version_id,data.model_dump(),lambda:enable_material(db,ctx,version_id,data,request))


@router.post('/content/sources/{version_id}/generate',response_model=ws.AgentRunOutput,status_code=202)
def regenerate(version_id: str,data: ws.GenerationSettings,request: Request,ctx=Depends(context),db=Depends(get_db)):
    w.active_source(db,ctx,version_id)
    return idempotent(db,ctx,request,'source-generate:'+version_id,data.model_dump(),lambda:enable_material(db,ctx,version_id,data,request,True))


@router.get('/agent-runs/{run_id}',response_model=ws.AgentRunOutput)
def agent_run(run_id: str,ctx=Depends(context),db=Depends(get_db)):
    return w.agent_view(w.run_access(db,ctx,run_id))


@router.post('/agent-runs/{run_id}/retry',response_model=ws.AgentRunOutput,status_code=202)
def retry_agent(run_id: str,request: Request,ctx=Depends(context),db=Depends(get_db)):
    run=w.run_access(db,ctx,run_id)
    def retry():
        if run.state!='failed':
            return w.agent_view(run)
        if not configured():
            fail(503,'MODEL_NOT_CONFIGURED','尚未配置模型')
        # Explicit manual retry starts a fresh bounded repair cycle. Automatic recovery resumes checkpoints.
        run.input={**run.input,'_retry':int(run.input.get('_retry',0))+1}
        run.state,run.error_code,run.stage='queued','','等待重试'
        db.add(m.Job(org_id=run.org_id,owner_id=run.owner_id,kind='teaching_agent',resource_id=run.id))
        return w.agent_view(run)
    return idempotent(db,ctx,request,'agent-retry:'+run_id,{},retry)


@router.get('/teaching/questions')
def question_bank(source_version_id: str | None=None,ctx=Depends(context),db=Depends(get_db)):
    need(ctx,'teacher')
    query=select(m.QuestionVersion,m.GeneratedQuestion).join(m.GeneratedQuestion,m.GeneratedQuestion.question_version_id==m.QuestionVersion.id).where(
        m.QuestionVersion.org_id==ctx.org_id,m.GeneratedQuestion.owner_membership_id==None,m.GeneratedQuestion.disabled==False)
    if source_version_id:
        query=query.where(m.QuestionVersion.source_version_id==source_version_id)
    result=[]
    for q,g in db.execute(query.order_by(m.QuestionVersion.created_at.desc())):
        version=db.get(m.SourceVersion,q.source_version_id)
        source=db.get(m.Source,version.source_id)
        if version.status!='published' or not source_allowed(db,ctx,source):
            continue
        result.append({**entity(q,'id','source_version_id','kind','prompt','options','answer','explanation','rubric','hints','max_score','number'),
            'knowledge':db.get(m.KnowledgePoint,q.knowledge_id).name,'source_title':source.title,'origin':'Agent生成并校验',
            'run_id':g.run_id,'option_analysis':g.option_analysis,'sources':w.question_evidence(db,ctx,q.id)})
    return result


@router.post('/teaching/questions/{question_id}/disable')
def disable_question(question_id: str,ctx=Depends(context),db=Depends(get_db)):
    need(ctx,'teacher')
    q=require(db.get(m.QuestionVersion,question_id))
    version_access(db,ctx,q.source_version_id)
    g=require(db.scalar(select(m.GeneratedQuestion).where(m.GeneratedQuestion.question_version_id==q.id,m.GeneratedQuestion.owner_membership_id==None)))
    g.disabled=True
    audit(db,ctx,'generated-question.disable',q.id)
    return {'id':q.id,'disabled':True}


@router.put('/teaching/questions/{question_id}')
def edit_generated(question_id: str,data: s.QuestionInput,ctx=Depends(context),db=Depends(get_db)):
    need(ctx,'teacher')
    q=require(db.get(m.QuestionVersion,question_id))
    w.active_source(db,ctx,q.source_version_id)
    generated=require(db.scalar(select(m.GeneratedQuestion).where(m.GeneratedQuestion.question_version_id==q.id,m.GeneratedQuestion.owner_membership_id==None)))
    if data.source_version_id!=q.source_version_id or data.kind!=q.kind:
        fail(422,'IMMUTABLE_IDENTITY','不能改变题目资料归属或题型')
    if generated.disabled:
        fail(409,'STALE_REVISION','此版本已被停用或修订，请刷新')
    number=db.scalar(select(func.max(m.QuestionVersion.number)).where(m.QuestionVersion.question_id==q.question_id))+1
    replacement=m.QuestionVersion(question_id=q.question_id,number=number,org_id=ctx.org_id,knowledge_id=q.knowledge_id,
        policy_id=q.policy_id,status='published',**data.model_dump())
    db.add(replacement)
    db.flush()
    generated.disabled=True
    db.add(m.GeneratedQuestion(question_version_id=replacement.id,run_id=generated.run_id,option_analysis={}))
    for evidence in db.scalars(select(m.ArtifactEvidence).where(m.ArtifactEvidence.artifact_kind=='question',m.ArtifactEvidence.artifact_id==q.id)):
        db.add(m.ArtifactEvidence(run_id=evidence.run_id,artifact_kind='question',artifact_id=replacement.id,chunk_id=evidence.chunk_id,quote=evidence.quote))
    audit(db,ctx,'generated-question.revise',replacement.id,{'previous_id':q.id})
    return {'id':replacement.id,'number':number}


@router.post('/teacher/assignments',status_code=201)
def publish_assignment(data: ws.AssignmentInput,request: Request,ctx=Depends(context),db=Depends(get_db)):
    w.teacher_class(db,ctx,data.class_id)
    if data.due_at and data.due_at.tzinfo is None:
        fail(422,'INVALID_DEADLINE','截止时间必须包含时区')
    if data.due_at and data.due_at<=datetime.now(timezone.utc):
        fail(422,'INVALID_DEADLINE','截止时间必须晚于当前时间')
    def publish():
        for qid in data.question_ids:
            q=require(db.get(m.QuestionVersion,qid))
            g=require(db.scalar(select(m.GeneratedQuestion).where(m.GeneratedQuestion.question_version_id==qid)))
            if q.org_id!=ctx.org_id or g.disabled or g.owner_membership_id or q.status!='published':
                fail(409,'QUESTION_UNAVAILABLE','请从已校验的公共题库中选题')
            _,source=w.active_source(db,ctx,q.source_version_id)
            if source.visibility=='private' or (source.visibility=='class' and source.class_id!=data.class_id):
                fail(403,'SOURCE_SCOPE','资料不能提供给所选班级')
            for e in db.scalars(select(m.ArtifactEvidence).where(m.ArtifactEvidence.artifact_id==qid,m.ArtifactEvidence.artifact_kind=='question')):
                _,support=w.active_source(db,ctx,db.get(m.SourceChunk,e.chunk_id).version_id)
                if support.visibility=='private' or (support.visibility=='class' and support.class_id!=data.class_id):
                    fail(403,'SOURCE_SCOPE','引用资料不能提供给所选班级')
        assignment=m.Assignment(org_id=ctx.org_id,teacher_membership_id=ctx.membership.id,class_id=data.class_id,
            title=data.title.strip(),due_at=data.due_at.astimezone(timezone.utc).isoformat() if data.due_at else None,question_ids=data.question_ids)
        db.add(assignment)
        db.flush()
        audit(db,ctx,'assignment.publish',assignment.id)
        return {'id':assignment.id,'title':assignment.title}
    return idempotent(db,ctx,request,'assignment.publish',data.model_dump(mode='json'),publish)


@router.get('/teacher/assignments')
def teacher_assignments(ctx=Depends(context),db=Depends(get_db)):
    need(ctx,'teacher')
    result=[]
    for a in db.scalars(select(m.Assignment).where(m.Assignment.org_id==ctx.org_id).order_by(m.Assignment.created_at.desc())):
        if not any(r.role=='teacher' and (r.class_id is None or r.class_id==a.class_id) for r in ctx.roles):
            continue
        subs=list(db.scalars(select(m.AssignmentSubmission).where(m.AssignmentSubmission.assignment_id==a.id)))
        result.append({**entity(a,'id','title','due_at','created_at','class_id'),'class_name':db.get(m.TeachingClass,a.class_id).name,
            'questions':len(a.question_ids),'submitted':sum(s.state=='submitted' for s in subs)})
    return result


@router.get('/assignments')
def student_assignments(ctx=Depends(context),db=Depends(get_db)):
    need(ctx,'student')
    class_ids=list(db.scalars(select(m.ClassMember.class_id).where(m.ClassMember.membership_id==ctx.membership.id)))
    result=[]
    for a in db.scalars(select(m.Assignment).where(m.Assignment.org_id==ctx.org_id,m.Assignment.class_id.in_(class_ids)).order_by(m.Assignment.created_at.desc())):
        sub=db.scalar(select(m.AssignmentSubmission).where(m.AssignmentSubmission.assignment_id==a.id,m.AssignmentSubmission.membership_id==ctx.membership.id))
        result.append({**entity(a,'id','title','due_at','created_at'),'questions':len(a.question_ids),'state':sub.state if sub else 'not_started'})
    return result


@router.post('/assignments/{assignment_id}/start',response_model=ws.GroupOutput)
def start_assignment(assignment_id: str,ctx=Depends(context),db=Depends(get_db)):
    return w.group_view(db,ctx,w.start_assignment(db,ctx,assignment_id))


@router.post('/assignments/{assignment_id}/submit',response_model=ws.GroupOutput)
def submit_assignment(assignment_id: str,request: Request,ctx=Depends(context),db=Depends(get_db)):
    need(ctx,'student')
    w.assignment_access(db,ctx,assignment_id)
    sub=require(db.scalar(select(m.AssignmentSubmission).where(m.AssignmentSubmission.assignment_id==assignment_id,m.AssignmentSubmission.membership_id==ctx.membership.id)))
    return idempotent(db,ctx,request,'assignment-submit:'+sub.id,{},lambda:w.submit_group(db,ctx,sub))


@router.get('/mistake-diagnoses')
def mistakes(ctx=Depends(context),db=Depends(get_db)):
    need(ctx,'student')
    rems=db.scalars(select(m.Remediation).join(m.Attempt,m.Remediation.attempt_id==m.Attempt.id).where(m.Attempt.membership_id==ctx.membership.id).order_by(m.Remediation.created_at.desc()))
    return [w.remediation_view(db,ctx,r) for r in rems]


@router.post('/remediations/{remediation_id}/diagnose',response_model=ws.AgentRunOutput,status_code=202)
def diagnose(remediation_id: str,request: Request,ctx=Depends(context),db=Depends(get_db)):
    need(ctx,'student')
    remediation=require(db.get(m.Remediation,remediation_id))
    a=owned_attempt(db,ctx,remediation.attempt_id)
    ev=require(current_evaluation(db,a.id),'请等待正式评价后再诊断')
    q=db.get(m.QuestionVersion,a.question_version_id)
    w.active_source(db,ctx,q.source_version_id)
    if not configured():
        fail(503,'MODEL_NOT_CONFIGURED','尚未配置真实模型')
    return idempotent(db,ctx,request,'diagnose:'+a.id,{},lambda:w.agent_view(w.new_run(db,ctx,'diagnosis',a.id+':'+str(ev['revision']),{},q.source_version_id,a.id)))


@router.post('/remediations/{remediation_id}/practice-generations',response_model=ws.AgentRunOutput,status_code=202)
def targeted(remediation_id: str,request: Request,ctx=Depends(context),db=Depends(get_db)):
    need(ctx,'student')
    remediation=require(db.get(m.Remediation,remediation_id))
    a=owned_attempt(db,ctx,remediation.attempt_id)
    q=db.get(m.QuestionVersion,a.question_version_id)
    w.active_source(db,ctx,q.source_version_id)
    diagnosis=require(db.scalar(select(m.AgentRun).where(m.AgentRun.attempt_id==a.id,m.AgentRun.purpose=='diagnosis',m.AgentRun.state=='succeeded').order_by(m.AgentRun.created_at.desc())),'请先完成AI诊断')
    # One practice generation per diagnosis; repeat clicks always recover the same personal group.
    if not configured():
        fail(503,'MODEL_NOT_CONFIGURED','尚未配置真实模型')
    return idempotent(db,ctx,request,'targeted:'+a.id,{},lambda:w.agent_view(w.new_run(db,ctx,'targeted',diagnosis.id,{'diagnosis_id':diagnosis.id},q.source_version_id,a.id)))


@router.post('/practice-groups/{practice_id}/open',response_model=ws.GroupOutput)
def open_practice(practice_id: str,ctx=Depends(context),db=Depends(get_db)):
    need(ctx,'student')
    return w.group_view(db,ctx,require(db.get(m.TargetedPractice,practice_id)),True)


@router.post('/practice-groups/{practice_id}/submit',response_model=ws.GroupOutput)
def submit_practice(practice_id: str,request: Request,ctx=Depends(context),db=Depends(get_db)):
    need(ctx,'student')
    practice=require(db.get(m.TargetedPractice,practice_id))
    return idempotent(db,ctx,request,'practice-submit:'+practice_id,{},lambda:w.submit_group(db,ctx,practice,True))


@router.post('/teacher/attempts/{attempt_id}/confirm-ai-evaluation',response_model=s.EvaluationOutput)
def confirm_evaluation(attempt_id: str,data: ws.ConfirmEvaluation,request: Request,ctx=Depends(context),db=Depends(get_db)):
    from .learning import score_essay
    need(ctx,'teacher')
    a=owned_attempt(db,ctx,attempt_id,teacher=True)
    if not teacher_can_view(db,ctx,a.membership_id):
        fail(404,'NOT_FOUND','作答不存在')
    def confirm():
        suggestion=require(db.scalar(select(m.EvaluationSuggestion).where(m.EvaluationSuggestion.attempt_id==a.id)),'尚无通过校验的AI初评')
        if suggestion.confirmed or current_evaluation(db,a.id):
            fail(409,'ALREADY_CONFIRMED','评价已确认，请刷新查看历史；修订请使用评分入口')
        run=db.get(m.AgentRun,suggestion.run_id)
        for cite in run.output.get('evidence',[]):
            w.active_source(db,ctx,db.get(m.SourceChunk,cite['chunk_id']).version_id)
        result=score_essay(db,ctx,a.id,s.EvaluationInput(parts=data.parts if data.parts is not None else suggestion.parts,
            feedback=data.feedback or suggestion.feedback,expected_revision=0))
        suggestion.confirmed=True
        return result
    return idempotent(db,ctx,request,'confirm-evaluation:'+attempt_id,data.model_dump(),confirm)
