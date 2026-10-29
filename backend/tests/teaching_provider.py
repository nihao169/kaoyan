"""Explicit synthetic provider used ONLY by the isolated browser-test server."""
import json


def create_provider():
    serial=0

    def completion(messages,metrics,max_tokens=4096):
        nonlocal serial
        metrics['calls']=metrics.get('calls',0)+1
        metrics['total_tokens']=metrics.get('total_tokens',0)+60
        data=json.loads(messages[-1]['content'])
        if 'artifact' in data:
            return {'accepted':True,'conflict':False,'issues':[]}
        e=data['evidence'][0]
        cite={'chunk_id':e['chunk_id'],'quote':e['text'][:80]}
        if 'expected_kinds' in data:
            scenarios=['社区走访改进开放安排','农田试验调整种植技术','交通调查修正路口设计','课堂观察调整教学节奏','企业访谈完善人员培训','体育测试修订训练计划','医院随访改善预约流程','工厂试运行优化操作方案','图书馆调查变化借阅规则','居民实测比较节能方案','研究者采样检验初步判断','志愿者访谈重新设计活动','环保团队实测核对效果','食品团队实验修改储藏办法','工程小组测试检查承重方案','产业调研发现市场变化']
            qs=[]
            for kind in data['expected_kinds']:
                scenario=scenarios[serial%len(scenarios)]
                serial+=1
                q={'kind':kind,'knowledge_name':data['topics'][0],'prompt':f'原创模拟情境：{scenario}。如何理解这一情境中的实践与认识关系？',
                   'options':{'A':f'{scenario}应核对客观条件','B':f'{scenario}体现实践检验和发展认识','C':f'{scenario}只凭猜测即可','D':f'{scenario}可以忽略实践反馈'},
                   'answer':['B'] if kind=='single' else ['A','B'],'explanation':'应根据实践与认识的关系分析客观条件、检验和认识的发展。',
                   'hints':['先回忆实践与认识的联系','找出情境中的检验与反馈','检查各选项是否尊重客观条件','实践检验并推动认识发展，结合材料作答'],
                   'rubric':[],'max_score':2 if kind=='single' else 4,'option_analysis':{k:'根据原文关于实践与认识的关系核对该项。' for k in 'ABCD'},'evidence':[cite]}
                if kind=='essay':
                    q.update(options={},answer=[],option_analysis={},max_score=10,rubric=[{'label':'原理阐述','score':4},{'label':'联系材料','score':6}])
                qs.append(q)
            return {'questions':qs}
        if 'original' not in data:
            return {'topics':[{'name':'实践与认识','section':'原文核心知识','card':'实践提供认识的来源，并在具体条件下检验和发展认识。','evidence':[cite]}],'coverage':'受控浏览器测试：仅覆盖上传资料中的实践与认识关系。'}
        if 'parts' in messages[0]['content']:
            return {'parts':[2,3],'feedback':'原理有所涉及，材料联系和条件分析仍需补充。此为受控测试建议。','evidence':[cite]}
        return {'explanation':'你的选择忽略了原文中的实践检验条件，过程有限，尚不能确定心理错因。',
            'candidate_cause':'可能忽视实践的检验作用','option_analysis':{k:'结合原文核对该选项。' for k in 'ABCD'},
            'knowledge_gaps':['实践与认识的具体联系'],'learning_advice':['阅读原文，比较错误选项与适用条件。'],
            'clarifying_questions':['当时是否注意到材料的条件？'],'evidence':[cite]}
    return completion
