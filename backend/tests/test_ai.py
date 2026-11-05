import json
import httpx
import pytest
from sqlalchemy import select, func
from app import models as m
from app.db import SessionLocal
from app.config import settings
from app.worker import tick
from app.ai import run_tutor
from conftest import checked, publish_all, create_task, save_and_submit


@pytest.mark.parametrize('mode', ['valid', 'invalid_citation', 'unauthorized_score', 'timeout', 'no_evidence', 'withdrawn'])
def test_ai_workflow_boundaries_and_failure_recovery(clients, monkeypatch, mode):
    student, teacher, _ = clients
    publish_all(teacher)
    with SessionLocal() as db:
        q = db.scalar(select(m.QuestionVersion).where(m.QuestionVersion.kind == 'single'))
        qid, answer, source_id = q.id, q.answer, q.source_version_id
    a = save_and_submit(student, create_task(student, qid), answer)
    monkeypatch.setattr(settings, 'model_api_key', 'isolated-test-key')
    monkeypatch.setattr(settings, 'model_base_url', 'https://example.invalid/v1')
    monkeypatch.setattr(settings, 'model_name', 'controlled-test-adapter')
    calls = []

    class ControlledClient:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, url, headers, json):
            # No DB transaction may stay open over an external network call.
            with SessionLocal.begin() as db:
                db.add(m.AuditEvent(action='test.external-call-without-lock'))
            calls.append(url)
            if mode == 'timeout':
                raise httpx.ReadTimeout('controlled timeout')
            prompt = __import__('json').loads(json['messages'][1]['content'])
            if prompt.get('_verify'):
                return httpx.Response(200,json={'choices':[{'message':{'content':__import__('json').dumps({'supported':True,'conflict':False,'leaks_answer':False,'reason':'受控引用审核'})}}], 'usage':{'total_tokens':30}})
            output = {'explanation': '依据资料，实践为认识提供来源；此为辅助解释。', 'candidate_cause': '待确认',
                      'citations': [prompt['evidence'][0]['chunk_id']]}
            if mode == 'invalid_citation':
                output['citations'] = ['fabricated-source']
            if mode == 'unauthorized_score':
                output['score'] = 100
            return httpx.Response(200, json={'choices': [{'message': {'content': __import__('json').dumps(output)}}], 'usage': {'total_tokens': 30}})

    monkeypatch.setattr('app.ai.httpx.Client', ControlledClient)
    queued = checked(student, f'/attempts/{a["id"]}/tutor-runs', 'POST', status=202)
    if mode == 'no_evidence':
        with SessionLocal.begin() as db:
            for chunk in db.scalars(select(m.SourceChunk).where(m.SourceChunk.version_id == source_id)):
                db.delete(chunk)
    if mode == 'withdrawn':
        checked(teacher, f'/content/sources/{source_id}/withdraw', 'POST', {'note': '测试来源冲突，停止使用'})
    tick()
    if mode == 'timeout':
        tick()
    job = checked(student, '/jobs/' + queued['job_id'])
    assert checked(student, '/attempts/' + a['id'])['evaluation'] == a['evaluation']
    if mode == 'valid':
        assert job['state'] == 'succeeded'
        assert job['result']['usage']['total_tokens'] == 60
        run_tutor(queued['run_id'])
        assert len(calls) == 2
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(m.Citation)) == 1
    else:
        assert job['state'] == 'failed'
        expected = {'invalid_citation': 'INVALID_CITATION', 'unauthorized_score': 'MODEL_OUTPUT_INVALID',
                    'timeout': 'MODEL_TIMEOUT', 'no_evidence': 'NO_EVIDENCE', 'withdrawn': 'CONTENT_UNAVAILABLE'}
        assert job['error_code'] == expected[mode]
        assert len(calls) <= (2 if mode == 'timeout' else 1)
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(m.Citation)) == 0
def test_structured_teacher_backend_is_pinned_and_does_not_fallback(monkeypatch):
    import pytest
    from app import ai_services as ai
    from app.ai import WorkflowError
    from app.config import settings
    from app.v2 import tutor

    monkeypatch.setattr(settings, 'deeptutor_structured_teacher', True)
    model = ai.advisory_model('initial_evaluation')
    assert model == ai.TUTOR_CHAT
    assert ai.advisory_model('targeted') == settings.model_name
    monkeypatch.setattr(settings, 'deeptutor_structured_teacher', False)
    calls = []

    async def execute(principal, prompt, capability, submission_id, on_event):
        calls.append((principal, capability, submission_id))
        on_event({'turn_id': 'native-turn-123'})
        assert '教师确认' in prompt
        if len(calls) == 1:
            return tutor.TurnResult('{"approved":false}')
        raise tutor.TutorError('EXECUTION_UNCERTAIN')

    def legacy(*args, **kwargs):
        pytest.fail('A pinned DeepTutor job must never fall back to the legacy model')

    monkeypatch.setattr(tutor, 'execute_turn', execute)
    monkeypatch.setattr(ai, 'completion', legacy)
    metrics = {}
    prompt = ai.messages('评分建议必须由教师确认', {})
    assert ai.advisory_completion(model, 'teacher-scope', 'job', prompt, metrics) == {'approved': False}
    assert metrics['external_id'] == 'native-turn-123' and metrics['provider'] == 'DeepTutor'
    with pytest.raises(WorkflowError, match='DEEPTUTOR_EXECUTION_FAILED'):
        ai.advisory_completion(model, 'teacher-scope', 'job', prompt, metrics)
    assert calls == [('teacher-scope', 'chat', 'job:1'), ('teacher-scope', 'chat', 'job:2')]
