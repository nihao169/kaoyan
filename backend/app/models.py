from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import String, Integer, Text, JSON, ForeignKey, UniqueConstraint, Index, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


class Entity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class Organization(Entity, Base):
    __tablename__ = 'organizations'
    name: Mapped[str] = mapped_column(String(150))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class User(Entity, Base):
    __tablename__ = 'users'
    username: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Membership(Entity, Base):
    __tablename__ = 'memberships'
    __table_args__ = (UniqueConstraint('user_id', 'org_id'),)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id'))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class TeachingClass(Entity, Base):
    __tablename__ = 'classes'
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id'), index=True)
    name: Mapped[str] = mapped_column(String(100))


class RoleAssignment(Entity, Base):
    __tablename__ = 'role_assignments'
    membership_id: Mapped[str] = mapped_column(ForeignKey('memberships.id'), index=True)
    role: Mapped[str] = mapped_column(String(30))
    class_id: Mapped[str | None] = mapped_column(ForeignKey('classes.id'), nullable=True)


class ClassMember(Entity, Base):
    __tablename__ = 'class_members'
    __table_args__ = (UniqueConstraint('class_id', 'membership_id'),)
    class_id: Mapped[str] = mapped_column(ForeignKey('classes.id'))
    membership_id: Mapped[str] = mapped_column(ForeignKey('memberships.id'))


class LoginSession(Entity, Base):
    __tablename__ = 'sessions'
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf: Mapped[str] = mapped_column(String(100))
    membership_id: Mapped[str] = mapped_column(ForeignKey('memberships.id'))
    expires_at: Mapped[str] = mapped_column(String(40))


class Subject(Entity, Base):
    __tablename__ = 'subjects'
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))


class Module(Entity, Base):
    __tablename__ = 'modules'
    subject_id: Mapped[str] = mapped_column(ForeignKey('subjects.id'))
    name: Mapped[str] = mapped_column(String(100))
    position: Mapped[int] = mapped_column(Integer)


class KnowledgePoint(Entity, Base):
    __tablename__ = 'knowledge_points'
    module_id: Mapped[str] = mapped_column(ForeignKey('modules.id'))
    name: Mapped[str] = mapped_column(String(150))


class Prerequisite(Entity, Base):
    __tablename__ = 'prerequisites'
    __table_args__ = (UniqueConstraint('knowledge_id', 'requires_id'),)
    knowledge_id: Mapped[str] = mapped_column(ForeignKey('knowledge_points.id'))
    requires_id: Mapped[str] = mapped_column(ForeignKey('knowledge_points.id'))


class Curriculum(Entity, Base):
    __tablename__ = 'curricula'
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id'))
    subject_id: Mapped[str] = mapped_column(ForeignKey('subjects.id'))
    title: Mapped[str] = mapped_column(String(150))


class CurriculumVersion(Entity, Base):
    __tablename__ = 'curriculum_versions'
    curriculum_id: Mapped[str] = mapped_column(ForeignKey('curricula.id'))
    number: Mapped[int] = mapped_column(Integer, default=1)
    applicable_year: Mapped[int] = mapped_column(Integer)
    knowledge_ids: Mapped[list] = mapped_column(JSON, default=list)
    __table_args__ = (UniqueConstraint('curriculum_id', 'number'),)


class Source(Entity, Base):
    __tablename__ = 'sources'
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id'), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    title: Mapped[str] = mapped_column(String(200))
    visibility: Mapped[str] = mapped_column(String(20), default='organization')
    class_id: Mapped[str | None] = mapped_column(ForeignKey('classes.id'), nullable=True)
    rights: Mapped[str] = mapped_column(Text, default='原创演示内容，仅用于平台功能演示')


class SourceVersion(Entity, Base):
    __tablename__ = 'source_versions'
    __table_args__ = (UniqueConstraint('source_id', 'number'),)
    source_id: Mapped[str] = mapped_column(ForeignKey('sources.id'), index=True)
    number: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(25), default='draft', index=True)
    text: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    file_key: Mapped[str | None] = mapped_column(String(150), nullable=True)
    knowledge_id: Mapped[str] = mapped_column(ForeignKey('knowledge_points.id'))
    review_note: Mapped[str] = mapped_column(Text, default='')
    revision: Mapped[int] = mapped_column(Integer, default=1)


class SourceChunk(Entity, Base):
    __tablename__ = 'source_chunks'
    version_id: Mapped[str] = mapped_column(ForeignKey('source_versions.id'), index=True)
    position: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(String(250))
    text: Mapped[str] = mapped_column(Text)


class CardVersion(Entity, Base):
    __tablename__ = 'card_versions'
    card_id: Mapped[str] = mapped_column(String(36), default=uid, index=True)
    number: Mapped[int] = mapped_column(Integer, default=1)
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id'), index=True)
    source_version_id: Mapped[str] = mapped_column(ForeignKey('source_versions.id'))
    knowledge_id: Mapped[str] = mapped_column(ForeignKey('knowledge_points.id'))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(25), default='draft')
    __table_args__ = (UniqueConstraint('card_id', 'number'),)


class ScoringPolicyVersion(Entity, Base):
    __tablename__ = 'scoring_policy_versions'
    strategy: Mapped[str] = mapped_column(String(50))
    version: Mapped[int] = mapped_column(Integer, default=1)
    config: Mapped[dict] = mapped_column(JSON, default=dict)


class QuestionVersion(Entity, Base):
    __tablename__ = 'question_versions'
    __table_args__ = (UniqueConstraint('question_id', 'number'),)
    question_id: Mapped[str] = mapped_column(String(36), default=uid, index=True)
    number: Mapped[int] = mapped_column(Integer, default=1)
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id'), index=True)
    source_version_id: Mapped[str] = mapped_column(ForeignKey('source_versions.id'))
    knowledge_id: Mapped[str] = mapped_column(ForeignKey('knowledge_points.id'))
    policy_id: Mapped[str] = mapped_column(ForeignKey('scoring_policy_versions.id'))
    kind: Mapped[str] = mapped_column(String(20))
    prompt: Mapped[str] = mapped_column(Text)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    answer: Mapped[list] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text)
    rubric: Mapped[list] = mapped_column(JSON, default=list)
    hints: Mapped[list] = mapped_column(JSON, default=list)
    max_score: Mapped[int] = mapped_column(Integer, default=2)
    status: Mapped[str] = mapped_column(String(25), default='draft', index=True)


class ContentReview(Entity, Base):
    __tablename__ = 'content_reviews'
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id'))
    version_id: Mapped[str] = mapped_column(ForeignKey('source_versions.id'))
    reviewer_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(30))
    note: Mapped[str] = mapped_column(Text)


class Goal(Entity, Base):
    __tablename__ = 'goals'
    __table_args__ = (UniqueConstraint('membership_id', 'subject_id'),)
    membership_id: Mapped[str] = mapped_column(ForeignKey('memberships.id'))
    subject_id: Mapped[str] = mapped_column(ForeignKey('subjects.id'))
    exam_year: Mapped[int] = mapped_column(Integer)
    target_score: Mapped[int] = mapped_column(Integer)
    daily_minutes: Mapped[int] = mapped_column(Integer)


class DiagnosticSession(Entity, Base):
    __tablename__ = 'diagnostics'
    membership_id: Mapped[str] = mapped_column(ForeignKey('memberships.id'), index=True)
    subject_id: Mapped[str] = mapped_column(ForeignKey('subjects.id'))
    status: Mapped[str] = mapped_column(String(20), default='active')


class LearningTask(Entity, Base):
    __tablename__ = 'learning_tasks'
    __table_args__ = (UniqueConstraint('membership_id', 'task_key'),)
    membership_id: Mapped[str] = mapped_column(ForeignKey('memberships.id'), index=True)
    question_version_id: Mapped[str] = mapped_column(ForeignKey('question_versions.id'))
    diagnostic_id: Mapped[str | None] = mapped_column(ForeignKey('diagnostics.id'), nullable=True)
    task_key: Mapped[str] = mapped_column(String(150))
    mode: Mapped[str] = mapped_column(String(25), default='practice')
    reason: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(25), default='todo')
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=5)


class Attempt(Entity, Base):
    __tablename__ = 'attempts'
    __table_args__ = (UniqueConstraint('membership_id', 'task_id'),)
    membership_id: Mapped[str] = mapped_column(ForeignKey('memberships.id'), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey('learning_tasks.id'))
    question_version_id: Mapped[str] = mapped_column(ForeignKey('question_versions.id'))
    status: Mapped[str] = mapped_column(String(25), default='draft')
    answer: Mapped[list] = mapped_column(JSON, default=list)
    response_text: Mapped[str] = mapped_column(Text, default='')
    process: Mapped[str] = mapped_column(Text, default='')
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    hint_level: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    submitted_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Evaluation(Entity, Base):
    __tablename__ = 'evaluations'
    attempt_id: Mapped[str] = mapped_column(ForeignKey('attempts.id'), unique=True)
    current_revision: Mapped[int] = mapped_column(Integer, default=1)


class EvaluationRevision(Entity, Base):
    __tablename__ = 'evaluation_revisions'
    __table_args__ = (UniqueConstraint('evaluation_id', 'number'),)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey('evaluations.id'))
    number: Mapped[int] = mapped_column(Integer)
    score: Mapped[int] = mapped_column(Integer)
    parts: Mapped[list] = mapped_column(JSON, default=list)
    feedback: Mapped[str] = mapped_column(Text)
    evaluator_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    method: Mapped[str] = mapped_column(String(20))


class ReviewCase(Entity, Base):
    __tablename__ = 'review_cases'
    evaluation_id: Mapped[str] = mapped_column(ForeignKey('evaluations.id'), index=True)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default='open')
    resolution: Mapped[str] = mapped_column(Text, default='')


class LearningEvent(Entity, Base):
    __tablename__ = 'learning_events'
    __table_args__ = (UniqueConstraint('attempt_id', 'kind', 'event_key'),)
    attempt_id: Mapped[str] = mapped_column(ForeignKey('attempts.id'), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    event_key: Mapped[str] = mapped_column(String(100), default='once')
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class Remediation(Entity, Base):
    __tablename__ = 'remediations'
    attempt_id: Mapped[str] = mapped_column(ForeignKey('attempts.id'), unique=True)
    card_version_id: Mapped[str | None] = mapped_column(ForeignKey('card_versions.id'), nullable=True)
    cause: Mapped[str] = mapped_column(String(150), default='待确认')
    cause_status: Mapped[str] = mapped_column(String(20), default='candidate')
    verification_task_id: Mapped[str | None] = mapped_column(ForeignKey('learning_tasks.id'), nullable=True)


class ReviewSchedule(Entity, Base):
    __tablename__ = 'review_schedules'
    __table_args__ = (UniqueConstraint('attempt_id', 'stage'), Index('ix_reviews_due', 'membership_id', 'due_at'))
    membership_id: Mapped[str] = mapped_column(ForeignKey('memberships.id'))
    attempt_id: Mapped[str] = mapped_column(ForeignKey('attempts.id'))
    knowledge_id: Mapped[str] = mapped_column(ForeignKey('knowledge_points.id'))
    stage: Mapped[int] = mapped_column(Integer, default=1)
    policy: Mapped[str] = mapped_column(String(50), default='spaced-1-3-7-v1')
    anchor_at: Mapped[str] = mapped_column(String(40))
    due_at: Mapped[str] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(25), default='scheduled')
    task_id: Mapped[str | None] = mapped_column(ForeignKey('learning_tasks.id'), nullable=True)


class WorkflowRun(Entity, Base):
    __tablename__ = 'workflow_runs'
    attempt_id: Mapped[str] = mapped_column(ForeignKey('attempts.id'))
    status: Mapped[str] = mapped_column(String(30), default='queued')
    template_version: Mapped[str] = mapped_column(String(50), default='tutor-v1')
    model: Mapped[str] = mapped_column(String(150), default='')
    result: Mapped[dict] = mapped_column(JSON, default=dict)


class Citation(Entity, Base):
    __tablename__ = 'citations'
    run_id: Mapped[str] = mapped_column(ForeignKey('workflow_runs.id'), index=True)
    chunk_id: Mapped[str] = mapped_column(ForeignKey('source_chunks.id'))
    quote: Mapped[str] = mapped_column(Text)


class Job(Entity, Base):
    __tablename__ = 'jobs'
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id'))
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    kind: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(25), default='queued', index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_code: Mapped[str] = mapped_column(String(60), default='')


class OutboxEvent(Entity, Base):
    __tablename__ = 'outbox_events'
    event_key: Mapped[str] = mapped_column(String(150), unique=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey('attempts.id'))
    state: Mapped[str] = mapped_column(String(20), default='queued')


class IdempotencyRecord(Entity, Base):
    __tablename__ = 'idempotency_records'
    __table_args__ = (UniqueConstraint('membership_id', 'operation', 'key'),)
    membership_id: Mapped[str] = mapped_column(ForeignKey('memberships.id'))
    operation: Mapped[str] = mapped_column(String(150))
    key: Mapped[str] = mapped_column(String(150))
    digest: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)


class AuditEvent(Entity, Base):
    __tablename__ = 'audit_events'
    org_id: Mapped[str | None] = mapped_column(ForeignKey('organizations.id'), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str] = mapped_column(String(100), default='')
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class SourceDocument(Entity, Base):
    __tablename__ = 'source_documents'
    version_id: Mapped[str] = mapped_column(ForeignKey('source_versions.id'), unique=True)
    filename: Mapped[str] = mapped_column(String(200))
    original_key: Mapped[str] = mapped_column(String(150))
    preview_key: Mapped[str | None] = mapped_column(String(150), nullable=True)
    state: Mapped[str] = mapped_column(String(30), default='queued')
    error_code: Mapped[str] = mapped_column(String(80), default='')
    pages: Mapped[list] = mapped_column(JSON, default=list)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class ChunkEmbedding(Entity, Base):
    __tablename__ = 'chunk_embeddings'
    __table_args__ = (UniqueConstraint('chunk_id', 'model_revision'),)
    chunk_id: Mapped[str] = mapped_column(ForeignKey('source_chunks.id', ondelete='CASCADE'))
    model_revision: Mapped[str] = mapped_column(String(200))
    vectors: Mapped[list] = mapped_column(JSON)


class CardRule(Entity, Base):
    __tablename__ = 'card_rules'
    card_id: Mapped[str] = mapped_column(ForeignKey('card_versions.id'), unique=True)
    causes: Mapped[list] = mapped_column(JSON, default=list)


class AIRequest(Entity, Base):
    __tablename__ = 'ai_requests'
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id'))
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    membership_id: Mapped[str] = mapped_column(ForeignKey('memberships.id'))
    attempt_id: Mapped[str | None] = mapped_column(ForeignKey('attempts.id'), nullable=True)
    knowledge_id: Mapped[str | None] = mapped_column(ForeignKey('knowledge_points.id'), nullable=True)
    purpose: Mapped[str] = mapped_column(String(30))
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(30), default='queued')
    model: Mapped[str] = mapped_column(String(150))
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str] = mapped_column(String(80), default='')
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)


class TeachingReferral(Entity, Base):
    __tablename__ = 'teaching_referrals'
    attempt_id: Mapped[str] = mapped_column(ForeignKey('attempts.id'))
    request_id: Mapped[str | None] = mapped_column(ForeignKey('ai_requests.id'), nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(30), default='open')
    response: Mapped[str] = mapped_column(Text, default='')
    teacher_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'), nullable=True)


class LessonDraft(Entity, Base):
    __tablename__ = 'lesson_drafts'
    request_id: Mapped[str] = mapped_column(ForeignKey('ai_requests.id'), unique=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    body: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1)
