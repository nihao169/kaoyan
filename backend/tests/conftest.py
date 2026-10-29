import sys
from pathlib import Path
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app import db as database
from app.config import settings
from app.seed import seed
from app.main import app


@pytest.fixture
def environment(tmp_path, monkeypatch, request):
    data = tmp_path / 'data'
    data.mkdir()
    url = f'sqlite:///{(data / "test.db").as_posix()}'
    engine = database.make_engine(url)
    monkeypatch.setattr(database, 'engine', engine)
    monkeypatch.setattr(settings, 'database_url', url)
    monkeypatch.setattr(settings, 'data_dir', data)
    monkeypatch.setattr(settings, 'model_api_key', '')
    # Explicit deterministic test adapter; real model retrieval is evaluated separately.
    def controlled_embedding(text):
        import hashlib
        values = [0.0]*32
        for char in text:
            values[hashlib.sha256(char.encode()).digest()[0]%32] += 1
        norm = sum(v*v for v in values)**0.5 or 1
        return [[v/norm for v in values]]
    monkeypatch.setattr('app.search.encode_segments', controlled_embedding)
    database.SessionLocal.configure(bind=engine)
    cfg = Config(str(ROOT / 'backend/alembic.ini'))
    cfg.set_main_option('script_location', str(ROOT / 'backend/migrations'))
    command.upgrade(cfg, 'head')
    seed(include_demo_content=getattr(request,'param',True))
    yield data
    engine.dispose()


@pytest.fixture(scope='session')
def document_fixture(tmp_path_factory):
    """Disposable parser inputs, independent of user-facing teaching files."""
    from docx import Document
    import pymupdf as fitz
    directory=tmp_path_factory.mktemp('parser-documents')
    text='自动化解析测试专用。实践是认识的来源，也是检验认识真理性的唯一标准。分析材料需要核对具体条件和实际反馈。本段不预设题目、选项和评分结果。'
    doc=Document()
    doc.add_heading('解析测试文档',0)
    doc.add_paragraph(text)
    doc.save(directory/'sample.docx')
    with fitz.open() as pdf:
        page=pdf.new_page()
        page.insert_textbox(fitz.Rect(72,72,520,400),text,fontname='china-s',fontsize=12)
        pdf.save(directory/'sample.pdf')
    return directory


def login_client(username):
    client = TestClient(app)
    result = client.post('/api/v1/auth/login', json={'username': username, 'password': 'Zhixing2026!'})
    assert result.status_code == 200, result.text
    user = client.get('/api/v1/me').json()['data']
    client.headers.update({'X-CSRF-Token': user['csrf_token']})
    return client


@pytest.fixture
def clients(environment):
    student, teacher, admin = (login_client(role) for role in ('student', 'teacher', 'admin'))
    yield student, teacher, admin
    for client in (student, teacher, admin):
        client.close()


def checked(client, path, method='GET', body=None, status=200, idem=None):
    from uuid import uuid4
    if method == 'POST' and path.startswith('/content/sources/') and path.endswith('/submit') and status < 400:
        # Drive the actual background worker deterministically in isolated API tests.
        from app.worker import tick
        for _ in range(100):
            if not tick(): break
    response = client.request(method, '/api/v1' + path, json=body, headers={'Idempotency-Key': idem or str(uuid4())})
    assert response.status_code == status, response.text
    return response.json().get('data') if status < 400 else response.json()['error']


def publish_all(teacher):
    sources = checked(teacher, '/content/sources')['items']
    for source in sources:
        checked(teacher, f'/content/sources/{source["id"]}/submit', 'POST', {'note': '测试教师核对'})
        checked(teacher, f'/content/sources/{source["id"]}/publish', 'POST', {'note': '测试数据，隔离环境发布'})
    return sources


def create_task(student, question_id, mode='practice'):
    from app import models as m
    with database.SessionLocal.begin() as db:
        membership_id = checked(student, '/me')['membership_id']
        task = m.LearningTask(membership_id=membership_id, question_version_id=question_id, task_key='test:' + m.uid(), mode=mode, reason='测试任务')
        db.add(task)
        db.flush()
        task_id = task.id
    return checked(student, f'/tasks/{task_id}/attempts', 'POST')


def save_and_submit(student, attempt, answer=None, response_text='', process='保留原始思考过程'):
    checked(student, f'/attempts/{attempt["id"]}/draft', 'PATCH', {
        'answer': answer or [], 'response_text': response_text, 'process': process,
        'duration_seconds': 42, 'revision': attempt['revision'],
    })
    return checked(student, f'/attempts/{attempt["id"]}/submit', 'POST')
