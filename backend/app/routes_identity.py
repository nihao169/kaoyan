import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select, func
from argon2.exceptions import VerificationError
from . import models as m
from . import schemas as s
from .auth import context, passwords, digest, need, me
from .config import settings
from .db import get_db
from .errors import fail, require
from .api_common import entity, EnvelopeRoute

router = APIRouter(route_class=EnvelopeRoute)


@router.post('/auth/login')
def login(data: s.LoginInput, request: Request, response: Response, db=Depends(get_db)):
    # Persistent throttling avoids resetting the limit when the API restarts.
    since = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    failures = db.scalar(select(func.count()).select_from(m.AuditEvent).where(m.AuditEvent.action == 'auth.failed', m.AuditEvent.resource_id == digest(data.username)[:32], m.AuditEvent.created_at > since))
    if failures >= 10:
        fail(429, 'LOGIN_THROTTLED', '尝试过于频繁，请五分钟后重试')
    user = db.scalar(select(m.User).where(m.User.username == data.username, m.User.active == True))
    valid = False
    try:
        valid = passwords.verify(user.password_hash if user else passwords.hash('invalid-account-placeholder'), data.password)
    except VerificationError:
        pass
    if not user or not valid:
        db.add(m.AuditEvent(action='auth.failed', resource_id=digest(data.username)[:32]))
        db.commit()
        fail(401, 'INVALID_CREDENTIALS', '账号或密码错误')
    stmt = select(m.Membership).where(m.Membership.user_id == user.id, m.Membership.active == True)
    if data.org_id:
        stmt = stmt.where(m.Membership.org_id == data.org_id)
    members = list(db.scalars(stmt))
    if not members:
        fail(403, 'NO_MEMBERSHIP', '没有可用的机构成员关系')
    if len(members) > 1:
        fail(409, 'ORG_SELECTION_REQUIRED', '请指定要登录的机构')
    token = secrets.token_urlsafe(48)
    session = m.LoginSession(token_hash=digest(token), csrf=secrets.token_urlsafe(32), membership_id=members[0].id,
                             expires_at=(datetime.now(timezone.utc) + timedelta(hours=settings.session_hours)).isoformat())
    db.add(session)
    db.flush()
    db.add(m.AuditEvent(org_id=members[0].org_id, actor_id=user.id, action='auth.login', resource_id=session.id))
    response.set_cookie('zx_session', token, httponly=True, secure=settings.secure_cookies, samesite='lax', max_age=settings.session_hours * 3600, path='/')
    return {'user_id': user.id}


@router.post('/auth/logout')
def logout(response: Response, ctx=Depends(context), db=Depends(get_db)):
    db.delete(ctx.session)
    response.delete_cookie('zx_session', path='/')
    return {'logged_out': True}


@router.get('/me', response_model=s.MeOutput)
def current_user(ctx=Depends(context)):
    return me(ctx)


@router.get('/catalog', response_model=s.CatalogOutput)
def catalog(ctx=Depends(context), db=Depends(get_db)):
    subjects = [entity(x, 'id', 'name', 'code') for x in db.scalars(select(m.Subject))]
    modules = [entity(x, 'id', 'name', 'subject_id', 'position') for x in db.scalars(select(m.Module).order_by(m.Module.position))]
    knowledge = [entity(x, 'id', 'name', 'module_id') for x in db.scalars(select(m.KnowledgePoint))]
    return {'subjects': subjects, 'modules': modules, 'knowledge': knowledge}


@router.get('/admin/users', response_model=list[s.AccountOutput])
def users(ctx=Depends(context), db=Depends(get_db)):
    need(ctx, 'admin')
    items = []
    for member, user in db.execute(select(m.Membership, m.User).join(m.User).where(m.Membership.org_id == ctx.org_id)):
        roles = list(db.scalars(select(m.RoleAssignment.role).where(m.RoleAssignment.membership_id == member.id)))
        items.append({**entity(user, 'id', 'username', 'name', 'active'), 'roles': sorted(set(roles))})
    return items


@router.post('/admin/users')
def add_user(data: s.UserInput, ctx=Depends(context), db=Depends(get_db)):
    need(ctx, 'admin')
    cls = require(db.get(m.TeachingClass, data.class_id))
    if cls.org_id != ctx.org_id:
        fail(404, 'NOT_FOUND', '班级不存在')
    if db.scalar(select(m.User.id).where(m.User.username == data.username)):
        fail(409, 'USERNAME_EXISTS', '账号已存在')
    user = m.User(username=data.username, name=data.name, password_hash=passwords.hash(data.password))
    db.add(user)
    db.flush()
    member = m.Membership(user_id=user.id, org_id=ctx.org_id)
    db.add(member)
    db.flush()
    db.add(m.ClassMember(class_id=cls.id, membership_id=member.id))
    for role in set(data.roles):
        db.add(m.RoleAssignment(membership_id=member.id, role=role, class_id=cls.id if role == 'teacher' else None))
    db.add(m.AuditEvent(org_id=ctx.org_id, actor_id=ctx.user.id, action='user.create', resource_id=user.id))
    return entity(user, 'id', 'name', 'username')


@router.get('/classes', response_model=list[s.NamedOutput])
def classes(ctx=Depends(context), db=Depends(get_db)):
    stmt = select(m.TeachingClass).where(m.TeachingClass.org_id == ctx.org_id)
    if not ctx.has('admin') and not any(r.role == 'teacher' and r.class_id is None for r in ctx.roles):
        class_ids = list(db.scalars(select(m.ClassMember.class_id).where(m.ClassMember.membership_id == ctx.membership.id)))
        class_ids += [r.class_id for r in ctx.roles if r.role == 'teacher']
        stmt = stmt.where(m.TeachingClass.id.in_(class_ids))
    return [entity(c, 'id', 'name') for c in db.scalars(stmt)]
