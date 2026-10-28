from datetime import datetime, timedelta
from sqlalchemy import select, func, update
from . import models as m
from .auth import Context, teacher_can_view
from .errors import fail, require
from .content import available_questions, version_access, retrieve, audit
from .scoring import score as score_answer
from .api_common import no_active_diagnostic


def owned_task(db, ctx, task_id):
    task = require(db.get(m.LearningTask, task_id))
    if task.membership_id != ctx.membership.id:
        fail(404, 'NOT_FOUND', '学习任务不存在')
    if task.mode != 'diagnostic':
        no_active_diagnostic(db, ctx)
    q = require(db.get(m.QuestionVersion, task.question_version_id))
    version_access(db, ctx, q.source_version_id, published=task.state == 'todo')
    return task, q


def owned_attempt(db, ctx, attempt_id, teacher=False):
    a = require(db.get(m.Attempt, attempt_id))
    if a.membership_id != ctx.membership.id and not (teacher and teacher_can_view(db, ctx, a.membership_id)):
        fail(404, 'NOT_FOUND', '作答不存在')
    return a


def current_evaluation(db, attempt_id):
    ev = db.scalar(select(m.Evaluation).where(m.Evaluation.attempt_id == attempt_id))
    if not ev:
        return None
    rev = db.scalar(select(m.EvaluationRevision).where(m.EvaluationRevision.evaluation_id == ev.id, m.EvaluationRevision.number == ev.current_revision))
    return {'id': ev.id, 'revision': ev.current_revision, 'score': rev.score, 'parts': rev.parts, 'feedback': rev.feedback, 'method': rev.method}


def question_view(q, reveal=False):
    data = {'id': q.id, 'question_id': q.question_id, 'number': q.number, 'kind': q.kind, 'prompt': q.prompt,
            'options': q.options, 'max_score': q.max_score, 'knowledge_id': q.knowledge_id}
    if reveal:
        data.update(answer=q.answer, explanation=q.explanation, rubric=q.rubric, source_version_id=q.source_version_id)
    return data


def attempt_view(db, ctx, a, teacher=False):
    task = db.get(m.LearningTask, a.task_id)
    if not teacher and task.mode != 'diagnostic':
        no_active_diagnostic(db, ctx)
    q = db.get(m.QuestionVersion, a.question_version_id)
    version, _ = version_access(db, ctx, q.source_version_id)
    diagnostic = db.get(m.DiagnosticSession, task.diagnostic_id) if task.diagnostic_id else None
    reveal = teacher or (a.status != 'draft' and (not diagnostic or diagnostic.status == 'completed'))
    remediation = db.scalar(select(m.Remediation).where(m.Remediation.attempt_id == a.id))
    result = {'id': a.id, 'status': a.status, 'task_id': task.id, 'mode': task.mode, 'reason': task.reason,
              'answer': a.answer, 'response_text': a.response_text, 'process': a.process,
              'duration_seconds': a.duration_seconds, 'hint_level': a.hint_level, 'revision': a.revision,
              'question': question_view(q, reveal), 'evaluation': current_evaluation(db, a.id) if reveal else None,
              'content_status': version.status, 'remediation_id': remediation.id if remediation else None,
              'submitted_at': a.submitted_at}
    if reveal:
        result['sources'] = retrieve(db, ctx, knowledge_id=q.knowledge_id, version_id=q.source_version_id)
    return result


def create_attempt(db, ctx, task_id):
    task, q = owned_task(db, ctx, task_id)
    existing = db.scalar(select(m.Attempt).where(m.Attempt.membership_id == ctx.membership.id, m.Attempt.task_id == task.id))
    if existing:
        return existing
    attempt = m.Attempt(membership_id=ctx.membership.id, task_id=task.id, question_version_id=q.id)
    db.add(attempt)
    db.flush()
    return attempt


def validate_answer(q, data):
    if q.kind == 'essay':
        if data.answer:
            fail(422, 'INVALID_ANSWER', '分析题不能提交选项')
    else:
        if len(set(data.answer)) != len(data.answer) or not set(data.answer).issubset(q.options):
            fail(422, 'INVALID_ANSWER', '选项无效或重复')
        if q.kind == 'single' and len(data.answer) > 1:
            fail(422, 'INVALID_ANSWER', '单选题只能选择一项')


def save_draft(db, ctx, attempt_id, data):
    a = owned_attempt(db, ctx, attempt_id)
    task, q = owned_task(db, ctx, a.task_id)
    if a.status != 'draft':
        fail(409, 'ALREADY_SUBMITTED', '提交后原始作答不能修改')
    validate_answer(q, data)
    values = data.model_dump(exclude={'revision'})
    changed = db.execute(update(m.Attempt).where(m.Attempt.id == a.id, m.Attempt.status == 'draft', m.Attempt.revision == data.revision).values(**values, revision=data.revision + 1))
    if changed.rowcount != 1:
        fail(409, 'STALE_REVISION', '草稿已变化，请重新读取')
    db.flush()
    db.refresh(a)
    return a


def submit_attempt(db, ctx, attempt_id):
    a = owned_attempt(db, ctx, attempt_id)
    if a.status != 'draft':
        return a
    task, q = owned_task(db, ctx, a.task_id)
    if (q.kind == 'essay' and not a.response_text.strip()) or (q.kind != 'essay' and not a.answer):
        fail(422, 'ANSWER_REQUIRED', '请先保存答案再提交')
    state = 'pending_teacher' if q.kind == 'essay' else 'graded'
    changed = db.execute(update(m.Attempt).where(m.Attempt.id == a.id, m.Attempt.status == 'draft').values(status=state, submitted_at=m.now(), revision=a.revision + 1))
    if changed.rowcount != 1:
        fail(409, 'SUBMISSION_CONFLICT', '作答正在提交，请刷新查看')
    db.refresh(a)
    task.state = 'pending_teacher' if q.kind == 'essay' else 'completed'
    if q.kind != 'essay':
        policy = require(db.get(m.ScoringPolicyVersion, q.policy_id))
        try:
            score = score_answer(policy.strategy, policy.version, q.answer, a.answer, q.max_score)
        except ValueError:
            fail(409, 'SCORING_POLICY_UNAVAILABLE', '评分规则版本不可用，请联系教师')
        ev = m.Evaluation(attempt_id=a.id)
        db.add(ev)
        db.flush()
        db.add(m.EvaluationRevision(evaluation_id=ev.id, number=1, score=score, feedback='答案正确。' if score else '答案与审核标准不一致，请结合资料补学并确认错因。', method='rule'))
        db.flush()
        if task.mode != 'diagnostic':
            derive_outcome(db, ctx, a)
    db.add(m.OutboxEvent(event_key=f'attempt-submitted:{a.id}', attempt_id=a.id))
    audit(db, ctx, 'attempt.submit', a.id)
    db.flush()
    return a


def add_review(db, a, knowledge_id, stage=1, anchor=None):
    existing = db.scalar(select(m.ReviewSchedule).where(m.ReviewSchedule.attempt_id == a.id, m.ReviewSchedule.stage == stage))
    if existing and existing.state != 'cancelled':
        return
    anchor = anchor or m.now()
    due = (datetime.fromisoformat(anchor) + timedelta(days={1: 1, 2: 3, 3: 7}[stage])).isoformat()
    if existing:
        existing.state, existing.anchor_at, existing.due_at = 'scheduled', anchor, due
    else:
        db.add(m.ReviewSchedule(membership_id=a.membership_id, attempt_id=a.id, knowledge_id=knowledge_id, stage=stage, anchor_at=anchor, due_at=due))


def derive_outcome(db, ctx, a):
    q = db.get(m.QuestionVersion, a.question_version_id)
    evaluation = current_evaluation(db, a.id)
    if not evaluation:
        return
    correct = evaluation['score'] == q.max_score and a.hint_level == 0
    if not correct:
        remediation = db.scalar(select(m.Remediation).where(m.Remediation.attempt_id == a.id))
        if not remediation:
            cards = list(db.scalars(select(m.CardVersion).where(m.CardVersion.org_id == ctx.org_id, m.CardVersion.knowledge_id == q.knowledge_id, m.CardVersion.status == 'published').order_by(m.CardVersion.number.desc())))
            card = next((c for c in cards if _card_allowed(db, ctx, c)), None)
            db.add(m.Remediation(attempt_id=a.id, card_version_id=card.id if card else None))
        # Cancel only future stages generated from this evidence; preserve all history.
        for r in db.scalars(select(m.ReviewSchedule).where(m.ReviewSchedule.attempt_id == a.id, m.ReviewSchedule.state == 'scheduled')):
            r.state = 'cancelled'
    active_review = db.scalar(select(m.ReviewSchedule).where(m.ReviewSchedule.task_id == a.task_id))
    if active_review:
        active_review.state = 'completed' if correct else 'needs_remediation'
        if not correct:
            for later in db.scalars(select(m.ReviewSchedule).where(m.ReviewSchedule.attempt_id == active_review.attempt_id, m.ReviewSchedule.stage > active_review.stage, m.ReviewSchedule.state == 'scheduled')):
                later.state = 'cancelled'
        if correct and active_review.stage < 3:
            original = db.get(m.Attempt, active_review.attempt_id)
            add_review(db, original, q.knowledge_id, active_review.stage + 1, active_review.anchor_at)
    elif correct:
        add_review(db, a, q.knowledge_id)
    kind = 'independent_correct' if correct else 'needs_remediation'
    key = f"evaluation-{evaluation['revision']}"
    if not db.scalar(select(m.LearningEvent.id).where(m.LearningEvent.attempt_id == a.id, m.LearningEvent.kind == kind, m.LearningEvent.event_key == key)):
        db.add(m.LearningEvent(attempt_id=a.id, kind=kind, event_key=key, payload={'evaluation_revision': evaluation['revision']}))
    db.flush()


def _card_allowed(db, ctx, card):
    version = db.get(m.SourceVersion, card.source_version_id)
    from .auth import source_allowed
    return version.status == 'published' and source_allowed(db, ctx, db.get(m.Source, version.source_id))


def change_cause(db, ctx, remediation, cause):
    from .auth import source_allowed
    a = db.get(m.Attempt, remediation.attempt_id)
    # Match cards using the learner's permissions, even when a teacher changes the cause.
    member = db.get(m.Membership, a.membership_id)
    learner = Context(db.get(m.User, member.user_id), member,
        list(db.scalars(select(m.RoleAssignment).where(m.RoleAssignment.membership_id == member.id))), None)
    q = db.get(m.QuestionVersion, a.question_version_id)
    old = remediation.cause
    required = list(db.scalars(select(m.Prerequisite.requires_id).where(m.Prerequisite.knowledge_id == q.knowledge_id)))
    targets = [q.knowledge_id] + (required if cause in ('概念混淆', '原理适用') else [])
    cards = list(db.scalars(select(m.CardVersion).where(m.CardVersion.knowledge_id.in_(targets),
        m.CardVersion.org_id == learner.org_id, m.CardVersion.status == 'published').order_by(m.CardVersion.number.desc())))
    allowed = [c for c in cards if _card_allowed(db, learner, c)]
    weak_preconditions = set()
    if cause in ('概念混淆', '原理适用'):
        for knowledge in required:
            evidence = list(db.scalars(select(m.Attempt).join(m.QuestionVersion).where(m.Attempt.membership_id == member.id,
                m.QuestionVersion.knowledge_id == knowledge, m.Attempt.status == 'graded')))
            if not any(a.hint_level == 0 and (current_evaluation(db, a.id) or {}).get('score') == db.get(m.QuestionVersion, a.question_version_id).max_score for a in evidence):
                weak_preconditions.add(knowledge)
    def preference(card):
        rule = db.scalar(select(m.CardRule).where(m.CardRule.card_id == card.id))
        return (0 if card.knowledge_id in weak_preconditions else 1, 0 if rule and cause in rule.causes else 1,
                0 if card.knowledge_id == q.knowledge_id else 1)
    allowed.sort(key=preference)
    selected = allowed[0] if allowed else None
    remediation.card_version_id = selected.id if selected else None
    remediation.cause, remediation.cause_status = cause, 'confirmed'
    db.add(m.LearningEvent(attempt_id=a.id, kind='cause_changed', event_key=m.uid(),
        payload={'before': old, 'after': cause, 'actor_id': ctx.user.id, 'card_version_id': remediation.card_version_id,
                 'prerequisites': required}))


def start_diagnostic(db, ctx, subject_id):
    existing = db.scalar(select(m.DiagnosticSession).where(m.DiagnosticSession.membership_id == ctx.membership.id, m.DiagnosticSession.subject_id == subject_id, m.DiagnosticSession.status == 'active'))
    if existing:
        return existing
    require(db.get(m.Subject, subject_id), '科目不存在')
    d = m.DiagnosticSession(membership_id=ctx.membership.id, subject_id=subject_id)
    db.add(d)
    db.flush()
    questions = available_questions(db, ctx)
    modules = list(db.scalars(select(m.Module).where(m.Module.subject_id == subject_id).order_by(m.Module.position)))
    for module in modules:
        kp_ids = set(db.scalars(select(m.KnowledgePoint.id).where(m.KnowledgePoint.module_id == module.id)))
        q = next((q for q in questions if q.knowledge_id in kp_ids and q.kind != 'essay'), None)
        if q:
            db.add(m.LearningTask(membership_id=ctx.membership.id, question_version_id=q.id, diagnostic_id=d.id,
                                  task_key=f'diagnostic:{d.id}:{module.id}', mode='diagnostic', reason=f'{module.name}代表题；诊断期间不提供提示'))
    db.flush()
    if not db.scalar(select(m.LearningTask.id).where(m.LearningTask.diagnostic_id == d.id)):
        fail(409, 'CONTENT_REQUIRED', '暂无审核发布的诊断题，请教师先发布演示内容')
    return d


def finish_diagnostic(db, ctx, diagnostic_id):
    d = require(db.get(m.DiagnosticSession, diagnostic_id))
    if d.membership_id != ctx.membership.id:
        fail(404, 'NOT_FOUND', '诊断不存在')
    tasks = list(db.scalars(select(m.LearningTask).where(m.LearningTask.diagnostic_id == d.id)))
    if any(t.state != 'completed' for t in tasks):
        fail(409, 'INCOMPLETE_DIAGNOSTIC', '请先完成全部诊断题')
    d.status = 'completed'
    for task in tasks:
        a = db.scalar(select(m.Attempt).where(m.Attempt.task_id == task.id))
        derive_outcome(db, ctx, a)
    ensure_plan(db, ctx, d.subject_id)
    return d


def ensure_plan(db, ctx, subject_id):
    if not db.scalar(select(m.DiagnosticSession.id).where(m.DiagnosticSession.membership_id == ctx.membership.id, m.DiagnosticSession.subject_id == subject_id, m.DiagnosticSession.status == 'completed')):
        return
    existing_tasks = list(db.scalars(select(m.LearningTask).where(m.LearningTask.membership_id == ctx.membership.id)))
    assigned = {db.get(m.QuestionVersion, t.question_version_id).question_id for t in existing_tasks}
    questions = available_questions(db, ctx)
    modules = list(db.scalars(select(m.Module).where(m.Module.subject_id == subject_id).order_by(m.Module.position)))
    for module in modules:
        kp_ids = set(db.scalars(select(m.KnowledgePoint.id).where(m.KnowledgePoint.module_id == module.id)))
        candidates = [q for q in questions if q.knowledge_id in kp_ids and q.question_id not in assigned]
        for kind in ('objective', 'essay'):
            def priority(question):
                prerequisites = list(db.scalars(select(m.Prerequisite.requires_id).where(m.Prerequisite.knowledge_id == question.knowledge_id)))
                evidence = list(db.scalars(select(m.Attempt).join(m.QuestionVersion).where(m.Attempt.membership_id == ctx.membership.id,
                    m.QuestionVersion.knowledge_id.in_(prerequisites + [question.knowledge_id]), m.Attempt.status == 'graded')))
                weak = any((current_evaluation(db, a.id) or {}).get('score', 0) < db.get(m.QuestionVersion, a.question_version_id).max_score for a in evidence)
                return 0 if weak else 1
            q = next((q for q in sorted(candidates, key=priority) if (q.kind == 'essay') == (kind == 'essay')), None)
            key = f'practice:{module.id}:{kind}:{q.question_id}' if q else ''
            def pending_same_group(t):
                if t.mode != 'practice' or t.state not in ('todo', 'pending_teacher'):
                    return False
                assigned_q = db.get(m.QuestionVersion, t.question_version_id)
                return assigned_q.knowledge_id in kp_ids and (assigned_q.kind == 'essay') == (kind == 'essay')
            if q and not any(pending_same_group(t) for t in existing_tasks):
                reason = f'{module.name}：' + ('诊断发现薄弱线索，结合前置知识优先巩固' if priority(q) == 0 else '补充未充分覆盖的知识与方法')
                if kind == 'essay':
                    reason += '；材料分析须教师评价'
                db.add(m.LearningTask(membership_id=ctx.membership.id, question_version_id=q.id, task_key=key, mode='practice', reason=reason, estimated_minutes=10 if kind == 'essay' else 5))
    db.flush()


def task_view(db, task):
    q = db.get(m.QuestionVersion, task.question_version_id)
    kp = db.get(m.KnowledgePoint, q.knowledge_id)
    module = db.get(m.Module, kp.module_id)
    attempt = db.scalar(select(m.Attempt).where(m.Attempt.task_id == task.id))
    return {'id': task.id, 'mode': task.mode, 'state': task.state, 'reason': task.reason, 'minutes': task.estimated_minutes,
            'module': module.name, 'knowledge': kp.name, 'kind': q.kind, 'prompt': q.prompt,
            'attempt_id': attempt.id if attempt else None}


def materialize_review(db, ctx, schedule):
    if schedule.task_id:
        return schedule.task_id
    if schedule.state != 'scheduled' or schedule.due_at > m.now():
        fail(409, 'REVIEW_NOT_DUE', '复习尚未到期或已结束')
    original = db.get(m.Attempt, schedule.attempt_id)
    question = db.get(m.QuestionVersion, original.question_version_id)
    candidates = available_questions(db, ctx, schedule.knowledge_id)
    q = next((q for q in candidates if q.question_id == question.question_id), None)
    if not q:
        fail(409, 'CONTENT_REQUIRED', '复习题已撤回，请教师补充内容')
    task = m.LearningTask(membership_id=ctx.membership.id, question_version_id=q.id, task_key=f'review:{schedule.id}', mode='review', reason=f'第 {schedule.stage} 阶段复习（旧题重做，非新题验证）')
    db.add(task)
    db.flush()
    schedule.task_id = task.id
    return task.id


def score_essay(db, ctx, attempt_id, data, case=None):
    a = owned_attempt(db, ctx, attempt_id, teacher=True)
    if not teacher_can_view(db, ctx, a.membership_id):
        fail(404, 'NOT_FOUND', '作答不存在')
    q = db.get(m.QuestionVersion, a.question_version_id)
    if a.status == 'draft' or (q.kind != 'essay' and case is None):
        fail(409, 'INVALID_STATE', '当前作答不接受此评分操作')
    if q.kind == 'essay':
        if len(data.parts) != len(q.rubric) or any(s < 0 or s > r['score'] for s, r in zip(data.parts, q.rubric)):
            fail(422, 'INVALID_SCORE', '分项得分超出评分要点范围')
    elif len(data.parts) != 1 or not 0 <= data.parts[0] <= q.max_score:
        fail(422, 'INVALID_SCORE', '分数超出范围')
    ev = db.scalar(select(m.Evaluation).where(m.Evaluation.attempt_id == a.id))
    if ev:
        if ev.current_revision != data.expected_revision:
            fail(409, 'STALE_REVISION', '评价已变化，请重新读取')
        number = ev.current_revision + 1
        changed = db.execute(update(m.Evaluation).where(m.Evaluation.id == ev.id, m.Evaluation.current_revision == data.expected_revision).values(current_revision=number))
        if changed.rowcount != 1:
            fail(409, 'STALE_REVISION', '评价已被其他教师修订')
    else:
        if data.expected_revision != 0:
            fail(409, 'STALE_REVISION', '评价版本无效')
        ev = m.Evaluation(attempt_id=a.id)
        db.add(ev)
        db.flush()
        number = 1
    db.add(m.EvaluationRevision(evaluation_id=ev.id, number=number, score=sum(data.parts), parts=data.parts, feedback=data.feedback, evaluator_id=ctx.user.id, method='teacher'))
    a.status = 'graded'
    db.get(m.LearningTask, a.task_id).state = 'completed'
    if case:
        case.status = 'resolved'
        case.resolution = data.feedback
    db.flush()
    target_member = db.get(m.Membership, a.membership_id)
    target_ctx = Context(db.get(m.User, target_member.user_id), target_member,
                         list(db.scalars(select(m.RoleAssignment).where(m.RoleAssignment.membership_id == target_member.id))), ctx.session)
    derive_outcome(db, target_ctx, a)
    audit(db, ctx, 'evaluation.revise' if number > 1 else 'evaluation.grade', ev.id, {'revision': number})
    return current_evaluation(db, a.id)
