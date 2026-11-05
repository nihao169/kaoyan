"""DeepTutor transport. Model execution remains outside business transactions."""
import asyncio
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
import httpx
from ..config import settings


class TutorError(RuntimeError):
    pass


def signed_assertion(principal, **claims):
    payload = {'principal': principal, 'expires': int(time.time()) + 60, 'audience': 'zhixing-deeptutor', **claims}
    body = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    return payload, hmac.new(settings.deeptutor_bridge_secret.encode(), body, hashlib.sha256).hexdigest()


@dataclass
class TurnResult:
    text: str
    result: dict = field(default_factory=dict)
    turn_id: str | None = None


def accumulate_usage(metrics, event):
    usage = (event.get('metadata') or {}).get('usage_summary') if event.get('type') == 'done' else None
    if not isinstance(usage, dict):
        return False
    for key in ('prompt_tokens', 'completion_tokens', 'total_tokens', 'cache_read_input_tokens', 'reasoning_tokens', 'total_calls'):
        value = usage.get(key)
        if type(value) is int and value >= 0:
            metrics[key] = metrics.get(key, 0) + value
    return True


def require_configuration():
    if not settings.deeptutor_url or len(settings.deeptutor_bridge_secret) < 32:
        raise TutorError('DEEPTUTOR_NOT_CONFIGURED：请配置独立集成服务和至少32字符的身份交换密钥')


def knowledge_request(principal, operation, name, **data):
    require_configuration()
    payload, signature = signed_assertion(principal, operation=operation, name=name, data=data)
    try:
        with httpx.Client(timeout=40, trust_env=False) as client:
            response = client.post(settings.deeptutor_url.rstrip('/') + '/internal/knowledge', json=payload,
                                   headers={'X-Zhixing-Signature': signature})
        if response.status_code == 404:
            return {'state': 'missing'}
        if not response.is_success:
            raise TutorError(f'DEEPTUTOR_KNOWLEDGE_FAILED：知识库服务返回 HTTP {response.status_code}')
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError('invalid knowledge response')
        return result
    except (httpx.HTTPError, ValueError) as exc:
        raise TutorError('DEEPTUTOR_KNOWLEDGE_UNAVAILABLE：无法访问知识库服务') from exc


async def execute_turn(principal, prompt, capability, submission_id, on_event, *, knowledge_bases=(), config=None, **context):
    require_configuration()
    payload, signature = signed_assertion(principal)
    try:
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            response = await client.post(settings.deeptutor_url.rstrip('/') + '/internal/exchange', json=payload, headers={'X-Zhixing-Signature': signature})
            if response.status_code != 200:
                raise TutorError('DEEPTUTOR_IDENTITY_FAILED：基础服务身份交换失败')
            token = response.json()['token']
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise TutorError('DEEPTUTOR_UNAVAILABLE：无法连接基础服务或交换身份') from exc
    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosed
    url = settings.deeptutor_url.rstrip('/').replace('https://', 'wss://').replace('http://', 'ws://') + '/ws'
    content = []
    result = {}
    cancel_sent = False
    turn_id, cursor = None, 0
    finished = False
    async with asyncio.timeout(settings.deeptutor_timeout):
        for attempt in range(3):
            try:
                # v1.7.1 authenticates WebSockets from dt_token.
                async with connect(url, additional_headers={'Cookie': 'dt_token=' + token}, proxy=None, max_size=4 * 1024 * 1024) as ws:
                    command = {'type':'subscribe_turn','turn_id':turn_id,'after_seq':cursor} if turn_id else {
                        'type':'start_turn','content':prompt,'capability':capability,'language':'zh',
                        'tools':[], 'client_submission_id':submission_id, 'auto_route':False,
                        'knowledge_bases':list(knowledge_bases), 'config':config or {}, **context}
                    await ws.send(json.dumps({**command,'protocol_version':'2.0'}))
                    async for raw in ws:
                        event = json.loads(raw)
                        turn_id = event.get('turn_id') or turn_id
                        seq = event.get('seq')
                        if isinstance(seq, int) and seq > 0:
                            if seq <= cursor:
                                continue
                            cursor = seq
                        cancel_requested = on_event(event)
                        if cancel_requested and not cancel_sent and turn_id:
                            await ws.send(json.dumps({'type':'cancel_turn','protocol_version':'2.0',
                                                      'turn_id':turn_id,'command_id':submission_id + ':cancel'}))
                            cancel_sent = True
                        if event.get('type') == 'content' and isinstance(event.get('content'), str):
                            content.append(event['content'])
                        if event.get('type') == 'result' and isinstance(event.get('metadata'), dict):
                            result = event['metadata']
                        if event.get('type') in ('error', 'protocol_error'):
                            code = str(event.get('error_code', 'execution_failed'))[:100]
                            raise TutorError('DEEPTUTOR_EXECUTION_FAILED：' + code)
                        if event.get('type') == 'wait_for_input':
                            raise TutorError('DEEPTUTOR_INPUT_REQUIRED：请补充问题和资料后重新发起')
                        if event.get('type') == 'done':
                            status = event.get('metadata', {}).get('status')
                            if status == 'cancelled' and cancel_sent:
                                return TurnResult('', turn_id=turn_id)
                            if status not in ('completed', None):
                                raise TutorError('DEEPTUTOR_INCOMPLETE：本次生成未正常完成')
                            finished = True
                            break
            except (ConnectionClosed, OSError):
                pass
            if finished:
                break
            if not turn_id:
                raise TutorError('EXECUTION_UNCERTAIN：未确认基础服务是否创建运行，未自动重新调用')
            if attempt < 2:
                await asyncio.sleep(.25 * (attempt+1))
    if not finished:
        raise TutorError('DEEPTUTOR_RECONNECT_FAILED：无法恢复已有运行，未重新提交')
    if not ''.join(content).strip() and not result:
        raise TutorError('DEEPTUTOR_EMPTY_RESULT：基础服务未返回内容')
    return TurnResult(''.join(content), result, turn_id)


async def execute(principal, prompt, capability, submission_id, on_event):
    return (await execute_turn(principal, prompt, capability, submission_id, on_event)).text


def lesson_text(capability, turn):
    # These native capabilities may publish their final answer as an envelope
    # rather than a stream of content deltas.
    response = turn.result.get('response')
    if isinstance(response, str) and response.strip():
        return response
    if turn.text.strip():
        return turn.text
    if not turn.result:
        return ''  # cancelled downstream
    raise TutorError(f'DEEPTUTOR_EMPTY_RESULT：{capability} 未返回可读内容')


QUESTION_TYPES = {'single': 'choice', 'multiple': 'multiple_choice', 'essay': 'written'}


async def generate_questions(principal, prompt, counts, submission_id, on_event, *, knowledge_bases=()):
    native_counts = {QUESTION_TYPES[kind]: count for kind, count in counts.items() if count}
    turn = await execute_turn(principal, prompt, 'deep_question', submission_id, on_event,
        knowledge_bases=knowledge_bases, config={'mode': 'custom', 'topic': prompt,
        'num_questions': sum(native_counts.values()), 'question_types': list(native_counts), 'per_type_counts': native_counts})
    if not turn.text and not turn.result:
        return []
    summary = turn.result.get('summary', {})
    if not isinstance(summary, dict) or not summary.get('success'):
        raise TutorError('QUESTION_GENERATION_FAILED：DeepTutor 未返回完整的原生题目结果')
    result = []
    actual = dict.fromkeys(native_counts, 0)
    for entry in summary.get('results', []):
        qa, metadata = entry.get('qa_pair', {}), entry.get('metadata', {})
        kind = qa.get('question_type')
        if kind not in actual or metadata.get('issues') or not metadata.get('kaoyan_quote'):
            raise TutorError(f'QUESTION_INVALID：原生题型 {kind if kind in QUESTION_TYPES.values() else "未知"} 未通过题型、格式或逐字引文校验')
        actual[kind] += 1
        result.append({'kind': next(key for key, value in QUESTION_TYPES.items() if value == kind),
            'prompt': qa.get('question'), 'options': qa.get('options') or {},
            'answer': [] if kind == 'written' else [part.strip() for part in qa.get('correct_answer', '').split(',')],
            'reference_answer': qa.get('correct_answer', '') if kind == 'written' else '',
            'explanation': qa.get('explanation'), 'quote': metadata['kaoyan_quote'],
            'rubric': metadata.get('kaoyan_rubric') or []})
    if actual != native_counts or any(item['kind'] == 'essay' and not item['rubric'] for item in result):
        raise TutorError('QUESTION_INVALID：原生题型数量不匹配，或分析题缺少评分要点')
    return result


def json_result(text):
    text = text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    return json.loads(text)
