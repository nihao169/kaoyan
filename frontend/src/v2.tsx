import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Alert, App as AntApp, Button, Checkbox, Form, Input, InputNumber, Modal, Radio, Select, Space, Tabs, Tag } from 'antd';
import { ArrowRightOutlined, PlusOutlined, ReadOutlined } from '@ant-design/icons';
import { api, apiV2, key, type Catalog } from './api';
import { Blank, PageTitle, State, useRun } from './ui';
import { CitationList, ExamResources, MaterialSearch, type Citation } from './v2-resources';
import './v2.css';

type Task = {id:string;project_id:string;project_title?:string;title:string;kind:string;reason:string;state:string;estimated_minutes:number;due_at?:string};
type Project = {id:string;title:string;scenario:string;subject_id:string;exam_year:number;daily_minutes:number;target_score?:number;deadline?:string;state:string;revision:number};
type Material = {id:string;title:string;state:string;source_version_id?:string;text?:string};
type Report = {knowledge:{knowledge:string;state:string;kind:string;created_at:string}[];evidence_count:number;completed_tasks:number;task_count:number;correct:number;answered:number;due_reviews:number;coverage_note:string;syllabi:{year:number;edition:string;total:number;studied:number;verified:number}[]};
type Detail = Project & {materials:Material[];tasks:Task[];report:Report};
type Question = {id:string;kind:string;prompt:string;options:Record<string,string>;origin:string;answer?:string[];quote?:string;explanation?:string};
type Result = {correct?:boolean;feedback?:string;evaluator?:string;state?:string;question?:Question;run_id?:string};
type Run = {id:string;state:string;kind:string;result:{text?:string;coverage_note?:string;citations?:Citation[]};error:string};
const names:Record<string,string> = {reading:'资料学习',practice:'理解检查',verification:'独立验证',review:'间隔复习',remediation:'针对性补学',todo:'待开始',in_progress:'进行中',completed:'已完成',deferred:'已暂缓',cancelled:'已取消'};
const evidenceNames:Record<string,string> = {reading:'阅读记录',needs_remediation:'需补学的作答',independent_pass:'新题独立通过',delayed_pass:'延迟复习通过'};

function TaskList({tasks}:{tasks:Task[]}) {
  return <div className="v2-task-list">{tasks.map(t=><div className="v2-task" key={t.id}><div><Space><Tag>{names[t.kind]||t.kind}</Tag><span className="muted">{t.project_title}</span></Space><h3>{t.title}</h3><p>{t.reason}</p>{t.due_at&&<small>安排时间：{new Date(t.due_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}</small>}</div><div className="v2-task-action"><span>{t.estimated_minutes} 分钟 · {names[t.state]}</span><Link to={'/learning/session/'+t.id}><Button icon={<ArrowRightOutlined aria-hidden/>}>{t.state==='completed'?'查看记录':'进入学习'}</Button></Link></div></div>)}</div>;
}

export function TodayV2() {
  const query = useQuery({queryKey:['v2-today'],queryFn:()=>apiV2<{tasks:Task[];deferred:Task[];projects:number;estimated_minutes:number}>('/today')});
  return <><PageTitle title="今天，从这里继续" description="学一点，试一试，再用证据决定下一步。" action={<Link to="/learning/projects"><Button icon={<PlusOutlined aria-hidden/>}>创建学习项目</Button></Link>}/><State query={query}>{query.data&&<>
    <div className="v2-overview"><div><span>今日安排</span><strong>{query.data.estimated_minutes}<small> 分钟</small></strong></div><div><span>可执行任务</span><strong>{query.data.tasks.length}</strong></div><div><span>进行中的项目</span><strong>{query.data.projects}</strong></div></div>
    {query.data.tasks.length?<><div className="v2-section-heading"><h2>你的下一步</h2><span>每项安排都有原因</span></div><TaskList tasks={query.data.tasks}/></>:<Blank description="还没有今日任务。选择一门课程或添加资料，就能开始。"><Link to="/learning/projects"><Button type="primary">开始我的学习</Button></Link></Blank>}
    {!!query.data.deferred.length&&<Alert type="info" message={`${query.data.deferred.length} 项任务超出今日预算`} description="这些任务仍保留在项目中。可以调整学习时间，或先完成今天的重点。"/>}
    <div className="v2-loop"><span>学习与尝试</span><ArrowRightOutlined/><span>反馈与补学</span><ArrowRightOutlined/><span>独立验证</span><ArrowRightOutlined/><span>复习与下一轮</span></div>
  </>}</State></>;
}

export function ProjectsV2() {
  const query = useQuery({queryKey:['v2-projects'],queryFn:()=>apiV2<Project[]>('/learning-projects')});
  const catalog = useQuery({queryKey:['catalog'],queryFn:()=>api<Catalog>('/catalog')});
  const [open,setOpen] = useState(false);
  const {run,busy} = useRun();
  const navigate=useNavigate();
  async function create(values:{title:string;exam_year:number;daily_minutes:number;target_score?:number}) {
    const subject=catalog.data?.subjects.find(x=>x.code==='politics');
    if (!subject) return;
    const p=await run(()=>apiV2<Project>('/learning-projects','POST',{...values,subject_id:subject.id,scenario:'kaoyan'},key()));
    if(p){setOpen(false);navigate('/learning/projects/'+p.id)}
  }
  return <><PageTitle title="我的学习项目" description="每个目标，都有自己的资料、计划和学习记录。" action={<Button type="primary" icon={<PlusOutlined aria-hidden/>} onClick={()=>setOpen(true)}>新建项目</Button>}/>
    <State query={query}>{query.data?.length?<div className="v2-project-grid">{query.data.map(p=><Link className="v2-project" to={'/learning/projects/'+p.id} key={p.id}><Space><Tag color={p.state==='active'?'green':'default'}>{p.state==='active'?'考研复习':'已归档'}</Tag><span>{p.exam_year}</span></Space><h2>{p.title}</h2><p>每日 {p.daily_minutes} 分钟{p.target_score!=null?` · 目标 ${p.target_score} 分`:''}</p><span className="v2-project-link">继续这个目标 <ArrowRightOutlined/></span></Link>)}</div>:<Blank description="从一个明确的目标开始，不需要先完成基础诊断。"><Button onClick={()=>setOpen(true)}>创建第一个项目</Button></Blank>}</State>
    <Modal title="你想怎样学习？" open={open} onCancel={()=>setOpen(false)} footer={null}><div className="v2-scenarios"><div className="selected"><strong>考研复习</strong><p>阶段学习、真题训练与持续巩固</p></div><div><strong>章节学习</strong><p>独立场景规划中</p></div><div><strong>期末备考</strong><p>规划中</p></div></div><p className="muted">首版支持考研政治；项目内可以按章节学习。</p><Form layout="vertical" initialValues={{exam_year:new Date().getFullYear()+1,daily_minutes:45}} onFinish={create}>
      <Form.Item label="项目名称" name="title" rules={[{required:true,whitespace:true}]}><Input maxLength={200} placeholder="例如：考研政治第一轮复习"/></Form.Item>
      <Space align="start"><Form.Item label="考试年份" name="exam_year"><InputNumber min={2026} max={2100}/></Form.Item><Form.Item label="每日分钟" name="daily_minutes"><InputNumber min={10} max={480}/></Form.Item><Form.Item label="目标分数（可选）" name="target_score"><InputNumber min={0} max={100}/></Form.Item></Space>
      <Button type="primary" htmlType="submit" loading={busy} disabled={!catalog.data?.subjects.some(x=>x.code==='politics')}>确认并创建学习计划</Button>
    </Form></Modal>
  </>;
}

export function ProjectV2() {
  const {projectId}=useParams();
  const query=useQuery({queryKey:['v2-project',projectId],queryFn:()=>apiV2<Detail>('/learning-projects/'+projectId)});
  return <State query={query}>{query.data&&<ProjectContent p={query.data}/>}</State>;
}

function ProjectContent({p}:{p:Detail}) {
  const {run,busy}=useRun();
  const {modal}=AntApp.useApp();
  const [materialOpen,setMaterialOpen]=useState(false);
  const [uploading,setUploading]=useState(false);
  const courses=useQuery({queryKey:['v2-courses'],queryFn:()=>apiV2<{id:string;title:string;version:number}[]>('/course-materials')});
  const [selectedCourse,setSelectedCourse]=useState<string>();
  const [form]=Form.useForm();
  const active=p.state==='active';
  async function upload(file:File) {
    setUploading(true);
    const body=new FormData();body.append('file',file);
    try {await run(()=>apiV2('/learning-projects/'+p.id+'/uploads','POST',body),'资料已导入，阅读任务已加入计划')} finally {setUploading(false)}
  }
  const materialPanel=<><Space wrap><Button type="primary" disabled={!active} onClick={()=>setMaterialOpen(true)}>粘贴学习资料</Button><label className="v2-file-button">{uploading?'正在导入…':'上传 PDF / Word / 文本'}<input type="file" disabled={uploading||!active} accept=".pdf,.docx,.txt,.md" onChange={e=>{if(e.target.files?.[0])void upload(e.target.files[0]);e.target.value=''}}/></label></Space>
    <div className="v2-course-picker"><Select style={{minWidth:230}} placeholder="选择教师已启用的课程资料" value={selectedCourse} onChange={setSelectedCourse} options={courses.data?.map(c=>({value:c.id,label:c.title+' · v'+c.version}))}/><Button disabled={!selectedCourse||!active} onClick={()=>run(()=>apiV2('/learning-projects/'+p.id+'/course-materials','POST',{source_version_id:selectedCourse}),'已加入项目')}>加入课程资料</Button></div>
    <p className="muted">个人资料默认私有。扫描件需先 OCR；目前每份最多 20 MB、正文30万字。</p>
    {p.materials.filter(m=>m.state==='ready').map(m=><div className="v2-material" key={m.id}><ReadOutlined/><div><strong>{m.title}</strong><p>{m.source_version_id?'关联课程资料，使用时检查当前权限':'个人资料 · 仅自己可用'}</p></div><Button danger type="text" disabled={!active} onClick={()=>modal.confirm({title:'移除这份学习资料？',content:'关联任务将停止，历史记录保留，旧助教运行不再继续使用。',onOk:()=>run(()=>apiV2('/learning-projects/'+p.id+'/materials/'+m.id,'DELETE'),'资料已移除')})}>移除</Button></div>)}
    {p.materials.some(m=>m.state==='ready')?<MaterialSearch projectId={p.id}/>:<Blank description="添加资料后，系统会安排第一项学习任务。"/>}</>;
  return <><PageTitle title={p.title} description={`${p.exam_year} 考研政治 · 每日 ${p.daily_minutes} 分钟 · 计划版本 ${p.revision}`} action={<Link to="/learning/projects">返回项目列表</Link>}/>
    {!active&&<Alert type="info" message="项目已归档，保留历史记录"/>}
    <Tabs items={[
      {key:'study',label:'学习与任务',children:<>{p.tasks.length?<TaskList tasks={p.tasks}/>:<Blank description="先在“课程与资料”中选择材料。"/>}{active&&!!p.tasks.filter(t=>t.state==='deferred').length&&<Button onClick={()=>run(()=>Promise.all(p.tasks.filter(t=>t.state==='deferred').map(t=>apiV2('/tasks/'+t.id,'PATCH',{state:'todo'}))),'已恢复暂缓任务')}>恢复暂缓任务</Button>}</>},
      {key:'materials',label:'课程与资料',children:materialPanel},
      {key:'annual',label:'年度考纲与试卷',children:<ExamResources projectId={p.id} examYear={p.exam_year} active={active}/>},
      {key:'notes',label:'笔记与闪卡',children:<NotesPanel projectId={p.id} disabled={!active}/>},
      {key:'report',label:'证据与报告',children:<ReportPanel report={p.report}/>},
      {key:'plan',label:'计划设置',children:<><Form layout="vertical" key={p.revision} initialValues={{daily_minutes:p.daily_minutes,target_score:p.target_score,deadline:p.deadline}} onFinish={values=>run(()=>apiV2('/learning-projects/'+p.id+'/plans','POST',{...values,deadline:values.deadline||null,revision:p.revision},key()),'计划已更新，历史版本已保留')}><Form.Item name="daily_minutes" label="每日时间预算（分钟）"><InputNumber min={10} max={480} disabled={!active}/></Form.Item><Form.Item name="target_score" label="目标分数"><InputNumber min={0} max={100} disabled={!active}/></Form.Item><Form.Item name="deadline" label="目标日期（可选）"><Input type="date" disabled={!active}/></Form.Item><Button htmlType="submit" type="primary" loading={busy} disabled={!active}>确认调整计划</Button></Form><Button danger style={{marginTop:32}} disabled={!active} onClick={()=>modal.confirm({title:'归档学习项目？',content:'项目将退出今日计划，历史记录仍保留。',onOk:()=>run(()=>apiV2('/learning-projects/'+p.id+'/archive','POST'),'已归档')})}>归档项目</Button></>},
    ]}/>
    <Modal title="添加个人学习资料" open={materialOpen} onCancel={()=>setMaterialOpen(false)} footer={null}><Form form={form} layout="vertical" onFinish={async values=>{const result=await run(()=>apiV2('/learning-projects/'+p.id+'/materials','POST',values,key()),'资料已添加');if(result){setMaterialOpen(false);form.resetFields()}}}><Form.Item name="title" label="资料标题" rules={[{required:true,whitespace:true}]}><Input maxLength={200}/></Form.Item><Form.Item name="text" label="资料正文" rules={[{required:true,whitespace:true}]}><Input.TextArea rows={12} maxLength={300000}/></Form.Item><Button type="primary" htmlType="submit" loading={busy}>保存并加入学习计划</Button></Form></Modal>
  </>;
}

function ReportPanel({report}:{report:Report}) {
  const syllabusSummary=report.syllabi.map(x=><p key={x.year+'/'+x.edition}>{x.year} 年考纲 · {x.edition}：已学习 {x.studied}/{x.total}，已独立验证 {x.verified}/{x.total}</p>);
  return <>{syllabusSummary}<EvidencePanel report={report}/></>;
}

function EvidencePanel({report}:{report:Report}) {
  return <><Alert type="info" message={report.coverage_note} style={{background:'#edf4ee',borderColor:'#d3e1d6'}}/><div className="v2-overview"><div><span>已完成任务</span><strong>{report.completed_tasks}<small> / {report.task_count}</small></strong></div><div><span>已答题目</span><strong>{report.answered}</strong></div><div><span>到期复习</span><strong>{report.due_reviews}</strong></div></div><h2>知识点与最新证据</h2>{report.knowledge.length?report.knowledge.map(k=><div className="v2-material" key={k.knowledge}><div><strong>{k.knowledge}</strong><p>{evidenceNames[k.kind]||'学习记录'} · {new Date(k.created_at).toLocaleDateString('zh-CN')}</p></div><Tag color={k.state==='待验证'?'gold':'green'}>{k.state}</Tag></div>):<Blank description="完成独立作答后，这里将显示知识点证据。"/>}</>;
}

function NotesPanel({projectId,disabled=false}:{projectId:string;disabled?:boolean}) {
  const query=useQuery({queryKey:['v2-notes',projectId],queryFn:()=>apiV2<{id:string;title:string;body:string;kind:string}[]>('/learning-projects/'+projectId+'/notes')});
  const {run,busy}=useRun();const [form]=Form.useForm();
  return <><Form form={form} layout="vertical" initialValues={{kind:'note'}} onFinish={async values=>{const result=await run(()=>apiV2('/learning-projects/'+projectId+'/notes','POST',values,key()),'已保存');if(result)form.resetFields()}}><Space><Form.Item name="kind"><Select options={[{value:'note',label:'学习笔记'},{value:'flashcard',label:'记忆闪卡'}]} style={{width:130}}/></Form.Item><Form.Item name="title" rules={[{required:true,whitespace:true}]}><Input placeholder="标题／卡片正面" maxLength={200}/></Form.Item></Space><Form.Item name="text" rules={[{required:true,whitespace:true}]}><Input.TextArea rows={4} placeholder="我的理解／卡片背面"/></Form.Item><Button disabled={disabled} loading={busy} htmlType="submit">保存</Button></Form><State query={query}>{query.data?.map(n=><article className="v2-note" key={n.id}><Tag>{n.kind==='flashcard'?'闪卡':'笔记'}</Tag><h3>{n.title}</h3>{n.kind==='flashcard'?<details><summary>尝试回忆后查看</summary><p>{n.body}</p></details>:<p>{n.body}</p>}</article>)}</State></>;
}

export function StudyV2() {
  const {taskId}=useParams();
  const query=useQuery({queryKey:['v2-session',taskId],queryFn:()=>apiV2<{task:Task;project:Project;material?:Material;checkpoint:{text?:string;answer?:string[]};revision:number;question?:Question;result?:Result;ai_run_id?:string}>('/study-sessions/'+taskId)});
  return <State query={query}>{query.data&&<StudyContent key={taskId} data={query.data}/>}</State>;
}

function StudyContent({data}:{data:{task:Task;project:Project;material?:Material;checkpoint:{text?:string;answer?:string[]};revision:number;question?:Question;result?:Result;ai_run_id?:string}}) {
  const {run,busy}=useRun();const navigate=useNavigate();
  const [text,setText]=useState(data.checkpoint.text||'');const [answer,setAnswer]=useState<string[]>(data.checkpoint.answer||[]);
  const [revision,setRevision]=useState(data.revision);const [confidence,setConfidence]=useState('normal');
  const [prompt,setPrompt]=useState('');const [runId,setRunId]=useState<string|undefined>(data.ai_run_id||data.result?.run_id);const [hint,setHint]=useState('');
  const t=data.task;const closed=['completed','cancelled'].includes(t.state)||!!data.result;
  const [questionKind,setQuestionKind]=useState('single');
  const ai=useQuery({queryKey:['v2-run',runId],queryFn:()=>apiV2<Run>('/ai-runs/'+runId),enabled:!!runId,refetchInterval:q=>q.state.data&&['succeeded','failed'].includes(q.state.data.state)?false:1500});
  const refresh=useRun();
  useEffect(()=>{if(ai.data?.state==='succeeded'&&['question','evaluate'].includes(ai.data.kind))void refresh.run(()=>Promise.resolve(true))},[ai.data?.state,ai.data?.kind]);
  async function save(){const result=await run(()=>apiV2<{revision:number}>('/study-sessions/'+t.id+'/checkpoint','PUT',{revision,text,answer}),'草稿已保存');if(result)setRevision(result.revision)}
  async function generate(){const result=await run(()=>apiV2<{run_id:string}>('/study-sessions/'+t.id+'/prepare','POST',{kind:questionKind},key()));if(result)setRunId(result.run_id)}
  async function ask(){const result=await run(()=>apiV2<{run_id:string}>('/learning-projects/'+data.project.id+'/ai-runs','POST',{kind:'chat',prompt,task_id:t.id},key()));if(result)setRunId(result.run_id)}
  return <><PageTitle title={t.title} description={t.reason} action={<Link to={'/learning/projects/'+data.project.id}>返回学习项目</Link>}/><div className="v2-study-grid"><section className="v2-reader"><Space><Tag>{names[t.kind]}</Tag><span>{data.material?.title}</span></Space><div className="v2-source-text">{data.material?.text||'暂无可阅读资料'}</div></section><section className="v2-learning-panel">
    <h2>{data.question?'独立尝试':'本次学习'}</h2>
    {!data.question&&['practice','verification','review'].includes(t.kind)&&<Select aria-label="练习题型" value={questionKind} onChange={setQuestionKind} style={{width:180,marginBottom:16}} options={[{value:'single',label:'单选题'},{value:'multiple',label:'多选题'},{value:'essay',label:'分析题训练'}]}/>}
    {data.question?<><Tag>AI生成练习 · 原文引用已校验</Tag><h3>{data.question.prompt}</h3>{data.question.kind==='essay'?<Input.TextArea aria-label="分析题作答" rows={8} disabled={closed} value={text} onChange={e=>setText(e.target.value)}/>:data.question.kind==='single'?<Radio.Group disabled={closed} value={answer[0]} onChange={e=>setAnswer([e.target.value])}>{Object.entries(data.question.options).map(([k,v])=><Radio key={k} value={k}>{k}. {v}</Radio>)}</Radio.Group>:<Checkbox.Group disabled={closed} value={answer} onChange={v=>setAnswer(v as string[])} options={Object.entries(data.question.options).map(([k,v])=>({label:k+'. '+v,value:k}))}/>}
      {!closed&&<><p>对这次作答的信心</p><Radio.Group value={confidence} onChange={e=>setConfidence(e.target.value)} options={[{value:'low',label:'不太确定'},{value:'normal',label:'一般'},{value:'high',label:'有把握'}]}/><Space wrap style={{marginTop:20}}><Button loading={busy} onClick={save}>保存草稿</Button><Button onClick={async()=>{const r=await run(()=>apiV2<{hint:string}>('/study-sessions/'+t.id+'/hint','POST'));if(r)setHint(r.hint)}}>需要提示</Button><Button type="primary" loading={busy} onClick={async()=>{const result=await run(()=>apiV2<{result:Result}>('/study-sessions/'+t.id+'/submit','POST',{answer,response_text:text,confidence},key()),'作答已提交');if(result?.result.run_id)setRunId(result.result.run_id)}}>提交作答</Button></Space></>}
      {hint&&<Alert type="info" message={hint} description="本次将记录为辅助完成，不产生独立验证证据。"/>}
    </>:['reading','remediation'].includes(t.kind)?<><p>先理解原文，用自己的话记录。完成后将安排一道独立检查题。</p><Input.TextArea rows={5} placeholder="用自己的话写下理解与疑问" value={text} onChange={e=>setText(e.target.value)} disabled={closed}/><Space style={{marginTop:16}}><Button disabled={closed} loading={busy} onClick={save}>保存学习位置</Button><Button type="primary" disabled={closed} loading={busy} onClick={async()=>{const result=await run(()=>apiV2<{next_task_id:string}>('/study-sessions/'+t.id+'/complete','POST',{},key()),'已记录阅读，接下来独立检查');if(result)navigate('/learning/session/'+result.next_task_id)}}>完成阅读，检查理解</Button></Space></>:<><p>从本项目资料准备一道未做过的新题。服务未配置或生成失败时，会保留任务并显示原因。</p><Button type="primary" loading={busy||ai.data?.state==='running'||ai.data?.state==='queued'} disabled={closed} onClick={generate}>准备练习</Button></>}
    {data.result&&<Alert style={{marginTop:20}} type={data.result.correct?'success':'info'} message={data.result.evaluator==='ai_training'?'AI训练评价，不是正式成绩':data.result.correct?'本次回答正确':data.result.state==='pending_ai'?'正在等待AI训练评价':'本次需要补学'} description={data.result.feedback}/>}
    {data.result?.question&&<div className="v2-feedback"><p>参考答案：{data.result.question.answer?.join('、')}</p><p>{data.result.question.explanation}</p><blockquote>{data.result.question.quote}</blockquote><Link to={'/learning/projects/'+data.project.id}><Button type="primary">查看下一步任务</Button></Link></div>}
    <hr/><h2>随学助教</h2><p className="muted">基于当前项目资料解释，保留问题与执行记录。</p><Input.TextArea aria-label="向助教提问" rows={3} value={prompt} onChange={e=>setPrompt(e.target.value)} placeholder="例如：这里的两个概念有什么区别？"/><Button style={{marginTop:12}} loading={busy} disabled={!prompt.trim()} onClick={ask}>解释我的问题</Button>
    {ai.data&&<div className="v2-ai-result"><Tag>{({queued:'排队中',running:'正在思考',succeeded:'已完成',failed:'未完成'} as Record<string,string>)[ai.data.state]||ai.data.state}</Tag>{ai.data.error&&<Alert type="error" message={ai.data.error}/>}<p>{ai.data.result.text}</p>{ai.data.result.coverage_note&&<small>{ai.data.result.coverage_note}</small>}{!!ai.data.result.citations?.length&&<CitationList projectId={data.project.id} citations={ai.data.result.citations}/>}</div>}
    <Button type="text" disabled={closed} onClick={()=>run(()=>apiV2('/tasks/'+t.id,'PATCH',{state:'deferred'}),'已暂缓，任务仍保留在项目中')}>暂缓这项任务</Button>
  </section></div></>;
}

export function LibraryV2() {
  const q=useQuery({queryKey:['v2-projects'],queryFn:()=>apiV2<Project[]>('/learning-projects')});
  return <><PageTitle title="资料与笔记" description="资料和自己的理解，都归属于明确的学习项目。"/><State query={q}>{q.data?.length?q.data.map(p=><div className="v2-material" key={p.id}><div><h3>{p.title}</h3><p>课程资料 · 个人资料 · 笔记 · 闪卡</p></div><Link to={'/learning/projects/'+p.id}><Button>打开项目资料</Button></Link></div>):<Blank description="先创建学习项目，再添加资料和笔记。"/>}</State></>;
}

export function ReportsV2() {
  const q=useQuery({queryKey:['v2-projects'],queryFn:()=>apiV2<Project[]>('/learning-projects')});
  const [id,setId]=useState<string>();
  const selected=id||q.data?.[0]?.id;
  const report=useQuery({queryKey:['v2-report',selected],queryFn:()=>apiV2<Report>('/learning-projects/'+selected+'/report'),enabled:!!selected});
  return <><PageTitle title="学习报告" description="查看已经发生的学习和证据，让下一步更清楚。"/><Select style={{minWidth:240,marginBottom:24}} placeholder="选择学习项目" value={selected} onChange={setId} options={q.data?.map(p=>({value:p.id,label:p.title}))}/>{selected?<State query={report}>{report.data&&<ReportPanel report={report.data}/>}</State>:<Blank description="创建项目并开始学习后，将逐步形成报告。"/>}</>;
}
