from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    database_url: str = f"sqlite:///{(ROOT / 'data/platform.db').as_posix()}"
    data_dir: Path = ROOT / 'data'
    model_base_url: str = 'https://api.deepseek.com'
    model_api_key: str = ''
    model_name: str = 'deepseek-flash'
    model_timeout: int = 30
    secure_cookies: bool = False
    session_hours: int = 8
    allowed_origin: str = 'http://127.0.0.1:5173'
    embedding_model: str = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
    embedding_revision: str = 'main'
    embedding_local_only: bool = True
    embedding_cache_dir: Path = ROOT / 'data' / 'models'
    document_converter: str = ''
    model_input_price: float = 0.3
    model_output_price: float = 1.2
    model_price_version: str = 'deepseek-flash-2026-10-28-peak-USD-estimate'


settings = Settings()
