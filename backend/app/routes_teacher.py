from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from . import models as m
from . import schemas as s
from .auth import context, need, teacher_can_view
from .db import get_db
from .errors import fail, require
from . import learning as l
from .api_common import entity, idempotent, EnvelopeRoute
from .workflows import grading_view

router = APIRouter(route_class=EnvelopeRoute)


def teacher(ctx=Depends(context)):
    need(ctx, 'teacher')
    return ctx


@router.get('/teacher/overview', response_model=list[s.TeacherOverviewOutput])
def overview(ctx=Depends(teacher), db=Depends(get_db)):
    students = []
    for member, user in db.execute(select(m.Membership, m.User).join(m.User).where(m.Membership.org_id == ctx.org_id)):
        if not teacher_can_view(db, ctx, member.id) or not db.scalar(select(m.RoleAssignment.id).where(m.RoleAssignment.membership_id == member.id, m.RoleAssignment.role == 'student')):
            continue
        attempts = list(db.scalars(select(m.Attempt).where(m.Attempt.membership_id == member.id, m.Attempt.status != 'draft')))
        evals = [l.current_evaluation(db, a.id) for a in attempts]
        students.append({'id': member.id, 'name': user.name, 'attempts': len(attempts), 'pending': sum(a.status == 'pending_teacher' for a in attempts),
                         'score': sum(e['score'] for e in evals if e),
                         'max_score': sum(db.get(m.QuestionVersion, a.question_version_id).max_score for a, ev in zip(attempts, evals) if ev)})
    return students


@router.get('/teacher/attempts', response_model=list[s.TeacherAttemptOutput])
def attempts(assignment_id: str | None = None, ctx=Depends(teacher), db=Depends(get_db)):
    result = []
    for a in db.scalars(select(m.Attempt).where(m.Attempt.status != 'draft').order_by(m.Attempt.created_at.desc())):
        if assignment_id and not db.scalar(select(m.AssignmentTask.id).join(m.AssignmentSubmission,m.AssignmentTask.submission_id==m.AssignmentSubmission.id).where(m.AssignmentTask.task_id==a.task_id,m.AssignmentSubmission.assignment_id==assignment_id)):
            continue
        if not teacher_can_view(db, ctx, a.membership_id):
            continue
        member = db.get(m.Membership, a.membership_id)
        q = db.get(m.QuestionVersion, a.question_version_id)
        result.append({**entity(a, 'id', 'status', 'submitted_at', 'hint_level'), 'student': db.get(m.User, member.user_id).name,
                       'kind': q.kind, 'prompt': q.prompt, 'evaluation': l.current_evaluation(db, a.id),
                       **grading_view(db, a)})
    return result


@router.get('/teacher/attempts/{attempt_id}', response_model=s.AttemptOutput, response_model_exclude_unset=True)
def attempt(attempt_id: str, ctx=Depends(teacher), db=Depends(get_db)):
    a = l.owned_attempt(db, ctx, attempt_id, teacher=True)
    if not teacher_can_view(db, ctx, a.membership_id):
        fail(404, 'NOT_FOUND', '作答不存在')
    data = l.attempt_view(db, ctx, a, teacher=True)
    ev = db.scalar(select(m.Evaluation).where(m.Evaluation.attempt_id == a.id))
    data['revisions'] = [entity(r, 'number', 'score', 'feedback', 'parts', 'method', 'evaluator_id', 'created_at') for r in db.scalars(select(m.EvaluationRevision).where(m.EvaluationRevision.evaluation_id == ev.id).order_by(m.EvaluationRevision.number))] if ev else []
    data['events'] = [entity(e, 'kind', 'payload', 'created_at') for e in db.scalars(select(m.LearningEvent).where(m.LearningEvent.attempt_id == a.id))]
    return data


@router.post('/teacher/attempts/{attempt_id}/evaluations', response_model=s.EvaluationOutput)
def grade(attempt_id: str, data: s.EvaluationInput, request: Request, ctx=Depends(teacher), db=Depends(get_db)):
    return idempotent(db, ctx, request, f'grade:{attempt_id}', data.model_dump(), lambda: l.score_essay(db, ctx, attempt_id, data))


@router.get('/teacher/review-cases', response_model=list[s.ReviewCaseOutput])
def review_cases(ctx=Depends(teacher), db=Depends(get_db)):
    result = []
    for case in db.scalars(select(m.ReviewCase).order_by(m.ReviewCase.created_at.desc())):
        ev = db.get(m.Evaluation, case.evaluation_id)
        a = db.get(m.Attempt, ev.attempt_id)
        if teacher_can_view(db, ctx, a.membership_id):
            result.append({**entity(case, 'id', 'reason', 'status', 'resolution', 'created_at'), 'attempt_id': a.id,
                           'evaluation': l.current_evaluation(db, a.id), 'prompt': db.get(m.QuestionVersion, a.question_version_id).prompt})
    return result


@router.post('/review-cases/{case_id}/resolve', response_model=s.EvaluationOutput)
def resolve(case_id: str, data: s.ResolveInput, request: Request, ctx=Depends(teacher), db=Depends(get_db)):
    case = require(db.get(m.ReviewCase, case_id))
    ev = db.get(m.Evaluation, case.evaluation_id)
    a = db.get(m.Attempt, ev.attempt_id)
    if not teacher_can_view(db, ctx, a.membership_id):
        fail(404, 'NOT_FOUND', '复核记录不存在')
    def run():
        if case.status != 'open':
            fail(409, 'CASE_CLOSED', '异议已处理')
        return l.score_essay(db, ctx, a.id, data, case=case)
    return idempotent(db, ctx, request, f'case-resolve:{case_id}', data.model_dump(), run)
