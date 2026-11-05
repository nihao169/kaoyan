"""Probe the patched DeepTutor image without touching the platform database."""
import asyncio
import os
from pathlib import Path
import sys
from uuid import uuid4

root = Path(__file__).resolve().parents[1]
preview = Path(sys.argv[1]).resolve()
if not preview.is_relative_to(root / '.runtime') or not preview.name.startswith('tutor-native-preview-'):
    raise SystemExit('Pass the isolated tutor-native-preview-* directory under .runtime')
os.environ.update(DEEPTUTOR_URL='http://127.0.0.1:18012',
                  DEEPTUTOR_BRIDGE_SECRET=(preview / 'bridge.key').read_text(encoding='utf-8-sig').strip(),
                  NO_PROXY='127.0.0.1,localhost', DEEPTUTOR_TIMEOUT='240')
sys.path.insert(0, str(root / 'backend'))
from app.v2 import tutor
from app import ai_services

source = ('实践是认识的来源，是认识发展的动力，是检验认识真理性的唯一标准，也是认识的目的。'
          '正确的认识能够促进实践，错误的认识会阻碍实践。真理是具体的、有条件的。')
prompt = ('以以下考研政治原文为唯一依据，生成一题单选、一题多选、一题分析。'
          '为每道题返回支持答案的逐字原文 kaoyan_quote；分析题还返回至少两条评分要点 kaoyan_rubric。'
          '多选答案至少两个，使用逗号分隔的字母。原文：' + source)
token = uuid4().hex
if '--trace-probe' in sys.argv:
    # This script only sends synthetic fixture data.
    original_turn = tutor.execute_turn

    async def traced_turn(principal, content, capability, submission, callback, **kwargs):
        def trace(event):
            if event.get('type') in ('error', 'protocol_error', 'progress', 'done'):
                print(event.get('type'), event.get('error_code'), event.get('content'), event.get('metadata'), flush=True)
            return callback(event)
        return await original_turn(principal, content, capability, submission, trace, **kwargs)

    tutor.execute_turn = traced_turn
if '--advisory-only' not in sys.argv:
    items = asyncio.run(tutor.generate_questions('question-acceptance:'+token, prompt,
                        {'single':1, 'multiple':1, 'essay':1}, token, lambda event: False))
    for item in items:
        assert len(item['quote']) >= 8 and item['quote'] in source, item
        if item['kind'] == 'multiple':
            assert 2 <= len(set(item['answer'])) <= 4 and set(item['answer']) <= set(item['options']), item
        if item['kind'] == 'essay':
            assert len(item['rubric']) >= 2, item
        print('PASS:', item['kind'], 'with exact quotation', flush=True)
response = ai_services.advisory_completion(ai_services.TUTOR_CHAT, 'teacher-advisory-acceptance:'+token, token,
    ai_services.messages('你是教师批阅助手。只返回 {"teacher_confirmation_required":true}。', {}), {})
assert response['teacher_confirmation_required'] is True
print('PASS: DeepTutor structured teacher advisory transport.', flush=True)
