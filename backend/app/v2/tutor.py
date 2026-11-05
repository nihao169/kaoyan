"""DeepTutor transport. Model execution remains outside business transactions."""
import asyncio
import hashlib
import hmac
import json
import time
import httpx
from ..config import settings


class TutorError(RuntimeError):
    pass


def signed_assertion(principal):
    payload = {'principal': principal, 'expires': int(time.time()) + 60, 'audience': 'zhixing-deeptutor'}
    body = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    return payload, hmac.new(settings.deeptutor_bridge_secret.encode(), body, hashlib.sha256).hexdigest()


async def execute(principal, prompt, capability, submission_id, on_event):
    if not settings.deeptutor_url or len(settings.deeptutor_bridge_secret) < 32:
        raise TutorError('DEEPTUTOR_NOT_CONFIGURED：请配置独立集成服务和至少32字符的身份交换密钥')
    payload, signature = signed_assertion(principal)
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(settings.deeptutor_url.rstrip('/') + '/internal/exchange', json=payload, headers={'X-Zhixing-Signature': signature})
        if response.status_code != 200:
            raise TutorError('DEEPTUTOR_IDENTITY_FAILED：基础服务身份交换失败')
        token = response.json()['token']
    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosed
    url = settings.deeptutor_url.rstrip('/').replace('https://', 'wss://').replace('http://', 'ws://') + '/ws'
    content = []
    cancel_sent = False
    turn_id, cursor = None, 0
    finished = False
    async with asyncio.timeout(settings.deeptutor_timeout):
        for attempt in range(3):
            try:
                # v1.7.1 authenticates WebSockets from dt_token.
                async with connect(url, additional_headers={'Cookie': 'dt_token=' + token}, max_size=4 * 1024 * 1024) as ws:
                    command = {'type':'subscribe_turn','turn_id':turn_id,'after_seq':cursor} if turn_id else {
                        'type':'start_turn','content':prompt,'capability':capability,'language':'zh',
                        'tools':[], 'client_submission_id':submission_id}
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
                        if event.get('type') in ('error', 'protocol_error'):
                            code = str(event.get('error_code', 'execution_failed'))[:100]
                            raise TutorError('DEEPTUTOR_EXECUTION_FAILED：' + code)
                        if event.get('type') == 'wait_for_input':
                            raise TutorError('DEEPTUTOR_INPUT_REQUIRED：请补充问题和资料后重新发起')
                        if event.get('type') == 'done':
                            status = event.get('metadata', {}).get('status')
                            if status == 'cancelled' and cancel_sent:
                                return ''
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
    if not ''.join(content).strip():
        raise TutorError('DEEPTUTOR_EMPTY_RESULT：基础服务未返回内容')
    return ''.join(content)


def json_result(text):
    text = text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    return json.loads(text)
