"""Autonomous learning rules. No model calls or HTTP inside these transactions."""
import hashlib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from .. import models as old
from ..auth import source_allowed
from ..errors import fail
from . import models as m


def clock():
    return datetime.now(timezone.utc)


def space(db, user_id):
    row = db.scalar(select(m.PersonalSpace).where(m.PersonalSpace.user_id == user_id))
    if not row:
        row = m.PersonalSpace(user_id=user_id)
        db.add(row)
        db.flush()
    return row


def project(db, ctx, project_id, active=True, lock=False):
    stmt = select(m.Project).join(m.PersonalSpace).where(m.Project.id == project_id, m.PersonalSpace.user_id == ctx.user.id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if not row:
        fail(404, 'NOT_FOUND', '学习项目不存在')
    if active and row.state != 'active':
        fail(409, 'PROJECT_ARCHIVED', '项目已归档，仅可查看记录')
    return row


def rows(db, cls, project_id):
    return list(db.scalars(select(cls).where(cls.project_id == project_id).order_by(cls.created_at, cls.id)))


def no_active_mock(db, project_id):
    space_id = select(m.Project.space_id).where(m.Project.id == project_id).scalar_subquery()
    if db.scalar(select(m.Assessment.id).join(m.Project, m.Project.id == m.Assessment.project_id)
                 .where(m.Project.space_id == space_id, m.Assessment.mode == 'mock', m.Assessment.state == 'active').limit(1)):
        fail(403, 'MOCK_RESTRICTION', '模考期间暂停助教、原文学习和解析，请先交卷')


def material_access(db, ctx, material):
    if not material or material.state == 'revoked':
        fail(403, 'MATERIAL_REVOKED', '资料已移除，不可继续访问')
    if material.source_version_id:
        version = db.get(old.SourceVersion, material.source_version_id)
        source = db.get(old.Source, version.source_id) if version else None
        enabled = version and (version.status == 'published' or db.scalar(select(old.SourceActivation.id).where(old.SourceActivation.version_id == version.id)))
        if not source or not source_allowed(db, ctx, source) or not enabled or version.status == 'withdrawn':
            fail(403, 'MATERIAL_REVOKED', '关联课程资料已撤回或无权访问，请移除后重新开始')
    return material


def authorized_materials(db, ctx, p):
    return [material_access(db, ctx, item) for item in rows(db, m.Material, p.id) if item.state == 'ready']


def task(db, ctx, task_id, lock=False, active=True, assessment=False):
    row = db.get(m.Task, task_id)
    if not row:
        fail(404, 'NOT_FOUND', '学习任务不存在')
    p = project(db, ctx, row.project_id, lock=lock, active=active)
    if row.payload.get('assessment_id') and not assessment:
        fail(403, 'ASSESSMENT_ONLY', '请在本次测评中作答和查看反馈')
    if row.material_id:
        material_access(db, ctx, db.get(m.Material, row.material_id))
    return row, p


def add_task(db, p, kind, title, task_key, reason, material_id=None, payload=None, due_at=None, minutes=10):
    found = db.scalar(select(m.Task).where(m.Task.project_id == p.id, m.Task.task_key == task_key))
    if found:
        return found
    row = m.Task(project_id=p.id, material_id=material_id, kind=kind, title=title, task_key=task_key,
                 reason=reason, payload=payload or {}, due_at=due_at, estimated_minutes=minutes)
    db.add(row)
    db.flush()
    return row


def snapshot_plan(db, p, reason):
    db.add(m.Plan(project_id=p.id, number=p.revision, daily_minutes=p.daily_minutes, reason=reason,
                  scope={'material_ids': [x.id for x in rows(db, m.Material, p.id) if x.state == 'ready'],
                         'syllabus_ids': [x.id for x in rows(db, m.ExamResource, p.id) if x.kind == 'syllabus'
                                          and db.get(m.Material, x.material_id).state == 'ready'],
                         'scope_revision': p.scope_revision, 'exam_year': p.exam_year, 'deadline': p.deadline,
                         'target_score': p.target_score, 'policy': p.policy}))


def add_material(db, p, title, text, source_version_id=None, reading=True, deduplicate=True):
    digest = hashlib.sha256(text.encode()).hexdigest()
    previous = next((x for x in rows(db, m.Material, p.id) if x.sha256 == digest and x.state == 'ready'
                     and x.source_version_id == source_version_id and x.title == title), None)
    if previous and deduplicate:
        return previous
    row = m.Material(project_id=p.id, title=title, text=text, sha256=digest, source_version_id=source_version_id)
    db.add(row)
    db.flush()
    p.scope_revision += 1
    p.revision += 1
    snapshot_plan(db, p, '新增学习资料，保留历史计划')
    if reading:
        add_task(db, p, 'reading', f'学习：{title}', f'read:{row.id}', '先阅读资料，再通过练习检查理解', row.id, minutes=15)
    return row


def evidence(db, p, t, kind, knowledge, **payload):
    row = m.Evidence(project_id=p.id, task_id=t.id, kind=kind, knowledge=knowledge, payload=payload)
    db.add(row)


def question_view(q, reveal=False):
    value = {key: getattr(q, key) for key in ('id', 'knowledge', 'kind', 'prompt', 'options', 'origin')}
    if reveal:
        value.update(answer=q.answer, explanation=q.explanation, rubric=q.rubric, quote=q.quote)
    return value


def finish_answer(db, p, t, q, attempt, correct, feedback, evaluator='rule', qualified=True):
    attempt.result = {'correct': correct, 'feedback': feedback, 'evaluator': evaluator, 'question': question_view(q, True)}
    t.state = 'completed'
    assisted = bool(attempt.hint_used)
    independent = correct and not assisted and qualified
    kind = 'independent_pass' if independent else 'needs_remediation'
    if independent and t.kind == 'review':
        kind = 'delayed_pass'
    evidence(db, p, t, kind, q.knowledge, correct=correct, hint_used=assisted, evaluator=evaluator,
             question_id=q.id, confidence=attempt.confidence, qualified=qualified)
    scope = {key: t.payload[key] for key in ('focus', 'source_span') if t.payload.get(key)}
    if not independent:
        add_task(db, p, 'remediation', f'补学：{q.knowledge}', f'remediate:{t.id}',
                 '回到原文，辨析错误，再用未做过的新题验证', q.material_id,
                 {**scope, 'knowledge': q.knowledge, 'origin_question_id': q.id, 'origin_task_id': t.id})
    else:
        if t.kind == 'review':
            sequence = t.payload.get('sequence', 1)
            if sequence < 3:
                anchor = datetime.fromisoformat(t.payload['anchor'])
                day = (1, 3, 7)[sequence]
                add_task(db, p, 'review', f'复习：{q.knowledge}', f'review:{t.payload["cycle"]}:{sequence + 1}',
                         f'独立通过后第 {day} 天的延迟检查', q.material_id,
                         {**t.payload, 'sequence': sequence + 1, 'exclude_question_id': q.id},
                         (anchor + timedelta(days=day)).isoformat())
        else:
            anchor = clock()
            add_task(db, p, 'review', f'复习：{q.knowledge}', f'review:{t.id}:1',
                     '独立通过后第 1 天的延迟检查', q.material_id,
                     {**scope, 'knowledge': q.knowledge, 'cycle': t.id, 'sequence': 1, 'anchor': anchor.isoformat(), 'exclude_question_id': q.id},
                     (anchor + timedelta(days=1)).isoformat())
        if attempt.confidence == 'low':
            add_task(db, p, 'verification', f'再检查：{q.knowledge}', f'confidence:{t.id}',
                     '本次答对但信心不足，用另一道题检查稳定性', q.material_id,
                     {**scope, 'knowledge': q.knowledge, 'exclude_question_id': q.id})
    return attempt.result


def submit_answer(db, ctx, task_id, data, assessment=False):
    t, p = task(db, ctx, task_id, lock=True, assessment=assessment)
    if t.state == 'completed':
        fail(409, 'ALREADY_SUBMITTED', '本次作答已经提交')
    if t.state == 'cancelled':
        fail(409, 'TASK_CANCELLED', '任务已取消')
    if t.due_at and datetime.fromisoformat(t.due_at) > clock():
        fail(409, 'REVIEW_NOT_DUE', '延迟复习尚未到期，可先开展其他练习')
    if not assessment:
        no_active_mock(db, p.id)
    q = db.get(m.Question, t.payload.get('question_id'))
    if not q or q.project_id != p.id:
        fail(409, 'QUESTION_REQUIRED', '请先准备一道经过校验的练习题')
    if q.kind == 'essay':
        if not data.response_text.strip():
            fail(422, 'ANSWER_REQUIRED', '请填写分析题作答')
    elif not data.answer or any(x not in q.options for x in data.answer) or (q.kind == 'single' and len(data.answer) != 1):
        fail(422, 'INVALID_ANSWER', '请选择有效答案')
    attempt = m.Attempt(task_id=t.id, answer=data.answer, response_text=data.response_text,
                        confidence=data.confidence, hint_used=int(bool(t.payload.get('hint_used'))))
    db.add(attempt)
    db.flush()
    if q.kind == 'essay':
        attempt.result = {'state': 'pending_ai', 'evaluator': 'ai_training'}
        return attempt, p, t, q
    correct = set(data.answer) == set(q.answer)
    finish_answer(db, p, t, q, attempt, correct, '回答正确' if correct else '请核对原文和选项差异，再完成针对性补学')
    return attempt, p, t, q


def report(db, p):
    items = rows(db, m.Evidence, p.id)
    states = {}
    for e in items:
        if e.kind == 'reading':
            continue
        states[e.knowledge] = {'knowledge': e.knowledge, 'state': {'reading': '学习中', 'needs_remediation': '待验证',
                              'independent_pass': '已验证', 'delayed_pass': '已巩固'}.get(e.kind, '待了解'),
                              'evidence_id': e.id, 'kind': e.kind, 'created_at': e.created_at}
    due = [t for t in rows(db, m.Task, p.id) if t.kind == 'review' and t.state not in ('completed', 'cancelled') and t.due_at and datetime.fromisoformat(t.due_at) <= clock()]
    for t in due:
        key = t.payload.get('knowledge')
        if key in states:
            states[key]['state'] = '待复习'
    tasks = rows(db, m.Task, p.id)
    attempts = [db.scalar(select(m.Attempt).where(m.Attempt.task_id == t.id)) for t in tasks]
    scored = [a for a in attempts if a and 'correct' in a.result]
    syllabi = []
    studied = {e.knowledge for e in items}
    for syllabus in rows(db, m.ExamResource, p.id):
        if syllabus.kind == 'syllabus' and db.get(m.Material, syllabus.material_id).state == 'ready':
            topics = [topic_key(syllabus, t) for t in syllabus.contents['topics']]
            syllabi.append({'year': syllabus.year, 'edition': syllabus.edition, 'total': len(topics),
                            'studied': sum(k in studied for k in topics),
                            'verified': sum(k in states and states[k]['kind'] in ('independent_pass', 'delayed_pass') for k in topics)})
    return {'project_id': p.id, 'knowledge': list(states.values()), 'evidence_count': len(items), 'syllabi': syllabi,
            'completed_tasks': sum(t.state == 'completed' for t in tasks), 'task_count': len(tasks),
            'correct': sum(bool(a.result['correct']) for a in scored), 'answered': len(scored),
            'due_reviews': len(due), 'coverage_note': '仅反映已有学习证据，不代表全科覆盖或预测分数'}


def topic_key(syllabus, topic):
    return f'{syllabus.year}/{syllabus.edition}/{topic["code"]} {topic["title"]}'[:200]


def today(db, ctx):
    projects = list(db.scalars(select(m.Project).join(m.PersonalSpace).where(m.PersonalSpace.user_id == ctx.user.id, m.Project.state == 'active')))
    end = clock().astimezone(ZoneInfo('Asia/Shanghai')).replace(hour=23, minute=59, second=59)
    selected, overflow = [], []
    for p in projects:
        spent = 0
        candidates = [t for t in rows(db, m.Task, p.id) if not t.payload.get('assessment_id') and t.state in ('todo', 'in_progress') and (not t.due_at or datetime.fromisoformat(t.due_at) <= end)]
        priority = {'review': 0, 'verification': 1, 'remediation': 2, 'practice': 3, 'reading': 4}
        candidates.sort(key=lambda t: (priority.get(t.kind, 5), t.due_at or '', t.created_at))
        for t in candidates:
            value = {'id': t.id, 'project_id': p.id, 'project_title': p.title, 'title': t.title, 'kind': t.kind,
                     'reason': t.reason, 'estimated_minutes': t.estimated_minutes, 'state': t.state, 'due_at': t.due_at}
            if t.due_at and datetime.fromisoformat(t.due_at) > clock():
                continue
            if spent + t.estimated_minutes <= p.daily_minutes:
                selected.append(value)
                spent += t.estimated_minutes
            else:
                overflow.append(value)
    return {'tasks': selected, 'deferred': overflow, 'projects': len(projects), 'estimated_minutes': sum(t['estimated_minutes'] for t in selected)}
