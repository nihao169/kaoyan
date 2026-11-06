from datetime import timedelta

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app import models as legacy
from app.v2 import mastery_reviews as reviews, models as m, service as s
from test_v2 import call, setup_project


def test_native_reviews_take_over_and_filter_revoked_scopes(clients, monkeypatch):
    student, teacher, _ = clients
    monkeypatch.setattr(settings, 'deeptutor_mastery_reviews', True)
    project, material, _ = setup_project(student)
    project_url = '/learning-projects/' + project['id']
    with SessionLocal.begin() as db:
        p = db.get(m.Project, project['id'])
        q = m.Question(project_id=p.id, material_id=material['id'], kind='single', knowledge='实践',
                       prompt='关于实践，哪项正确？', options={'A': '甲', 'B': '乙'},
                       answer=['A'], explanation='甲', quote='实践是认识的来源')
        db.add(q)
        db.flush()
        task = s.add_task(db, p, 'verification', '验证', 'check', '独立完成', material['id'], {'question_id': q.id})
        old = s.add_task(db, p, 'review', '历史复习', 'historical-review', '历史记录', material['id'],
                         due_at=(s.clock() - timedelta(days=1)).isoformat())
        task_id, old_id = task.id, old.id
    call(student, '/study-sessions/' + task_id + '/submit', 'POST', {'answer': ['A']})
    assert call(student, '/study-sessions/' + old_id)['archived_review']
    call(student, '/study-sessions/' + old_id + '/prepare', 'POST', {'kind': 'single'}, 409)
    assert all(row['kind'] != 'review' for row in call(student, '/today')['tasks'])
    assert call(student, '/mastery-reviews')['pending'] == 1

    assert reviews.tick()  # queues the already authorized material for indexing
    with SessionLocal.begin() as db:
        scope = db.scalar(select(m.MasteryReviewScope))
        event = db.scalar(select(m.MasteryReviewEvent))
        index = db.scalar(select(m.TutorIndex))
        assert event.payload['correct'] and index.material_id == material['id']
        assert len(list(db.scalars(select(m.Task).where(m.Task.kind == 'review')))) == 1
        index.state, event.next_at = 'ready', s.clock().isoformat()
        scope_id = scope.id

    native_id = 'topic_zx_' + scope_id.replace('-', '')
    monkeypatch.setattr(reviews, 'evidence_request', lambda principal, **claims: native_id)
    assert reviews.tick()
    when = (s.clock() - timedelta(hours=1)).timestamp()

    async def topic(principal, path_id):
        assert path_id == native_id
        return {'reviews': [{'id': 'review-1', 'knowledge_point_name': '实践', 'due_at': when,
                             'due': True, 'priority': 1, 'reason': '原生安排'}]}

    monkeypatch.setattr(reviews, 'topic', topic)
    queue = call(student, '/mastery-reviews')
    assert queue['pending'] == 0 and queue['items'][0]['due_at'] == when
    session = '/mastery-reviews/' + scope_id + '/session'
    call(teacher, session, status=403)
    monkeypatch.setattr(reviews, 'session_request', lambda *args, **kwargs: {'state': 'question', 'question': {'prompt': '试题'}})
    assert call(student, session, 'POST', {'operation': 'start', 'submission_id': 'start-key'})['state'] == 'question'
    call(student, project_url + '/materials/' + material['id'], 'DELETE')
    assert call(student, '/mastery-reviews')['items'] == []
    call(student, session, status=403)


def test_unified_execution_enables_only_native_paths():
    from app.config import Settings
    configured = Settings(deeptutor_unified_execution=True, deeptutor_native_questions=False,
                          legacy_retrieval_enabled=True, _env_file=None)
    assert configured.native_teaching_pipeline and configured.deeptutor_native_questions
    assert configured.deeptutor_native_lessons and not configured.legacy_retrieval_enabled


def test_teacher_revision_replaces_the_pending_review_evidence(clients, monkeypatch):
    from conftest import checked, publish_all, create_task, save_and_submit

    student, teacher, _ = clients
    publish_all(teacher)
    with SessionLocal.begin() as db:
        question = db.scalar(select(legacy.QuestionVersion).where(legacy.QuestionVersion.kind == 'essay'))
        source = db.get(legacy.Source, db.get(legacy.SourceVersion, question.source_version_id).source_id)
        db.add(legacy.SourceActivation(version_id=question.source_version_id, org_id=source.org_id, teacher_id=source.owner_id))
        question_id = question.id
    monkeypatch.setattr(settings, 'deeptutor_mastery_reviews', True)
    attempt = save_and_submit(student, create_task(student, question_id), response_text='实践检验认识。')
    grading = f'/teacher/attempts/{attempt["id"]}/evaluations'
    evaluation = checked(teacher, grading, 'POST', {'parts': [3, 4], 'feedback': '继续结合材料', 'expected_revision': 0})
    assert evaluation['score'] == 7
    checked(teacher, grading, 'POST', {'parts': [4, 6], 'feedback': '补充材料核对后改为满分', 'expected_revision': 1})
    with SessionLocal() as db:
        event, = db.scalars(select(m.MasteryReviewEvent))
        assert event.attempt_id == attempt['id'] and event.revision == 2 and event.payload['correct']
        assert db.scalar(select(legacy.ReviewSchedule)) is None
