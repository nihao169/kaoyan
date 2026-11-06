"""Deterministic operations surrounding teacher materials and advisory agents."""
import hashlib
import json
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from . import models as m
from .auth import Context, need, source_allowed, teacher_can_view
from .errors import fail, require
from .content import version_access, audit


def teacher_class(db, ctx, class_id):
    need(ctx, 'teacher')
    cls = require(db.get(m.TeachingClass, class_id))
    if cls.org_id != ctx.org_id or not any(r.role == 'teacher' and (r.class_id is None or r.class_id == cls.id) for r in ctx.roles):
        fail(404, 'NOT_FOUND', '班级不存在或无权访问')
    return cls


def active_source(db, ctx, version_id):
    version, source = version_access(db, ctx, version_id, published=True)
    if not db.scalar(select(m.SourceActivation.id).where(m.SourceActivation.version_id == version_id)):
        fail(409, 'SOURCE_NOT_ENABLED', '请教师先启用原文，Agent只使用已启用的教师资料')
    return version, source


def new_run(db, ctx, purpose, key, data, source_id=None, attempt_id=None):
    from .ai_services import TUTOR_MODELS, advisory_model
    from .config import settings

    fingerprint = hashlib.sha256((purpose + ':' + key).encode()).hexdigest()
    previous = db.scalar(select(m.AgentRun).where(m.AgentRun.org_id == ctx.org_id, m.AgentRun.fingerprint == fingerprint))
    if previous:
        return previous
    model = advisory_model(purpose)
    run = m.AgentRun(org_id=ctx.org_id, owner_id=ctx.user.id, membership_id=ctx.membership.id,
        purpose=purpose, source_version_id=source_id, attempt_id=attempt_id, fingerprint=fingerprint,
        input={**data, '_native_retrieval': model in TUTOR_MODELS and settings.deeptutor_native_knowledge}, model=model)
    db.add(run)
    db.flush()
    db.add(m.Job(org_id=ctx.org_id, owner_id=ctx.user.id, kind='teaching_agent', resource_id=run.id))
    return run


def agent_view(run):
    result = {k:getattr(run,k) for k in ('id','purpose','state','stage','source_version_id','attempt_id',
            'input','output','metrics','error_code','model','workflow_version','created_at')}
    result['metrics'] = {key: value for key, value in run.metrics.items() if key not in ('external_id', '_native_turns')}
    if run.purpose == 'targeted':
        # Raw generation includes answers, hints and rubrics. Reveal them only through
        # the normal attempt view after submission, never via a progress endpoint.
        result['output'] = {k:v for k,v in run.output.items() if k not in ('questions','extraction')}
    return result


def require_current_agent_sources(db, ctx, run):
    from .ai_services import TUTOR_MODELS
    if run.model in TUTOR_MODELS and (run.state == 'succeeded' or run.output):
        owner = run_context(db, run)
        for version_id in [run.source_version_id, *run.input.get('supplement_ids', [])]:
            active_source(db, owner, version_id)
            if ctx.membership.id != owner.membership.id:
                active_source(db, ctx, version_id)
    return run


def visible_agents(db, ctx, runs):
    result = []
    for run in runs:
        try:
            result.append(agent_view(require_current_agent_sources(db, ctx, run)))
        except HTTPException:
            continue
    return result


def run_access(db, ctx, run_id):
    run = require(db.get(m.AgentRun, run_id))
    if run.org_id != ctx.org_id:
        fail(404, 'NOT_FOUND', '任务不存在')
    if run.membership_id == ctx.membership.id:
        return require_current_agent_sources(db, ctx, run)
    if run.purpose == 'content' and ctx.has('teacher'):
        version_access(db, ctx, run.source_version_id)
        return require_current_agent_sources(db, ctx, run)
    if run.attempt_id and teacher_can_view(db, ctx, db.get(m.Attempt, run.attempt_id).membership_id):
        return require_current_agent_sources(db, ctx, run)
    fail(404, 'NOT_FOUND', '任务不存在或无权访问')


def run_context(db, run):
    member = require(db.get(m.Membership, run.membership_id))
    user = require(db.get(m.User, run.owner_id))
    if not member.active or not user.active or member.org_id != run.org_id or member.user_id != user.id:
        fail(403, 'ACCESS_REVOKED', '任务授权已变化')
    ctx = Context(user, member, list(db.scalars(select(m.RoleAssignment).where(m.RoleAssignment.membership_id == member.id))), None)
    need(ctx, 'teacher' if run.purpose == 'content' else 'student')
    if run.attempt_id:
        attempt = require(db.get(m.Attempt, run.attempt_id))
        if attempt.membership_id != member.id or attempt.status == 'draft':
            fail(403, 'ACCESS_REVOKED', '作答状态或授权已变化')
    return ctx


def grading_view(db, ctx, attempt):
    from .learning import current_evaluation
    evaluation = current_evaluation(db, attempt.id)
    suggestion = db.scalar(select(m.EvaluationSuggestion).where(m.EvaluationSuggestion.attempt_id == attempt.id))
    run = db.scalar(select(m.AgentRun).where(m.AgentRun.attempt_id == attempt.id, m.AgentRun.purpose == 'initial_evaluation').order_by(m.AgentRun.created_at.desc()))
    if suggestion:
        suggestion_run = db.get(m.AgentRun, suggestion.run_id)
        try:
            require_current_agent_sources(db, ctx, suggestion_run)
        except HTTPException:
            suggestion, run = None, None
    if attempt.status == 'draft':
        state = '未提交'
    elif evaluation:
        state = '教师已确认' if evaluation['method'] == 'teacher' else '系统已判分'
    elif suggestion:
        state = 'AI初评待教师确认'
    elif run and run.state == 'failed':
        state = 'AI初评失败，待人工处理'
    elif run and run.state in ('queued','running'):
        state = 'AI初评中'
    else:
        state = '待教师评分'
    result = {'grading_state':state, 'ai_suggestion':None}
    if suggestion:
        result['ai_suggestion'] = {'parts':suggestion.parts, 'score':sum(suggestion.parts),
            'feedback':suggestion.feedback,'confirmed':suggestion.confirmed, 'run_id':suggestion.run_id,
            'sources':suggestion_run.output.get('sources',[])}
    elif run:
        result['ai_suggestion'] = {'run_id':run.id,'state':run.state,'error_code':run.error_code}
    return result


def task_group_url(db, task_id):
    relation = db.scalar(select(m.AssignmentTask).where(m.AssignmentTask.task_id == task_id))
    if relation:
        sub = db.get(m.AssignmentSubmission, relation.submission_id)
        return '/assignments/' + sub.assignment_id
    relation = db.scalar(select(m.PracticeTask).where(m.PracticeTask.task_id == task_id))
    if relation:
        return '/practice/' + relation.practice_id
    return None


def evidence_view(db, ctx, records):
    """Only materialized real source chunks; never accept URLs from a model."""
    result, seen = [], set()
    for record in records:
        chunk = require(db.get(m.SourceChunk, record['chunk_id']))
        version, source = version_access(db, ctx, chunk.version_id)
        quote = record.get('quote', chunk.text)
        key = (chunk.id, quote)
        if key in seen:
            continue
        seen.add(key)
        doc = db.scalar(select(m.SourceDocument.id).where(m.SourceDocument.version_id == version.id))
        result.append({'chunk_id':chunk.id,'version_id':version.id,'source_title':source.title,
            'version':version.number,'position':chunk.position,'heading':chunk.heading,'text':quote,
            'page':chunk.position if doc else None,'url':f'/sources/{version.id}?page={chunk.position}&chunk={chunk.id}'})
    return result


def question_evidence(db, ctx, question_id):
    records = db.scalars(select(m.ArtifactEvidence).where(m.ArtifactEvidence.artifact_kind == 'question', m.ArtifactEvidence.artifact_id == question_id))
    visible = []
    for record in records:
        chunk = db.get(m.SourceChunk, record.chunk_id)
        try:
            version_access(db, ctx, chunk.version_id, published=True)
        except HTTPException:
            continue
        visible.append({'chunk_id':record.chunk_id,'quote':record.quote})
    return evidence_view(db,ctx,visible)


def assignment_access(db, ctx, assignment_id):
    assignment = require(db.get(m.Assignment, assignment_id))
    if assignment.org_id != ctx.org_id:
        fail(404,'NOT_FOUND','作业不存在')
    if ctx.has('teacher'):
        teacher_class(db,ctx,assignment.class_id)
    elif ctx.has('student'):
        if not db.scalar(select(m.ClassMember.id).where(m.ClassMember.class_id == assignment.class_id, m.ClassMember.membership_id == ctx.membership.id)):
            fail(404,'NOT_FOUND','作业不存在或未布置给你')
    else:
        fail(403,'ROLE_REQUIRED','需要学生或教师角色')
    return assignment


def start_assignment(db, ctx, assignment_id):
    from .learning import create_attempt
    need(ctx,'student')
    # Serialize the first open for this student, even before a submission exists.
    db.get(m.Membership, ctx.membership.id, with_for_update=True)
    assignment = assignment_access(db,ctx,assignment_id)
    sub = db.scalar(select(m.AssignmentSubmission).where(m.AssignmentSubmission.assignment_id == assignment.id, m.AssignmentSubmission.membership_id == ctx.membership.id))
    if sub:
        return sub
    sub = m.AssignmentSubmission(assignment_id=assignment.id, membership_id=ctx.membership.id)
    db.add(sub)
    db.flush()
    for position, qid in enumerate(assignment.question_ids):
        q = require(db.get(m.QuestionVersion,qid))
        version_access(db,ctx,q.source_version_id,published=True)
        task = m.LearningTask(membership_id=ctx.membership.id, question_version_id=qid,
            task_key=f'assignment:{assignment.id}:{position}',mode='assignment',reason=assignment.title,
            estimated_minutes=10 if q.kind=='essay' else 5)
        db.add(task)
        db.flush()
        db.add(m.AssignmentTask(submission_id=sub.id,task_id=task.id,position=position))
        create_attempt(db,ctx,task.id)
    db.flush()
    return sub


def group_tasks(db, group, practice=False):
    cls = m.PracticeTask if practice else m.AssignmentTask
    field = cls.practice_id if practice else cls.submission_id
    return list(db.scalars(select(cls).where(field == group.id).order_by(cls.position)))


def group_view(db, ctx, group, practice=False):
    from .learning import task_view, attempt_view
    if group.membership_id != ctx.membership.id:
        fail(404,'NOT_FOUND','作答不存在')
    assignment = None if practice else db.get(m.Assignment,group.assignment_id)
    entries = []
    for link in group_tasks(db,group,practice):
        task = db.get(m.LearningTask,link.task_id)
        attempt = db.scalar(select(m.Attempt).where(m.Attempt.task_id == task.id))
        entries.append({'task':task_view(db,task),'attempt':attempt_view(db,ctx,attempt)})
    return {'id':group.id,'title':'针对性练习' if practice else assignment.title,'state':group.state,
            'due_at':None if practice else assignment.due_at,'entries':entries,
            'origin_attempt_id':group.origin_attempt_id if practice else None}


def submit_group(db, ctx, group, practice=False):
    from .learning import submit_attempt
    if group.membership_id != ctx.membership.id:
        fail(404,'NOT_FOUND','作答不存在')
    if group.state != 'draft':
        return group_view(db,ctx,group,practice)
    if not practice:
        assignment = assignment_access(db,ctx,group.assignment_id)
        if assignment.due_at and datetime.fromisoformat(assignment.due_at) < datetime.now(timezone.utc):
            fail(409,'ASSIGNMENT_CLOSED','作业已截止，已保存草稿不会被删除')
    attempts = []
    missing = []
    for link in group_tasks(db,group,practice):
        attempt = db.scalar(select(m.Attempt).where(m.Attempt.task_id == link.task_id))
        q = db.get(m.QuestionVersion,attempt.question_version_id)
        if (q.kind=='essay' and not attempt.response_text.strip()) or (q.kind!='essay' and not attempt.answer):
            missing.append(str(link.position+1))
        attempts.append(attempt)
    if missing:
        fail(422,'INCOMPLETE_ASSIGNMENT','请先完成第 ' + '、'.join(missing) + ' 题')
    for attempt in attempts:
        submit_attempt(db,ctx,attempt.id,group_submit=True)
        q = db.get(m.QuestionVersion,attempt.question_version_id)
        if q.kind=='essay':
            new_run(db,ctx,'initial_evaluation',attempt.id,{},q.source_version_id,attempt.id)
    group.state = 'submitted'
    if not practice:
        group.submitted_at = m.now()
    audit(db,ctx,'practice.submit' if practice else 'assignment.submit',group.id)
    db.flush()
    return group_view(db,ctx,group,practice)


def remediation_view(db, ctx, remediation):
    from .learning import owned_attempt, current_evaluation
    attempt = owned_attempt(db,ctx,remediation.attempt_id)
    q = db.get(m.QuestionVersion,attempt.question_version_id)
    answer = set(q.answer)
    selected = set(attempt.answer)
    eval_ = current_evaluation(db,attempt.id)
    diagnosis = db.scalar(select(m.AgentRun).where(m.AgentRun.attempt_id==attempt.id,m.AgentRun.purpose=='diagnosis').order_by(m.AgentRun.created_at.desc()))
    practices = list(db.scalars(select(m.AgentRun).where(m.AgentRun.attempt_id==attempt.id,m.AgentRun.purpose=='targeted').order_by(m.AgentRun.created_at.desc())))
    cards = list(db.scalars(select(m.CardVersion).where(m.CardVersion.knowledge_id==q.knowledge_id,m.CardVersion.status=='published',m.CardVersion.org_id==ctx.org_id)))
    public_cards=[]
    for c in cards:
        v=db.get(m.SourceVersion,c.source_version_id)
        if v.status=='published' and source_allowed(db,ctx,db.get(m.Source,v.source_id)):
            public_cards.append({'id':c.id,'title':c.title,'body':c.body,'source_version_id':c.source_version_id})
    practice_results=[]
    for practice in db.scalars(select(m.TargetedPractice).where(m.TargetedPractice.origin_attempt_id==attempt.id,m.TargetedPractice.membership_id==ctx.membership.id)):
        attempts=[]
        for link in group_tasks(db,practice,True):
            a=db.scalar(select(m.Attempt).where(m.Attempt.task_id==link.task_id))
            e=current_evaluation(db,a.id)
            attempts.append({'id':a.id,'grading_state':grading_view(db,ctx,a)['grading_state'],
                'independent_correct':bool(e and e['score']==db.get(m.QuestionVersion,a.question_version_id).max_score and a.hint_level==0)})
        practice_results.append({'id':practice.id,'state':practice.state,'total':len(attempts),
            'independent_correct':sum(a['independent_correct'] for a in attempts),'attempts':attempts})
    return {'id':remediation.id,'attempt_id':attempt.id,'task_id':attempt.task_id,'prompt':q.prompt,'kind':q.kind,
        'options':q.options,'selected':attempt.answer,'correct_answer':q.answer,'wrong_options':sorted(selected-answer),
        'missing_options':sorted(answer-selected),'response_text':attempt.response_text,'process':attempt.process,
        'hint_level':attempt.hint_level,'explanation':q.explanation,'evaluation':eval_,
        'sources':question_evidence(db,ctx,q.id),'cards':public_cards,'group_url':task_group_url(db,attempt.task_id),
        'resolved':bool(eval_ and eval_['score']==q.max_score and attempt.hint_level==0) or any(p['state']=='submitted' and p['total']>0 and p['independent_correct']==p['total'] for p in practice_results),
        'practice_results':practice_results,
        'diagnosis':next(iter(visible_agents(db,ctx,[diagnosis])),None) if diagnosis else None,
        'practices':visible_agents(db,ctx,practices)}
