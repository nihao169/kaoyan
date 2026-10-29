from app.config import Settings


def test_empty_dotenv_key_does_not_hide_deepseek_environment_key(tmp_path, monkeypatch):
    monkeypatch.delenv('MODEL_API_KEY', raising=False)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-user-environment-key')
    dotenv = tmp_path / '.env'
    dotenv.write_text('MODEL_API_KEY=\n', encoding='utf-8')
    assert Settings(_env_file=dotenv).model_api_key == 'test-user-environment-key'


def test_explicit_model_key_has_priority(tmp_path, monkeypatch):
    monkeypatch.setenv('MODEL_API_KEY', 'test-explicit-model-key')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-user-environment-key')
    assert Settings(_env_file=None).model_api_key == 'test-explicit-model-key'
