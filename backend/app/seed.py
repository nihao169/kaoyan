"""Initialize accounts/configuration; legacy teaching fixtures require explicit test opt-in."""
import hashlib
from sqlalchemy import select
from . import models as m
from .auth import passwords
from .db import SessionLocal
from .content import parse_chunks
from .ports import LocalFileStore
from .config import settings

DATA = [
    {
        'module': '马克思主义基本原理', 'topic': '实践与认识',
        'principle': '实践是认识的来源、发展的动力、目的，也是检验认识真理性的唯一标准。感性认识与理性认识相互依赖，认识需要在实践中反复深化。',
        'method': '分析材料时，区分经验来源、认识发展和检验标准。个人经验具有条件与范围，不能把一次成功等同于普遍真理。',
        'questions': [
            ('single', '某学习小组通过实地调查修正了原有判断。这首先说明什么？', {'A': '实践能够推动认识发展', 'B': '书本知识没有价值', 'C': '任何个人经验都是普遍真理', 'D': '认识可以脱离实践'}, ['A']),
            ('multiple', '关于实践与认识，下列说法恰当的有：', {'A': '实践为认识提供来源', 'B': '实践检验认识的真理性', 'C': '理性认识无需感性材料', 'D': '认识可以反过来指导实践'}, ['A', 'B', 'D']),
            ('single', '一项方案需要投入实践检验，而不能仅以支持者人数判断其正确性，强调的是：', {'A': '多数意见必然错误', 'B': '实践是检验认识真理性的标准', 'C': '理论研究不再必要', 'D': '所有检验都只需一次'}, ['B']),
            ('multiple', '将一次调研结论用于新地区前，合理的做法有：', {'A': '核对新地区的具体条件', 'B': '在新实践中检验和修正', 'C': '将原结论视为永远不变', 'D': '保留必要的调查材料'}, ['A', 'B', 'D']),
        ],
        'essay': '原创模拟材料：社区志愿者最初认为居民不愿参与活动，访谈后发现主要障碍是时间安排。调整方案后参与增加。请用实践与认识的关系分析这一过程。',
        'rubric': [{'label': '指出实践为认识提供来源和检验依据', 'score': 4}, {'label': '结合访谈、调整和反馈解释认识深化，避免绝对化', 'score': 6}],
    },
    {
        'module': '毛泽东思想和中国特色社会主义理论体系概论', 'topic': '实事求是与调查研究',
        'principle': '实事求是要求从客观实际出发，探求事物的内部联系及规律，以实践检验认识。理论联系实际需要调查研究，不能机械套用经验。',
        'method': '区分坚持一般原理与照搬具体做法。分析政策选择时，先识别具体条件，再说明调查、论证、实施和反馈的联系。',
        'questions': [
            ('single', '某地在借鉴外地经验前先调查自身产业和人口条件，体现了：', {'A': '拒绝学习一切外部经验', 'B': '从实际出发', 'C': '以主观愿望代替规律', 'D': '否定理论的作用'}, ['B']),
            ('multiple', '理论联系实际的要求包括：', {'A': '调查具体条件', 'B': '把外地做法原样复制', 'C': '用实践反馈修正方案', 'D': '理解一般原理的适用条件'}, ['A', 'C', 'D']),
            ('single', '将某地的成功做法不加分析地复制到条件不同的地区，主要问题是：', {'A': '重视了调查研究', 'B': '缺少对具体实际的分析', 'C': '坚持了实事求是', 'D': '完全没有任何经验'}, ['B']),
            ('multiple', '形成工作方案前，有助于实事求是的做法有：', {'A': '核实数据口径', 'B': '听取不同群体意见', 'C': '把愿望当作既成事实', 'D': '识别试点经验的条件'}, ['A', 'B', 'D']),
        ],
        'essay': '原创模拟材料：甲村照搬邻村产业项目，未考虑交通和市场条件而受挫。重新调研后调整项目。请分析调查研究与实事求是的联系。',
        'rubric': [{'label': '解释从实际出发和调查研究的关系', 'score': 4}, {'label': '结合条件差异、方案调整与实践反馈分析', 'score': 6}],
    },
    {
        'module': '习近平新时代中国特色社会主义思想概论', 'topic': '以人民为中心与发展质量',
        'principle': '以人民为中心的发展思想重视人民的主体地位和实际需要。评价发展需要关注质量与效益，不能把单一数量指标作为全部尺度。',
        'method': '分析公共服务材料时，识别服务对象、实际需求、资源约束和反馈机制。区分发展成果的数量增长与群众实际获得的改善。',
        'questions': [
            ('single', '某服务中心根据居民意见调整开放时间，其直接关注的是：', {'A': '只增加宣传数量', 'B': '脱离需求设计服务', 'C': '回应群众实际需要', 'D': '取消一切管理规则'}, ['C']),
            ('multiple', '评价一项公共服务改进，可以关注：', {'A': '服务是否可及', 'B': '群众实际反馈', 'C': '只有设施数量', 'D': '资源使用效益'}, ['A', 'B', 'D']),
            ('single', '服务设施数量增加，但部分居民仍难使用。进一步评价应重点补充：', {'A': '实际可用性和受益情况', 'B': '仅继续统计数量', 'C': '完全忽略资源约束', 'D': '停止收集意见'}, ['A']),
            ('multiple', '改进服务方案的合理环节有：', {'A': '了解不同群体需要', 'B': '设置反馈渠道', 'C': '把建设数量等同于全部效果', 'D': '检查方案实施后的变化'}, ['A', 'B', 'D']),
        ],
        'essay': '原创模拟材料：某街道新增服务设施后，发现老年人使用不便，于是调整指引和办理方式。请从人民需要与发展质量角度分析。',
        'rubric': [{'label': '说明回应人民实际需要的意义', 'score': 4}, {'label': '结合可及性、反馈与实际效益分析', 'score': 6}],
    },
    {
        'module': '中国近现代史纲要', 'topic': '历史材料与历史条件',
        'principle': '认识历史事件需要放在具体历史条件中，结合时间、社会背景、参与主体和材料来源分析。史料之间应相互印证，区分事实记录与后来的评价。',
        'method': '阅读材料先辨明形成时间、作者身份与所述对象，再核对不同材料。不能凭一段文字越过证据直接推出所有历史结论。',
        'questions': [
            ('single', '理解某一历史选择，首先需要：', {'A': '脱离时代背景', 'B': '放入当时的具体条件', 'C': '只看今天的生活经验', 'D': '忽略事件参与者'}, ['B']),
            ('multiple', '评价一份历史材料时应关注：', {'A': '形成时间', 'B': '作者身份与立场', 'C': '是否存在其他材料印证', 'D': '文字越长就必然越可靠'}, ['A', 'B', 'C']),
            ('single', '两份材料对同一事件描述不同，合理的做法是：', {'A': '任意选择有利的一份', 'B': '不再研究该事件', 'C': '核对来源并分析形成条件', 'D': '认定两份材料都毫无价值'}, ['C']),
            ('multiple', '历史分析中应避免：', {'A': '把后来的评价当作当时的直接记录', 'B': '脱离条件使用孤立材料', 'C': '核查资料来源', 'D': '以个人猜测替代证据'}, ['A', 'B', 'D']),
        ],
        'essay': '原创方法训练材料：研究者发现两篇关于同一历史活动的回忆文字，形成时间和作者身份不同。请说明如何分析其证据价值。材料不指向特定真实事件。',
        'rubric': [{'label': '辨析时间、作者、背景和材料性质', 'score': 4}, {'label': '说明相互印证和结论边界，避免无证据断言', 'score': 6}],
    },
    {
        'module': '思想道德与法治', 'topic': '道德与法治的关系',
        'principle': '道德与法律在社会治理中各有作用并相互配合。分析行为应区分道德评价与法律责任，法律责任需要明确事实、适用规范和程序，不能只凭道德不满作出认定。',
        'method': '先区分事实与评价，再识别讨论的是道德义务还是法律责任。学习材料中的一般分析不能代替具体案件的专业法律判断。',
        'questions': [
            ('single', '对某行为不满就直接认定其违法，主要忽略了：', {'A': '道德与法律评价的区别', 'B': '任何事实都无关紧要', 'C': '情绪可以代替法律依据', 'D': '不需要任何程序'}, ['A']),
            ('multiple', '分析社会行为时，应当：', {'A': '区分事实与评价', 'B': '关注相关规范', 'C': '以网络情绪直接认定责任', 'D': '尊重必要程序'}, ['A', 'B', 'D']),
            ('single', '讨论一项行为的法律责任时，优先需要核实：', {'A': '讨论热度', 'B': '事实与适用规范', 'C': '评论数量', 'D': '个人好恶'}, ['B']),
            ('multiple', '关于道德与法治，下列理解恰当的有：', {'A': '二者可以共同发挥治理作用', 'B': '二者在任何情况下完全相同', 'C': '应区分评价维度', 'D': '法律判断需尊重事实与程序'}, ['A', 'C', 'D']),
        ],
        'essay': '原创模拟材料：校园公共空间出现争议，部分同学仅凭片段信息要求立即追责。请从事实、道德评价与程序角度说明应如何理性分析。',
        'rubric': [{'label': '区分事实、道德评价与法律责任', 'score': 4}, {'label': '说明核实信息、尊重规则与程序的必要性', 'score': 6}],
    },
    {
        'module': '形势与政策', 'topic': '政策材料的证据与分析',
        'principle': '本资料使用虚构场景训练政策材料分析，不提供最新时政结论。分析应区分政策目标、实施措施和实际效果，核对来源与时间，并考虑数据口径和适用范围。',
        'method': '阅读政策材料时，先识别发布主体、时间、目标与措施，再考察效果证据。相关性不能直接当作因果关系，单一指标不能代表全部结果。',
        'questions': [
            ('single', '虚构材料称某项目启动后满意度上升，直接认定全部变化由项目造成，主要问题是：', {'A': '混淆相关性与因果性', 'B': '充分识别了所有因素', 'C': '完成了来源核验', 'D': '说明了全部适用条件'}, ['A']),
            ('multiple', '阅读政策分析材料，应核对：', {'A': '发布主体与时间', 'B': '数据口径', 'C': '措施与效果的区别', 'D': '只看标题不看正文'}, ['A', 'B', 'C']),
            ('single', '将一份旧材料称为最新政策，应首先补充核验：', {'A': '标题是否醒目', 'B': '发布与更新日期及有效范围', 'C': '转发次数', 'D': '排版颜色'}, ['B']),
            ('multiple', '对虚构项目效果进行审慎分析，需要：', {'A': '检查基期和比较口径', 'B': '考虑其他影响因素', 'C': '仅凭一个数字下最终结论', 'D': '说明证据不足之处'}, ['A', 'B', 'D']),
        ],
        'essay': '原创虚构场景：某城市试行预约服务，报告称平均等待时间缩短，但未说明样本和比较时段。请区分政策目标、措施与效果，并指出还需哪些证据。此场景不是现实新闻。',
        'rubric': [{'label': '区分目标、措施与效果', 'score': 4}, {'label': '指出样本、时间、口径及其他因素，避免无依据因果判断', 'score': 6}],
    },
]


def seed(include_demo_content=False):
    with SessionLocal.begin() as db:
        if db.scalar(select(m.Organization.id)):
            if include_demo_content:
                augment(db)
            return False
        org = m.Organization(name='知行研学 · 演示机构', is_demo=True)
        db.add(org)
        db.flush()
        cls = m.TeachingClass(org_id=org.id, name='政治基础研习班')
        db.add(cls)
        subject = m.Subject(code='politics', name='考研政治')
        db.add(subject)
        db.flush()
        teacher_user = None
        for username, name, roles in [('student', '林同学', ['student']), ('teacher', '陈老师', ['teacher']), ('admin', '平台管理员', ['admin'])]:
            user = m.User(username=username, name=name, password_hash=passwords.hash('Zhixing2026!'))
            db.add(user)
            db.flush()
            member = m.Membership(user_id=user.id, org_id=org.id)
            db.add(member)
            db.flush()
            db.add(m.ClassMember(class_id=cls.id, membership_id=member.id))
            for role in roles:
                db.add(m.RoleAssignment(membership_id=member.id, role=role, class_id=cls.id if role == 'teacher' else None))
            if username == 'teacher':
                teacher_user = user
        policies = {}
        for kind in ('single', 'multiple', 'essay'):
            p = m.ScoringPolicyVersion(strategy=kind, config={'rule': 'all_or_nothing' if kind != 'essay' else 'teacher_rubric'})
            db.add(p)
            db.flush()
            policies[kind] = p.id
        knowledge_ids = []
        for index, item in enumerate(DATA):
            module = m.Module(subject_id=subject.id, name=item['module'], position=index)
            db.add(module)
            db.flush()
            if not include_demo_content:
                continue
            kp = m.KnowledgePoint(module_id=module.id, name=item['topic'])
            db.add(kp)
            db.flush()
            knowledge_ids.append(kp.id)
            source = m.Source(org_id=org.id, owner_id=teacher_user.id, title=f"原创示例讲义 · {item['topic']}")
            db.add(source)
            db.flush()
            text = f"# {item['topic']}\n\n原创演示内容，仅用于平台功能与基础学习方法演示，未经正式教学认证。\n\n## 基本认识\n\n{item['principle']}\n\n## 材料分析方法\n\n{item['method']}"
            key = LocalFileStore(settings.data_dir / 'files').put(text.encode())
            version = m.SourceVersion(source_id=source.id, text=text, sha256=hashlib.sha256(text.encode()).hexdigest(), knowledge_id=kp.id, file_key=key)
            db.add(version)
            db.flush()
            parse_chunks(db, version)
            for label, body in [('概念梳理', item['principle']), ('材料辨析', item['method'])]:
                db.add(m.CardVersion(org_id=org.id, source_version_id=version.id, knowledge_id=kp.id, title=f"{item['topic']} · {label}", body=body))
            for kind, prompt, options, answer in item['questions']:
                answer_text = '、'.join(answer)
                explanation = f"正确选项：{answer_text}。{item['principle']} {item['method']}"
                db.add(m.QuestionVersion(org_id=org.id, source_version_id=version.id, knowledge_id=kp.id, policy_id=policies[kind], kind=kind,
                    prompt=prompt, options=options, answer=answer, explanation=explanation,
                    hints=[item['principle'], item['method'], '逐项检查：选项是否符合资料中的条件？注意绝对化表述，并结合具体材料。', explanation], max_score=2 if kind == 'single' else 4))
            db.add(m.QuestionVersion(org_id=org.id, source_version_id=version.id, knowledge_id=kp.id, policy_id=policies['essay'], kind='essay',
                prompt=item['essay'], explanation=f"参考分析：{item['principle']} 应结合材料，{item['method']}", rubric=item['rubric'], max_score=10,
                hints=[item['principle'], item['method'], '按“原理—材料—结论及边界”组织回答，每一点对应材料事实。', f"{item['principle']} {item['method']}"]))
        curriculum = m.Curriculum(org_id=org.id, subject_id=subject.id, title='政治原创演示课程范围')
        db.add(curriculum)
        db.flush()
        db.add(m.CurriculumVersion(curriculum_id=curriculum.id, applicable_year=2027, knowledge_ids=knowledge_ids))
        db.flush()
        if include_demo_content:
            augment(db)
        return True


def augment(db):
    """Append original draft examples only; never replace published content or learning records."""
    for item in DATA:
        source = db.scalar(select(m.Source).where(m.Source.title == f"原创示例讲义 · {item['topic']}"))
        if not source or not db.get(m.Organization, source.org_id).is_demo:
            continue
        version = db.scalar(select(m.SourceVersion).where(m.SourceVersion.source_id == source.id, m.SourceVersion.status == 'draft').order_by(m.SourceVersion.number.desc()))
        if not version:
            continue
        if not db.scalar(select(m.Job.id).where(m.Job.resource_id == version.id, m.Job.kind == 'index', m.Job.state.in_(['queued', 'running']))):
            db.add(m.Job(org_id=source.org_id, owner_id=source.owner_id, kind='index', resource_id=version.id))
        label = item['topic'] + ' · 适用条件与表达'
        if not db.scalar(select(m.CardVersion.id).where(m.CardVersion.source_version_id == version.id, m.CardVersion.title == label)):
            db.add(m.CardVersion(org_id=source.org_id, source_version_id=version.id, knowledge_id=version.knowledge_id,
                title=label, body='先明确概念与条件，再提取材料事实，最后解释联系。' + item['method']))
        db.flush()
        for card in db.scalars(select(m.CardVersion).where(m.CardVersion.source_version_id == version.id)):
            if not db.scalar(select(m.CardRule.id).where(m.CardRule.card_id == card.id)):
                causes = ['概念混淆', '原理适用'] if '概念' in card.title else ['材料理解', '审题'] if '材料辨析' in card.title else ['论证表达', '时间管理']
                db.add(m.CardRule(card_id=card.id, causes=causes))
        extras = [
            (f"围绕“{item['topic']}”，学习者应如何处理教材观点与材料？", {'A': '只背结论，不看条件', 'B': item['method'], 'C': '使用未经核实的网络说法', 'D': '仅凭个人好恶判断'}, ['B']),
            (f"关于“{item['topic']}”的材料分析，哪种论证结构更合适？", {'A': '列出术语，不解释事实', 'B': '以一个案例证明所有情形', 'C': '明确原理及条件，结合事实，说明结论边界', 'D': '省略材料直接表态'}, ['C']),
            (f"同学讨论“{item['topic']}”时出现不同观点，应优先采取什么做法？", {'A': '核对资料依据和材料条件', 'B': '以声音大小判定正确', 'C': '只听多数人意见', 'D': '不再阅读原文'}, ['A']),
            (f"阅读“{item['topic']}”的新材料时，以下哪种做法有助于避免误用原理？", {'A': '用旧结论替代材料阅读', 'B': '把相关关系一律当成因果关系', 'C': '默认所有案例条件相同', 'D': '先标出主体、条件和证据，再选择适用原理'}, ['D']),
        ]
        policy = db.scalar(select(m.ScoringPolicyVersion).where(m.ScoringPolicyVersion.strategy == 'single'))
        for prompt, options, answer in extras:
            if not db.scalar(select(m.QuestionVersion.id).where(m.QuestionVersion.source_version_id == version.id, m.QuestionVersion.prompt == prompt)):
                explanation = item['principle'] + ' ' + item['method']
                db.add(m.QuestionVersion(org_id=source.org_id, source_version_id=version.id, knowledge_id=version.knowledge_id,
                    policy_id=policy.id, kind='single', prompt=prompt, options=options, answer=answer,
                    explanation=explanation, hints=[item['principle'], item['method'], '逐项核对材料条件与证据，不以表态代替分析。', explanation], max_score=2))
        essay_prompt = '比较与反思：' + item['essay'] + '另有同学只写教材结论而未联系事实，请说明这种回答的不足，并给出改进结构。'
        if not db.scalar(select(m.QuestionVersion.id).where(m.QuestionVersion.source_version_id == version.id, m.QuestionVersion.prompt == essay_prompt)):
            policy = db.scalar(select(m.ScoringPolicyVersion).where(m.ScoringPolicyVersion.strategy == 'essay'))
            db.add(m.QuestionVersion(org_id=source.org_id, source_version_id=version.id, knowledge_id=version.knowledge_id,
                policy_id=policy.id, kind='essay', prompt=essay_prompt, options={}, answer=[], rubric=item['rubric'],
                explanation=item['principle'] + ' 应联系材料中的事实并解释条件。',
                hints=[item['principle'], item['method'], '按原理、事实、联系和边界组织回答。', item['principle'] + item['method']], max_score=10))
    db.flush()
    points = {k.name:k.id for k in db.scalars(select(m.KnowledgePoint))}
    a, b = points.get(DATA[0]['topic']), points.get(DATA[1]['topic'])
    if a and b and not db.scalar(select(m.Prerequisite.id).where(m.Prerequisite.knowledge_id == b, m.Prerequisite.requires_id == a)):
        db.add(m.Prerequisite(knowledge_id=b, requires_id=a))


if __name__ == '__main__':
    print('已初始化账号与政治教学配置，未导入资料或题目。' if seed() else '已存在数据，未导入演示内容。')
