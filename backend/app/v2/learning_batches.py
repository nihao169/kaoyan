"""Bounded learning stages backed by the project's durable command queue."""
import asyncio
import json
import re
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ..errors import fail
from . import models as m, service as s, search, tutor


STAGES = {'final_diagnose': 3, 'final_retest': 3, 'kaoyan_start': 1, 'kaoyan_next': 1}
CHAPTER = {'chapter_continue', 'chapter_pause', 'chapter_practice', 'chapter_summary'}


class InvalidPlan(tutor.TutorError):
    """The model finished, but its plan must be generated again."""


def day():
    return s.clock().astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()


def modules(native):
    return ((native.get('curriculum') or {}).get('map') or {}).get('modules') or []


def objectives(native):
    return {point['id']: point for module in modules(native) for point in module.get('knowledge_points', [])}


def today(db, p):
    return db.scalar(select(m.LearningBatch).where(
        m.LearningBatch.project_id == p.id, m.LearningBatch.scope_revision == p.scope_revision,
        m.LearningBatch.key == day()))


def previous_day(db, p):
    return db.scalar(select(m.LearningBatch).where(
        m.LearningBatch.project_id == p.id, m.LearningBatch.scope_revision == p.scope_revision,
        m.LearningBatch.action == 'chapter_continue', m.LearningBatch.key < day())
        .order_by(m.LearningBatch.key.desc()).limit(1))


def stage(db, p):
    return db.scalar(select(m.LearningBatch).where(
        m.LearningBatch.project_id == p.id, m.LearningBatch.scope_revision == p.scope_revision,
        m.LearningBatch.action.in_(STAGES)).order_by(m.LearningBatch.created_at.desc(), m.LearningBatch.id.desc()).limit(1))


def stage_results(db, p, actions):
    found = {}
    for batch in db.scalars(select(m.LearningBatch).where(
            m.LearningBatch.project_id == p.id, m.LearningBatch.scope_revision == p.scope_revision,
            m.LearningBatch.action.in_(actions)).order_by(m.LearningBatch.created_at.desc(), m.LearningBatch.id.desc())):
        if batch.data['state'] == 'completed':
            found.setdefault(batch.action, batch.data['items'])
    return found


def queue(db, p, row, member, body, **metrics):
    run = m.AIRun(project_id=p.id, membership_id=member, scope_revision=p.scope_revision,
        kind='learning', backend='project_learning', prompt=json.dumps(body, ensure_ascii=False),
        metrics={'binding_id': row.id, 'plan_revision': p.revision, **metrics})
    db.add(run)
    db.flush()
    return run


def create_today(db, p, row, member, native):
    points = objectives(native)
    if not points:
        return None
    previous = previous_day(db, p)
    carry = [item['id'] for item in (previous.data.get('items', []) if previous else [])
             if not item.get('result') and item['id'] in points]
    previous_cards = [item['question_id'] for item in (previous.data.get('items', []) if previous else [])
                      if item.get('question_id')]
    due = [item['knowledge_point_id'] for item in (native.get('curriculum') or {}).get('reviews', [])
           if item.get('due') and item.get('knowledge_point_id') in points]
    priority = list(dict.fromkeys(due + carry))
    eligible = {key: value for key, value in points.items()
                if key in priority or (value.get('status') != 'mastered' and not value.get('deferred'))}
    local_zone = ZoneInfo('Asia/Shanghai')
    plan_date = day()
    today_checked = {item.get('objective_id') for item in native.get('recent_evidence', [])
                     if item.get('timestamp') and datetime.fromtimestamp(item['timestamp'], local_zone).date().isoformat() == plan_date}
    eligible = {key: value for key, value in eligible.items() if key not in today_checked or key in priority}
    batch = m.LearningBatch(project_id=p.id, scope_revision=p.scope_revision, key=plan_date,
        action='chapter_continue', data={'budget': p.daily_minutes, 'items': [], 'state': 'planning',
                                        'seconds': 0, 'member': member})
    db.add(batch)
    db.flush()
    if not eligible:
        batch.data = {**batch.data, 'state': 'completed'}
        return batch
    prompt = {
        '每日分钟': p.daily_minutes, '优先安排（依次为到期复习和上次未完成）': priority,
        '已讲解': [key for key in native.get('explained', []) if key in eligible],
        '近期结果': [{k: e[k] for k in ('objective_id', 'result')} for e in native.get('recent_evidence', [])
                     if e.get('objective_id') in eligible][-40:],
        '可选知识点': [{'id': key, 'name': value['name'], 'status': value.get('status'),
                      'prerequisites': value.get('prerequisite_ids', [])} for key, value in eligible.items()],
    }
    queue(db, p, row, member, {'operation': 'daily_plan', 'context': prompt,
          'eligible': {key: value['name'] for key, value in eligible.items()}, 'priority': priority,
          'review': due, 'previous_cards': previous_cards}, batch_id=batch.id)
    return batch


def generate_plan(owner, body, run_id):
    prompt = ('制定今天可完成的学习任务。优先按给出的复习和未完成顺序安排，再安排新内容。'
              '每个知识点只安排一次讲解与检查。每项至少 5 分钟，计入讲解和作答。'
              '只返回 JSON 对象，格式为 {"items":[{"id":"知识点 ID","minutes":5}]}。'
              '至少选一项，总用时不得超过预算。\n' + json.dumps(body['context'], ensure_ascii=False))
    try:
        result = asyncio.run(tutor.structured_chat(owner, prompt, run_id, lambda _: False))
    except ValueError as exc:
        raise InvalidPlan('助教未返回可执行的今日计划') from exc
    return validate_plan(body, result)


def validate_plan(body, result):
    raw = result.get('items')
    eligible = body['eligible']
    budget = body['context']['每日分钟']
    items = []
    seen = set()
    if not isinstance(raw, list) or not raw:
        raise InvalidPlan('助教未返回可执行的今日计划')
    for item in raw:
        key, minutes = (item.get('id'), item.get('minutes')) if isinstance(item, dict) else (None, None)
        if not isinstance(key, str) or key not in eligible or key in seen or type(minutes) is not int or minutes < 5:
            raise InvalidPlan('今日计划包含无效知识点、重复任务或预计用时')
        seen.add(key)
        items.append({'id': key, 'name': eligible[key], 'minutes': minutes, 'review': key in body['review']})
    if sum(item['minutes'] for item in items) > budget:
        raise InvalidPlan('今日计划超过每日时间预算')
    priority = body['priority']
    required = priority[:min(len(items), len(priority))]
    if any(key not in seen for key in required):
        raise InvalidPlan('今日计划遗漏了优先复习或未完成的任务')
    items.sort(key=lambda item: priority.index(item['id']) if item['id'] in priority else len(priority))
    return items


def targets(native, action, supported=None):
    points = objectives(native)
    if action.startswith('kaoyan'):
        next_id = ((native.get('curriculum') or {}).get('next') or {}).get('knowledge_point_id')
        checked = {item.get('objective_id') for item in native.get('recent_evidence', [])}
        order = [key for key in points if key not in checked]
        if next_id in order:
            order.remove(next_id)
            order.insert(0, next_id)
        order = order or ([next_id] if next_id in points else list(points))
    else:
        order = list(points)
        if action == 'final_retest':
            weak = list(dict.fromkeys(item.get('objective_id') for item in reversed(native.get('recent_evidence', []))
                                     if item.get('result') != 'correct' and item.get('objective_id') in points))
            order = weak + [key for key in order if key not in weak]
    if supported is not None:
        order = [key for key in order if key in supported]
    return [{'id': key, 'name': points[key]['name']} for key in order[:STAGES[action]]]


def create_stage(db, p, member, action, guidance, items):
    if not items:
        fail(409, 'NO_OBJECTIVES', '当前范围还没有可检查的知识点')
    batch = m.LearningBatch(project_id=p.id, scope_revision=p.scope_revision, key=uuid4().hex,
        action=action, data={'items': items, 'state': 'active', 'member': member, 'guidance': guidance})
    db.add(batch)
    db.flush()
    return batch


def supported_objectives(native, materials, scope):
    if scope.get('sections'):
        from types import SimpleNamespace

        whole = set(scope.get('material_ids', []))
        selected = [material for material in materials if material.id in whole]
        headings = re.compile(r'^(?:(#{1,6})[ \t]+(.+)|(第[一二三四五六七八九十百零\d]+[章节].{0,80}))$')
        for section in scope['sections']:
            if section['material_id'] in whole:
                continue
            material = next((m for m in materials if m.id == section['material_id']), None)
            if not material:
                continue
            lines = material.text.splitlines()
            for index, line in enumerate(lines):
                match = headings.match(line)
                if not match or (match[2] or match[3]).strip()[:160] != section['title']:
                    continue
                depth = len(match[1] or '')
                end = next((j for j in range(index + 1, len(lines))
                            if (following := headings.match(lines[j])) and len(following[1] or '') <= depth), len(lines))
                selected.append(SimpleNamespace(id=material.id, project_id=material.project_id,
                                                 text='\n'.join(lines[index:end])))
                break
        materials = selected
    points = objectives(native)
    if not materials:
        return set()
    vocabulary = {word for material in materials for word in search.terms(material.text) if len(word) > 1}
    return {key for key, point in points.items()
            if any(word in vocabulary for word in search.terms(point['name']) if len(word) > 1)}


def batch_view(batch):
    if not batch:
        return None
    data = batch.data
    items = data['items']
    completed = sum(bool(item.get('result')) for item in items)
    return {'id': batch.id, 'date': batch.key if batch.action == 'chapter_continue' else None,
            'action': batch.action, 'state': data['state'], 'budget': data.get('budget'),
            'seconds': data.get('seconds', 0), 'items': items, 'completed': completed, 'error': data.get('error', ''),
            'question_id': next((item.get('question_id') for item in items if not item.get('result')), None),
            'last_question': bool(items and completed == len(items) - 1
                                  and items[-1].get('question_id') and data['state'] == 'active')}


def remember_question(batch, native, objective):
    if (native.get('state') != 'question' or native.get('question_objective') != objective
            or native.get('question_leaves') or not native.get('request_id')):
        return
    if native['request_id'] in batch.data.get('previous_cards', []):
        return
    if any(item.get('question_id') == native['request_id'] for item in batch.data['items']):
        return
    batch.data = {**batch.data, 'items': [
        {**item, 'question_id': native['request_id'], 'explained': objective in native.get('explained', [])}
        if item['id'] == objective and not item.get('result') else item
        for item in batch.data['items']
    ]}


def sync(db, p, row, batch, native, busy, *, resume=False, advance=True):
    """Persist native evidence and queue at most one next turn under the project lock."""
    if not batch or batch.data['state'] not in ('active', 'paused', 'budget_reached'):
        return None
    data = dict(batch.data)
    items = [dict(item) for item in data['items']]
    for item in items:
        qid = item.get('question_id')
        if qid and not item.get('result'):
            match = next((e for e in native.get('recent_evidence', [])
                          if e['question_id'] == qid and e['objective_id'] == item['id']), None)
            if match:
                item['result'] = match['result']
                item['evidence_id'] = match.get('id')
    remaining = [item for item in items if not item.get('result')]
    valid = objectives(native)
    data['items'] = items
    if not remaining:
        data['state'] = 'completed'
    elif data.get('budget') and data.get('seconds', 0) >= data['budget'] * 60:
        data['state'] = 'budget_reached'
    elif any(item['id'] not in valid for item in remaining):
        data['state'] = 'paused'
        data['error'] = '学习大纲已更新，原计划中的知识点已无法继续'
    if data != batch.data:
        batch.data = data
    if data['state'] != 'active' or busy:
        return None
    item = remaining[0]
    if native.get('state') == 'question':
        if not item.get('question_id'):
            remember_question(batch, native, item['id'])
        return None
    if native.get('state') == 'failed':
        if not resume:
            batch.data = {**data, 'state': 'paused', 'error': '助教未完成本次检查，请继续当前任务'}
            return None
    elif native.get('state') != 'idle':
        return None
    if item.get('question_id'):
        if not resume:
            batch.data = {**data, 'state': 'paused', 'error': '没有找到这道题的有效作答记录，请继续当前任务'}
            return None
        item.pop('question_id', None)
        batch.data = {**data, 'items': items}
    if not advance:
        return None
    if p.scenario == 'chapter' and batch.key != day():
        return None
    previous = db.scalar(select(m.AIRun).where(
        m.AIRun.project_id == p.id, m.AIRun.backend == 'project_learning',
        m.AIRun.metrics['batch_id'].as_string() == batch.id,
        m.AIRun.metrics['objective'].as_string() == item['id'],
    ).order_by(m.AIRun.created_at.desc(), m.AIRun.id.desc()).limit(1))
    if not resume and previous and previous.state == 'succeeded' and previous.result.get('turn_id') != native.get('turn_id'):
        return None
    if not resume and previous and previous.state in ('failed', 'succeeded'):
        data['state'] = 'paused'
        data['error'] = '助教未能登记计划内的题卡，请重试当前任务'
        batch.data = data
        return None
    teach = batch.action in ('chapter_continue', 'kaoyan_start', 'kaoyan_next') and not item.get('review')
    kind = '讲解与检查' if teach else '知识检查'
    return queue(db, p, row, data['member'], {
        'operation': 'mode', 'mode': 'study', 'text': kind + '：' + item['name'],
        'objective': item['id'],
        'teach': teach,
        'guidance': ('本轮仅处理知识点 ' + item['id'] + '（' + item['name'] +
                     '）。' + ('先讲解并调用 mastery_note_explained 记录。' if teach else '直接检查，先不要揭示答案。') +
                     '只登记一道针对该知识点的原生检查题卡，概念题也以题卡提交。优先使用有明确答案的选择题。'
                     '讲评和下一步由平台安排。'
                     '请用中性称呼引出题卡。\n' + data.get('guidance', ''))[:16000],
    }, batch_id=batch.id, objective=item['id'], action_id=batch.action)


def activity(batch):
    data = dict(batch.data)
    now = s.clock()
    previous = data.get('activity_at')
    if previous:
        seconds = (now - datetime.fromisoformat(previous)).total_seconds()
        if 0 <= seconds <= 16:
            data['seconds'] = data.get('seconds', 0) + int(seconds)
    data['activity_at'] = now.isoformat()
    batch.data = data


def practice_prompt(materials, topic, points):
    focus = '、'.join([topic, *points])
    hits = search.retrieve(materials, focus, limit=12)
    quotes = tutor.quote_options(hit.text for hit in hits)
    if not quotes:
        raise tutor.TutorError('所选章节缺少可核对的出题资料')
    return ('围绕以下章节和知识点生成练习：' + focus + '\n每道题必须在 kaoyan_quote 原样复制一条支持答案的原文，'
            '分析题提供 kaoyan_rubric。原文：' + json.dumps(quotes, ensure_ascii=False)), hits
