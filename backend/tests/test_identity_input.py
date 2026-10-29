import pytest
from pydantic import ValidationError
from app.schemas import LoginInput


def test_login_trims_accidental_username_whitespace():
    assert LoginInput(username=' teacher ', password='example').username == 'teacher'


def test_login_rejects_username_that_is_only_whitespace():
    with pytest.raises(ValidationError):
        LoginInput(username='   ', password='example')


def test_login_preserves_password_whitespace():
    assert LoginInput(username='teacher', password=' example ').password == ' example '
