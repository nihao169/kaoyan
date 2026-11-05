"""Annual study scope and private past-paper imports with explicit provenance."""
from typing import Literal
from fastapi import APIRouter, Depends, Request
from pydantic import Field, HttpUrl, model_validator
from sqlalchemy import select
from ..api_common import EnvelopeRoute, entity, idempotent
from ..auth import context
from ..models import AuditEvent
from ..db import get_db
from ..errors import fail
from . import models as m, service as s
from .routes import Input

router = APIRouter(route_class=EnvelopeRoute)
REFERENCE = [
    {'year': 2027, 'kind': 'syllabus', 'title': '2027 年思想政治理论考试大纲',
     'publisher': '高等教育出版社', 'isbn': '978-7-04-068500-8',
     'url': 'https://www.hep.com.cn/book/show/2104375928531001345'},
    {'year': 2024, 'kind': 'exam_analysis', 'title': '2024 年考试分析（含 2022、2023 年试题分析）',
     'publisher': '高等教育出版社', 'url': 'https://xuanshu.hep.com.cn/front/book/findBookDetails?bookId=64fdf9fa74ce561611bd9669'},
]


class Topic(Input):
    code: str = Field(min_length=1, max_length=60, pattern=r'^[a-zA-Z0-9._-]+$')
    chapter: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=160)
    text: str = Field(min_length=1, max_length=6000)


class PaperQuestion(Input):
    number: int = Field(ge=1, le=50)
    kind: Literal['single', 'multiple', 'essay']
    prompt: str = Field(min_length=1, max_length=8000)
    knowledge: str = Field(min_length=1, max_length=160)
    options: dict[str, str] = Field(default_factory=dict, max_length=10)
    answer: list[str] = Field(default_factory=list, max_length=10)
    rubric: list[str] = Field(default_factory=list, max_length=20)
    explanation: str = Field(min_length=8, max_length=5000)
    points: int = Field(ge=1, le=100)

    @model_validator(mode='after')
    def validate_structure(self):
        if self.kind == 'essay':
            if self.options or self.answer or not self.rubric or any(not 1 <= len(x) <= 500 for x in self.rubric):
                raise ValueError('分析题须有评分要点，不能包含选项或客观题答案')
        elif (len(self.options) < 2 or self.rubric or
              any(not k.isascii() or not k.isalpha() or len(k) != 1 or not 1 <= len(v) <= 1000 for k, v in self.options.items()) or
              len(set(self.answer)) != len(self.answer) or not set(self.answer) <= self.options.keys() or
              (len(self.answer) != 1 if self.kind == 'single' else len(self.answer) < 2)):
            raise ValueError('客观题的选项或答案不符合题型')
        return self


class ResourceInput(Input):
    kind: Literal['syllabus', 'past_paper', 'simulated_paper']
    year: int = Field(ge=1980, le=2100)
    edition: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=150)
    source_title: str = Field(min_length=1, max_length=200)
    source_url: HttpUrl | None = None
    rights_confirmed: Literal[True]
    topics: list[Topic] = Field(default_factory=list, max_length=500)
    questions: list[PaperQuestion] = Field(default_factory=list, max_length=50)
    minutes: int = Field(default=180, ge=5, le=180)


def load_resource(db, ctx, p, resource_id, kind):
    resource = db.get(m.ExamResource, resource_id)
    if not resource or resource.project_id != p.id or resource.kind not in ((kind,) if isinstance(kind, str) else kind):
        fail(404, 'NOT_FOUND', '本项目没有该版本的年度资料')
    s.material_access(db, ctx, db.get(m.Material, resource.material_id))
    return resource


def view(row, include_topics=False):
    result = entity(row, 'id', 'kind', 'year', 'edition', 'title', 'source', 'material_id')
    if row.kind == 'syllabus':
        result['topic_count'] = len(row.contents['topics'])
        if include_topics:
            result['topics'] = row.contents['topics']
    else:
        result.update(minutes=row.contents['minutes'], question_count=len(row.contents['question_ids']),
                      total_points=sum(row.contents['points'].values()))
    return result


@router.get('/learning-projects/{project_id}/exam-resources')
def resources(project_id: str, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, active=False)
    s.no_active_mock(db, p.id)
    rows = db.scalars(select(m.ExamResource).join(m.Material).where(
        m.ExamResource.project_id == p.id, m.Material.state == 'ready'
    ).order_by(m.ExamResource.year.desc(), m.ExamResource.created_at.desc()))
    return {'exam_year': p.exam_year, 'references': REFERENCE, 'resources': [view(row, True) for row in rows]}


@router.post('/learning-projects/{project_id}/exam-resources', status_code=201)
def import_resource(project_id: str, data: ResourceInput, request: Request, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, lock=True)
    s.no_active_mock(db, p.id)
    if data.kind == 'syllabus':
        if data.year != p.exam_year or data.questions or not data.topics or len({t.code for t in data.topics}) != len(data.topics):
            fail(422, 'INVALID_SYLLABUS', '考纲须与项目同年，并包含代码不重复的知识点')
        text = '\n\n'.join(f'{t.code} · {t.chapter} · {t.title}\n{t.text}' for t in data.topics)
    else:
        if (data.year > p.exam_year or data.topics or not data.questions or
                [q.number for q in data.questions] != list(range(1, len(data.questions)+1))):
            fail(422, 'INVALID_PAPER', '真题年份不能超过项目年份，题号须从 1 顺序排列')
        text = '\n\n'.join(f'第{q.number}题 {q.knowledge}\n{q.prompt}\n{q.explanation}' for q in data.questions)
    if len(text) > 300000:
        fail(422, 'RESOURCE_TOO_LARGE', '导入正文超过 30 万字')

    def save():
        if db.scalar(select(m.ExamResource.id).where(m.ExamResource.project_id == p.id,
                m.ExamResource.year == data.year, m.ExamResource.kind == data.kind, m.ExamResource.edition == data.edition)):
            fail(409, 'EDITION_EXISTS', '该年度版本已存在，请使用新的版本号')
        material = s.add_material(db, p, f'{data.year} · {data.title} · {data.edition}'[:200], text,
                                  reading=data.kind == 'syllabus')
        contents = {}
        if data.kind == 'syllabus':
            # Store the complete content once in the immutable source material.
            contents['topics'] = []
            offset = 0
            for t in data.topics:
                size = len(f'{t.code} · {t.chapter} · {t.title}\n{t.text}')
                contents['topics'].append({**t.model_dump(exclude={'text'}), 'start': offset, 'end': offset+size})
                offset += size+2
        else:
            ids, points = [], {}
            for question in data.questions:
                q = m.Question(project_id=p.id, material_id=material.id,
                    knowledge=f'{data.year}/{data.edition} {question.knowledge}'[:200],
                    kind=question.kind, prompt=question.prompt, options=question.options,
                    answer=question.answer, rubric=question.rubric, explanation=question.explanation,
                    quote=question.explanation[:600], origin=data.kind)
                db.add(q)
                db.flush()
                ids.append(q.id)
                points[q.id] = question.points
            contents = {'question_ids': ids, 'points': points, 'minutes': data.minutes}
        row = m.ExamResource(project_id=p.id, material_id=material.id, kind=data.kind, year=data.year,
            edition=data.edition, title=data.title, contents=contents,
            source={'title': data.source_title, 'url': str(data.source_url) if data.source_url else None,
                    'visibility': 'private', 'verification': 'user_supplied', 'importer_id': ctx.user.id})
        db.add(row)
        db.flush()
        db.add(AuditEvent(org_id=ctx.org_id, actor_id=ctx.user.id, action='exam_resource.imported',
                          resource_id=row.id, detail={'kind':row.kind, 'year':row.year, 'edition':row.edition}))
        if data.kind == 'syllabus':
            p.revision += 1
            s.snapshot_plan(db, p, '纳入新的年度考纲版本，原版本与证据保留')
        return view(row, True)
    return idempotent(db, ctx, request, f'v2.exam-resource:{p.id}:{data.kind}', data.model_dump(mode='json'), save)


@router.post('/learning-projects/{project_id}/exam-resources/{resource_id}/topics/{code}/study')
def study_topic(project_id: str, resource_id: str, code: str, ctx=Depends(context), db=Depends(get_db)):
    p = s.project(db, ctx, project_id, lock=True)
    s.no_active_mock(db, p.id)
    row = load_resource(db, ctx, p, resource_id, 'syllabus')
    topic = next((t for t in row.contents['topics'] if t['code'] == code), None)
    if not topic:
        fail(404, 'NOT_FOUND', '该考纲版本中没有此知识点')
    # Edition-specific label prevents implicitly merging independent knowledge evidence.
    knowledge = s.topic_key(row, topic)
    t = s.add_task(db, p, 'reading', f'考纲学习：{topic["title"]}', f'syllabus:{row.id}:{code}',
                   f'{row.year} 年 · {topic["chapter"]} · {row.edition}', row.material_id,
                   {'knowledge': knowledge, 'focus': topic['title'], 'source_span': [topic['start'], topic['end']]}, minutes=15)
    return {'task_id': t.id}


@router.post('/learning-projects/{project_id}/exam-resources/sample', status_code=201)
def add_sample(project_id: str, request: Request, ctx=Depends(context), db=Depends(get_db)):
    from .simulated_content import paper, syllabus
    p = s.project(db, ctx, project_id, lock=True)
    s.no_active_mock(db, p.id)
    existing = db.scalars(select(m.ExamResource).where(m.ExamResource.project_id == p.id,
        m.ExamResource.edition == 'simulation-v1'))
    by_kind = {(row.kind, row.year): row for row in existing}
    return [view(by_kind[(data['kind'], data['year'])], True) if (data['kind'], data['year']) in by_kind
            else import_resource(p.id, ResourceInput.model_validate(data), request, ctx, db)
            for data in (syllabus(p.exam_year), paper(p.exam_year-1))]
