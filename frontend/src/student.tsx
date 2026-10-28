import { AILearning } from './extensions';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, App, Button, Card, Checkbox, Collapse, Form, Input, InputNumber, Modal, Progress, Radio, Select, Space, Statistic, Table, Tag } from 'antd';
import { ArrowRightOutlined, CheckCircleOutlined, ClockCircleOutlined, FileTextOutlined, FlagOutlined, ReadOutlined } from '@ant-design/icons';
import { api, key, kindName, ApiError, type Attempt, type Catalog, type Contracts, type DraftInput, type Evaluation, type GoalInput, type Task } from './api';
import { useUser } from './App';
import { Blank, PageTitle, Sources, State, Status, date, useRun } from './ui';

type Plan = Contracts['PlanOutput'];
type Diag = Contracts['DiagnosticOutput'];
type Review = Contracts['ReviewScheduleOutput'];
type HistoryItem = Contracts['HistoryOutput'];
type Remediation = Contracts['RemediationOutput'];
const causes = ['概念混淆','原理适用','材料理解','论证表达','审题','时间管理'];

function TaskList({tasks}:{tasks:Task[]}) {
  return <div className="task-list">{tasks.map((task,i)=><div className="task-row" key={task.id}><div className="task-number">{String(i+1).padStart(2,'0')}</div><div className="task-copy"><div className="task-labels"><span>{task.module}</span><Tag>{kindName(task.kind)}</Tag><Status value={task.state}/></div><h3>{task.knowledge}</h3><p>{task.reason}</p></div><div className="task-action"><span><ClockCircleOutlined aria-hidden/> {task.minutes} 分钟</span><Link to={'/study/'+task.id}><Button type={task.state==='todo'?'primary':'default'}>{task.state==='todo'?'开始学习':'查看记录'} <ArrowRightOutlined aria-hidden/></Button></Link></div></div>)}</div>;
}

export function Home() {
  const user=useUser();
  const plan=useQuery({queryKey:['plan'],queryFn:()=>api<Plan>('/plans/today')});
  const goal=useQuery({queryKey:['goal'],queryFn:()=>api<GoalInput|null>('/goals/current')});
  const diag=useQuery({queryKey:['diagnostic'],queryFn:()=>api<Diag|null>('/diagnostics/current')});
  const reviews=useQuery({queryKey:['reviews'],queryFn:()=>api<Review[]>('/review-schedules')});
  const completed=plan.data?.all_tasks.filter(t=>t.state==='completed').length??0;
  const total=plan.data?.all_tasks.length??0;
  const todayIds=new Set(plan.data?.tasks.map(t=>t.id)??[]);
  const optionalTasks=plan.data?.all_tasks.filter(t=>t.state==='todo'&&!todayIds.has(t.id))??[];
  return <><PageTitle title={`${user.name}，今天也向前一步`} description="把时间留给思考，把每一次练习变成看得见的进步。"/>
    <div className="welcome-banner"><div><div className="banner-label">我的学习计划</div><h2>{goal.data?'按自己的节奏，稳步积累。':'先找到起点，再规划下一步。'}</h2><p>{goal.data?`每日 ${goal.data.daily_minutes} 分钟 · ${goal.data.exam_year} 年目标 · 目标 ${goal.data.target_score} 分`:'设置一个清晰的目标，完成基础诊断，我们将据此安排你的学习任务。'}</p><Link to={goal.data?'/diagnostic':'/goals'}><Button size="large">{goal.data?(diag.data?.status==='completed'?'查看诊断结果':'进行基础诊断'):'设置学习目标'} <ArrowRightOutlined aria-hidden/></Button></Link></div><div className="banner-symbol"><ReadOutlined aria-hidden/><span>知 · 行 · 进</span></div></div>
    <div className="stat-grid"><Card><Statistic title="练习任务完成" value={completed} suffix={<small>/ {total}</small>} prefix={<CheckCircleOutlined aria-hidden/>}/><p>按已保存的学习任务统计</p></Card><Card><Statistic title="到期复习" value={reviews.data?.filter(r=>r.state==='scheduled'&&r.due).length??0} suffix="项" prefix={<ClockCircleOutlined aria-hidden/>}/><p>按第 1、3、7 天逐步巩固</p></Card><Card><Statistic title="待教师评价" value={plan.data?.all_tasks.filter(t=>t.state==='pending_teacher').length??0} suffix="项" prefix={<FileTextOutlined aria-hidden/>}/><p>分析题由教师审核评分</p></Card></div>
    <div className="dashboard-grid"><section className="panel"><div className="section-heading"><div><h2>今日学习任务</h2><p>根据目标与诊断安排，优先处理复习和补学。</p></div><Link to="/history">学习记录 <ArrowRightOutlined aria-hidden/></Link></div><State query={plan}>{plan.data?.tasks.length?<TaskList tasks={plan.data.tasks}/>:<Blank description={total?'今日安排已完成，或剩余时间不足。可展开下方其余任务继续学习。':'今天还没有待学习任务'}>{total?<Link to="/reviews"><Button>查看复习计划</Button></Link>:<Link to={goal.data?'/diagnostic':'/goals'}><Button>{goal.data?'开始基础诊断':'设置目标'}</Button></Link>}</Blank>}</State></section>
    <aside className="panel learning-guide"><div className="guide-icon"><FlagOutlined aria-hidden/></div><h2>学习，需要一次真正的理解</h2><p>答错后先确认问题，再阅读有出处的知识卡。完成一道新题，验证是否能独立运用。</p><ol><li>保留自己的思考过程</li><li>提示逐级使用，留下记录</li><li>补学后再独立完成新题</li></ol><Link to="/mistakes"><Button block>查看错题与补学</Button></Link><div className="notice-note">当前课程为原创演示内容。正式学习范围与教学结论需教师核对。</div></aside></div>
    {!!optionalTasks.length&&<section className="section-space"><Collapse items={[{key:'optional',label:`其他可选学习任务（${optionalTasks.length} 项）`,children:<><p className="muted">今日安排按时间预算展示；你也可以根据精力选择其他已审核任务。</p><TaskList tasks={optionalTasks}/></>}]}/></section>}
    {total>0&&<section className="panel section-space"><div className="section-heading"><h2>任务进度</h2><span>{completed} / {total} 项已完成</span></div><Progress percent={Math.round(completed/total*100)} strokeColor="#477a62"/></section>}
  </>;
}

export function Goals() {
  const [form]=Form.useForm();
  const {run,busy}=useRun();
  const navigate=useNavigate();
  const catalog=useQuery({queryKey:['catalog'],queryFn:()=>api<Catalog>('/catalog')});
  const goal=useQuery({queryKey:['goal'],queryFn:()=>api<GoalInput|null>('/goals/current')});
  useEffect(()=>{if (catalog.data) form.setFieldsValue(goal.data??{subject_id:catalog.data.subjects[0]?.id,exam_year:2027,target_score:75,daily_minutes:30})},[goal.data,catalog.data,form]);
  return <><PageTitle title="目标与安排" description="目标用于安排学习节奏，随时可以根据自己的情况调整。"/><div className="form-columns"><Card title="我的学习目标"><State query={catalog}><Form form={form} layout="vertical" onFinish={async values=>{if(await run(()=>api('/goals/current','PUT',values),'学习目标已保存'))navigate('/diagnostic')}} requiredMark={false}>
    <Form.Item name="subject_id" label="学习科目" rules={[{required:true}]}><Select options={catalog.data?.subjects.map(s=>({value:s.id,label:s.name}))}/></Form.Item>
    <Form.Item name="exam_year" label="考试年份" rules={[{required:true}]}><InputNumber min={2026} max={2100} style={{width:'100%'}}/></Form.Item>
    <Form.Item name="target_score" label="目标分数" rules={[{required:true}]}><InputNumber min={1} max={100} style={{width:'100%'}}/></Form.Item>
    <Form.Item name="daily_minutes" label="每日学习时间（分钟）" rules={[{required:true}]}><InputNumber min={5} max={480} style={{width:'100%'}}/></Form.Item>
    <Button type="primary" htmlType="submit" loading={busy}>保存并前往诊断 <ArrowRightOutlined aria-hidden/></Button>
  </Form></State></Card><div className="panel guide-block"><h2>计划如何生成？</h2><p>先通过代表性题目了解当前表现，再安排基础练习和材料分析。复习与补学会优先进入今日任务。</p><p>少量诊断只能提供有限线索，未覆盖的知识点保持“待诊断”，不会据此生成全科预测分数。</p><Alert type="info" showIcon message="建议先安排能持续完成的时间" description="一个可坚持的小计划，比过量的任务更容易形成稳定节奏。"/></div></div></>;
}

export function Diagnostic() {
  const {run,busy}=useRun();
  const [startError,setStartError]=useState<{message:string;contentRequired:boolean}|null>(null);
  const catalog=useQuery({queryKey:['catalog'],queryFn:()=>api<Catalog>('/catalog')});
  const diag=useQuery({queryKey:['diagnostic'],queryFn:()=>api<Diag|null>('/diagnostics/current')});
  const goal=useQuery({queryKey:['goal'],queryFn:()=>api<GoalInput|null>('/goals/current')});
  const d=diag.data;
  const done=d?.tasks.filter(t=>t.state==='completed').length??0;
  async function startDiagnostic(){
    setStartError(null);
    await run(async()=>{
      try{return await api('/diagnostics','POST',{subject_id:goal.data?.subject_id})}
      catch(error){setStartError({message:error instanceof Error?error.message:'开始诊断失败，请稍后重试。',contentRequired:error instanceof ApiError&&error.code==='CONTENT_REQUIRED'});throw error}
    },'诊断已开始');
  }
  return <><PageTitle title="基础诊断" description="用独立作答找到学习起点。诊断期间不提供提示、答案或资料检索。"/><Alert className="section-space" type="info" showIcon message="诊断只覆盖少量示例知识点" description="结果用于生成学习任务，不等同于全科掌握度或考试预测。未覆盖内容保持待诊断。"/><State query={diag}>
    {!d?<Card>{startError&&<Alert className="section-space" type="warning" showIcon message="暂时无法开始诊断" description={<><p>{startError.message}</p>{startError.contentRequired&&<p>请教师在“教学内容”中打开待审核资料，点击“审核确认并发布”。仅“提交审核”还未完成发布；正式发布后，可返回这里重新开始诊断。</p>}</>}/>}<Blank description="先完成目标设置，再开始六个模块的代表题诊断。">{!goal.data?<Link to="/goals"><Button type="primary">设置目标</Button></Link>:<Button type="primary" loading={busy} disabled={!catalog.data?.subjects.length} onClick={startDiagnostic}>开始基础诊断</Button>}</Blank></Card>:<>
    <div className="panel section-space"><div className="section-heading"><h2>{d.status==='completed'?'诊断已完成':'诊断进行中'}</h2><Tag color="green">{done} / {d.tasks.length} 题已提交</Tag></div><Progress percent={Math.round(done/d.tasks.length*100)}/></div>
    <div className="panel"><TaskList tasks={d.tasks}/></div>
    <div className="page-actions">{d.status==='active'?<Button type="primary" size="large" loading={busy} disabled={done!==d.tasks.length} onClick={()=>run(()=>api('/diagnostics/'+d.id+'/submit','POST'),'诊断已完成，学习任务已生成')}>结束诊断并生成学习安排</Button>:<Link to="/"><Button type="primary">查看学习任务 <ArrowRightOutlined aria-hidden/></Button></Link>}</div></>}
  </State></>;
}

export function Study() {
  const {taskId}=useParams();
  return <StudyTask key={taskId} taskId={taskId!}/>;
}

function StudyTask({taskId}:{taskId:string}) {
  const query=useQuery({queryKey:['study',taskId],queryFn:()=>api<Attempt>('/tasks/'+taskId+'/attempts','POST'),refetchOnWindowFocus:false,staleTime:Infinity});
  return <State query={query}>{query.data&&<AttemptEditor initial={query.data} onReload={()=>query.refetch()}/>}</State>;
}

function AttemptEditor({initial,onReload}:{initial:Attempt;onReload:()=>unknown}) {
  const [attempt,setAttempt]=useState(initial);
  const [answer,setAnswer]=useState(initial.answer);
  const [text,setText]=useState(initial.response_text);
  const [process,setProcess]=useState(initial.process);
  const [saveState,setSaveState]=useState('已读取保存记录');
  const [hint,setHint]=useState<{text:string;level:number}|null>(null);
  const [dirty,setDirty]=useState(false);
  const [appeal,setAppeal]=useState(false);
  const [appealText,setAppealText]=useState('');
  const saving=useRef<Promise<Attempt>|null>(null);
  const snapshot=useRef({answer,text,process});
  const savedContent=useRef({answer:initial.answer,response_text:initial.response_text,process:initial.process});
  const latestAttempt=useRef(initial);
  const [draftConflict,setDraftConflict]=useState(false);
  const started=useRef(Date.now());
  const baseDuration=useRef(initial.duration_seconds);
  const {run,busy}=useRun();
  const contentOf=(a:Attempt)=>({answer:a.answer,response_text:a.response_text,process:a.process});
  const matches=(a:unknown,b:unknown)=>JSON.stringify(a)===JSON.stringify(b);
  const acceptAttempt=useCallback((value:Attempt)=>{
    if(value.revision>=latestAttempt.current.revision){latestAttempt.current=value;setAttempt(value)}
  },[]);
  useEffect(()=>{acceptAttempt(initial)},[initial,acceptAttempt]);
  snapshot.current={answer,text,process};
  const save=useCallback(async function saveLatest():Promise<Attempt>{
    if(saving.current){
      const saved=await saving.current;
      const current=snapshot.current;
      return matches(contentOf(saved),{answer:current.answer,response_text:current.text,process:current.process})?saved:saveLatest();
    }
    const local=snapshot.current;
    const draft={answer:local.answer,response_text:local.text,process:local.process};
    setSaveState('正在保存…');
    const operation=(async()=>{
      for(let retry=0;retry<2;retry++){
        const current=await api<Attempt>('/attempts/'+initial.id);
        if(current.status!=='draft'){
          acceptAttempt(current);setDraftConflict(true);
          throw new Error('作答已在其他页面提交，当前输入未写入。请读取服务器记录。');
        }
        // A new revision may only record a hint/AI event. Rebase only when
        // the answer is unchanged, or the server already has this exact draft.
        if(!matches(contentOf(current),savedContent.current)&&!matches(contentOf(current),draft)){
          setDraftConflict(true);
          throw new Error('其他页面修改了此草稿，当前输入已保留，未覆盖服务器内容。');
        }
        try{
          const saved=await api<Attempt>('/attempts/'+initial.id+'/draft','PATCH',{
            ...draft,duration_seconds:Math.min(86400,baseDuration.current+Math.floor((Date.now()-started.current)/1000)),revision:current.revision,
          } satisfies DraftInput);
          savedContent.current=contentOf(saved);acceptAttempt(saved);setDraftConflict(false);
          const now=snapshot.current;
          if(matches(draft,{answer:now.answer,response_text:now.text,process:now.process}))setDirty(false);
          setSaveState('已保存到服务器');return saved;
        }catch(error){
          if(error instanceof ApiError&&error.code==='STALE_REVISION'&&retry===0)continue;
          throw error;
        }
      }
      throw new Error('草稿正在更新，请稍后重试。');
    })();
    saving.current=operation;
    let saved:Attempt;
    try{saved=await operation}catch(error){setSaveState('保存失败，当前输入尚未同步');throw error}
    finally{if(saving.current===operation)saving.current=null}
    const now=snapshot.current;
    if(!matches(contentOf(saved),{answer:now.answer,response_text:now.text,process:now.process}))return saveLatest();
    return saved;
  },[initial.id,acceptAttempt]);
  useEffect(()=>{
    if(!dirty||attempt.status!=='draft'||busy||draftConflict)return;
    const timer=setTimeout(()=>{save().catch(()=>{})},1000);
    return()=>clearTimeout(timer);
  },[answer,text,process,dirty,attempt.status,save,busy,draftConflict]);
  async function loadServerDraft(){
    await run(async()=>{
      const current=await api<Attempt>('/attempts/'+initial.id);
      savedContent.current=contentOf(current);acceptAttempt(current);
      setAnswer(current.answer);setText(current.response_text);setProcess(current.process);
      setDirty(false);setDraftConflict(false);setSaveState('已读取服务器最新记录');return current;
    });
  }
  useEffect(()=>{
    const warn=(e:BeforeUnloadEvent)=>{if(dirty){e.preventDefault();e.returnValue=''}};
    window.addEventListener('beforeunload',warn);
    return()=>window.removeEventListener('beforeunload',warn);
  },[dirty]);
  const q=attempt.question;
  const editable=attempt.status==='draft';
  async function submit(){
    await run(async()=>{
      await save();
      const submitted=await api<Attempt>('/attempts/'+attempt.id+'/submit','POST',undefined,key());
      setDirty(false);acceptAttempt(submitted);await onReload();return submitted;
    },'作答已提交并保存');
  }
  return <><PageTitle title={attempt.mode==='diagnostic'?'独立完成诊断':attempt.mode==='review'?'到期复习':attempt.mode==='verification'?'补学后的新题验证':'专注完成这道题'} description={attempt.reason} action={<Link to={attempt.mode==='diagnostic'?'/diagnostic':'/'}><Button>返回任务</Button></Link>}/>
    {draftConflict&&<Alert className="section-space" type="warning" showIcon message="草稿存在其他页面的修改" description="当前输入仍保留在本页，系统没有覆盖服务器内容。确认需要采用服务器记录后，再点击读取。" action={<Button onClick={loadServerDraft} loading={busy}>读取服务器草稿</Button>}/>}
    <div className="study-layout"><section className="panel question-panel"><div className="question-meta"><Tag color="green">{kindName(q.kind)}</Tag><span>{q.max_score} 分</span><span>题目版本 {q.number}</span><Status value={attempt.status}/></div><h2 className="question-prompt">{q.prompt}</h2>
      {q.kind==='multiple'&&<p className="muted">多选题全部选对得分，多选、漏选、错选均不得分。</p>}
      {q.kind==='single'?<Radio.Group className="answer-options" value={answer[0]} disabled={!editable||busy} onChange={e=>{setAnswer([e.target.value]);setDirty(true)}}>{Object.entries(q.options).map(([label,value])=><Radio key={label} value={label}><span className="option-label">{label}</span>{value}</Radio>)}</Radio.Group>:q.kind==='multiple'?<div className="answer-options" role="group" aria-label="多选答案">{Object.entries(q.options).map(([label,value])=><Checkbox key={label} value={label} checked={answer.includes(label)} disabled={!editable||busy} onChange={e=>{const checked=e.target.checked;setAnswer(previous=>checked?[...previous.filter(v=>v!==label),label]:previous.filter(v=>v!==label));setDirty(true)}}><span className="option-label">{label}</span>{value}</Checkbox>)}</div>:<div className="essay-answer"><label>你的材料分析</label><Input.TextArea aria-label="你的材料分析" value={text} onChange={e=>{setText(e.target.value);setDirty(true)}} disabled={!editable||busy} rows={9} maxLength={20000} showCount placeholder="结合原理与材料，写下你的分析…"/></div>}
      <div className="process-area"><label>思考过程 <span>帮助你回看思路，也帮助教师理解你的判断</span></label><Input.TextArea aria-label="思考过程" value={process} onChange={e=>{setProcess(e.target.value);setDirty(true)}} rows={4} maxLength={10000} disabled={!editable||busy} placeholder="为什么这样选择？哪些地方还不确定？"/></div>
      {editable?<div className="answer-footer"><span className={saveState.startsWith('保存失败')?'save-error':'muted'}>{saveState}</span><Space><Button aria-label="保存草稿" loading={busy} onClick={()=>run(save)}>保存草稿</Button><Button aria-label="提交作答" type="primary" loading={busy} onClick={submit}>提交作答</Button></Space></div>:<Alert type={attempt.status==='pending_teacher'?'info':'success'} showIcon message={attempt.status==='pending_teacher'?'分析题已提交，等待教师评分':'作答记录已保存'} description={attempt.mode==='diagnostic'&&!attempt.evaluation?'结束全部诊断后统一查看结果。':'原始答案与提示使用情况已记录，提交后不再覆盖。'}/>}
      {attempt.evaluation&&<div className="evaluation-box"><div className="section-heading"><h2>本次评价</h2><strong className="score">{attempt.evaluation.score}<small> / {q.max_score}</small></strong></div><p>{attempt.evaluation.feedback}</p><Tag>{attempt.evaluation.method==='teacher'?'教师评价':'规则评分'} · 第 {attempt.evaluation.revision} 次评价</Tag><Button type="link" onClick={()=>setAppeal(true)}>对评价有异议？</Button></div>}
      {q.explanation&&<div className="analysis-box"><h3>审核解析</h3><p>{q.explanation}</p>{q.answer&&q.answer.length>0&&<p>正确选项：<strong>{q.answer.join('、')}</strong></p>}</div>}
      {attempt.remediation_id&&<div className="page-actions"><Link to="/mistakes"><Button type="primary" icon={<ReadOutlined aria-hidden/>}>确认错因并开始补学</Button></Link></div>}
    </section><aside className="study-aside"><Card title={attempt.mode==='diagnostic'?'诊断规则':'循序获得帮助'}>
      {attempt.mode==='diagnostic'?<p className="muted">请独立完成。诊断期间不提供提示、解析和资料检索。</p>:<><p className="muted">先独立思考，再逐级使用提示。使用情况将计入学习记录。</p><div className="hint-levels">{['相关概念','突破口','分步引导','完整解析'].map((label,i)=><Button key={label} block disabled={!editable||i>attempt.hint_level} loading={busy} onClick={()=>run(async()=>{await save();const result=await api<{text:string;level:number;revision:number}>('/attempts/'+attempt.id+'/hints','POST',{level:i+1});setHint(result);const current=await api<Attempt>('/attempts/'+attempt.id);acceptAttempt(current);return result})}>{i+1}. {label}{i<attempt.hint_level?' · 已查看':''}</Button>)}</div>{hint&&<div className="hint-content"><Tag>审核教学内容</Tag><p>{hint.text}</p></div>}<p className="small-note">已使用 {attempt.hint_level} 级提示。有提示的正确作答与独立完成分别记录。</p></>}
    </Card>{attempt.mode!=='diagnostic'&&<AILearning attemptId={attempt.id} draft={editable} essay={q.kind==='essay'} hintLevel={attempt.hint_level} beforeRun={async()=>{if(editable)await save()}} afterRun={onReload}/>}</aside></div>
    {attempt.sources&&<section className="panel section-space"><h2>资料依据</h2><Sources items={attempt.sources}/></section>}
    <Modal title="提出评价异议" okText="提交异议" open={appeal} onCancel={()=>setAppeal(false)} confirmLoading={busy} onOk={()=>run(async()=>{if(!appealText.trim())throw new Error('请填写异议说明');const result=await api('/evaluations/'+attempt.evaluation?.id+'/review-cases','POST',{reason:appealText});setAppeal(false);return result},'已提交教师复核')}><p>请说明你认为需要重新核对的部分，教师会保留原评价并给出复核意见。</p><Input.TextArea aria-label="异议说明" rows={4} value={appealText} onChange={e=>setAppealText(e.target.value)} maxLength={5000}/></Modal>
  </>;
}

export function Mistakes() {
  const query=useQuery({queryKey:['remediations'],queryFn:()=>api<Remediation[]>('/remediations')});
  const {run,busy}=useRun();
  const navigate=useNavigate();
  return <><PageTitle title="错题与补学" description="确认错因，回到有依据的知识，再用一道新题验证。"/><State query={query}>{!query.data?.length?<Blank description="还没有需要补学的记录。完成诊断或练习后，这里会保留相关线索。"/>:<div className="remediation-list">{query.data.map(r=><Card key={r.id} title={<span className="wrap-title">{r.prompt}</span>} extra={<Tag color={r.resolved?'green':'gold'}>{r.resolved?'已有独立正确证据':'需要补学'}</Tag>}>
    <div className="remediation-layout"><div><h3>1. 确认本次错因</h3><p className="muted">这里保留的是候选判断，你可以根据真实作答更正。</p><p>候选错因：{r.cause}</p><Select aria-label="确认错因" value={r.cause_status==='confirmed'?r.cause:undefined} placeholder="选择最符合实际的原因" style={{width:'100%',maxWidth:320}} options={causes.map(c=>({value:c,label:c}))} disabled={busy} onChange={cause=>run(()=>api('/remediations/'+r.id+'/cause','POST',{cause}),'错因已确认')}/><div className="page-actions"><Link to="/history">回看原始作答 <ArrowRightOutlined aria-hidden/></Link></div></div><div><h3>2. 阅读补学知识卡</h3>{r.card?<><div className="knowledge-card"><div className="eyebrow">知识卡 · 原创演示内容</div><h3>{r.card.title}</h3><p>{r.card.body}</p><Link to={'/sources/'+r.card.source_version_id}>查看原文出处 <ArrowRightOutlined aria-hidden/></Link></div><Space wrap><Button loading={busy} disabled={r.cause_status!=='confirmed'} onClick={()=>run(async()=>{const result=await api<{task_id:string|null;message:string}>('/remediations/'+r.id+'/read','POST');return result},'阅读记录已保存')}>{r.read?'已阅读，检查验证题':'我已阅读并理解'}</Button>{r.verification_task_id&&<Button type="primary" onClick={()=>navigate('/study/'+r.verification_task_id)}>3. 开始新题验证</Button>}</Space>{r.read&&!r.verification_task_id&&<Alert type="info" className="section-space" message="待补充验证题：审核题库中暂时没有尚未使用的新题。"/>}</>:<Alert type="info" message="暂无对应审核知识卡，请教师补充。"/>}</div></div>
  </Card>)}</div>}</State></>;
}

export function Reviews() {
  const query=useQuery({queryKey:['reviews'],queryFn:()=>api<Review[]>('/review-schedules')});
  const {run,busy}=useRun();
  const navigate=useNavigate();
  return <><PageTitle title="复习计划" description="独立验证后，按第 1、3、7 天逐步巩固。到期前不提前计为完成。"/><State query={query}>
    {!query.data?.length?<Blank description="完成独立验证后，复习安排将出现在这里。"/>:<Table rowKey="id" dataSource={query.data} scroll={{x:700}} pagination={{pageSize:10}} columns={[
      {title:'知识点',dataIndex:'knowledge'},{title:'阶段',dataIndex:'stage',render:v=>`第 ${v} 阶段`},{title:'安排时间',dataIndex:'due_at',render:date},{title:'状态',render:(_,r)=><><Status value={r.state}/>{r.due&&r.state==='scheduled'&&<Tag color="orange">已到期</Tag>}</>},
      {title:'操作',render:(_,r)=><Button disabled={!r.task_id&&(!r.due||r.state!=='scheduled')} loading={busy} onClick={()=>run(async()=>{const result=await api<{task_id:string}>('/review-schedules/'+r.id+'/attempts','POST');navigate('/study/'+result.task_id);return result})}>{r.task_id?'查看复习':'开始复习'}</Button>},
    ]}/>}
  </State><Alert type="info" showIcon message="旧题重做与新题验证分别记录" description="复习可以重做原题；补学验证会优先使用尚未作答的新题。"/></>;
}

export function History() {
  const query=useQuery({queryKey:['history'],queryFn:()=>api<HistoryItem[]>('/attempt-history')});
  return <><PageTitle title="学习记录" description="原始答案、提示使用和评价结果都保存在每次作答中。"/><State query={query}><Table rowKey="id" dataSource={query.data??[]} pagination={{pageSize:10}} scroll={{x:800}} columns={[
    {title:'题目',render:(_,r)=><Link to={'/study/'+r.task.id}>{r.task.prompt}</Link>},{title:'题型',render:(_,r)=>kindName(r.task.kind)},{title:'状态',dataIndex:'status',render:v=><Status value={v}/>},{title:'正式得分',render:(_,r)=>r.evaluation?r.evaluation.score:'—'},{title:'记录时间',dataIndex:'created_at',render:date},
  ]}/></State></>;
}
