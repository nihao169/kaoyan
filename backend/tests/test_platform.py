from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import hashlib
import json
import sqlite3
import pytest
from sqlalchemy import select, func
from app import models as m
from app.db import SessionLocal
from app.config import settings
from app.auth import passwords
from app.worker import tick
from conftest import checked, publish_all, create_task, save_and_submit, login_client


def test_seed_and_publish_gate(clients):
    student, teacher, admin = clients
    catalog = checked(student, '/catalog')
    assert len(catalog['modules']) == 6
    checked(student, '/diagnostics', 'POST', {'subject_id': catalog['subjects'][0]['id']}, status=409)
    source = checked(teacher, '/content/sources')['items'][0]
    checked(student, f'/sources/versions/{source["id"]}', status=404)
    checked(admin, f'/content/sources/{source["id"]}/submit', 'POST', {'note': '管理权限不是评分或发布权限'}, status=403)
    publish_all(teacher)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(m.QuestionVersion).where(m.QuestionVersion.status == 'published')) == 60
        assert db.scalar(select(func.count()).select_from(m.CardVersion).where(m.CardVersion.status == 'published')) == 18


def test_diagnostic_hides_answers_and_resumes(clients):
    student, teacher, _ = clients
    publish_all(teacher)
    subject = checked(student, '/catalog')['subjects'][0]['id']
    checked(student, '/goals/current', 'PUT', {'subject_id': subject, 'exam_year': 2027, 'target_score': 75, 'daily_minutes': 30})
    diagnostic = checked(student, '/diagnostics', 'POST', {'subject_id': subject})
    assert checked(student, '/diagnostics', 'POST', {'subject_id': subject})['id'] == diagnostic['id']
    tasks = checked(student, '/diagnostics/current')['tasks']
    assert len(tasks) == 6
    for index, task in enumerate(tasks):
        a = checked(student, f'/tasks/{task["id"]}/attempts', 'POST')
        assert 'answer' not in a['question']
        assert 'explanation' not in a['question']
        if index == 0:
            checked(student, f'/attempts/{a["id"]}/hints', 'POST', {'level': 1}, status=403)
            checked(student, '/retrieval?query=实践', status=403)
            with SessionLocal() as db:
                source_id = db.get(m.QuestionVersion, a['question']['id']).source_version_id
            checked(student, '/sources/versions/' + source_id, status=403)
        submitted = save_and_submit(student, a, ['A'])
        assert submitted['evaluation'] is None
        assert 'answer' not in submitted['question']
    checked(student, f'/diagnostics/{diagnostic["id"]}/submit', 'POST')
    plan = checked(student, '/plans/today')
    assert len(plan['all_tasks']) == 12
    assert sum(t['minutes'] for t in plan['tasks']) <= 30
    second_login = login_client('student')
    assert checked(second_login, '/diagnostics/current')['status'] == 'completed'
    assert checked(second_login, '/goals/current')['daily_minutes'] == 30
    second_login.close()


@pytest.mark.parametrize('kind,correct', [('single', True), ('single', False), ('multiple', True), ('multiple', False)])
def test_objective_scoring_and_immutable_evidence(clients, kind, correct):
    student, teacher, _ = clients
    publish_all(teacher)
    with SessionLocal() as db:
        q = db.scalar(select(m.QuestionVersion).where(m.QuestionVersion.kind == kind))
        answer = q.answer if correct else ([q.answer[0]] if kind == 'multiple' else [next(k for k in q.options if k not in q.answer)])
        qid, max_score = q.id, q.max_score
    attempt = create_task(student, qid)
    result = save_and_submit(student, attempt, answer)
    assert result['evaluation']['score'] == (max_score if correct else 0)
    assert result['process'] == '保留原始思考过程'
    assert result['duration_seconds'] == 42
    again = checked(student, '/attempts/' + attempt['id'] + '/submit', 'POST')
    assert again['evaluation']['id'] == result['evaluation']['id']
    checked(student, '/attempts/' + attempt['id'] + '/draft', 'PATCH', {'revision': result['revision'], 'answer': ['A']}, status=409)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(m.Evaluation).where(m.Evaluation.attempt_id == attempt['id'])) == 1


def test_wrong_answer_to_remediation_new_question_and_review(clients):
    student, teacher, _ = clients
    publish_all(teacher)
    with SessionLocal() as db:
        q = db.scalar(select(m.QuestionVersion).where(m.QuestionVersion.kind == 'single'))
        qid, logical_id = q.id, q.question_id
        wrong = [next(k for k in q.options if k not in q.answer)]
    a = save_and_submit(student, create_task(student, qid), wrong)
    r = next(r for r in checked(student, '/remediations') if r['attempt_id'] == a['id'])
    checked(student, f'/remediations/{r["id"]}/read', 'POST', status=409)
    checked(student, f'/remediations/{r["id"]}/cause', 'POST', {'cause': '概念混淆'})
    result = checked(student, f'/remediations/{r["id"]}/read', 'POST')
    assert result['task_id']
    new = checked(student, f'/tasks/{result["task_id"]}/attempts', 'POST')
    assert new['question']['question_id'] != logical_id
    with SessionLocal() as db:
        answer = db.get(m.QuestionVersion, new['question']['id']).answer
    independent = save_and_submit(student, new, answer)
    reviews = checked(student, '/review-schedules')
    assert len(reviews) == 1
    checked(student, f'/review-schedules/{reviews[0]["id"]}/attempts', 'POST', status=409)
    # Controlled clock: no waiting or changing the production clock.
    with SessionLocal.begin() as db:
        schedule = db.get(m.ReviewSchedule, reviews[0]['id'])
        schedule.anchor_at = (datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
        schedule.due_at = (datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
    review_task = checked(student, f'/review-schedules/{reviews[0]["id"]}/attempts', 'POST')
    review_attempt = checked(student, f'/tasks/{review_task["task_id"]}/attempts', 'POST')
    save_and_submit(student, review_attempt, answer)
    stages = checked(student, '/review-schedules')
    assert {r['stage'] for r in stages} == {1, 2}
    assert next(r for r in stages if r['stage'] == 1)['state'] == 'completed'


def test_essay_grading_appeal_revision_and_idempotency(clients):
    student, teacher, admin = clients
    publish_all(teacher)
    with SessionLocal() as db:
        qid = db.scalar(select(m.QuestionVersion.id).where(m.QuestionVersion.kind == 'essay'))
    a = save_and_submit(student, create_task(student, qid), response_text='调查提供认识来源，调整方案后用实践检验认识。')
    assert a['status'] == 'pending_teacher' and a['evaluation'] is None
    body = {'parts': [3, 4], 'feedback': '原理基本清楚，需要结合材料进一步论证。', 'expected_revision': 0}
    checked(admin, f'/teacher/attempts/{a["id"]}/evaluations', 'POST', body, status=403)
    idem = str(uuid4())
    result = checked(teacher, f'/teacher/attempts/{a["id"]}/evaluations', 'POST', body, idem=idem)
    assert result['score'] == 7
    assert checked(teacher, f'/teacher/attempts/{a["id"]}/evaluations', 'POST', body, idem=idem) == result
    checked(teacher, f'/teacher/attempts/{a["id"]}/evaluations', 'POST', {**body, 'feedback': '不同请求'}, status=409, idem=idem)
    checked(teacher, f'/teacher/attempts/{a["id"]}/evaluations', 'POST', body, status=409)
    case = checked(student, f'/evaluations/{result["id"]}/review-cases', 'POST', {'reason': '已在第二段结合调整方案论证，请核对。'})
    revised = checked(teacher, f'/review-cases/{case["id"]}/resolve', 'POST', {'parts': [4, 6], 'feedback': '重新核对原文，材料论证完整，修订为满分。', 'expected_revision': 1})
    assert revised['score'] == 10 and revised['revision'] == 2
    detail = checked(teacher, '/teacher/attempts/' + a['id'])
    assert len(detail['revisions']) == 2
    assert detail['response_text'] == a['response_text']
    assert len(checked(student, '/review-schedules')) == 1


def test_content_version_pinning_and_withdrawal(clients):
    student, teacher, _ = clients
    sources = publish_all(teacher)
    old = sources[0]['id']
    detail = checked(teacher, '/sources/versions/' + old)
    question = detail['questions'][0]
    a = save_and_submit(student, create_task(student, question['id']), question['answer'])
    new = checked(teacher, f'/content/sources/{old}/versions', 'POST')
    new_detail = checked(teacher, '/sources/versions/' + new['id'])
    new_text = new_detail['text'] + '\n\n新增修订标记：VERSION_TWO'
    checked(teacher, '/content/sources/' + new['id'], 'PATCH', {'text': new_text, 'revision': new_detail['revision']})
    checked(teacher, f'/content/sources/{new["id"]}/submit', 'POST', {'note': '核对修订'})
    checked(teacher, f'/content/sources/{new["id"]}/publish', 'POST', {'note': '确认新版本'})
    found = checked(student, '/retrieval?query=VERSION_TWO')
    assert found and all(x['version_id'] == new['id'] for x in found)
    history = checked(student, '/attempts/' + a['id'])
    assert history['question']['id'] == question['id']
    assert all(x['version_id'] == old for x in history['sources'])
    checked(teacher, '/content/sources/' + old, 'PATCH', {'text': '覆盖已发布内容', 'revision': detail['revision']}, status=409)
    checked(teacher, f'/content/sources/{new["id"]}/withdraw', 'POST', {'note': '教师发现内容冲突，暂停新使用并复核'})
    assert not checked(student, '/retrieval?query=VERSION_TWO')


def test_cross_user_org_class_and_private_permissions(clients):
    student, teacher, admin = clients
    sources = publish_all(teacher)
    classes = checked(admin, '/classes')
    checked(admin, '/admin/users', 'POST', {'username': 'student2', 'name': '另一位学生', 'password': 'Zhixing2026!', 'roles': ['student'], 'class_id': classes[0]['id']})
    other = login_client('student2')
    with SessionLocal() as db:
        qid = db.scalar(select(m.QuestionVersion.id).where(m.QuestionVersion.kind == 'single'))
    a = create_task(student, qid)
    checked(other, '/attempts/' + a['id'], status=404)
    checked(other, '/attempts/' + a['id'] + '/draft', 'PATCH', {'answer': ['A'], 'revision': a['revision']}, status=404)
    with SessionLocal.begin() as db:
        private = db.get(m.SourceVersion, sources[0]['id'])
        src = db.get(m.Source, private.source_id)
        src.visibility = 'private'
    checked(student, '/sources/versions/' + sources[0]['id'], status=404)
    assert all(r['version_id'] != sources[0]['id'] for r in checked(student, '/retrieval'))
    assert all(r['version_id'] != sources[0]['id'] for r in checked(student, '/retrieval?mode=hybrid&query=实践'))
    with SessionLocal.begin() as db:
        outsider = m.Organization(name='外部机构')
        db.add(outsider);db.flush()
        member = db.scalar(select(m.Membership).join(m.User).where(m.User.username == 'student2'))
        member.org_id = outsider.id
    checked(other, '/sources/versions/' + sources[1]['id'], status=404)
    assert checked(other, '/retrieval') == []
    assert checked(other, '/retrieval?mode=hybrid&query=实践') == []
    assert checked(other, '/teacher/attempts', status=403)['code'] == 'ROLE_REQUIRED'
    other.close()


def test_csrf_extra_fields_and_stale_draft(clients):
    student, teacher, _ = clients
    publish_all(teacher)
    with SessionLocal() as db:
        qid = db.scalar(select(m.QuestionVersion.id).where(m.QuestionVersion.kind == 'single'))
    a = create_task(student, qid)
    no_csrf = student.headers.pop('X-CSRF-Token')
    checked(student, f'/attempts/{a["id"]}/submit', 'POST', status=403)
    student.headers['X-CSRF-Token'] = no_csrf
    checked(student, f'/attempts/{a["id"]}/draft', 'PATCH', {'revision': 1, 'answer': ['A'], 'score': 100}, status=422)
    checked(student, f'/attempts/{a["id"]}/draft', 'PATCH', {'revision': 1, 'answer': ['A']})
    checked(student, f'/attempts/{a["id"]}/draft', 'PATCH', {'revision': 1, 'answer': ['B']}, status=409)
    checked(student, f'/attempts/{a["id"]}/draft', 'PATCH', {'revision': 2, 'answer': ['A', 'B']}, status=422)


def test_hints_are_sequential_and_not_independent(clients):
    student, teacher, _ = clients
    publish_all(teacher)
    with SessionLocal() as db:
        q = db.scalar(select(m.QuestionVersion).where(m.QuestionVersion.kind == 'single'))
        qid, answer = q.id, q.answer
    a = create_task(student, qid)
    checked(student, f'/attempts/{a["id"]}/hints', 'POST', {'level': 3}, status=409)
    hint = checked(student, f'/attempts/{a["id"]}/hints', 'POST', {'level': 1})
    a['revision'] = hint['revision']
    result = save_and_submit(student, a, answer)
    assert result['hint_level'] == 1
    assert checked(student, '/review-schedules') == []
    assert len(checked(student, '/remediations')) == 1


def test_worker_parse_and_lease_recovery(clients):
    student, teacher, _ = clients
    for _ in range(20):
        if not tick(): break
    kp = checked(teacher, '/catalog')['knowledge'][0]['id']
    result = checked(teacher, '/content/sources', 'POST', {'title': '恢复测试', 'text': '# 定义\n\n恢复后的正文。', 'knowledge_id': kp, 'rights': '原创测试资料'}, status=202)
    with SessionLocal.begin() as db:
        job = db.get(m.Job, result['job_id'])
        job.state, job.attempts = 'running', 1
        job.lease_until = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    assert tick()
    assert checked(teacher, '/jobs/' + result['job_id'])['state'] == 'succeeded'
    assert checked(teacher, '/sources/versions/' + result['id'])['chunks']
    checked(student, '/jobs/' + result['job_id'], status=404)


def test_unconfigured_ai_does_not_change_grade(clients):
    student, teacher, _ = clients
    publish_all(teacher)
    with SessionLocal() as db:
        q = db.scalar(select(m.QuestionVersion).where(m.QuestionVersion.kind == 'single'))
        qid, answer = q.id, q.answer
    a = save_and_submit(student, create_task(student, qid), answer)
    checked(student, f'/attempts/{a["id"]}/tutor-runs', 'POST', status=503)
    assert checked(student, '/attempts/' + a['id'])['evaluation'] == a['evaluation']


def test_login_logout_session_and_origin(clients):
    student, _, _ = clients
    response = student.put('/api/v1/goals/current', headers={'Origin': 'https://untrusted.example'}, json={})
    assert response.status_code == 403
    checked(student, '/auth/logout', 'POST')
    checked(student, '/me', status=401)


def test_concurrent_submit_never_duplicates_scores(clients):
    student, teacher, _ = clients
    publish_all(teacher)
    with SessionLocal() as db:
        q = db.scalar(select(m.QuestionVersion).where(m.QuestionVersion.kind == 'single'))
        qid, answer = q.id, q.answer
    a = create_task(student, qid)
    checked(student, f'/attempts/{a["id"]}/draft', 'PATCH', {'answer': answer, 'revision': 1})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: student.post(f'/api/v1/attempts/{a["id"]}/submit', headers={'Idempotency-Key': str(uuid4())}), range(2)))
    assert any(r.status_code == 200 for r in results)
    assert all(r.status_code in (200, 409, 503) for r in results)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(m.Evaluation).where(m.Evaluation.attempt_id == a['id'])) == 1
        assert db.scalar(select(func.count()).select_from(m.OutboxEvent).where(m.OutboxEvent.attempt_id == a['id'])) == 1


def test_upload_validation_and_rejected_content_can_be_corrected(clients):
    student, teacher, _ = clients
    knowledge = checked(teacher, '/catalog')['knowledge'][0]['id']
    fields = {'knowledge_id': knowledge, 'rights': '原创测试内容'}
    for filename, content, status in [('bad.html', b'<script>bad</script>', 422), ('empty.txt', b'', 422), ('bad.txt', b'\xff\xfe\xfa', 422), ('large.txt', b'x' * (50*1024*1024+1), 413)]:
        response = teacher.post('/api/v1/content/sources/upload', data=fields, files={'file': (filename, content)})
        assert response.status_code == status, response.text
    response = teacher.post('/api/v1/content/sources/upload', data=fields, files={'file': ('original.md', '# 主题\n\n定义与适用条件。'.encode('utf-8'))})
    assert response.status_code == 202, response.text
    version_id = response.json()['data']['id']
    checked(teacher, f'/content/sources/{version_id}/submit', 'POST', {'note': '请审核'})
    checked(teacher, f'/content/sources/{version_id}/publish', 'POST', {'note': '缺少题卡，不允许发布'}, status=422)
    checked(teacher, f'/content/sources/{version_id}/reject', 'POST', {'note': '退回补充题目与知识卡'})
    detail = checked(teacher, f'/sources/versions/{version_id}')
    assert detail['status'] == 'draft'
    checked(teacher, f'/content/sources/{version_id}', 'PATCH', {'text': '# 新正文\n\n已修订的定义。', 'revision': detail['revision']})


def test_openapi_matches_envelope_and_private_question_fields(clients):
    student, _, _ = clients
    schema = student.get('/openapi.json').json()
    success = schema['paths']['/api/v1/attempts/{attempt_id}']['get']['responses']['200']['content']['application/json']['schema']
    assert set(success['required']) == {'data', 'request_id'}
    assert success['properties']['data']['$ref'].endswith('/AttemptOutput')
    assert schema['paths']['/api/v1/me']['get']['responses']['401']['content']['application/json']['schema']['$ref'].endswith('/APIErrorEnvelope')
