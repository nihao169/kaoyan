"""V2 records. Evidence is immutable; projections and schedules are derived."""
from sqlalchemy import String, Text, Integer, JSON, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from ..db import Base
from ..models import Entity


class PersonalSpace(Entity, Base):
    __tablename__ = 'v2_personal_spaces'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), unique=True)


class Project(Entity, Base):
    __tablename__ = 'v2_projects'
    space_id: Mapped[str] = mapped_column(ForeignKey('v2_personal_spaces.id'), index=True)
    title: Mapped[str] = mapped_column(String(200))
    scenario: Mapped[str] = mapped_column(String(30), default='kaoyan')
    subject_id: Mapped[str] = mapped_column(ForeignKey('subjects.id'))
    exam_year: Mapped[int] = mapped_column(Integer)
    daily_minutes: Mapped[int] = mapped_column(Integer, default=45)
    target_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deadline: Mapped[str | None] = mapped_column(String(10), nullable=True)
    state: Mapped[str] = mapped_column(String(20), default='active')
    revision: Mapped[int] = mapped_column(Integer, default=1)
    scope_revision: Mapped[int] = mapped_column(Integer, default=1)
    policy: Mapped[str] = mapped_column(String(60), default='kaoyan-politics-v1')


class Material(Entity, Base):
    __tablename__ = 'v2_materials'
    project_id: Mapped[str] = mapped_column(ForeignKey('v2_projects.id'), index=True)
    title: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    source_version_id: Mapped[str | None] = mapped_column(ForeignKey('source_versions.id'), nullable=True)
    state: Mapped[str] = mapped_column(String(20), default='ready')


class Plan(Entity, Base):
    __tablename__ = 'v2_plans'
    __table_args__ = (UniqueConstraint('project_id', 'number'),)
    project_id: Mapped[str] = mapped_column(ForeignKey('v2_projects.id'), index=True)
    number: Mapped[int] = mapped_column(Integer)
    daily_minutes: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    scope: Mapped[dict] = mapped_column(JSON, default=dict)


class Task(Entity, Base):
    __tablename__ = 'v2_tasks'
    __table_args__ = (UniqueConstraint('project_id', 'task_key'),)
    project_id: Mapped[str] = mapped_column(ForeignKey('v2_projects.id'), index=True)
    material_id: Mapped[str | None] = mapped_column(ForeignKey('v2_materials.id'), nullable=True)
    kind: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    task_key: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default='todo')
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=10)
    due_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class StudySession(Entity, Base):
    __tablename__ = 'v2_study_sessions'
    task_id: Mapped[str] = mapped_column(ForeignKey('v2_tasks.id'), unique=True)
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class Question(Entity, Base):
    __tablename__ = 'v2_questions'
    project_id: Mapped[str] = mapped_column(ForeignKey('v2_projects.id'), index=True)
    material_id: Mapped[str] = mapped_column(ForeignKey('v2_materials.id'))
    knowledge: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    prompt: Mapped[str] = mapped_column(Text)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    answer: Mapped[list] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text)
    rubric: Mapped[list] = mapped_column(JSON, default=list)
    quote: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(30), default='ai_generated')


class Attempt(Entity, Base):
    __tablename__ = 'v2_attempts'
    task_id: Mapped[str] = mapped_column(ForeignKey('v2_tasks.id'), unique=True)
    answer: Mapped[list] = mapped_column(JSON, default=list)
    response_text: Mapped[str] = mapped_column(Text, default='')
    confidence: Mapped[str] = mapped_column(String(20), default='normal')
    hint_used: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict] = mapped_column(JSON, default=dict)


class Evidence(Entity, Base):
    __tablename__ = 'v2_evidence'
    __table_args__ = (UniqueConstraint('task_id', 'kind'),)
    project_id: Mapped[str] = mapped_column(ForeignKey('v2_projects.id'), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey('v2_tasks.id'))
    knowledge: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class Note(Entity, Base):
    __tablename__ = 'v2_notes'
    project_id: Mapped[str] = mapped_column(ForeignKey('v2_projects.id'), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), default='note')
    material_id: Mapped[str | None] = mapped_column(ForeignKey('v2_materials.id'), nullable=True)


class AIRun(Entity, Base):
    __tablename__ = 'v2_ai_runs'
    __table_args__ = (Index('ix_v2_ai_run_queue', 'state', 'created_at'), Index('ix_v2_ai_run_lease', 'state', 'lease_until'))
    project_id: Mapped[str] = mapped_column(ForeignKey('v2_projects.id'), index=True)
    membership_id: Mapped[str | None] = mapped_column(ForeignKey('memberships.id'), nullable=True)
    lease_until: Mapped[str | None] = mapped_column(String(40), nullable=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey('v2_tasks.id'), nullable=True)
    scope_revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))
    prompt: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(25), default='queued')
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default='')
    external_id: Mapped[str | None] = mapped_column(String(150), nullable=True)


class AIEvent(Entity, Base):
    __tablename__ = 'v2_ai_events'
    __table_args__ = (UniqueConstraint('run_id', 'seq'),)
    run_id: Mapped[str] = mapped_column(ForeignKey('v2_ai_runs.id'), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class Assessment(Entity, Base):
    __tablename__ = 'v2_assessments'
    __table_args__ = (Index('ix_v2_assessment_deadline', 'state', 'deadline_at'),)
    project_id: Mapped[str] = mapped_column(ForeignKey('v2_projects.id'), index=True)
    title: Mapped[str] = mapped_column(String(200))
    mode: Mapped[str] = mapped_column(String(20), default='mock')
    state: Mapped[str] = mapped_column(String(20), default='active')
    task_ids: Mapped[list] = mapped_column(JSON, default=list)
    drafts: Mapped[dict] = mapped_column(JSON, default=dict)
    deadline_at: Mapped[str] = mapped_column(String(40))
    revision: Mapped[int] = mapped_column(Integer, default=1)


class ExamResource(Entity, Base):
    """An immutable, privately imported syllabus or paper edition."""
    __tablename__ = 'v2_exam_resources'
    __table_args__ = (UniqueConstraint('project_id', 'kind', 'year', 'edition', name='uq_v2_exam_resource_edition'),)
    project_id: Mapped[str] = mapped_column(ForeignKey('v2_projects.id'), index=True)
    material_id: Mapped[str] = mapped_column(ForeignKey('v2_materials.id'))
    kind: Mapped[str] = mapped_column(String(20))
    year: Mapped[int] = mapped_column(Integer)
    edition: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    source: Mapped[dict] = mapped_column(JSON)
    contents: Mapped[dict] = mapped_column(JSON)
