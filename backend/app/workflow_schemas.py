from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class GenerationSettings(Strict):
    single: int = Field(default=6, ge=0, le=30)
    multiple: int = Field(default=4, ge=0, le=30)
    essay: int = Field(default=2, ge=0, le=30)
    chapters: list[int] = Field(default_factory=list, max_length=1000)
    supplement_ids: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def total(self):
        if not 1 <= self.single + self.multiple + self.essay <= 30:
            raise ValueError('单批题目总数须为1至30题')
        if len(set(self.supplement_ids)) != len(self.supplement_ids):
            raise ValueError('补充资料不能重复')
        return self


class AssignmentInput(Strict):
    title: str = Field(min_length=1, max_length=200)
    class_id: str
    question_ids: list[str] = Field(min_length=1, max_length=50)
    due_at: datetime | None = None

    @model_validator(mode='after')
    def unique_questions(self):
        if len(set(self.question_ids)) != len(self.question_ids):
            raise ValueError('作业题目不能重复')
        return self


class ConfirmEvaluation(Strict):
    parts: list[int] | None = None
    feedback: str | None = Field(default=None, max_length=5000)


class CitationInput(Strict):
    chunk_id: str
    quote: str = Field(min_length=5, max_length=3000)


class TopicInput(Strict):
    name: str = Field(min_length=1, max_length=150)
    section: str = Field(default='', max_length=250)
    card: str = Field(min_length=10, max_length=10000)
    evidence: list[CitationInput] = Field(min_length=1, max_length=5)


class Extraction(Strict):
    topics: list[TopicInput] = Field(min_length=1, max_length=20)
    coverage: str = Field(min_length=1, max_length=2000)


class GeneratedItem(Strict):
    kind: Literal['single', 'multiple', 'essay']
    knowledge_name: str = Field(min_length=1, max_length=150)
    prompt: str = Field(min_length=8, max_length=10000)
    options: dict[str, str] = Field(default_factory=dict)
    answer: list[str] = Field(default_factory=list)
    explanation: str = Field(min_length=10, max_length=10000)
    hints: list[str] = Field(min_length=4, max_length=4)
    rubric: list[dict] = Field(default_factory=list, max_length=20)
    max_score: int = Field(ge=1, le=100)
    option_analysis: dict[str, str] = Field(default_factory=dict)
    evidence: list[CitationInput] = Field(min_length=1, max_length=5)


class QuestionBatch(Strict):
    questions: list[GeneratedItem] = Field(min_length=1, max_length=3)


class Critique(Strict):
    accepted: bool
    conflict: bool
    issues: list[str] = Field(default_factory=list, max_length=30)


class Diagnosis(Strict):
    explanation: str = Field(min_length=10, max_length=10000)
    candidate_cause: str = Field(max_length=200)
    option_analysis: dict[str, str] = Field(default_factory=dict)
    knowledge_gaps: list[str] = Field(max_length=12)
    learning_advice: list[str] = Field(min_length=1, max_length=12)
    clarifying_questions: list[str] = Field(default_factory=list, max_length=5)
    evidence: list[CitationInput] = Field(min_length=1, max_length=5)


class InitialEvaluation(Strict):
    parts: list[int] = Field(min_length=1, max_length=20)
    feedback: str = Field(min_length=5, max_length=5000)
    evidence: list[CitationInput] = Field(min_length=1, max_length=5)


class AgentRunOutput(BaseModel):
    id: str
    purpose: str
    state: str
    stage: str
    source_version_id: str | None
    attempt_id: str | None
    input: dict
    output: dict
    metrics: dict
    error_code: str
    model: str
    workflow_version: str
    created_at: str


from .schemas import TaskOutput, AttemptOutput


class GroupEntry(BaseModel):
    task: TaskOutput
    attempt: AttemptOutput


class GroupOutput(BaseModel):
    id: str
    title: str
    state: str
    due_at: str | None
    entries: list[GroupEntry]
    origin_attempt_id: str | None = None
