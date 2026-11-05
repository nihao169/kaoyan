"""Self-service registration creates a private compatibility membership.

PersonalSpace owns autonomous learning; the private organization only preserves
the V1 login/session contract and never joins the learner to a teaching class.
"""
import secrets
from datetime import timedelta
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from .. import models as m
from ..auth import passwords, digest
from ..api_common import EnvelopeRoute
from ..config import settings
from ..db import get_db
from ..errors import fail
from .service import clock, space

router = APIRouter(route_class=EnvelopeRoute)


class RegisterInput(BaseModel):
    username: str = Field(min_length=3, max_length=60, pattern=r'^[a-zA-Z0-9_-]+$')
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=10, max_length=128)

    @field_validator('name')
    @classmethod
    def name_not_blank(cls, value):
        if not value.strip():
            raise ValueError('姓名不能为空')
        return value.strip()


@router.post('/auth/register', status_code=201)
def register(data: RegisterInput, response: Response, db=Depends(get_db)):
    if db.scalar(select(m.User.id).where(m.User.username == data.username)):
        fail(409, 'USERNAME_EXISTS', '账号已存在')
    user = m.User(username=data.username, name=data.name, password_hash=passwords.hash(data.password))
    org = m.Organization(name='个人学习空间', is_demo=False)
    db.add_all([user, org])
    db.flush()
    member = m.Membership(user_id=user.id, org_id=org.id)
    db.add(member)
    db.flush()
    db.add(m.RoleAssignment(membership_id=member.id, role='student'))
    space(db, user.id)
    token = secrets.token_urlsafe(48)
    db.add(m.LoginSession(token_hash=digest(token), csrf=secrets.token_urlsafe(32), membership_id=member.id,
                          expires_at=(clock() + timedelta(hours=settings.session_hours)).isoformat()))
    response.set_cookie('zx_session', token, httponly=True, secure=settings.secure_cookies, samesite='lax', max_age=settings.session_hours * 3600, path='/')
    return {'user_id': user.id}
