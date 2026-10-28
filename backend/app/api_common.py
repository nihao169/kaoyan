import hashlib
import json
from fastapi import Request
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from sqlalchemy import select
from . import models as m
from .errors import fail


class EnvelopeRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handler(request):
            response = await original(request)
            if response.status_code < 400 and getattr(response, 'media_type', None) == 'application/json':
                payload = json.loads(response.body)
                headers = {k: v for k, v in response.headers.items() if k.lower() not in ('content-length', 'content-type', 'set-cookie')}
                wrapped = JSONResponse({'data': payload, 'request_id': request.state.request_id}, status_code=response.status_code, headers=headers, background=response.background)
                for name, value in response.raw_headers:
                    if name == b'set-cookie':
                        wrapped.raw_headers.append((name, value))
                return wrapped
            return response
        return handler


def entity(row, *fields):
    return {k: getattr(row, k) for k in fields}


def idempotent(db, ctx, request: Request, operation, body, callback):
    key = request.headers.get('Idempotency-Key', '')
    if not key or len(key) > 150:
        fail(422, 'IDEMPOTENCY_KEY_REQUIRED', '请提供 Idempotency-Key（最多150字符）')
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    existing = db.scalar(select(m.IdempotencyRecord).where(m.IdempotencyRecord.membership_id == ctx.membership.id, m.IdempotencyRecord.operation == operation, m.IdempotencyRecord.key == key))
    if existing:
        if existing.digest != digest:
            fail(409, 'IDEMPOTENCY_CONFLICT', '相同幂等键不能提交不同内容')
        return existing.result
    result = callback()
    db.add(m.IdempotencyRecord(membership_id=ctx.membership.id, operation=operation, key=key, digest=digest, result=result))
    db.flush()
    return result


def no_active_diagnostic(db, ctx):
    if db.scalar(select(m.DiagnosticSession.id).where(m.DiagnosticSession.membership_id == ctx.membership.id, m.DiagnosticSession.status == 'active')):
        fail(403, 'DIAGNOSTIC_RESTRICTION', '诊断期间不可查看提示、解析或检索资料')
