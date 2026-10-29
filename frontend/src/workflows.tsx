import { useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Alert, Button, Card, Collapse, Form, Input, Modal, Select, Space, Table, Tag } from 'antd';
import { api, key, kindName, type Attempt, type Task, type Evidence, type QuestionInput } from './api';
import { Blank, PageTitle, Sources, State, date, useRun } from './ui';
import { AgentResult, pendingAgent, type AgentRun } from './agents';
import { StudyTask } from './student';
import { QuestionEditor } from './content';

type Assignment={id:string;title:string;due_at:string|null;created_at:string;questions:number;state?:string;class_name?:string;submitted?:number};
type BankQuestion=QuestionInput & {id:string;answer:string[];source_title:string;knowledge:string;number:number;option_analysis:Record<string,string>;sources:Evidence[]};
type Group={id:string;title:string;state:string;due_at:string|null;origin_attempt_id:string|null;entries:{task:Task;attempt:Attempt}[]};

export function StudentAssignments(){
  const query=useQuery({queryKey:['assignments'],queryFn:()=>api<Assignment[]>('/assignments')});
  return <><PageTitle title="我的作业" description="完成教师布置的题组，再针对错题分析和练习。无需先做基础诊断。" action={<Link to="/mistakes"><Button>查看错题诊断</Button></Link>}/>
    <State query={query}>{!query.data?.length?<Blank description="还没有教师作业。请教师先上传资料、启用生成题目，再向班级发布作业。"/>:<div className="assignment-list">{query.data.map(a=><section className="panel assignment-card" key={a.id}><div className="section-heading"><div><Tag color={a.state==='submitted'?'green':'default'}>{a.state==='submitted'?'已提交':a.state==='draft'?'作答中':'未开始'}</Tag><h2>{a.title}</h2><p>{a.questions} 道题 · {a.due_at?'截止 '+date(a.due_at):'未设置截止时间'}</p></div><Link to={'/assignments/'+a.id}><Button type={a.state==='submitted'?'default':'primary'}>{a.state==='submitted'?'查看作答':a.state==='draft'?'继续作答':'开始作业'}</Button></Link></div></section>)}</div>}</State>
    <section className="panel section-space"><h2>学习记录与巩固</h2><Space wrap><Link to="/mistakes"><Button>错题诊断</Button></Link><Link to="/reviews"><Button>复习计划</Button></Link><Link to="/history"><Button>历史学习记录</Button></Link><Link to="/goals"><Button>学习目标（可选）</Button></Link></Space></section>
  </>;
}

export function AssignmentWork({practice=false}:{practice?:boolean}){
  const {groupId}=useParams();
  return <GroupWork key={groupId} groupId={groupId!} practice={practice}/>;
}

function GroupWork({groupId,practice}:{groupId:string;practice:boolean}){
  const path=practice?'/practice-groups/'+groupId:'/assignments/'+groupId;
  const query=useQuery({queryKey:['assignment-work',groupId,practice],queryFn:()=>api<Group>(path+(practice?'/open':'/start'),'POST'),refetchOnWindowFocus:false,refetchInterval:q=>q.state.data?.state==='submitted'&&q.state.data.entries.some(e=>e.attempt.grading_state==='AI初评中')?3000:false});
  const [current,setCurrent]=useState(0);
  const saveCurrent=useRef<(()=>Promise<unknown>)|null>(null);
  const {run,busy}=useRun();
  const group=query.data;
  async function changeQuestion(index:number){await run(async()=>{if(group?.state==='draft')await saveCurrent.current?.();saveCurrent.current=null;setCurrent(index);});}
  async function submit(){await run(async()=>{await saveCurrent.current?.();const result=await api<Group>(path+'/submit','POST',{},key());await query.refetch();return result;},'整组答案已提交，客观题由系统判分，分析题进入AI初评');}
  return <><PageTitle title={group?.title??'读取题组'} description={practice?'针对原错题生成的个人练习，完成后统一提交。':'逐题填写与自动保存，整组提交后统一判分。'} action={<Link to={practice?'/mistakes':'/'}><Button>返回{practice?'错题诊断':'作业列表'}</Button></Link>}/><State query={query}>{group&&<>
    <section className="panel group-toolbar"><Space wrap><Tag color={group.state==='submitted'?'green':'default'}>{group.state==='submitted'?'整组已提交':'作答中'}</Tag><span>共 {group.entries.length} 题</span>{group.due_at&&<span>截止 {date(group.due_at)}</span>}</Space>
      <div className="question-navigation">{group.entries.map((e,i)=><Button key={e.task.id} type={i===current?'primary':'default'} loading={busy&&i!==current} onClick={()=>changeQuestion(i)} aria-label={`切换第${i+1}题`}>{i+1}. {kindName(e.attempt.question.kind)}{e.attempt.status==='draft'?(e.attempt.answer.length||e.attempt.response_text?' · 已存草稿':''):' · '+e.attempt.grading_state}</Button>)}</div>
      {group.state==='draft'?<Button type="primary" loading={busy} onClick={submit}>提交整组{practice?'练习':'作业'}</Button>:<Space wrap><Link to="/mistakes"><Button type="primary">查看错题并手动诊断</Button></Link><span className="muted">AI建议分不计入正式成绩，分析题等待教师确认。</span></Space>}
    </section>
    {group.entries[current]&&<StudyTask key={group.entries[current].task.id} taskId={group.entries[current].task.id} registerSave={fn=>{saveCurrent.current=fn;}}/>}
  </>}</State></>;
}

type Mistake={id:string;attempt_id:string;task_id:string;prompt:string;kind:string;options:Record<string,string>;selected:string[];correct_answer:string[];wrong_options:string[];missing_options:string[];response_text:string;process:string;hint_level:number;explanation:string;group_url:string|null;resolved:boolean;sources:Evidence[];cards:{id:string;title:string;body:string;source_version_id:string}[];diagnosis:AgentRun|null;practices:AgentRun[];practice_results:{id:string;state:string;total:number;independent_correct:number}[]};

export function MistakeDiagnoses(){
  const [search]=useSearchParams();
  const attempt=search.get('attempt');
  const query=useQuery({queryKey:['mistake-diagnoses'],queryFn:()=>api<Mistake[]>('/mistake-diagnoses'),refetchInterval:q=>q.state.data?.some(m=>(m.diagnosis&&pendingAgent(m.diagnosis))||m.practices.some(pendingAgent))?2000:false});
  const {run,busy}=useRun();
  const items=query.data?.filter(m=>!attempt||m.attempt_id===attempt);
  return <><PageTitle title="错题诊断" description="回看自己选了什么，再由 Agent 分析错选、漏选和知识缺口。诊断与针对性出题均由你手动发起。" action={attempt?<Link to="/mistakes"><Button>查看全部错题</Button></Link>:undefined}/><State query={query}>
    {!items?.length?<Blank description="暂无可诊断错题。完成教师作业后，客观错题或教师确认后的分析题错题会出现在这里。"/>:<div className="remediation-list">{items.map(m=><section className="panel mistake-card" key={m.id}>
      <Space wrap><Tag>{kindName(m.kind)}</Tag><Tag color={m.resolved?'green':'gold'}>{m.resolved?'已有独立巩固证据':'需要巩固'}</Tag><Link to={'/study/'+m.task_id}>直接查看原始作答</Link>{m.group_url&&<Link to={m.group_url}>查看对应作业</Link>}</Space><h2>{m.prompt}</h2>
      {!!Object.keys(m.options).length&&<div className="mistake-options">{Object.entries(m.options).map(([label,text])=><div key={label} className={m.wrong_options.includes(label)?'option-wrong':m.missing_options.includes(label)?'option-missing':m.correct_answer.includes(label)?'option-correct':''}><strong>{label}. </strong>{text}<Space wrap>{m.selected.includes(label)&&<Tag color={m.wrong_options.includes(label)?'red':'blue'}>你的选择</Tag>}{m.correct_answer.includes(label)&&<Tag color="green">正确选项</Tag>}{m.missing_options.includes(label)&&<Tag color="orange">漏选</Tag>}</Space></div>)}</div>}
      <p><strong>你的答案：</strong>{m.kind==='essay'?m.response_text:m.selected.join('、')||'未选'}</p>{m.kind!=='essay'&&<p><strong>正确答案：</strong>{m.correct_answer.join('、')}　{m.wrong_options.length>0&&`错选：${m.wrong_options.join('、')}　`}{m.missing_options.length>0&&`漏选：${m.missing_options.join('、')}`}</p>}
      <p className="preserve-text"><strong>原始思考过程：</strong>{m.process||'未填写；仅凭选项不能确定心理错因。'}</p><p className="muted">已使用 {m.hint_level} 级学习帮助。</p>
      <Collapse items={[{key:'explanation',label:'查看原题解析与原文依据',children:<><p>{m.explanation}</p><Sources items={m.sources}/></>},{key:'cards',label:`相关知识卡（${m.cards.length}）`,children:m.cards.map(c=><article key={c.id}><h3>{c.title}</h3><p>{c.body}</p><Link to={'/sources/'+c.source_version_id}>核对知识卡原文</Link></article>)}]}/>
      <Space wrap className="section-space"><Button type="primary" loading={busy} disabled={!!m.diagnosis&&pendingAgent(m.diagnosis)} onClick={()=>run(()=>api('/remediations/'+m.id+'/diagnose','POST',{},key()),'已提交AI错题诊断')}>{m.diagnosis?'查看 / 恢复AI诊断':'AI诊断'}</Button>
        <Button loading={busy} disabled={m.diagnosis?.state!=='succeeded'||m.practices.some(pendingAgent)} onClick={()=>run(()=>api('/remediations/'+m.id+'/practice-generations','POST',{},key()),'已提交针对性出题任务')}>生成针对性练习</Button></Space>
      {!m.diagnosis&&<p className="muted">点击“AI诊断”后才会调用模型，不需要先手工选择错因。</p>}
      {m.diagnosis&&<AgentResult item={m.diagnosis}/>} {m.practices.map(p=><AgentResult key={p.id} item={p}/>)}
      {m.practice_results.map(p=><p key={p.id}>针对性练习：{p.state==='submitted'?'已提交':'作答中'}，{p.independent_correct} / {p.total} 题已有独立正确证据。<Link to={'/practice/'+p.id}>对比练习结果</Link></p>)}
    </section>)}</div>}
  </State></>;
}

export function TeacherAssignments(){
  const query=useQuery({queryKey:['teacher-assignments'],queryFn:()=>api<Assignment[]>('/teacher/assignments')});
  const bank=useQuery({queryKey:['question-bank'],queryFn:()=>api<BankQuestion[]>('/teaching/questions')});
  const classes=useQuery({queryKey:['classes'],queryFn:()=>api<{id:string;name:string}[]>('/classes')});
  const [open,setOpen]=useState(false);
  const [selected,setSelected]=useState<React.Key[]>([]);
  const [filter,setFilter]=useState<string>();
  const [editor,setEditor]=useState<BankQuestion|null>(null);
  const [form]=Form.useForm();
  const {run,busy}=useRun();
  const navigate=useNavigate();
  async function publish(values:{title:string;class_id:string;due_at?:string}){
    const result=await run(()=>api('/teacher/assignments','POST',{title:values.title,class_id:values.class_id,question_ids:selected,due_at:values.due_at?new Date(values.due_at).toISOString():null},key()),'作业已发布给班级');
    if(result){setOpen(false);setSelected([]);}
  }
  const sourceOptions=Array.from(new Map((bank.data??[]).map(q=>[q.source_version_id,{value:q.source_version_id,label:q.source_title}])).values());
  return <><PageTitle title="作业与批阅" description="从原文生成的可用题库选题，发布给班级，再确认分析题的 AI 初评。" action={<Link to="/content"><Button>上传资料与生成题目</Button></Link>}/>
    <section className="panel"><div className="section-heading"><div><h2>已发布作业</h2><p>客观题显示系统判分；分析题初评需要教师确认。</p></div><Link to="/teacher"><Button type="primary">查看学生作答与确认评分</Button></Link></div><State query={query}><Table rowKey="id" dataSource={query.data??[]} scroll={{x:650}} columns={[{title:'作业',dataIndex:'title'},{title:'班级',dataIndex:'class_name'},{title:'题数',dataIndex:'questions'},{title:'已提交人数',dataIndex:'submitted'},{title:'截止时间',dataIndex:'due_at',render:v=>v?date(v):'未设置'},{title:'操作',render:(_,a)=><Button onClick={()=>navigate('/teacher?assignment='+a.id)}>查看作答 / 批阅</Button>}]}/></State></section>
    <section className="panel section-space"><div className="section-heading"><div><h2>Agent 生成题库</h2><p>只展示真实生成并通过校验的题目，原演示题不混入。勾选后发布作业。</p></div><Button type="primary" disabled={!selected.length} onClick={()=>{form.resetFields();setOpen(true);}}>布置所选题目（{selected.length}）</Button></div>
      <Select allowClear placeholder="按资料筛选" aria-label="题库资料筛选" value={filter} onChange={setFilter} style={{width:'100%',maxWidth:440,marginBottom:16}} options={sourceOptions}/>
      <State query={bank}><Table rowKey="id" scroll={{x:850}} dataSource={(bank.data??[]).filter(q=>!filter||q.source_version_id===filter)} rowSelection={{selectedRowKeys:selected,onChange:setSelected,preserveSelectedRowKeys:true}} pagination={{pageSize:8}} columns={[{title:'题目',dataIndex:'prompt'},{title:'题型',dataIndex:'kind',render:kindName},{title:'资料 / 知识点',render:(_,q)=><>{q.source_title}<br/>{q.knowledge}</>},{title:'满分',dataIndex:'max_score'},{title:'操作',render:(_,q)=><Space wrap><Button onClick={()=>setEditor(q)}>编辑题目</Button><Button onClick={()=>run(()=>api('/teaching/questions/'+q.id+'/disable','POST'),'已停用；既有作业保留原题版本')}>停用</Button></Space>}]} expandable={{expandedRowRender:q=><><p>答案：{q.answer.join('、')||'按评分要点评价'}</p><p>{q.explanation}</p>{Object.entries(q.option_analysis).map(([label,text])=><p key={label}>{label}：{text}</p>)}<Sources items={q.sources}/></>}}/></State>
    </section>
    <Modal title="发布班级作业" open={open} onCancel={()=>setOpen(false)} footer={null}><p>已选 {selected.length} 题。发布后固定题目与来源版本。</p><Form form={form} layout="vertical" onFinish={publish}><Form.Item name="title" label="作业名称" rules={[{required:true,whitespace:true}]}><Input maxLength={200}/></Form.Item><Form.Item name="class_id" label="班级" rules={[{required:true}]}><Select options={classes.data?.map(c=>({label:c.name,value:c.id}))}/></Form.Item><Form.Item name="due_at" label="截止时间（可选）"><Input type="datetime-local"/></Form.Item><Button type="primary" htmlType="submit" loading={busy}>发布作业</Button></Form></Modal>
    {editor&&<QuestionEditor versionId={editor.source_version_id} question={{...editor,question_id:editor.id,status:'published'}} agentEdit close={()=>setEditor(null)}/>}
  </>;
}
