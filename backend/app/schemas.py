from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class LoginInput(Input):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)
    org_id: str | None = None


class GoalInput(Input):
    subject_id: str
    exam_year: int = Field(ge=2026, le=2100)
    target_score: int = Field(ge=1, le=100)
    daily_minutes: int = Field(ge=5, le=480)


class DiagnosticInput(Input):
    subject_id: str


class DraftInput(Input):
    answer: list[str] = Field(default_factory=list, max_length=8)
    response_text: str = Field(default='', max_length=20000)
    process: str = Field(default='', max_length=10000)
    duration_seconds: int = Field(default=0, ge=0, le=86400)
    revision: int = Field(ge=1)


class HintInput(Input):
    level: int = Field(ge=1, le=4)


class CauseInput(Input):
    cause: Literal['概念混淆', '原理适用', '材料理解', '论证表达', '审题', '时间管理', '原理适用错误', '材料理解偏差', '选项辨析错误', '论证表达不足', '审题或时间管理']


class EvaluationInput(Input):
    parts: list[int] = Field(max_length=20)
    feedback: str = Field(min_length=1, max_length=5000)
    expected_revision: int = Field(default=0, ge=0)


class ReasonInput(Input):
    reason: str = Field(min_length=1, max_length=5000)


class ResolveInput(EvaluationInput):
    pass


class SourceInput(Input):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=500000)
    knowledge_id: str
    rights: str = Field(min_length=1, max_length=2000)
    visibility: Literal['organization', 'private', 'class'] = 'organization'
    class_id: str | None = None


class SourceEdit(Input):
    text: str = Field(min_length=1, max_length=500000)
    revision: int = Field(ge=1)


class CardInput(Input):
    source_version_id: str
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)


class QuestionInput(Input):
    source_version_id: str
    kind: Literal['single', 'multiple', 'essay']
    prompt: str = Field(min_length=1, max_length=10000)
    options: dict[str, str] = Field(default_factory=dict)
    answer: list[str] = Field(default_factory=list)
    explanation: str = Field(min_length=1, max_length=10000)
    hints: list[str] = Field(min_length=4, max_length=4)
    rubric: list[dict] = Field(default_factory=list, max_length=20)
    max_score: int = Field(ge=1, le=100)

    @model_validator(mode='after')
    def validate_question(self):
        if self.kind == 'essay':
            if self.answer or self.options or not self.rubric:
                raise ValueError('分析题需提供评分要点，不能有选项或客观答案')
            if any(not isinstance(r.get('score'), int) or r['score'] < 1 or not r.get('label') for r in self.rubric):
                raise ValueError('评分要点需包含 label 和正整数 score')
            if sum(r['score'] for r in self.rubric) != self.max_score:
                raise ValueError('评分要点之和必须等于满分')
        else:
            if len(self.options) < 2 or len(self.options) > 8 or not set(self.answer).issubset(self.options):
                raise ValueError('选项或答案无效')
            if len(set(self.answer)) != len(self.answer) or not self.answer:
                raise ValueError('答案不能为空或重复')
            if self.kind == 'single' and len(self.answer) != 1:
                raise ValueError('单选只能有一个正确选项')
            if self.kind == 'multiple' and len(self.answer) < 2:
                raise ValueError('多选需至少两个正确选项')
        return self


class PublishInput(Input):
    note: str = Field(min_length=1, max_length=2000)


class UserInput(Input):
    username: str = Field(min_length=3, max_length=80, pattern=r'^[a-zA-Z0-9_.-]+$')
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=10, max_length=200)
    roles: list[Literal['student', 'teacher', 'admin']] = Field(min_length=1, max_length=3)
    class_id: str


class MeOutput(BaseModel):
    id: str
    name: str
    username: str
    org_id: str
    membership_id: str
    roles: list[str]
    csrf_token: str


class RubricOutput(BaseModel):
    label: str
    score: int


class QuestionOutput(BaseModel):
    id: str
    question_id: str
    number: int
    kind: str
    prompt: str
    options: dict[str, str]
    max_score: int
    knowledge_id: str
    answer: list[str] | None = None
    explanation: str | None = None
    rubric: list[RubricOutput] | None = None
    source_version_id: str | None = None


class EvaluationOutput(BaseModel):
    id: str
    revision: int
    score: int
    parts: list[int]
    feedback: str
    method: str


class EvidenceOutput(BaseModel):
    chunk_id: str
    version_id: str
    source_title: str
    version: int
    position: int
    heading: str
    text: str
    url: str
    page: int | None = None
    score: float = 0
    retrieval: str = 'keyword'


class AttemptOutput(BaseModel):
    id: str
    status: str
    task_id: str
    mode: str
    reason: str
    answer: list[str]
    response_text: str
    process: str
    duration_seconds: int
    hint_level: int
    revision: int
    question: QuestionOutput
    evaluation: EvaluationOutput | None
    content_status: str
    remediation_id: str | None
    submitted_at: str | None
    sources: list[EvidenceOutput] | None = None
    revisions: list[dict] | None = None
    events: list[dict] | None = None


class TaskOutput(BaseModel):
    id: str
    mode: str
    state: str
    reason: str
    minutes: int
    module: str
    knowledge: str
    kind: str
    prompt: str
    attempt_id: str | None


class PlanOutput(BaseModel):
    tasks: list[TaskOutput]
    all_tasks: list[TaskOutput]
    daily_minutes: int
    content_note: str


class NamedOutput(BaseModel):
    id: str
    name: str


class SubjectOutput(NamedOutput):
    code: str


class ModuleOutput(NamedOutput):
    subject_id: str
    position: int


class KnowledgeOutput(NamedOutput):
    module_id: str


class CatalogOutput(BaseModel):
    subjects: list[SubjectOutput]
    modules: list[ModuleOutput]
    knowledge: list[KnowledgeOutput]


class AccountOutput(NamedOutput):
    username: str
    active: bool
    roles: list[str]


class DiagnosticOutput(BaseModel):
    id: str
    status: str
    tasks: list[TaskOutput]


class HintOutput(BaseModel):
    text: str
    level: int
    origin: str
    revision: int
    sources: list[EvidenceOutput]


class RemediationCardOutput(BaseModel):
    id: str
    title: str
    body: str
    source_version_id: str


class RemediationOutput(BaseModel):
    id: str
    attempt_id: str
    cause: str
    cause_status: str
    verification_task_id: str | None
    prompt: str
    resolved: bool
    card: RemediationCardOutput | None
    read: bool


class ReviewScheduleOutput(BaseModel):
    id: str
    stage: int
    due_at: str
    state: str
    task_id: str | None
    policy: str
    knowledge: str
    due: bool


class HistoryOutput(BaseModel):
    id: str
    status: str
    created_at: str
    task: TaskOutput
    evaluation: EvaluationOutput | None


class SourceListItemOutput(BaseModel):
    id: str
    number: int
    status: str
    revision: int
    knowledge_id: str
    review_note: str
    title: str
    rights: str
    visibility: str
    source_id: str


class SourceListOutput(BaseModel):
    items: list[SourceListItemOutput]
    total: int
    page: int
    page_size: int


class SourceChunkOutput(BaseModel):
    id: str
    position: int
    heading: str
    text: str


class CardOutput(BaseModel):
    id: str
    title: str
    body: str
    status: str
    number: int
    causes: list[str] = []


class EditorialQuestionOutput(QuestionInput):
    id: str
    question_id: str
    number: int
    status: str


class AffectedAttemptOutput(BaseModel):
    id: str
    student: str
    status: str


class SourceOutput(BaseModel):
    id: str
    number: int
    status: str
    text: str
    sha256: str
    revision: int
    knowledge_id: str
    review_note: str
    title: str
    rights: str
    visibility: str
    chunks: list[SourceChunkOutput]
    cards: list[CardOutput]
    questions: list[EditorialQuestionOutput] | None = None
    affected_attempts: list[AffectedAttemptOutput] | None = None
    document_info: dict | None = None


class JobOutput(BaseModel):
    id: str
    kind: str
    state: str
    attempts: int
    error_code: str
    result: dict | None = None


class TeacherOverviewOutput(NamedOutput):
    attempts: int
    pending: int
    score: int
    max_score: int


class TeacherAttemptOutput(BaseModel):
    id: str
    status: str
    submitted_at: str
    hint_level: int
    student: str
    kind: str
    prompt: str
    evaluation: EvaluationOutput | None


class ReviewCaseOutput(BaseModel):
    id: str
    reason: str
    status: str
    resolution: str
    created_at: str
    attempt_id: str
    evaluation: EvaluationOutput
    prompt: str
