"""Original examples to exercise the annual workflow without distributing exam items."""

TOPICS = [
    ('marx.practice', '马克思主义基本原理', '实践与认识', '实践为认识提供经验与问题，也为检验认识是否符合客观实际提供标准。认识能指导后续实践，两者在反复检验和修正中发展。'),
    ('mao.investigation', '毛泽东思想和中国特色社会主义理论体系概论', '调查研究与实事求是', '调查研究从实际问题出发，通过收集、核对和分析材料形成判断。应避免先有结论、再选择支持结论的材料。'),
    ('xi.development', '习近平新时代中国特色社会主义思想概论', '高质量发展', '高质量发展关注发展的质量、效益和可持续性。评价具体政策时，可结合创新能力、资源利用效率和公共服务成效等证据。'),
    ('history.method', '中国近现代史纲要', '史料与历史解释', '理解历史事件要把事实放回其时代条件。不同来源的记载应交叉核对，并区分材料记述、因果推断和价值评价。'),
    ('law.process', '思想道德与法治', '法治思维', '分析公共事务应区分权限、实体依据与程序保障。即使有合理目标，也需要依据规则并履行相应程序。'),
    ('world.cooperation', '形势与政策以及当代世界经济与政治', '全球治理与国际合作', '跨境问题需要考虑共同利益和差异化条件。比较合作机制时，应区分目标、责任分工、执行措施和反馈渠道。'),
]


def syllabus(year):
    return dict(kind='syllabus', year=year, edition='simulation-v1', title='考研政治模拟考纲（示例范围）',
        source_title='平台原创模拟资料；章节导航不代表本年度官方细目', rights_confirmed=True,
        topics=[dict(code=code, chapter=chapter, title=title, text=text) for code, chapter, title, text in TOPICS])


def paper(year):
    return dict(kind='simulated_paper', year=year, edition='simulation-v1', title='考研政治模拟练习卷（短卷）',
        source_title='平台原创模拟题；未使用历年真题', rights_confirmed=True, minutes=35,
        questions=[
          dict(number=1, kind='single', knowledge='实践与认识', points=2,
               prompt='某小组提出节水方案，随后实际试运行并统计用水量。试运行在这里主要承担什么作用？',
               options={'A':'检验原先判断','B':'证明判断不必修正','C':'代替理论分析','D':'消除所有误差'},
               answer=['A'], explanation=TOPICS[0][3]),
          dict(number=2, kind='single', knowledge='调查研究与实事求是', points=2,
               prompt='开展社区服务调查时，哪项做法最符合从实际出发？',
               options={'A':'只访谈满意者','B':'先公布结论','C':'核对不同来源的数据后作判断','D':'以调查者的印象代替记录'},
               answer=['C'], explanation=TOPICS[1][3]),
          dict(number=3, kind='multiple', knowledge='高质量发展', points=3,
               prompt='比较两套园区发展方案的质量，哪些指标可以提供直接证据？',
               options={'A':'单位产出能耗','B':'公共服务可及性','C':'宣传海报数量','D':'创新成果转化情况'},
               answer=['A','B','D'], explanation=TOPICS[2][3]),
          dict(number=4, kind='multiple', knowledge='史料与历史解释', points=3,
               prompt='两份报刊对同一历史事件的报道出现差异。研究时，哪些处理是适当的？',
               options={'A':'核对写作时间与来源','B':'寻找相互独立的其他材料','C':'直接删去不合预期的报道','D':'区分事实记载与解释'},
               answer=['A','B','D'], explanation=TOPICS[3][3]),
          dict(number=5, kind='essay', knowledge='法治思维', points=10,
               prompt='一项公共场所管理措施的目标是减少噪声，但制定时未说明法律依据，也未公开征求意见。请从权限、依据和程序三个方面分析还需核对什么。',
               rubric=['说明需核对发布主体是否有相应权限','核对实体依据与限制范围','检查该事项适用的程序及公众参与要求'],
               explanation=TOPICS[4][3]),
          dict(number=6, kind='essay', knowledge='全球治理与国际合作', points=10,
               prompt='相邻地区准备建立跨境河流污染治理机制。请说明如何把共同目标转化为可执行并可检查的合作安排。',
               rubric=['给出可以共同检查的治理目标','依据各方条件明确分工与行动','设置监测和反馈机制'],
               explanation=TOPICS[5][3]),
        ])
