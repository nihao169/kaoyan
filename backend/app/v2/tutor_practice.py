"""Personal question bank and objective grading through DeepTutor Practice."""
import asyncio

from ..config import settings
from ..errors import fail
from . import tutor


BANK = '/api/question-notebook'


def enabled(project_id):
    return project_id in settings.deeptutor_practice_projects.split()


def eligible(question, material):
    return question.origin == 'ai_generated' and bool(question.quote) and question.quote in material.text


async def entry(owner, scope_id, question_id, material_id, kind, prompt, options, answer, explanation):
    identity = {'origin_type': 'external_import', 'origin_ref': scope_id, 'question_id': question_id}
    payload = {
        **identity, 'source': 'deep_question', 'material_id': material_id,
        'question_type': {'single': 'single_choice', 'multiple': 'multi_choice', 'essay': 'essay'}[kind],
        'question': prompt, 'options': options, 'correct_answer': ','.join(answer),
        'explanation': explanation, 'assessment_type': 'quiz', 'result': 'ungraded',
    }
    result = await tutor.native_request(owner, 'GET', BANK + '/entries/lookup/by-question',
                                        params={**identity, 'missing_ok': 'true'}, missing_ok=True, timeout=8)
    if not result:
        result = await tutor.native_request(owner, 'POST', BANK + '/entries/upsert', body=payload, timeout=8)
    fields = (*identity, 'material_id', 'question_type', 'question', 'options', 'correct_answer')
    if type(result.get('id')) is not int or any(result.get(key) != payload[key] for key in fields):
        raise tutor.TutorError('题库条目与经过核验的题目不一致')
    return result


async def personal_entry(owner, project_id, q):
    return await entry(owner, project_id, q.id, q.material_id, q.kind, q.prompt, q.options, q.answer, q.explanation)


def call(operation):
    try:
        return asyncio.run(operation)
    except tutor.TutorError:
        fail(503, 'TUTOR_PRACTICE_UNAVAILABLE', '原生题库或练习服务暂不可用，请稍后重试')


async def grade(user_id, project_id, question, answer):
    owner = f'{user_id}:{project_id}:practice'
    item = await personal_entry(owner, project_id, question)
    result = await tutor.native_request(owner, 'POST', f"{BANK}/practice/questions/{item['id']}/check",
                                        body={'answer': ','.join(answer)}, timeout=8)
    if type(result.get('correct')) is not bool:
        raise tutor.TutorError('原生练习未返回有效判分')
    if result['correct'] != (set(answer) == set(question.answer)):
        raise tutor.TutorError('原生判分与考研客观题规则不一致')
    return result['correct']


async def question_views(user_id, project_id, questions):
    from .service import question_view

    views = []
    owner = f'{user_id}:{project_id}:practice'
    for question in questions:
        item = await personal_entry(owner, project_id, question)
        views.append({**question_view(question), 'prompt': item['question'], 'options': item['options']})
    return views


async def teacher_entries(org_id, questions):
    owner = f'{org_id}:teacher-bank'
    entries = {}
    for q in questions:
        entries[q['id']] = await entry(owner, org_id, q['id'], q['source_version_id'], q['kind'],
                                       q['prompt'], q['options'], q['answer'], q['explanation'])
    return entries
