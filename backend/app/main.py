import json
import logging
import time
from uuid import uuid4
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.utils import get_openapi
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from .config import settings
from .db import SessionLocal
from . import routes_identity, routes_learning, routes_content, routes_teacher
from . import routes_extensions
from . import routes_workflows
from .v2.routes import router as v2_router
from .v2.identity import router as v2_identity
from .v2.assessments import router as v2_assessments
from .v2.exam_resources import router as v2_exam_resources
from .v2.mastery_review_routes import router as v2_mastery_reviews

logger = logging.getLogger('zhixing')


def create_app():
    @asynccontextmanager
    async def lifespan(app):
        from .search import encode_segments, SearchUnavailable
        app.state.retrieval_ready = False
        if settings.legacy_retrieval_enabled:
            try:
                encode_segments('学习资料检索准备')
                app.state.retrieval_ready = True
            except SearchUnavailable:
                logger.warning('local retrieval not ready; run scripts/setup_models.py --download')
        yield
    app = FastAPI(title='知行研学平台 API', version='0.2.0', description='政治学习、资料原页、混合检索与 DeepSeek 辅助教学。', lifespan=lifespan)
    @app.middleware('http')
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid4())
        started = time.monotonic()
        origin = request.headers.get('origin')
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin and origin not in (settings.allowed_origin, str(request.base_url).rstrip('/')):
            return JSONResponse({'error': {'code': 'ORIGIN_DENIED', 'message': '请求来源不被允许'}, 'request_id': request.state.request_id}, status_code=403)
        response = await call_next(request)
        response.headers['X-Request-ID'] = request.state.request_id
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'none'"
        logger.info('request id=%s method=%s status=%s duration_ms=%d', request.state.request_id, request.method, response.status_code, (time.monotonic()-started)*1000)
        return response

    def error_response(request, status, code, message, fields=None):
        body = {'error': {'code': code, 'message': message}, 'request_id': getattr(request.state, 'request_id', '')}
        if fields:
            body['error']['fields'] = fields
        return JSONResponse(body, status_code=status)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        detail = exc.detail if isinstance(exc.detail, dict) else {'code': 'HTTP_ERROR', 'message': str(exc.detail)}
        return error_response(request, exc.status_code, detail['code'], detail['message'])

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        fields = [{'field': '.'.join(map(str, e['loc'])), 'message': e['msg']} for e in exc.errors()]
        return error_response(request, 422, 'VALIDATION_ERROR', '请求字段无效', fields)

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, exc):
        return error_response(request, 409, 'CONCURRENT_CONFLICT', '记录已存在或正在被更新，请刷新查看')

    @app.exception_handler(OperationalError)
    async def database_error(request, exc):
        logger.error('database operation failed request=%s', request.state.request_id)
        return error_response(request, 503, 'DATABASE_UNAVAILABLE', '数据服务暂不可用，请重试')

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        logger.error('unexpected error type=%s request=%s', type(exc).__name__, getattr(request.state, 'request_id', ''))
        return error_response(request, 500, 'INTERNAL_ERROR', '服务暂时无法完成请求，原有记录已保留')

    @app.get('/health/live')
    def live():
        return {'status': 'ok'}

    @app.get('/health/ready')
    def ready():
        import tempfile
        with SessionLocal() as db:
            revision = db.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
            db.execute(text('SELECT id FROM users LIMIT 1'))
            if settings.frontend_dist:
                db.execute(text('SELECT id FROM v2_exam_resources LIMIT 1'))
        if not revision:
            return JSONResponse({'status': 'not_ready'}, status_code=503)
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=settings.data_dir) as file:
            file.write(b'readiness')
        return {'status': 'ready', 'migration': revision, 'ai': 'configured' if settings.model_api_key and settings.model_name and settings.model_base_url else 'not_configured',
                'retrieval': 'ready' if getattr(app.state, 'retrieval_ready', False) else 'not_ready',
                'deeptutor': 'configured' if settings.deeptutor_url and settings.deeptutor_bridge_secret else 'not_configured'}

    @app.get('/health/ai')
    def ai_health():
        import httpx
        if not settings.deeptutor_url or len(settings.deeptutor_bridge_secret) < 32:
            return JSONResponse({'status':'not_configured'}, status_code=503)
        try:
            response = httpx.get(settings.deeptutor_url.rstrip('/')+'/health/ready', timeout=2)
            if response.is_success and response.json().get('status') == 'ready':
                return {'status':'ready','checks':['deeptutor_runtime']}
        except (httpx.HTTPError, ValueError, AttributeError):
            pass
        return JSONResponse({'status':'unavailable'}, status_code=503)

    # Fixed workflow actions must precede the legacy /content/sources/{id}/{action} route.
    for module in (routes_identity, routes_learning, routes_workflows, routes_content, routes_teacher, routes_extensions):
        app.include_router(module.router, prefix='/api/v1')
    app.include_router(v2_router, prefix='/api/v2')
    app.include_router(v2_identity, prefix='/api/v2')
    app.include_router(v2_assessments, prefix='/api/v2')
    app.include_router(v2_exam_resources, prefix='/api/v2')
    app.include_router(v2_mastery_reviews, prefix='/api/v2')

    def openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
        for path, item in schema['paths'].items():
            if not path.startswith(('/api/v1/', '/api/v2/')):
                continue
            for operation in item.values():
                if not isinstance(operation, dict) or 'responses' not in operation:
                    continue
                for status, response in operation['responses'].items():
                    if status.startswith('2') and 'application/json' in response.get('content', {}):
                        data = response['content']['application/json'].get('schema', {})
                        response['content']['application/json']['schema'] = {'type': 'object', 'required': ['data', 'request_id'], 'properties': {'data': data, 'request_id': {'type': 'string'}}}
                for status in ('401', '403', '404', '409', '422', '503'):
                    operation['responses'][status] = {'description': '标准错误响应', 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/APIErrorEnvelope'}}}}
        schema.setdefault('components', {}).setdefault('schemas', {})['APIErrorEnvelope'] = {
            'type': 'object', 'required': ['error', 'request_id'], 'properties': {
                'request_id': {'type': 'string'}, 'error': {'type': 'object', 'required': ['code', 'message'], 'properties': {
                    'code': {'type': 'string'}, 'message': {'type': 'string'}, 'fields': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': True}}}}}}
        app.openapi_schema = schema
        return schema
    app.openapi = openapi
    if settings.frontend_dist:
        dist = settings.frontend_dist.resolve(strict=True)
        app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='frontend-assets')

        @app.get('/{path:path}', include_in_schema=False)
        def spa(path: str):
            # API mistakes must retain their 404, even on the same origin as the SPA.
            if path.partition('/')[0] in ('api', 'health', 'internal') or '.' in path.rsplit('/', 1)[-1]:
                return JSONResponse({'error': {'code': 'NOT_FOUND', 'message': '资源不存在'}}, status_code=404)
            return FileResponse(dist / 'index.html', media_type='text/html')
    return app


app = create_app()
