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
os.environ['DATABASE_URL'] = f'sqlite:///{(data / "test.db").as_posix()}'
os.environ['DATA_DIR'] = str(data)
os.environ['ALLOWED_ORIGIN'] = 'http://127.0.0.1:5181'
if os.environ.get('ZX_REAL_AI') != '1':
    os.environ['MODEL_API_KEY'] = ''
sys.path.insert(0, str(root / 'backend'))
from alembic.config import Config
from alembic import command
from app.seed import seed
from app.main import app
import uvicorn

command.upgrade(Config(str(root / 'backend/alembic.ini')), 'head')
seed()
# Load the actual local model before advertising readiness, so browser timeouts
# measure interactions rather than torch/model cold startup.
from app.search import encode_segments
encode_segments('学习准备检查')
if os.environ.get('ZX_REAL_AI') == '1':
    from app.config import settings
    if not settings.model_api_key:
        raise RuntimeError('Real acceptance requires MODEL_API_KEY in server .env')
    from attach_sample_pages import attach
    attach()
import threading
import logging
logging.basicConfig(level=logging.WARNING)
from app.worker import main as run_worker
threading.Thread(target=run_worker, daemon=True).start()
uvicorn.run(app, host='127.0.0.1', port=8001, log_level='warning')
