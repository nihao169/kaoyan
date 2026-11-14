"""Project-specific preparation and actions for the native tutor."""
import json
import re

from sqlalchemy import select

from ..errors import fail
from . import models as m, service as s, tutor_index


# Each action supplies a teaching brief. The native tutor owns the resulting
# outline, questions, assessment evidence and review queue.
ACTIONS = {
    'chapter_continue': ('继续学习', 'study', ''),
    'chapter_pause': ('暂停学习', 'study', ''),
    'chapter_practice': ('章节练习', 'study', ''),
    'chapter_outline': ('生成学习大纲', 'outline', '根据本章讲义按前置概念和依赖顺序拟定大纲。先展示方案，等学习者确认。'),
    'chapter_start': ('确认并开始第一节', 'study', '从大纲第一节开始，只讲一个知识点。用讲义中可核对的例子解释，讲完等待理解检查。'),
    'chapter_next': ('继续下一节', 'study', '根据刚才的真实答题证据，推进到下一个合适知识点。用讲义例子解释后等待检查。'),
    'chapter_check': ('做理解检查', 'study', '针对刚讲的知识点发出一道原生理解检查题，等待独立作答，提交前不透露答案。'),
    'chapter_reteach': ('补学后再测', 'study', '根据上一道检查题的真实作答找出误解，引用讲义补讲，并用不同情境的新题发起原生检查。'),
    'chapter_summary': ('查看学习小结', 'study', '依据原生大纲与作答证据，总结已经理解和仍待练习的内容。给出下次学习建议，本轮不出题。'),
    'final_outline': ('生成复习范围', 'outline', '只使用已确认的期末考试范围规划复习大纲。按可测概念和典型应用组织，先展示方案并等待确认。'),
    'final_diagnose': ('确认并开始摸底', 'study', '假定学生学过本课程。在考试范围内先发原生摸底题，覆盖不同概念或应用。先等作答再讲解。'),
    'final_weakness': ('查看薄弱点', 'study', '用实际摸底作答区分概念混淆、应用错误与尚未测到的内容。列出证据和优先级，本轮不出题。'),
    'final_remediate': ('开始专项补学', 'study', '从真实摸底证据中选择最优先的薄弱点，用范围内讲义对比相近概念并示范如何应用。'),
    'final_retest': ('做综合复测', 'study', '发出与摸底不同的原生题卡，检查已补学的薄弱点及最容易混淆的相邻概念。等待独立作答。'),
    'final_checklist': ('查看考前清单', 'study', '比较摸底和复测的真实作答，列出考前要重看的概念、练习优先级和未测范围。本轮不出题。'),
    'kaoyan_outline': ('生成考纲学习路线', 'outline', '只用目标年度考纲界定专题，用教材支撑学习顺序。标出教材未覆盖的考纲主题，先展示方案并等待确认。'),
    'kaoyan_start': ('确认并开始专题', 'study', '按已确认考纲路线讲第一项专题。明确对应考纲主题并引用教材，最后发原生理解检查题。'),
    'kaoyan_next': ('继续考纲专题', 'study', '按考纲和原生作答证据选下一专题或补学当前专题，引用教材并发一道原生检查题。'),
    'kaoyan_coverage': ('查看考纲覆盖', 'study', '对照目标考纲与真实学习记录，逐项区分学过、已经独立验证和仍待补学，不预测总分。'),
    'kaoyan_analyze': ('分析真题与补弱', 'study', '只按本次已交卷的真题数据归纳错题、未答题和薄弱考点。对照考纲，结合教材补弱，不把分析题反馈当正式分。'),
    'kaoyan_review': ('查看下一步复习', 'study', '依据已交卷模考和原生证据安排后续专题与复习优先级，分别说明实际得分、待补弱与未测范围。'),
    'due_review': ('开始到期复习', 'review', '依据原生复习队列处理到期知识点，用原生复习题卡检查长期保持。'),
}


def annual_rows(db, p, materials):
    allowed = {x.id for x in materials}
    return [row for row in s.rows(db, m.ExamResource, p.id) if row.material_id in allowed]


def scope_options(books):
    options = []
    for book in books:
        headings = re.findall(r'^(?:#{1,6}[ \t]+([^\n]+)|(第[一二三四五六七八九十百零\d]+[章节][^\n]{0,80}))$', book.text, re.M)
        titles = list(dict.fromkeys((markdown or numbered).strip()[:160] for markdown, numbered in headings))
        options.append({'id': book.id, 'title': book.title, 'sections': [title for title in titles[:80] if title]})
    return options


def preparation(db, p, materials):
    annual = annual_rows(db, p, materials)
    books = [x for x in materials if x.id not in {r.material_id for r in annual}]
    scope = p.study_scope or {}
    scope_file = scope.get('file_id')
    syllabus = next((r for r in reversed(annual) if r.kind == 'syllabus' and r.year == p.exam_year), None)
    papers = [r for r in annual if r.kind == 'past_paper' and r.year < p.exam_year]
    if p.scenario != 'final':
        scope_file = None
    selected = [x for x in books if x.id != scope_file]
    index = tutor_index.mappings(db, materials)
    labels = {'chapter': '本章教材或讲义', 'final': '课程讲义或复习资料', 'kaoyan': '教材或讲义'}

    def item(name, label, sources):
        entries = [{'id': x.id, 'title': x.title,
                    'state': index[x.id].state if x.id in index and index[x.id].state != 'deleted' else 'missing',
                    'error': index[x.id].error if x.id in index else ''} for x in sources]
        state = 'missing'
        if entries:
            states = {entry['state'] for entry in entries}
            state = 'ready' if states == {'ready'} else 'failed' if 'failed' in states else 'indexing'
        return {'id': name, 'label': label, 'state': state, 'items': entries}

    options = scope_options(books) if p.scenario == 'final' else []
    scope_check = None
    if p.scenario == 'final':
        file = next((x for x in books if x.id == scope_file), None)
        allowed = {(x['id'], section) for x in options for section in x['sections']}
        choices = scope.get('sections', [])
        whole = set(scope.get('material_ids', []))
        confirmed = scope.get('text') or ((whole or choices) and whole <= {x.id for x in books}
                    and all((x['material_id'], x['title']) in allowed for x in choices))
        if confirmed and (whole or choices):
            selected_ids = whole | {x['material_id'] for x in choices}
            selected = [x for x in selected if x.id in selected_ids]
        scope_check = item('scope', '期末考试范围', [file] if file else [])
        if not file and confirmed:
            scope_check['state'] = 'ready'
    checks = [item('books', labels[p.scenario], selected)]
    sources = list(selected)
    if scope_check:
        checks.append(scope_check)
        if file:
            sources.append(file)
    if p.scenario == 'kaoyan':
        current = [x for x in materials if syllabus and x.id == syllabus.material_id]
        checks.insert(0, item('syllabus', f'{p.exam_year} 年考纲', current))
        sources.extend(current)
    return {'checks': checks, 'ready': all(x['state'] == 'ready' for x in checks) and len(sources) <= 16,
            'too_many': len(sources) > 16, 'scope_options': options, 'scope': scope if p.scenario == 'final' else {},
            'papers': [{'id': r.id, 'title': r.title, 'year': r.year} for r in papers]}, sources


def paper_attempts(db, p, paper_ids):
    if not paper_ids:
        return {}
    found = {}
    for exam in db.scalars(select(m.Assessment).where(m.Assessment.project_id == p.id,
                           m.Assessment.state == 'submitted').order_by(m.Assessment.created_at.desc())):
        first = db.get(m.Task, exam.task_ids[0]) if exam.task_ids else None
        if first and first.payload.get('resource_id') in paper_ids:
            found.setdefault(exam.mode, exam)
    return found


def assessment_evidence(db, exam):
    evidence = []
    for task_id in exam.task_ids:
        task = db.get(m.Task, task_id)
        question = db.get(m.Question, task.payload['question_id'])
        attempt = db.scalar(select(m.Attempt).where(m.Attempt.task_id == task_id))
        evidence.append({'题号': len(evidence) + 1, '考点': question.knowledge[:100], '题型': question.kind,
                         '分值': task.payload.get('points'), '已作答': bool(attempt and (attempt.answer or attempt.response_text)),
                         '已选': attempt.answer if attempt and question.kind != 'essay' else None,
                         '参考选项': question.answer if question.kind != 'essay' else None,
                         '客观题正确': attempt.result.get('correct') if attempt and question.kind != 'essay' else None})
    return json.dumps(evidence, ensure_ascii=False, separators=(',', ':'))


def workflow(p, prep, native, runs, exams, *, stage=None):
    scene = p.scenario
    outline_action = f'{scene}_outline'
    has_outline = bool((native.get('curriculum') or {}).get('map', {}).get('modules'))
    available = []
    names = {
        'chapter': ['准备资料', '学习大纲', '讲解与理解检查', '小结与复习'],
        'final': ['准备资料', '复习范围', '摸底与专项补学', '综合复测', '考前清单'],
        'kaoyan': ['准备资料', '考纲学习路线', '专题学习', '历年真题', '限时模考', '后续复习'],
    }[scene]
    step = 0
    confirm_outline = False
    started = set(runs)
    last_result = native.get('evidence') or {}
    count = last_result.get('count', 0)
    analysis_done = ('practice' in exams and 'kaoyan_analyze' in runs
                     and runs['kaoyan_analyze'].metrics.get('assessment_id') == exams['practice'].id)

    def answered(action):
        if stage and stage.action == action:
            return stage.data['state'] == 'completed'
        return action in runs and count > runs[action].metrics.get('evidence_count', 0)

    if prep['ready']:
        step = 1
        if not has_outline:
            available.append(outline_action)
            confirm_outline = outline_action in started
        elif scene == 'chapter':
            step = 2
            lessons = started.intersection(('chapter_start', 'chapter_check', 'chapter_next', 'chapter_reteach'))
            if not lessons:
                available.append('chapter_next' if count else 'chapter_start')
            else:
                lesson = max(lessons, key=lambda a: (runs[a].created_at, runs[a].id))
                if answered(lesson):
                    independent = last_result.get('result') == 'correct' and not last_result.get('hints')
                    available.extend(['chapter_next' if independent else 'chapter_reteach', 'chapter_summary'])
                else:
                    available.append('chapter_check')
                if 'chapter_summary' in started and runs['chapter_summary'].created_at >= runs[lesson].created_at:
                    step = 3
        elif scene == 'final':
            step = 2
            if not answered('final_diagnose'):
                available.append('final_diagnose')
            elif 'final_weakness' not in started:
                available.append('final_weakness')
            elif 'final_remediate' not in started:
                available.append('final_remediate')
            elif not answered('final_retest') or runs['final_remediate'].created_at > (
                    stage.created_at if stage and stage.action == 'final_retest' else runs['final_retest'].created_at):
                step = 3
                available.append('final_retest')
            else:
                step = 4
                available.extend(['final_checklist', 'final_remediate'])
        else:
            step = 2
            available.extend(['kaoyan_next', 'kaoyan_coverage'] if count or 'kaoyan_start' in started else ['kaoyan_start'])
        if has_outline and any(x.get('due') for x in (native.get('curriculum') or {}).get('reviews', [])):
            available.append('due_review')

    if prep['ready'] and scene == 'kaoyan':
        if 'kaoyan_coverage' in started or prep['papers']:
            step = 3
        if exams.get('practice'):
            step = 4 if analysis_done else 3
            available.append('kaoyan_analyze')
        if exams.get('mock'):
            step = 5
            available.append('kaoyan_review')
    return {'steps': names, 'step': step, 'confirm_outline': confirm_outline,
            'actions': [{'id': a, 'label': ACTIONS[a][0]} for a in available],
            'practice_id': exams['practice'].id if 'practice' in exams else None,
            'mock_id': exams['mock'].id if 'mock' in exams else None,
            'mock_ready': analysis_done}
