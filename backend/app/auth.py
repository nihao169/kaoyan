import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, Request
from sqlalchemy import select
from .db import get_db
from .models import User, Membership, LoginSession, RoleAssignment, ClassMember, TeachingClass, now
from .errors import fail

passwords = PasswordHasher()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass
class Context:
    user: User
    membership: Membership
    roles: list[RoleAssignment]
    session: LoginSession

    @property
    def org_id(self):
        return self.membership.org_id

    def has(self, role):
        return any(r.role == role for r in self.roles)


def context(request: Request, db=Depends(get_db)):
    token = request.cookies.get('zx_session', '')
    session = db.scalar(select(LoginSession).where(LoginSession.token_hash == digest(token), LoginSession.expires_at > now()))
    if not session:
        fail(401, 'UNAUTHENTICATED', '请先登录')
    member = db.get(Membership, session.membership_id)
    user = db.get(User, member.user_id)
    if not member.active or not user.active:
        fail(401, 'ACCOUNT_DISABLED', '账号或机构成员关系已停用')
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        if not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), session.csrf):
            fail(403, 'CSRF_INVALID', '请求校验失效，请刷新后重试')
    roles = list(db.scalars(select(RoleAssignment).where(RoleAssignment.membership_id == member.id)))
    return Context(user, member, roles, session)


def need(ctx, role):
    if not ctx.has(role):
        fail(403, 'ROLE_REQUIRED', '当前角色不能执行此操作')


def teacher_can_view(db, ctx, membership_id):
    target = db.get(Membership, membership_id)
    if not target or target.org_id != ctx.org_id or not ctx.has('teacher'):
        return False
    assignments = [r for r in ctx.roles if r.role == 'teacher']
    if any(r.class_id is None for r in assignments):
        return True
    class_ids = [r.class_id for r in assignments]
    return db.scalar(select(ClassMember.id).where(ClassMember.membership_id == membership_id, ClassMember.class_id.in_(class_ids))) is not None


def source_allowed(db, ctx, source):
    if source.org_id != ctx.org_id:
        return False
    if source.visibility == 'private':
        return source.owner_id == ctx.user.id
    if source.visibility == 'class':
        if any(r.role in ('teacher', 'admin') and (r.class_id is None or r.class_id == source.class_id) for r in ctx.roles):
            return True
        return db.scalar(select(ClassMember.id).where(ClassMember.membership_id == ctx.membership.id, ClassMember.class_id == source.class_id)) is not None
    return source.visibility == 'organization'


def me(ctx):
    return {'id': ctx.user.id, 'name': ctx.user.name, 'username': ctx.user.username,
            'org_id': ctx.org_id, 'membership_id': ctx.membership.id,
            'roles': sorted({r.role for r in ctx.roles}), 'csrf_token': ctx.session.csrf}
