import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Alert, App as AntApp, Button, Checkbox, Form, Input, InputNumber, Modal, Radio, Select, Space, Tabs, Tag } from 'antd';
import { ArrowRightOutlined, PlusOutlined, ReadOutlined } from '@ant-design/icons';
import { apiV2, key } from './api';
import { Blank, PageTitle, State, useRun } from './ui';
import { CitationList, ExamResources, MaterialSearch, type Citation } from './v2-resources';
import { MasteryReviewQueue } from './mastery-reviews';
import { useUser } from './App';
import { LearningSceneOptions, learningScenes, politicsPracticeNotice, readLearningScene, type LearningScene } from './v2-scenes';
import { LearningProfileForm, ProjectLearning, NativeLearningOverview, LearningSummary, type LearningProject } from './project-learning';
import './v2.css';

type Task = {id:string;project_id:string;project_title?:string;title:string;kind:string;reason:string;state:string;estimated_minutes:number;due_at?:string};
type Project = LearningProject & {subject_id:string;daily_minutes:number;target_score?:number;deadline?:string};
type Material = {id:string;title:string;state:string;source_version_id?:string;text?:string};
type Report = {knowledge:{knowledge:string;state:string;kind:string;created_at:string}[];evidence_count:number;completed_tasks:number;task_count:number;correct:number;answered:number;due_reviews:number;coverage_note:string;syllabi:{year:number;edition:string;total:number;studied:number;verified:number}[]};
type Outline = {name:string;points:string[]}[];
type Detail = Project & {materials:Material[];tasks:Task[];report:Report;mastery_outline?:Outline};
type Question = {id:string;kind:string;prompt:string;options:Record<string,string>;origin:string;answer?:string[];quote?:string;explanation?:string;rubric?:string[]};
type Result = {correct?:boolean;feedback?:string;evaluator?:string;state?:string;question?:Question;run_id?:string};
type Run = {id:string;state:string;kind:string;result:{text?:string;coverage_note?:string;citations?:Citation[];outline?:Outline};error:string};
const names:Record<string,string> = {reading:'资料学习',practice:'理解检查',verification:'独立验证',review:'间隔复习',remediation:'针对性补学',todo:'待开始',in_progress:'进行中',completed:'已完成',deferred:'已暂缓',cancelled:'已取消'};
const evidenceNames:Record<string,string> = {reading:'阅读记录',needs_remediation:'需补学的作答',independent_pass:'新题独立通过',delayed_pass:'延迟复习通过'};

function MasteryOutline({outline}:{outline?:Outline}) {
  if (!outline?.length) return null;
  return <section aria-label="知识点地图"><h3>知识点地图</h3><ol>{outline.map((module,i)=><li key={i}><strong>{module.name}</strong><ul>{module.points.map((point,j)=><li key={j}>{point}</li>)}</ul></li>)}</ol></section>;
}

function TaskList({tasks}:{tasks:Task[]}) {
  return <div className="v2-task-list">{tasks.map(t=><div className="v2-task" key={t.id}><div><Space><Tag>{names[t.kind]||t.kind}</Tag><span className="muted">{t.project_title}</span></Space><h3>{t.title}</h3><p>{t.reason}</p>{t.due_at&&<small>安排时间：{new Date(t.due_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}</small>}</div><div className="v2-task-action"><span>{t.estimated_minutes} 分钟 · {names[t.state]}</span><Link to={'/learning/session/'+t.id}><Button icon={<ArrowRightOutlined aria-hidden/>}>{t.state==='completed'?'查看记录':'进入学习'}</Button></Link></div></div>)}</div>;
}

export function TodayV2() {
  return <><PageTitle title="今天，从这里继续" description="带着目标和问题，与助教一起学习。" action={<StartLearning label="开始新学习"/>}/>
    <NativeLearningOverview/><MasteryReviewQueue dueOnly/></>;
}

export function ProjectsV2() {
  const query = useQuery({queryKey:['v2-projects'],queryFn:()=>apiV2<Project[]>('/learning-projects')});
  return <><PageTitle title="我的学习项目" description="每个目标，都有自己的资料、计划和学习记录。" action={<StartLearning label="新建项目"/>}/>
    <State query={query}>{query.data?.length?<div className="v2-project-grid">{query.data.map(p=>{
      const scene = p.scene_confirmed?p.scenario:undefined;
      return <Link className="v2-project" to={'/learning/projects/'+p.id} key={p.id}>
        <Space><Tag color={p.state==='active'?'green':'default'}>{p.state==='active'?(scene?learningScenes[scene].title:'学习项目'):'已归档'}</Tag>
          {(!scene || scene==='kaoyan')&&<span>{p.exam_year}</span>}
          {scene==='final'&&p.deadline&&<span>考试日期 {p.deadline}</span>}</Space>
        <h2>{p.title}</h2><p>每日 {p.daily_minutes} 分钟{(!scene || scene==='kaoyan')&&p.target_score!=null?` · 目标 ${p.target_score} 分`:''}</p>
        <span className="v2-project-link">继续这个目标 <ArrowRightOutlined/></span>
      </Link>;
    })}</div>:<Blank description="从一个明确的目标开始，不需要先完成基础诊断。"/>}</State>
  </>;
}

function StartLearning({label}:{label:string}) {
  const [open,setOpen] = useState(false);
  return <><Button type="primary" icon={<PlusOutlined aria-hidden/>} onClick={()=>setOpen(true)}>{label}</Button>
    {open&&<StartLearningDialog onClose={()=>setOpen(false)}/>}
  </>;
}

type ProjectForm = {title:string;course_name:string;learning_goal?:string;exam_year?:number;daily_minutes:number;target_score?:number;deadline?:string};

function StartLearningDialog({onClose}:{onClose:()=>void}) {
  const projects = useQuery({queryKey:['v2-projects'],queryFn:()=>apiV2<Project[]>('/learning-projects')});
  const [scene,setScene] = useState<LearningScene>();
  const [step,setStep] = useState<'choose'|'create'|'existing'>('choose');
  const [projectId,setProjectId] = useState<string>();
  const {run,busy} = useRun();
  const navigate = useNavigate();
  const activeProjects = projects.data?.filter(p=>p.state==='active') ?? [];
  const defaultYear = new Date().getFullYear()+1;

  function openProject(id:string, _selected:LearningScene) {
    onClose();
    navigate('/learning/projects/'+id);
  }

  async function create(values:ProjectForm) {
    if (!scene || busy) return;
    const project = await run(()=>apiV2<Project>('/learning-projects','POST',{
      title:values.title, course_name:values.course_name, learning_goal:values.learning_goal||'', daily_minutes:values.daily_minutes, scenario:scene,
      ...(scene==='kaoyan'?{exam_year:values.exam_year}:{}),
      ...(scene==='kaoyan'?{target_score:values.target_score}:{}),
      ...(scene==='final'?{deadline:values.deadline||null}:{}),
    },key()));
    if (project) openProject(project.id, scene);
  }

  return <Modal title={step==='choose'||!scene?'你想怎样学习？':learningScenes[scene].title} open footer={null}
    closable={!busy} maskClosable={!busy} keyboard={!busy} onCancel={onClose}>
    {step==='choose'&&<>
      <LearningSceneOptions value={scene} onChange={setScene}/>
      <Space wrap>
        <Button type="primary" disabled={!scene} onClick={()=>setStep('create')}>创建新项目</Button>
        <Button disabled={!scene || (!activeProjects.length&&!projects.error)} onClick={()=>setStep('existing')}>使用已有项目</Button>
      </Space>
    </>}
    {step==='existing'&&scene&&<>
      <State query={projects}><label htmlFor="existing-learning-project">选择进行中的项目</label>
        <Select id="existing-learning-project" className="scene-project-select" value={projectId} onChange={setProjectId}
          options={activeProjects.map(p=>({value:p.id,label:p.title}))}/>
        {!activeProjects.length&&<p className="muted">没有可继续的项目，可以返回创建新项目。</p>}
      </State>
      <Space wrap><Button autoInsertSpace={false} onClick={()=>setStep('choose')}>返回</Button>
        <Button type="primary" disabled={!activeProjects.some(p=>p.id===projectId)} onClick={()=>projectId&&openProject(projectId,scene)}>打开项目</Button></Space>
    </>}
    {step==='create'&&<>
      <Form layout="vertical" initialValues={{exam_year:defaultYear,daily_minutes:45}} onFinish={create}>
        <Form.Item label={scene==='chapter'?'课程或章节名称':'项目名称'} name="title" rules={[{required:true,whitespace:true}]}>
          <Input autoFocus maxLength={200} placeholder={scene==='chapter'?'例如：统计学 · 第一章':scene==='final'?'例如：统计学期末复习':'例如：考研政治第一轮复习'}/>
        </Form.Item>
        <Form.Item label="课程名称" name="course_name" rules={[{required:true,whitespace:true}]}><Input maxLength={200} placeholder="例如：统计学、高等数学、考研政治"/></Form.Item>
        <Form.Item label="学习目标与范围（可选）" name="learning_goal"><Input.TextArea rows={3} maxLength={2000} placeholder="也可以进入项目后与助教一起明确。"/></Form.Item>
        {scene==='kaoyan'&&<Form.Item label="考试年份" name="exam_year" rules={[{required:true,type:'integer'}]}><InputNumber min={2026} max={2100}/></Form.Item>}
        <Form.Item label="每日学习时间（分钟）" name="daily_minutes" rules={[{required:true,type:'integer'}]}><InputNumber min={10} max={480}/></Form.Item>
        {scene==='kaoyan'&&<Form.Item label="目标分数（可选）" name="target_score"><InputNumber min={0} max={100} precision={0}/></Form.Item>}
        {scene==='final'&&<Form.Item label="考试日期（可选）" name="deadline"><Input type="date"/></Form.Item>}
        <Space wrap><Button autoInsertSpace={false} disabled={busy} onClick={()=>setStep('choose')}>返回</Button>
          <Button type="primary" htmlType="submit" loading={busy}>创建并与助教开始学习</Button></Space>
      </Form>
    </>}
  </Modal>;
}

export function ProjectV2() {
  const {projectId}=useParams();
  const user = useUser();
  const query=useQuery({queryKey:['v2-project',projectId],queryFn:()=>apiV2<Detail>('/learning-projects/'+projectId)});
  return <State query={query}>{query.data&&<ProjectContent key={`${user.id}:${query.data.id}`} p={query.data}/>}</State>;
}

function ProjectContent({p}:{p:Detail}) {
  const {run,busy}=useRun();
  const {modal}=AntApp.useApp();
  const [tab,setTab]=useState('study');
  const [profileOpen,setProfileOpen]=useState(false);
  const [materialOpen,setMaterialOpen]=useState(false);
  const [uploading,setUploading]=useState(false);
  const [selectedCourse,setSelectedCourse]=useState<string>();
  const [form]=Form.useForm();
  const projectContent=useRef<HTMLElement>(null);
  const courses=useQuery({queryKey:['v2-courses'],queryFn:()=>apiV2<{id:string;title:string;version:number}[]>('/course-materials')});
  const active=p.state==='active';
  function showTab(next:string){setTab(next);requestAnimationFrame(()=>projectContent.current?.scrollIntoView({block:'start'}));}
  async function upload(file:File){
    setUploading(true);const body=new FormData();body.append('file',file);
    try{await run(()=>apiV2('/learning-projects/'+p.id+'/uploads','POST',body),'资料已导入，索引就绪后可与助教学习');}finally{setUploading(false);}
  }
  const materialPanel=<><Space wrap><Button type="primary" disabled={!active} onClick={()=>setMaterialOpen(true)}>粘贴学习资料</Button>
    <label className="v2-file-button">{uploading?'正在导入…':'上传 PDF / Word / 文本'}<input type="file" disabled={!active||uploading} accept=".pdf,.docx,.txt,.md"
      onChange={e=>{if(e.target.files?.[0])void upload(e.target.files[0]);e.target.value='';}}/></label></Space>
    <div className="v2-course-picker"><Select aria-label="教师课程资料" style={{minWidth:230}} placeholder="选择教师已启用的课程资料" value={selectedCourse}
      onChange={setSelectedCourse} options={courses.data?.map(c=>({value:c.id,label:c.title+' · v'+c.version}))}/>
      <Button disabled={!active||!selectedCourse} onClick={()=>run(()=>apiV2('/learning-projects/'+p.id+'/course-materials','POST',{source_version_id:selectedCourse}),'已加入项目')}>加入课程资料</Button></div>
    <p className="muted">资料默认私有，支持文字型 PDF、Word、TXT 和 Markdown。扫描件请先 OCR。</p>
    {active&&<TutorIndexPanel projectId={p.id}/>}
    {p.materials.filter(m=>m.state==='ready').map(m=><div className="v2-material" key={m.id}><ReadOutlined/><div><strong>{m.title}</strong>
      <p>{m.source_version_id?'关联课程资料':'个人学习资料'}</p></div><Button danger type="text" disabled={!active} onClick={()=>modal.confirm({title:'移除这份学习资料？',
        content:'原学习记录保留，助教需要依据新的资料范围重新确认路径。',onOk:()=>run(()=>apiV2('/learning-projects/'+p.id+'/materials/'+m.id,'DELETE'),'资料已移除')})}>移除</Button></div>)}
    {p.materials.some(m=>m.state==='ready')?<MaterialSearch projectId={p.id}/>:<Blank description="添加资料后，请回到与助教学习，一起确定大纲。"/>}</>;
  return <><PageTitle title={p.title} description={`${p.scene_confirmed?learningScenes[p.scenario].title:'待确认学习背景'} · ${p.course_name||'课程待确认'} · 每日 ${p.daily_minutes} 分钟`}
    action={<Space wrap>{active&&<Button onClick={()=>setProfileOpen(true)}>调整学习背景</Button>}<Link to="/learning/projects">返回项目列表</Link></Space>}/>
    {!active&&<Alert type="info" message="项目已归档，保留历史记录"/>}
    <section ref={projectContent} className="v2-project-content" aria-label="项目学习内容" tabIndex={-1}>
      <Tabs activeKey={tab} onChange={setTab} items={[
        {key:'study',label:'与助教学习',children:<ProjectLearning project={p} materials={p.materials} showMaterials={()=>showTab('materials')}/>},
        {key:'materials',label:'课程与资料',children:materialPanel},
        ...(p.scenario==='kaoyan'?[{key:'annual',label:'年度考纲与试卷',children:<ExamResources projectId={p.id} examYear={p.exam_year} active={active}/>}]:[]),
        {key:'notes',label:'笔记与闪卡',children:<NotesPanel projectId={p.id} disabled={!active}/>},
        {key:'history',label:'历史学习记录',children:<><p className="muted">此前的任务与证据保留查阅。当前教学和掌握进度见“与助教学习”。</p><TaskList tasks={p.tasks}/><ChatHistory projectId={p.id}/><ReportPanel report={p.report}/></>},
        {key:'plan',label:'计划设置',children:<><Form layout="vertical" key={p.revision} initialValues={{daily_minutes:p.daily_minutes,target_score:p.target_score,deadline:p.deadline}}
          onFinish={values=>run(()=>apiV2('/learning-projects/'+p.id+'/plans','POST',{...values,deadline:values.deadline||null,revision:p.revision},key()),'时间与目标已更新')}>
          <Form.Item name="daily_minutes" label="每日时间预算（分钟）"><InputNumber min={10} max={480} disabled={!active}/></Form.Item>
          <Form.Item name="target_score" label="目标分数（可选）"><InputNumber min={0} max={100} disabled={!active}/></Form.Item>
          <Form.Item name="deadline" label="目标日期（可选）"><Input type="date" disabled={!active}/></Form.Item>
          <Button htmlType="submit" type="primary" loading={busy} disabled={!active}>确认调整计划</Button></Form>
          <Button danger disabled={!active} onClick={()=>modal.confirm({title:'归档学习项目？',content:'历史记录保留。',onOk:()=>run(()=>apiV2('/learning-projects/'+p.id+'/archive','POST'),'已归档')})}>归档项目</Button></>},
      ]}/>
    </section>
    <Modal title="调整学习背景" open={profileOpen} footer={null} onCancel={()=>setProfileOpen(false)} destroyOnHidden>
      <LearningProfileForm project={p} onDone={()=>setProfileOpen(false)}/></Modal>
    <Modal title="添加个人学习资料" open={materialOpen} footer={null} onCancel={()=>setMaterialOpen(false)}><Form form={form} layout="vertical" onFinish={async values=>{
      const result=await run(()=>apiV2('/learning-projects/'+p.id+'/materials','POST',values,key()),'资料已添加');if(result){form.resetFields();setMaterialOpen(false);}}}>
      <Form.Item name="title" label="资料标题" rules={[{required:true,whitespace:true}]}><Input maxLength={200}/></Form.Item>
      <Form.Item name="text" label="资料正文" rules={[{required:true,whitespace:true}]}><Input.TextArea rows={12} maxLength={300000}/></Form.Item>
      <Button type="primary" htmlType="submit" loading={busy}>保存学习资料</Button></Form></Modal>
  </>;
}

type TutorIndexStatus = {enabled:boolean;items:{material_id:string;title:string;state:string;error:string}[]};
const indexLabels:Record<string,string> = {missing:'未建立',queued:'等待处理',indexing:'正在建立',ready:'已就绪',failed:'建立失败',deleted:'已清理'};

function TutorIndexPanel({projectId}:{projectId:string}) {
  const path='/learning-projects/'+projectId+'/tutor-index';
  const {run,busy}=useRun();
  const status=useQuery({queryKey:['v2-tutor-index',projectId],queryFn:()=>apiV2<TutorIndexStatus>(path),
    refetchInterval:q=>q.state.data?.items.some(item=>['queued','indexing'].includes(item.state))?3000:false});
  if(!status.data?.enabled||!status.data.items.length)return null;
  const needsIndex=status.data.items.some(item=>['missing','failed','deleted'].includes(item.state));
  return <div className="v2-material"><div><strong>助教资料索引</strong>{status.data.items.map(item=><p key={item.material_id}>
    {item.title}：{indexLabels[item.state]||item.state}{item.error&&` · ${item.error}`}</p>)}</div>
    {needsIndex&&<Button loading={busy} onClick={async()=>{await run(()=>apiV2(path,'POST'),'已安排建立索引');void status.refetch()}}>
      准备或重试索引</Button>}</div>;
}

function ReportPanel({report}:{report:Report}) {
  const syllabusSummary=report.syllabi.map(x=><p key={x.year+'/'+x.edition}>{x.year} 年考纲 · {x.edition}：已学习 {x.studied}/{x.total}，已独立验证 {x.verified}/{x.total}</p>);
  return <>{syllabusSummary}<EvidencePanel report={report}/></>;
}

function EvidencePanel({report}:{report:Report}) {
  return <><Alert type="info" message={report.coverage_note} style={{background:'#edf4ee',borderColor:'#d3e1d6'}}/><div className="v2-overview"><div><span>已完成任务</span><strong>{report.completed_tasks}<small> / {report.task_count}</small></strong></div><div><span>已答题目</span><strong>{report.answered}</strong></div><div><span>到期复习</span><strong>{report.due_reviews}</strong></div></div><h2>知识点与最新证据</h2>{report.knowledge.length?report.knowledge.map(k=><div className="v2-material" key={k.knowledge}><div><strong>{k.knowledge}</strong><p>{evidenceNames[k.kind]||'学习记录'} · {new Date(k.created_at).toLocaleDateString('zh-CN')}</p></div><Tag color={k.state==='待验证'?'gold':'green'}>{k.state}</Tag></div>):<Blank description="完成独立作答后，这里将显示知识点证据。"/>}</>;
}

type ChatHistoryPage = {items:{id:string;title:string;created_at:string}[];next_offset:number|null};
type ChatHistoryItem = {prompt:string;text?:string;citations?:Citation[];coverage_note?:string};

function ChatHistory({projectId}:{projectId:string}) {
  const [offset,setOffset]=useState(0);
  const [selected,setSelected]=useState<string>();
  const path='/learning-projects/'+projectId+'/chat-history';
  const history=useQuery({queryKey:[path,offset],queryFn:()=>apiV2<ChatHistoryPage>(path+'?offset='+offset)});
  const answer=useQuery({queryKey:[path,selected],queryFn:()=>apiV2<ChatHistoryItem>(path+'/'+selected),enabled:!!selected});
  return <State query={history}>{history.data&&<>
    {history.data.items.length===0&&<Blank description="本项目暂无可查看的答疑记录。"/>}
    {history.data.items.map(item=><div className="v2-note" key={item.id}>
      <Button type="link" onClick={()=>setSelected(item.id)}>{item.title}</Button>
      <span className="muted">{new Date(item.created_at).toLocaleString()}</span>
    </div>)}
    <Space>
      {offset>0&&<Button onClick={()=>setOffset(offset-20)}>上一页</Button>}
      {history.data.next_offset!==null&&<Button onClick={()=>setOffset(history.data?.next_offset??offset)}>下一页</Button>}
    </Space>
    <Modal title="答疑记录" open={!!selected} footer={null} onCancel={()=>setSelected(undefined)}>
      {selected&&<State query={answer}>{answer.data&&<>
        <h3>{answer.data.prompt}</h3>
        <p style={{whiteSpace:'pre-wrap'}}>{answer.data.text}</p>
        <p className="muted">{answer.data.coverage_note}</p>
        <CitationList projectId={projectId} citations={answer.data.citations??[]}/>
      </>}</State>}
    </Modal>
  </>}</State>;
}

function NotesPanel({projectId,disabled=false}:{projectId:string;disabled?:boolean}) {
  const path='/learning-projects/'+projectId+'/notes';
  const query=useQuery({queryKey:['v2-notes',projectId],queryFn:()=>apiV2<{id:string;title:string;body:string;kind:string}[]>(path)});
  const {run,busy}=useRun();
  const [form]=Form.useForm();
  const pending=useRef<{content:string;key:string}|undefined>(undefined);

  async function save(values:{kind:string;title:string;text:string}) {
    const content=JSON.stringify([path,values.kind,values.title,values.text]);
    const idempotencyKey=pending.current?.content===content?pending.current.key:key();
    pending.current={content,key:idempotencyKey};
    const result=await run(()=>apiV2(path,'POST',values,idempotencyKey),'已保存');
    if(result) {
      pending.current=undefined;
      form.resetFields();
    }
  }

  return <><Form form={form} layout="vertical" initialValues={{kind:'note'}} onFinish={save}>
    <Space>
      <Form.Item name="kind"><Select options={[{value:'note',label:'学习笔记'},{value:'flashcard',label:'记忆闪卡'}]} style={{width:130}}/></Form.Item>
      <Form.Item name="title" rules={[{required:true,whitespace:true}]}><Input placeholder="标题／卡片正面" maxLength={200}/></Form.Item>
    </Space>
    <Form.Item name="text" rules={[{required:true,whitespace:true}]}><Input.TextArea rows={4} placeholder="我的理解／卡片背面"/></Form.Item>
    <Button disabled={disabled} loading={busy} htmlType="submit">保存</Button>
  </Form><State query={query}>{query.data?.map(n=><article className="v2-note" key={n.id}>
    <Tag>{n.kind==='flashcard'?'闪卡':'笔记'}</Tag><h3>{n.title}</h3>
    {n.kind==='flashcard'?<details><summary>尝试回忆后查看</summary><p>{n.body}</p></details>:<p>{n.body}</p>}
  </article>)}</State></>;
}

type StudyData = {task:Task;project:Project;material?:Material;checkpoint:{text?:string;answer?:string[]};revision:number;question?:Question;result?:Result;ai_run_id?:string;native_solve?:boolean;native_lessons?:boolean;archived_review?:boolean};

export function StudyV2() {
  const {taskId}=useParams();
  const query=useQuery({queryKey:['v2-session',taskId],queryFn:()=>apiV2<StudyData>('/study-sessions/'+taskId)});
  return <State query={query}>{query.data&&<StudyContent key={taskId} data={query.data}/>}</State>;
}

function StudyContent({data}:{data:StudyData}) {
  const user = useUser();
  const scene = readLearningScene(user.id,data.project.id);
  const {run,busy}=useRun();const navigate=useNavigate();
  const [text,setText]=useState(data.checkpoint.text||'');const [answer,setAnswer]=useState<string[]>(data.checkpoint.answer||[]);
  const [revision,setRevision]=useState(data.revision);const [confidence,setConfidence]=useState('normal');
  const [prompt,setPrompt]=useState('');const [runId,setRunId]=useState<string|undefined>(data.ai_run_id||data.result?.run_id);const [hint,setHint]=useState('');
  const [readingQuestion,setReadingQuestion]=useState('');
  const t=data.task;const closed=['completed','cancelled'].includes(t.state)||!!data.result||!!data.archived_review;
  const [questionKind,setQuestionKind]=useState('single');
  const ai=useQuery({queryKey:['v2-run',runId],queryFn:()=>apiV2<Run>('/ai-runs/'+runId),enabled:!!runId,refetchInterval:q=>q.state.data&&['succeeded','failed','cancelled'].includes(q.state.data.state)?false:1500});
  const refresh=useRun();
  useEffect(()=>{if(ai.data?.state==='succeeded'&&['question','evaluate'].includes(ai.data.kind))void refresh.run(()=>Promise.resolve(true))},[ai.data?.state,ai.data?.kind]);
  async function save(){const result=await run(()=>apiV2<{revision:number}>('/study-sessions/'+t.id+'/checkpoint','PUT',{revision,text,answer}),'草稿已保存');if(result)setRevision(result.revision)}
  async function generate(){const result=await run(()=>apiV2<{run_id:string}>('/study-sessions/'+t.id+'/prepare','POST',{kind:questionKind},key()));if(result)setRunId(result.run_id)}
  async function ask(){const result=await run(()=>apiV2<{run_id:string}>('/learning-projects/'+data.project.id+'/ai-runs','POST',{kind:'chat',prompt,task_id:t.id},key()));if(result)setRunId(result.run_id)}
  async function lesson(kind:'solve'|'read'|'guide', request:string){const result=await run(()=>apiV2<{run_id:string}>('/learning-projects/'+data.project.id+'/ai-runs','POST',{kind,prompt:request,task_id:t.id},key()));if(result)setRunId(result.run_id)}
  return <><PageTitle title={t.title} description={t.reason} action={<Link to={'/learning/projects/'+data.project.id}>返回学习项目</Link>}/><div className="v2-study-grid"><section className="v2-reader"><Space><Tag>{names[t.kind]}</Tag><span>{data.material?.title}</span></Space><div className="v2-source-text">{data.material?.text||'暂无可阅读资料'}</div></section><section className="v2-learning-panel">
    <h2>{data.question?'独立尝试':'本次学习'}</h2>
    {scene&&scene!=='kaoyan'&&<p className="muted">{politicsPracticeNotice}</p>}
    {!data.question&&['practice','verification','review'].includes(t.kind)&&<Select aria-label="练习题型" value={questionKind} onChange={setQuestionKind} style={{width:180,marginBottom:16}} options={[{value:'single',label:'单选题'},{value:'multiple',label:'多选题'},{value:'essay',label:'分析题训练'}]}/>}
    {data.question?<><Tag>AI生成练习 · 原文引用已校验</Tag><h3>{data.question.prompt}</h3>{data.question.kind==='essay'?<Input.TextArea aria-label="分析题作答" rows={8} disabled={closed} value={text} onChange={e=>setText(e.target.value)}/>:data.question.kind==='single'?<Radio.Group disabled={closed} value={answer[0]} onChange={e=>setAnswer([e.target.value])}>{Object.entries(data.question.options).map(([k,v])=><Radio key={k} value={k}>{k}. {v}</Radio>)}</Radio.Group>:<Checkbox.Group disabled={closed} value={answer} onChange={v=>setAnswer(v as string[])} options={Object.entries(data.question.options).map(([k,v])=>({label:k+'. '+v,value:k}))}/>}
      {!closed&&<><p>对这次作答的信心</p><Radio.Group value={confidence} onChange={e=>setConfidence(e.target.value)} options={[{value:'low',label:'不太确定'},{value:'normal',label:'一般'},{value:'high',label:'有把握'}]}/><Space wrap style={{marginTop:20}}><Button loading={busy} onClick={save}>保存草稿</Button><Button onClick={async()=>{const r=await run(()=>apiV2<{hint:string}>('/study-sessions/'+t.id+'/hint','POST'));if(r)setHint(r.hint)}}>需要提示</Button><Button type="primary" loading={busy} onClick={async()=>{const result=await run(()=>apiV2<{result:Result}>('/study-sessions/'+t.id+'/submit','POST',{answer,response_text:text,confidence},key()),'作答已提交');if(result?.result.run_id)setRunId(result.result.run_id)}}>提交作答</Button></Space></>}
      {hint&&<Alert type="info" message={hint} description="本次将记录为辅助完成，不产生独立验证证据。"/>}
    </>:['reading','remediation'].includes(t.kind)?<><p>先理解原文，用自己的话记录。完成后将安排一道独立检查题。</p><Input.TextArea rows={5} placeholder="用自己的话写下理解与疑问" value={text} onChange={e=>setText(e.target.value)} disabled={closed}/><Space style={{marginTop:16}}><Button disabled={closed} loading={busy} onClick={save}>保存学习位置</Button><Button type="primary" disabled={closed} loading={busy} onClick={async()=>{const result=await run(()=>apiV2<{next_task_id:string}>('/study-sessions/'+t.id+'/complete','POST',{},key()),'已记录阅读，接下来独立检查');if(result)navigate('/learning/session/'+result.next_task_id)}}>完成阅读，检查理解</Button></Space></>:<><p>从本项目资料准备一道未做过的新题。服务未配置或生成失败时，会保留任务并显示原因。</p><Button type="primary" loading={busy||ai.data?.state==='running'||ai.data?.state==='queued'} disabled={closed} onClick={generate}>准备练习</Button></>}
    {data.result&&<Alert style={{marginTop:20}} type={data.result.correct?'success':'info'} message={data.result.evaluator==='ai_training'?'AI训练评价，不是正式成绩':data.result.correct?'本次回答正确':data.result.state==='pending_ai'?'正在等待AI训练评价':'本次需要补学'} description={data.result.feedback}/>}
    {data.result?.question&&<div className="v2-feedback">{data.result.question.kind==='essay'?<><p>参考评分要点</p><ul>{data.result.question.rubric?.map((item,i)=><li key={i}>{item}</li>)}</ul></>:<p>参考答案：{data.result.question.answer?.join('、')}</p>}<p>{data.result.question.explanation}</p><blockquote>{data.result.question.quote}</blockquote><Link to={'/learning/projects/'+data.project.id}><Button type="primary">查看下一步任务</Button></Link></div>}
    <Space wrap style={{marginTop:12}}>
      {data.native_solve&&t.state==='completed'&&data.result?.question&&<Button loading={busy} onClick={()=>lesson('solve','请讲解这道题')}>讲这道题</Button>}
      {data.native_lessons&&data.material&&['reading','remediation'].includes(t.kind)&&<Button loading={busy} onClick={()=>lesson('read','帮我精读这份讲义，找出关键概念和容易混淆的考点')}>读讲义</Button>}
      {data.native_lessons&&<Button loading={busy} onClick={()=>lesson('guide','围绕当前任务建议下一步复习：'+t.title)}>学习路径</Button>}
    </Space>
    {data.native_lessons&&ai.data?.kind==='read'&&ai.data.state==='succeeded'&&<Space.Compact style={{marginTop:12,width:'100%'}}><Input aria-label="精读追问" value={readingQuestion} onChange={e=>setReadingQuestion(e.target.value)} placeholder="就同一份讲义继续提问"/><Button loading={busy} disabled={!readingQuestion.trim()} onClick={()=>lesson('read',readingQuestion.trim())}>继续精读</Button></Space.Compact>}
    <hr/><h2>随学助教</h2><p className="muted">基于当前项目资料解释，保留问题与执行记录。</p><Input.TextArea aria-label="向助教提问" rows={3} value={prompt} onChange={e=>setPrompt(e.target.value)} placeholder="例如：这里的两个概念有什么区别？"/><Button style={{marginTop:12}} loading={busy} disabled={!prompt.trim()} onClick={ask}>解释我的问题</Button>
    {ai.data&&<div className="v2-ai-result"><Tag>{({queued:'排队中',running:'正在思考',cancel_requested:'正在停止',cancelled:'已停止',succeeded:'已完成',failed:'未完成'} as Record<string,string>)[ai.data.state]||ai.data.state}</Tag>{['queued','running'].includes(ai.data.state)&&<Button size="small" loading={busy} onClick={async()=>{await run(()=>apiV2('/ai-runs/'+runId+'/cancel','POST'));void ai.refetch()}}>停止生成</Button>}{ai.data.error&&<Alert type="error" message={ai.data.error}/>}<p>{ai.data.result.text}</p>{ai.data.result.coverage_note&&<small>{ai.data.result.coverage_note}</small>}{!!ai.data.result.citations?.length&&<CitationList projectId={data.project.id} citations={ai.data.result.citations}/>}</div>}
    {ai.data?.state==='failed'&&<Button loading={busy} onClick={async()=>{const result=await run(()=>apiV2<{run_id:string}>('/ai-runs/'+runId+'/retry','POST',{},key()));if(result)setRunId(result.run_id)}}>重试</Button>}
    {ai.data?.kind==='guide'&&ai.data.state==='succeeded'&&<><MasteryOutline outline={ai.data.result.outline}/>{!!ai.data.result.citations?.length&&<Button loading={busy} onClick={async()=>{const result=await run(()=>apiV2<{task_id:string}>('/ai-runs/'+runId+'/accept-guide','POST'),'已加入学习计划');if(result)navigate('/learning/session/'+result.task_id)}}>加入学习计划</Button>}</>}
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
  const project=q.data?.find(p=>p.id===selected);
  return <><PageTitle title="学习报告" description="查看助教学习进度与已经发生的作答证据。"/><Select style={{minWidth:240,marginBottom:24}} placeholder="选择学习项目" value={selected} onChange={setId} options={q.data?.map(p=>({value:p.id,label:p.title}))}/>
    {project&&<LearningSummary project={project}/>}
    {selected?<State query={report}><h2>历史作答证据</h2>{report.data&&<ReportPanel report={report.data}/>}</State>:<Blank description="创建项目并开始学习后，将逐步形成报告。"/>}</>;
}
