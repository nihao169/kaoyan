import pytest
from sqlalchemy import select,func
from app import models as m
from app.db import SessionLocal
from app.seed import seed
from conftest import checked


@pytest.mark.parametrize('environment',[False],indirect=True)
def test_normal_initialization_never_injects_teaching_content(clients):
    student,teacher,_=clients
    assert seed() is False
    assert checked(teacher,'/content/sources')['items']==[]
    assert checked(teacher,'/teaching/questions')==[]
    assert checked(student,'/assignments')==[]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(m.User))==3
        assert db.scalar(select(func.count()).select_from(m.ScoringPolicyVersion))==3
        assert db.scalar(select(func.count()).select_from(m.QuestionVersion))==0
