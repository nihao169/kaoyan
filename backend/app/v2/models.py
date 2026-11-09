"""V2 records. Evidence is immutable; projections and schedules are derived."""
from sqlalchemy import Boolean, String, Text, Integer, JSON, ForeignKey, UniqueConstraint, Index, false
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
    native_records: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    course_name: Mapped[str] = mapped_column(String(200), default='', server_default='')
    learning_goal: Mapped[str] = mapped_column(Text, default='', server_default='')
    scene_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class ProjectLearning(Entity, Base):
    __tablename__ = 'v2_project_learning'
    __table_args__ = (UniqueConstraint('project_id', 'scope_revision', 'plan_revision'),)
    project_id: Mapped[str] = mapped_column(ForeignKey('v2_projects.id'), index=True)
    scope_revision: Mapped[int] = mapped_column(Integer)
    plan_revision: Mapped[int] = mapped_column(Integer)
    path_id: Mapped[str] = mapped_column(String(150))
    session_id: Mapped[str] = mapped_column(String(150))
    context: Mapped[dict] = mapped_column(JSON, default=dict)


class Material(Entity, Base):
    __tablename__ = 'v2_materials'
    project_id: Mapped[str] = mapped_column(ForeignKey('v2_projects.id'), index=True)
    title: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    original_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_version_id: Mapped[str | None] = mapped_column(ForeignKey('source_versions.id'), nullable=True)
    state: Mapped[str] = mapped_column(String(20), default='ready')


class TutorIndex(Entity, Base):
    __tablename__ = 'v2_tutor_indexes'
    __table_args__ = (UniqueConstraint('material_id', 'sha256'), Index('ix_v2_tutor_index_queue', 'state', 'next_at'))
    material_id: Mapped[str] = mapped_column(ForeignKey('v2_materials.id'))
    membership_id: Mapped[str] = mapped_column(ForeignKey('memberships.id'))
    sha256: Mapped[str] = mapped_column(String(64))
    principal: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(60))
    state: Mapped[str] = mapped_column(String(20), default='queued')
    next_at: Mapped[str] = mapped_column(String(40))
    error: Mapped[str] = mapped_column(Text, default='')


class TutorTeachingIndex(Entity, Base):
    __tablename__ = 'v2_tutor_teaching_indexes'
    __table_args__ = (UniqueConstraint('membership_id', 'version_id', 'sha256'),
                      Index('ix_tutor_teaching_index_queue', 'state', 'next_at'))
    membership_id: Mapped[str] = mapped_column(ForeignKey('memberships.id'))
    version_id: Mapped[str] = mapped_column(ForeignKey('source_versions.id'))
    sha256: Mapped[str] = mapped_column(String(64))
    principal: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(60))
    state: Mapped[str] = mapped_column(String(20), default='indexing')
    next_at: Mapped[str] = mapped_column(String(40))


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


class MasteryReviewScope(Entity, Base):
    __tablename__ = 'v2_mastery_review_scopes'
    __table_args__ = (UniqueConstraint('owner_id', 'kind', 'resource_id'),)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    membership_id: Mapped[str] = mapped_column(ForeignKey('memberships.id'))
    kind: Mapped[str] = mapped_column(String(8))
    resource_id: Mapped[str] = mapped_column(String(36))
    path_id: Mapped[str | None] = mapped_column(String(80), nullable=True)


class MasteryReviewEvent(Entity, Base):
    __tablename__ = 'v2_mastery_review_events'
    __table_args__ = (UniqueConstraint('scope_id', 'attempt_id'),
                      Index('ix_mastery_review_pending', 'state', 'next_at'))
    scope_id: Mapped[str] = mapped_column(ForeignKey('v2_mastery_review_scopes.id'))
    attempt_id: Mapped[str] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(20))
    next_at: Mapped[str] = mapped_column(String(40))


class AIRun(Entity, Base):
    __tablename__ = 'v2_ai_runs'
    __table_args__ = (Index('ix_v2_ai_run_queue', 'state', 'created_at'), Index('ix_v2_ai_run_lease', 'state', 'lease_until'))
    project_id: Mapped[str] = mapped_column(ForeignKey('v2_projects.id'), index=True)
    membership_id: Mapped[str | None] = mapped_column(ForeignKey('memberships.id'), nullable=True)
    lease_until: Mapped[str | None] = mapped_column(String(40), nullable=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey('v2_tasks.id'), nullable=True)
    scope_revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    prompt: Mapped[str] = mapped_column(Text)
    backend: Mapped[str] = mapped_column(String(30), default='bounded_chat', server_default='bounded_chat')
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
