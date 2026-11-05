"""Isolated browser-test server; never points at the delivered demo database."""
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.chdir(root)
data = Path(os.environ['ZX_E2E_DATA']).resolve()
if not data.is_relative_to(root / '.runtime'):
    raise RuntimeError('Browser test data must stay inside the workspace .runtime directory')
data.mkdir(parents=True, exist_ok=True)
database_url = os.environ.get('ZX_E2E_ISOLATED_DATABASE_URL')
if database_url:
    from sqlalchemy.engine import make_url
    url = make_url(database_url)
    if (url.get_backend_name() != 'postgresql' or url.host not in ('127.0.0.1', 'localhost') or
            not (url.database or '').startswith('zhixing_tutor_native_')):
        raise RuntimeError('Use a dedicated local PostgreSQL database named zhixing_tutor_native_*')
os.environ['DATABASE_URL'] = database_url or f'sqlite:///{(data / "test.db").as_posix()}'
os.environ['DATA_DIR'] = str(data)
os.environ['ALLOWED_ORIGIN'] = 'http://127.0.0.1:5181'
if os.environ.get('ZX_REAL_AI') != '1':
    os.environ['MODEL_API_KEY'] = ''
sys.path.insert(0, str(root / 'backend'))
from alembic.config import Config
from alembic import command
from app.seed import seed
from app.config import settings
if os.environ.get('ZX_REAL_AI') != '1':
    # Empty environment values are intentionally ignored in production settings.
    # Explicitly disable real provider access in ordinary isolated browser tests.
    settings.model_api_key = ''
from app.main import app
import uvicorn

if os.environ.get('ZX_V2_TEST_PROVIDER') == '1':
    if os.environ.get('ZX_REAL_AI') == '1':
        raise RuntimeError('Controlled V2 provider cannot be used in real AI acceptance')
    import json
    import re
    from app.v2 import tutor
    from app import search
    async def controlled_v2(principal, prompt, capability, submission_id, on_event):
        material_id=re.search(r'资料ID:([0-9a-f-]+)',prompt)
        if '请独立校验' in prompt:
            return json.dumps({'valid':True,'reason':'显式受控校验通过'})
        if '只输出JSON对象，字段material_id' in prompt:
            return json.dumps({'material_id':material_id.group(1),'knowledge':'实践与认识','kind':'single','prompt':'实践与认识的关系中，哪项是检验标准？'+submission_id[:6], 'options':{'A':'实践','B':'主观愿望'},'answer':['A'],'explanation':'实践是检验认识真理性的唯一标准。','quote':'实践是检验认识真理性的唯一标准','rubric':[]},ensure_ascii=False)
        return '受控浏览器测试答复：请回到资料中核对实践与认识的关系。'
    tutor.execute=controlled_v2
    search.encode_segments=lambda text:[[1.0,0.0,0.0]]

command.upgrade(Config(str(root / 'backend/alembic.ini')), 'head')
seed(include_demo_content=os.environ.get('ZX_TEACHING_FLOW')!='1' and os.environ.get('ZX_V2_TEST_PROVIDER')!='1')
if os.environ.get('ZX_TEACHING_TEST_PROVIDER') == '1':
    if os.environ.get('ZX_REAL_AI') == '1':
        raise RuntimeError('Controlled and real providers must never be combined')
    sys.path.insert(0,str(root / 'backend/tests'))
    from teaching_provider import create_provider
    from app import ai_services
    ai_services.completion = create_provider()
    settings.model_api_key = 'explicit-controlled-browser-test-key'
    settings.model_name = 'controlled-browser-provider'
# Load the actual local model before advertising readiness, so browser timeouts
# measure interactions rather than torch/model cold startup.
from app.search import encode_segments
encode_segments('学习准备检查')
if os.environ.get('ZX_REAL_AI') == '1':
    from app.config import settings
    from app.ai_services import TUTOR_CHAT, configured
    native_teaching = (os.environ.get('ZX_TEACHING_FLOW') == '1' and settings.deeptutor_native_teacher_questions and
                       settings.deeptutor_structured_teacher and configured(TUTOR_CHAT))
    if not settings.model_api_key and not native_teaching:
        raise RuntimeError('Real acceptance requires MODEL_API_KEY in server .env')
    if os.environ.get('ZX_TEACHING_FLOW') != '1':
        from attach_sample_pages import attach
        attach()
import threading
import logging
logging.basicConfig(level=logging.WARNING)
from app.worker import main as run_worker
threading.Thread(target=run_worker, daemon=True).start()
uvicorn.run(app, host='127.0.0.1', port=8001, log_level='warning')
