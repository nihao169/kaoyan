from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, func
from . import models as m
from . import schemas as s
from . import learning as l
from .auth import context, need
from .content import retrieve, version_access, available_questions
from .db import get_db
from .errors import fail, require
from .api_common import entity, idempotent, no_active_diagnostic, EnvelopeRoute
from .workflows import grading_view

router = APIRouter(route_class=EnvelopeRoute)


def student_context(ctx=Depends(context)):
    need(ctx, 'student')
    return ctx


@router.get('/goals/current', response_model=s.GoalInput | None)
def goal(ctx=Depends(student_context), db=Depends(get_db)):
    row = db.scalar(select(m.Goal).where(m.Goal.membership_id == ctx.membership.id))
    return entity(row, 'subject_id', 'exam_year', 'target_score', 'daily_minutes') if row else None


@router.put('/goals/current')
def put_goal(data: s.GoalInput, ctx=Depends(student_context), db=Depends(get_db)):
    require(db.get(m.Subject, data.subject_id))
    row = db.scalar(select(m.Goal).where(m.Goal.membership_id == ctx.membership.id, m.Goal.subject_id == data.subject_id))
    previous = entity(row, 'exam_year', 'target_score', 'daily_minutes') if row else None
    if not row:
        row = m.Goal(membership_id=ctx.membership.id, **data.model_dump())
        db.add(row)
    else:
        for k, v in data.model_dump().items():
            setattr(row, k, v)
    audit_data = {'before': previous, 'after': data.model_dump()}
    from .content import audit
    audit(db, ctx, 'goal.updated', ctx.membership.id, audit_data)
    return data.model_dump()


@router.post('/diagnostics')
def start(data: s.DiagnosticInput, ctx=Depends(student_context), db=Depends(get_db)):
    d = l.start_diagnostic(db, ctx, data.subject_id)
    return {'id': d.id, 'status': d.status}


@router.get('/diagnostics/current', response_model=s.DiagnosticOutput | None)
def current_diag(ctx=Depends(student_context), db=Depends(get_db)):
    d = db.scalar(select(m.DiagnosticSession).where(m.DiagnosticSession.membership_id == ctx.membership.id).order_by(m.DiagnosticSession.created_at.desc()))
    if not d:
        return None
    tasks = list(db.scalars(select(m.LearningTask).where(m.LearningTask.diagnostic_id == d.id).order_by(m.LearningTask.created_at, m.LearningTask.id)))
    return {'id': d.id, 'status': d.status, 'tasks': [l.task_view(db, t) for t in tasks]}


@router.post('/diagnostics/{diagnostic_id}/submit')
def finish(diagnostic_id: str, ctx=Depends(student_context), db=Depends(get_db)):
    d = l.finish_diagnostic(db, ctx, diagnostic_id)
    return {'id': d.id, 'status': d.status}


@router.get('/plans/today', response_model=s.PlanOutput)
def plan(ctx=Depends(student_context), db=Depends(get_db)):
    goal = db.scalar(select(m.Goal).where(m.Goal.membership_id == ctx.membership.id))
    if goal:
        l.ensure_plan(db, ctx, goal.subject_id)
    active_diagnostic = db.scalar(select(m.DiagnosticSession.id).where(m.DiagnosticSession.membership_id == ctx.membership.id, m.DiagnosticSession.status == 'active'))
    if not active_diagnostic:
        for schedule in db.scalars(select(m.ReviewSchedule).where(m.ReviewSchedule.membership_id == ctx.membership.id, m.ReviewSchedule.state == 'scheduled', m.ReviewSchedule.due_at <= m.now(), m.ReviewSchedule.task_id.is_(None))):
            # Withdrawn sources are a visible content gap, not a reason to fail the entire plan.
            original = db.get(m.Attempt, schedule.attempt_id)
            question = db.get(m.QuestionVersion, original.question_version_id)
            if any(q.question_id == question.question_id for q in available_questions(db, ctx, schedule.knowledge_id)):
                l.materialize_review(db, ctx, schedule)
    tasks = list(db.scalars(select(m.LearningTask).where(m.LearningTask.membership_id == ctx.membership.id, m.LearningTask.mode != 'diagnostic').order_by(m.LearningTask.created_at, m.LearningTask.id)))
    remaining = goal.daily_minutes if goal else 30
    local_zone = timezone(timedelta(hours=8))
    today = datetime.now(local_zone).date()
    for done_task in tasks:
        attempt = db.scalar(select(m.Attempt).where(m.Attempt.task_id == done_task.id))
        if attempt and attempt.submitted_at and datetime.fromisoformat(attempt.submitted_at).astimezone(local_zone).date() == today:
            remaining = max(0, remaining - done_task.estimated_minutes)
    picked = []
    def daily_priority(task):
        base = 0 if task.mode == 'review' else 1 if task.mode == 'verification' else 2
        analytical = db.get(m.QuestionVersion, task.question_version_id).kind == 'essay'
        emphasis = 0 if goal and goal.target_score >= 80 and analytical else 1
        return base, emphasis, task.created_at
    for task in sorted(tasks, key=daily_priority):
        if task.state != 'todo':
            continue
        if task.estimated_minutes <= remaining:
            picked.append(l.task_view(db, task))
            remaining -= task.estimated_minutes
    return {'tasks': picked, 'all_tasks': [l.task_view(db, t) for t in tasks], 'daily_minutes': goal.daily_minutes if goal else 30,
            'content_note': '暂无任务时请先设置目标、完成诊断，并确认教师已发布教学内容。'}


@router.get('/tasks/{task_id}', response_model=s.TaskOutput)
def task(task_id: str, ctx=Depends(student_context), db=Depends(get_db)):
    task, _ = l.owned_task(db, ctx, task_id)
    return l.task_view(db, task)


@router.post('/tasks/{task_id}/attempts', response_model=s.AttemptOutput, response_model_exclude_unset=True)
def create_attempt(task_id: str, ctx=Depends(student_context), db=Depends(get_db)):
    return l.attempt_view(db, ctx, l.create_attempt(db, ctx, task_id))


@router.get('/attempts/{attempt_id}', response_model=s.AttemptOutput, response_model_exclude_unset=True)
def attempt(attempt_id: str, ctx=Depends(student_context), db=Depends(get_db)):
    return l.attempt_view(db, ctx, l.owned_attempt(db, ctx, attempt_id))


@router.patch('/attempts/{attempt_id}/draft', response_model=s.AttemptOutput, response_model_exclude_unset=True)
def draft(attempt_id: str, data: s.DraftInput, ctx=Depends(student_context), db=Depends(get_db)):
    return l.attempt_view(db, ctx, l.save_draft(db, ctx, attempt_id, data))


@router.post('/attempts/{attempt_id}/submit', response_model=s.AttemptOutput, response_model_exclude_unset=True)
def submit(attempt_id: str, request: Request, ctx=Depends(student_context), db=Depends(get_db)):
    return idempotent(db, ctx, request, f'attempt-submit:{attempt_id}', {}, lambda: l.attempt_view(db, ctx, l.submit_attempt(db, ctx, attempt_id)))


@router.post('/attempts/{attempt_id}/hints', response_model=s.HintOutput)
def hint(attempt_id: str, data: s.HintInput, ctx=Depends(student_context), db=Depends(get_db)):
    no_active_diagnostic(db, ctx)
    a = l.owned_attempt(db, ctx, attempt_id)
    task, q = l.owned_task(db, ctx, a.task_id)
    if task.mode == 'diagnostic':
        fail(403, 'DIAGNOSTIC_RESTRICTION', '诊断不允许提示')
    if a.status != 'draft':
        fail(409, 'ALREADY_SUBMITTED', '提交后请查看解析')
    if data.level > a.hint_level + 1:
        fail(409, 'HINT_ORDER', '请按顺序逐级查看提示')
    a.hint_level = max(a.hint_level, data.level)
    a.revision += 1
    event_key = f'level-{data.level}'
    if not db.scalar(select(m.LearningEvent.id).where(m.LearningEvent.attempt_id == a.id, m.LearningEvent.kind == 'hint', m.LearningEvent.event_key == event_key)):
        db.add(m.LearningEvent(attempt_id=a.id, kind='hint', event_key=event_key, payload={'level': data.level, 'source_version_id': q.source_version_id}))
    return {'text': q.hints[data.level-1], 'level': data.level, 'origin': '审核教学内容', 'revision': a.revision, 'sources': retrieve(db, ctx, knowledge_id=q.knowledge_id, version_id=q.source_version_id)}


@router.get('/remediations', response_model=list[s.RemediationOutput])
def remediations(ctx=Depends(student_context), db=Depends(get_db)):
    no_active_diagnostic(db, ctx)
    rows = db.execute(select(m.Remediation, m.Attempt).join(m.Attempt).where(m.Attempt.membership_id == ctx.membership.id).order_by(m.Remediation.created_at.desc()))
    items = []
    for r, a in rows:
        q = db.get(m.QuestionVersion, a.question_version_id)
        card = db.get(m.CardVersion, r.card_version_id) if r.card_version_id else None
        if card:
            version_access(db, ctx, card.source_version_id)
        read = db.scalar(select(m.LearningEvent.id).where(m.LearningEvent.attempt_id == a.id, m.LearningEvent.kind == 'card_read', m.LearningEvent.event_key == (card.id if card else 'none')))
        ev = l.current_evaluation(db, a.id)
        verified = db.scalar(select(m.Attempt).where(m.Attempt.task_id == r.verification_task_id)) if r.verification_task_id else None
        verified_ev = l.current_evaluation(db, verified.id) if verified else None
        independently_verified = bool(verified and verified_ev and verified.hint_level == 0 and verified_ev['score'] == db.get(m.QuestionVersion, verified.question_version_id).max_score)
        items.append({**entity(r, 'id', 'attempt_id', 'cause', 'cause_status', 'verification_task_id'), 'prompt': q.prompt,
                      'resolved': independently_verified or bool(ev and ev['score'] == q.max_score and a.hint_level == 0),
                      'card': entity(card, 'id', 'title', 'body', 'source_version_id') if card else None, 'read': bool(read)})
    return items


def owned_remediation(db, ctx, remediation_id):
    r = require(db.get(m.Remediation, remediation_id))
    a = l.owned_attempt(db, ctx, r.attempt_id)
    return r, a


@router.post('/remediations/{remediation_id}/cause')
def confirm_cause(remediation_id: str, data: s.CauseInput, ctx=Depends(student_context), db=Depends(get_db)):
    no_active_diagnostic(db, ctx)
    r, _ = owned_remediation(db, ctx, remediation_id)
    l.change_cause(db, ctx, r, data.cause)
    return {'confirmed': True}


@router.post('/remediations/{remediation_id}/read')
def read_card(remediation_id: str, ctx=Depends(student_context), db=Depends(get_db)):
    no_active_diagnostic(db, ctx)
    r, a = owned_remediation(db, ctx, remediation_id)
    if r.cause_status != 'confirmed':
        fail(409, 'CAUSE_REQUIRED', '请先确认错因')
    card = require(db.get(m.CardVersion, r.card_version_id), '暂无审核知识卡，请教师补充')
    version_access(db, ctx, card.source_version_id, published=True)
    if not db.scalar(select(m.LearningEvent.id).where(m.LearningEvent.attempt_id == a.id, m.LearningEvent.kind == 'card_read', m.LearningEvent.event_key == card.id)):
        db.add(m.LearningEvent(attempt_id=a.id, kind='card_read', event_key=card.id, payload={'card_version_id': card.id}))
    if not r.verification_task_id:
        old_q = db.get(m.QuestionVersion, a.question_version_id)
        used = set(db.scalars(select(m.QuestionVersion.question_id).join(m.LearningTask, m.LearningTask.question_version_id == m.QuestionVersion.id).where(m.LearningTask.membership_id == ctx.membership.id)))
        q = next((q for q in available_questions(db, ctx, old_q.knowledge_id) if q.question_id not in used and q.kind != 'essay'), None)
        if q:
            task = m.LearningTask(membership_id=ctx.membership.id, question_version_id=q.id, task_key=f'verification:{r.id}', mode='verification', reason=f'补学后独立验证：{r.cause}')
            db.add(task)
            db.flush()
            r.verification_task_id = task.id
    return {'task_id': r.verification_task_id, 'message': '已记录阅读；请独立完成新题' if r.verification_task_id else '待补充验证题：审核题库中没有尚未使用的新题'}


@router.get('/review-schedules', response_model=list[s.ReviewScheduleOutput])
def reviews(ctx=Depends(student_context), db=Depends(get_db)):
    result = []
    for r in db.scalars(select(m.ReviewSchedule).where(m.ReviewSchedule.membership_id == ctx.membership.id).order_by(m.ReviewSchedule.due_at)):
        kp = db.get(m.KnowledgePoint, r.knowledge_id)
        result.append({**entity(r, 'id', 'stage', 'due_at', 'state', 'task_id', 'policy'), 'knowledge': kp.name, 'due': r.due_at <= m.now()})
    return result


@router.post('/review-schedules/{schedule_id}/attempts')
def start_review(schedule_id: str, ctx=Depends(student_context), db=Depends(get_db)):
    no_active_diagnostic(db, ctx)
    r = require(db.get(m.ReviewSchedule, schedule_id))
    if r.membership_id != ctx.membership.id:
        fail(404, 'NOT_FOUND', '复习任务不存在')
    return {'task_id': l.materialize_review(db, ctx, r)}


@router.post('/evaluations/{evaluation_id}/review-cases')
def appeal(evaluation_id: str, data: s.ReasonInput, ctx=Depends(student_context), db=Depends(get_db)):
    ev = require(db.get(m.Evaluation, evaluation_id))
    l.owned_attempt(db, ctx, ev.attempt_id)
    if db.scalar(select(m.ReviewCase.id).where(m.ReviewCase.evaluation_id == ev.id, m.ReviewCase.status == 'open')):
        fail(409, 'CASE_EXISTS', '已有待处理异议')
    case = m.ReviewCase(evaluation_id=ev.id, reason=data.reason)
    db.add(case)
    db.flush()
    return {'id': case.id}


@router.get('/attempt-history', response_model=list[s.HistoryOutput])
def history(ctx=Depends(student_context), db=Depends(get_db)):
    no_active_diagnostic(db, ctx)
    return [{'id': a.id, 'status': a.status, 'created_at': a.created_at, 'task': l.task_view(db, db.get(m.LearningTask, a.task_id)),
             'evaluation': l.current_evaluation(db, a.id) if not db.get(m.LearningTask, a.task_id).diagnostic_id or db.get(m.DiagnosticSession, db.get(m.LearningTask, a.task_id).diagnostic_id).status in ('completed','archived') else None,
             'grading_state': grading_view(db,a)['grading_state']}
            for a in db.scalars(select(m.Attempt).where(m.Attempt.membership_id == ctx.membership.id).order_by(m.Attempt.created_at.desc()))]
