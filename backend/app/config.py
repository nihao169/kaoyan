from pathlib import Path
from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore', env_ignore_empty=True)
    database_url: str = f"sqlite:///{(ROOT / 'data/platform.db').as_posix()}"
    data_dir: Path = ROOT / 'data'
    model_base_url: str = 'https://api.deepseek.com'
    model_api_key: str = Field(default='', validation_alias=AliasChoices('MODEL_API_KEY', 'DEEPSEEK_API_KEY'))
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
    deeptutor_url: str = ''
    deeptutor_bridge_secret: str = ''
    deeptutor_timeout: int = 120
    deeptutor_native_knowledge: bool = False
    deeptutor_native_questions: bool = False
    deeptutor_native_teacher_questions: bool = False
    deeptutor_native_lessons: bool = False
    deeptutor_structured_teacher: bool = False
    deeptutor_practice_projects: str = ''
    deeptutor_teacher_bank_orgs: str = ''
    deeptutor_records_projects: str = ''
    deeptutor_unified_execution: bool = False
    deeptutor_mastery_reviews: bool = False
    frontend_dist: Path | None = None
    legacy_retrieval_enabled: bool = True
    model_input_price: float = 0.3
    model_output_price: float = 1.2
    model_price_version: str = 'deepseek-flash-2026-10-28-peak-USD-estimate'

    @model_validator(mode='after')
    def unified_tutor(self):
        if self.deeptutor_unified_execution:
            self.deeptutor_native_knowledge = True
            self.deeptutor_native_questions = True
            self.deeptutor_native_teacher_questions = True
            self.deeptutor_native_lessons = True
            self.deeptutor_structured_teacher = True
            self.legacy_retrieval_enabled = False
        return self

    @property
    def native_teaching_pipeline(self) -> bool:
        return self.deeptutor_native_knowledge and self.deeptutor_native_teacher_questions and self.deeptutor_structured_teacher


settings = Settings()
