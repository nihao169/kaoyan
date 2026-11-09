import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { Alert, App as AntApp, Button, Checkbox, Form, Input, InputNumber, Modal, Radio, Select, Space, Tabs, Tag } from 'antd';
import { ArrowRightOutlined, PlusOutlined, ReadOutlined } from '@ant-design/icons';
import { api, apiV2, key, type Catalog } from './api';
import { Blank, PageTitle, State, useRun } from './ui';
import { CitationList, ExamResources, MaterialSearch, type Citation } from './v2-resources';
import { MasteryReviewQueue } from './mastery-reviews';
import { useUser } from './App';
import { LearningSceneOptions, learningScenes, politicsPracticeNotice, readLearningScene, saveLearningScene, type LearningScene } from './v2-scenes';
import './v2.css';

type Task = {id:string;project_id:string;project_title?:string;title:string;kind:string;reason:string;state:string;estimated_minutes:number;due_at?:string};
type Today = {tasks:Task[];deferred:Task[];projects:number;estimated_minutes:number};
type Project = {id:string;title:string;scenario:string;subject_id:string;exam_year:number;daily_minutes:number;target_score?:number;deadline?:string;state:string;revision:number};
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

function useToday(enabled=true) {
  return useQuery({queryKey:['v2-today'],queryFn:()=>apiV2<Today>('/today'),enabled});
}

export function TodayV2() {
  const query = useToday();
  return <><PageTitle title="今天，从这里继续" description="学一点，试一试，再用证据决定下一步。" action={<StartLearning label="开始新学习"/>}/><MasteryReviewQueue dueOnly/><State query={query}>{query.data&&<>
    <div className="v2-overview"><div><span>今日安排</span><strong>{query.data.estimated_minutes}<small> 分钟</small></strong></div><div><span>可执行任务</span><strong>{query.data.tasks.length}</strong></div><div><span>进行中的项目</span><strong>{query.data.projects}</strong></div></div>
    {query.data.tasks.length?<><div className="v2-section-heading"><h2>你的下一步</h2><span>每项安排都有原因</span></div><TaskList tasks={query.data.tasks}/></>:<Blank description="还没有今日任务。开始新学习，或到学习项目里继续添加资料。"/>}
    {!!query.data.deferred.length&&<Alert type="info" message={`${query.data.deferred.length} 项任务超出今日预算`} description="这些任务仍保留在项目中。可以调整学习时间，或先完成今天的重点。"/>}
    <div className="v2-loop"><span>学习与尝试</span><ArrowRightOutlined/><span>反馈与补学</span><ArrowRightOutlined/><span>独立验证</span><ArrowRightOutlined/><span>复习与下一轮</span></div>
  </>}</State></>;
}

export function ProjectsV2() {
  const user = useUser();
  const query = useQuery({queryKey:['v2-projects'],queryFn:()=>apiV2<Project[]>('/learning-projects')});
  return <><PageTitle title="我的学习项目" description="每个目标，都有自己的资料、计划和学习记录。" action={<StartLearning label="新建项目"/>}/>
    <State query={query}>{query.data?.length?<div className="v2-project-grid">{query.data.map(p=>{
      const scene = readLearningScene(user.id, p.id);
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

type ProjectForm = {title:string;exam_year?:number;daily_minutes:number;target_score?:number;deadline?:string};

function StartLearningDialog({onClose}:{onClose:()=>void}) {
  const user = useUser();
  const {message} = AntApp.useApp();
  const catalog = useQuery({queryKey:['catalog'],queryFn:()=>api<Catalog>('/catalog')});
  const projects = useQuery({queryKey:['v2-projects'],queryFn:()=>apiV2<Project[]>('/learning-projects')});
  const [scene,setScene] = useState<LearningScene>();
  const [step,setStep] = useState<'choose'|'create'|'existing'>('choose');
  const [projectId,setProjectId] = useState<string>();
  const {run,busy} = useRun();
  const navigate = useNavigate();
  const subject = catalog.data?.subjects.find(x=>x.code==='politics');
  const activeProjects = projects.data?.filter(p=>p.state==='active') ?? [];
  const defaultYear = new Date().getFullYear()+1;

  function openProject(id:string, selected:LearningScene) {
    const saved = saveLearningScene(user.id, id, selected);
    if (!saved) message.warning('浏览器未能记住场景，本次仍可使用。');
    onClose();
    navigate('/learning/projects/'+id, {state:saved?null:{learningScene:selected}});
  }

  async function create(values:ProjectForm) {
    if (!subject || !scene || busy) return;
    const project = await run(()=>apiV2<Project>('/learning-projects','POST',{
      title:values.title, daily_minutes:values.daily_minutes, subject_id:subject.id, scenario:'kaoyan',
      exam_year:scene==='kaoyan'?values.exam_year:defaultYear,
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
      {catalog.error&&<Alert type="error" message="暂时无法读取项目配置" action={<Button onClick={()=>catalog.refetch()}>重试</Button>}/>}
      <Form layout="vertical" initialValues={{exam_year:defaultYear,daily_minutes:45}} onFinish={create}>
        <Form.Item label={scene==='chapter'?'课程或章节名称':'项目名称'} name="title" rules={[{required:true,whitespace:true}]}>
          <Input autoFocus maxLength={200} placeholder={scene==='chapter'?'例如：统计学 · 第一章':scene==='final'?'例如：统计学期末复习':'例如：考研政治第一轮复习'}/>
        </Form.Item>
        {scene==='kaoyan'&&<Form.Item label="考试年份" name="exam_year" rules={[{required:true,type:'integer'}]}><InputNumber min={2026} max={2100}/></Form.Item>}
        <Form.Item label="每日学习时间（分钟）" name="daily_minutes" rules={[{required:true,type:'integer'}]}><InputNumber min={10} max={480}/></Form.Item>
        {scene==='kaoyan'&&<Form.Item label="目标分数（可选）" name="target_score"><InputNumber min={0} max={100} precision={0}/></Form.Item>}
        {scene==='final'&&<Form.Item label="考试日期（可选）" name="deadline"><Input type="date"/></Form.Item>}
        <Space wrap><Button autoInsertSpace={false} disabled={busy} onClick={()=>setStep('choose')}>返回</Button>
          <Button type="primary" htmlType="submit" loading={busy} disabled={!subject}>确认并创建学习计划</Button></Space>
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

function defaultProjectTab(scene:LearningScene|undefined, p:Detail) {
  if (!scene || p.state!=='active' || p.materials.some(m=>m.state==='ready')) return 'study';
  return scene==='kaoyan'?'annual':'materials';
}

function ProjectNextStep({p,scene,showTab}:{p:Detail;scene:LearningScene;showTab:(tab:string)=>void}) {
  const navigate = useNavigate();
  const hasMaterials = p.materials.some(m=>m.state==='ready');
  const today = useToday(hasMaterials);
  const bank = useQuery({queryKey:['v2-bank',p.id],queryFn:()=>apiV2<{id:string}[]>('/learning-projects/'+p.id+'/question-bank'),
    enabled:scene==='final'&&hasMaterials});
  const next = today.data?.tasks.find(t=>t.project_id===p.id);
  const canSelfTest = scene==='final'&&!bank.error&&!!bank.data?.length;
  const assessmentLink = `/learning/assessments?project=${encodeURIComponent(p.id)}${scene==='final'?'&mode=practice':''}`;
  const materialLabel = scene==='chapter'?'添加本章资料':scene==='final'?'添加考试范围内的资料':'添加复习资料';
  const actionLabel = scene==='chapter'&&next?.kind==='reading'?'开始阅读':'继续学习任务';

  return <section className="scene-next-step" aria-labelledby="project-next-step">
    <h2 id="project-next-step">下一步</h2>
    {!hasMaterials&&<p>{scene==='chapter'?'建议先添加一章的讲义，导入后即可开始阅读。':scene==='final'?'先添加考试范围内的讲义和复习提纲。':'先确认考试范围，或添加手头的讲义开始学习。'}</p>}
    {hasMaterials&&next&&<p>{next.title} · {next.estimated_minutes} 分钟</p>}
    {hasMaterials&&!next&&<p>{canSelfTest?'可以从已有题目开始自测，做完后查看反馈和补学安排。':'可以查看项目任务、学习记录或继续添加资料。'}</p>}
    <Space wrap>
      {!hasMaterials&&scene==='kaoyan'&&<Button type="primary" onClick={()=>showTab('annual')}>查看年度考纲与试卷</Button>}
      {!hasMaterials&&<Button type={scene==='kaoyan'?'default':'primary'} onClick={()=>showTab('materials')}>{materialLabel}</Button>}
      {hasMaterials&&next&&<Button type="primary" onClick={()=>navigate('/learning/session/'+next.id)}>{actionLabel}</Button>}
      {hasMaterials&&canSelfTest&&<Button type={next?'default':'primary'} onClick={()=>navigate(assessmentLink)}>开始成组练习</Button>}
      {hasMaterials&&scene==='chapter'&&<Button type={next?'default':'primary'} onClick={()=>showTab('notes')}>打开笔记与闪卡</Button>}
      {hasMaterials&&scene==='kaoyan'&&<Button onClick={()=>navigate(assessmentLink)}>练习或模考</Button>}
      {hasMaterials&&scene!=='chapter'&&<Button onClick={()=>showTab('report')}>查看学习反馈</Button>}
      {hasMaterials&&!next&&!canSelfTest&&<Button onClick={()=>showTab('study')}>查看项目任务</Button>}
    </Space>
    {scene==='final'&&hasMaterials&&bank.isSuccess&&!bank.data.length&&<p className="muted">项目暂无可用题目。可以先阅读资料并使用学习任务里的理解检查。</p>}
    {scene==='final'&&hasMaterials&&bank.error&&<p className="muted">暂时无法读取题库。可以继续复习，或 <Button type="link" size="small" onClick={()=>bank.refetch()}>重试读取题库</Button>。</p>}
  </section>;
}

function ProjectContent({p}:{p:Detail}) {
  const user = useUser();
  const {state} = useLocation();
  const {run,busy}=useRun();
  const {modal,message}=AntApp.useApp();
  const [scene,setScene] = useState<LearningScene|undefined>(()=>readLearningScene(user.id,p.id) ?? state?.learningScene);
  const [sceneOpen,setSceneOpen] = useState(false);
  const [selectedScene,setSelectedScene] = useState<LearningScene>();
  const [tab,setTab] = useState(()=>defaultProjectTab(scene,p));
  const [materialOpen,setMaterialOpen]=useState(false);
  const materialAction = useRef<HTMLButtonElement>(null);
  const projectContent = useRef<HTMLElement>(null);
  const [uploading,setUploading]=useState(false);
  const courses=useQuery({queryKey:['v2-courses'],queryFn:()=>apiV2<{id:string;title:string;version:number}[]>('/course-materials')});
  const [selectedCourse,setSelectedCourse]=useState<string>();
  const [form]=Form.useForm();
  const active=p.state==='active';
  const description = [
    scene?learningScenes[scene].title:`${p.exam_year} 考研政治`,
    scene==='kaoyan'?`${p.exam_year} 考研政治`:null,
    scene==='final'&&p.deadline?`考试日期 ${p.deadline}`:null,
    `每日 ${p.daily_minutes} 分钟`, `计划版本 ${p.revision}`,
  ].filter(Boolean).join(' · ');

  function changeScene() {
    if (!selectedScene) return;
    if (!saveLearningScene(user.id,p.id,selectedScene)) message.warning('浏览器未能记住场景，本次仍可使用。');
    setScene(selectedScene);
    setTab(defaultProjectTab(selectedScene,p));
    setSceneOpen(false);
  }

  function showTab(next:string) {
    setTab(next);
    requestAnimationFrame(()=>{
      projectContent.current?.scrollIntoView({block:'start'});
      const target=next==='materials'?materialAction.current:projectContent.current;
      target?.focus({preventScroll:true});
    });
  }

  async function upload(file:File) {
    setUploading(true);
    const body=new FormData();body.append('file',file);
    try {await run(()=>apiV2('/learning-projects/'+p.id+'/uploads','POST',body),'资料已导入，阅读任务已加入计划')} finally {setUploading(false)}
  }
  const materialPanel=<><Space wrap><Button ref={materialAction} type="primary" disabled={!active} onClick={()=>setMaterialOpen(true)}>粘贴学习资料</Button><label className="v2-file-button">{uploading?'正在导入…':'上传 PDF / Word / 文本'}<input type="file" disabled={uploading||!active} accept=".pdf,.docx,.txt,.md" onChange={e=>{if(e.target.files?.[0])void upload(e.target.files[0]);e.target.value=''}}/></label></Space>
    <div className="v2-course-picker"><Select style={{minWidth:230}} placeholder="选择教师已启用的课程资料" value={selectedCourse} onChange={setSelectedCourse} options={courses.data?.map(c=>({value:c.id,label:c.title+' · v'+c.version}))}/><Button disabled={!selectedCourse||!active} onClick={()=>run(()=>apiV2('/learning-projects/'+p.id+'/course-materials','POST',{source_version_id:selectedCourse}),'已加入项目')}>加入课程资料</Button></div>
    <p className="muted">个人资料默认私有。扫描件需先 OCR；目前每份最多 20 MB、正文30万字。</p>
    {active&&<TutorIndexPanel projectId={p.id}/>}
    {p.materials.filter(m=>m.state==='ready').map(m=><div className="v2-material" key={m.id}><ReadOutlined/><div><strong>{m.title}</strong><p>{m.source_version_id?'关联课程资料，使用时检查当前权限':'个人资料 · 仅自己可用'}</p></div><Button danger type="text" disabled={!active} onClick={()=>modal.confirm({title:'移除这份学习资料？',content:'关联任务将停止，历史记录保留，旧助教运行不再继续使用。',onOk:()=>run(()=>apiV2('/learning-projects/'+p.id+'/materials/'+m.id,'DELETE'),'资料已移除')})}>移除</Button></div>)}
    {p.materials.some(m=>m.state==='ready')?<MaterialSearch projectId={p.id}/>:<Blank description="添加资料后，系统会安排第一项学习任务。"/>}</>;
  return <><PageTitle title={p.title} description={description} action={<Space wrap>
    {active&&<Button onClick={()=>{setSelectedScene(scene);setSceneOpen(true)}}>{scene?'切换场景':'选择场景'}</Button>}
    <Link to="/learning/projects">返回项目列表</Link>
  </Space>}/>
    {!active&&<Alert type="info" message="项目已归档，保留历史记录"/>}
    {active&&scene&&<ProjectNextStep p={p} scene={scene} showTab={showTab}/>}
    {scene&&scene!=='kaoyan'&&<p className="muted">{politicsPracticeNotice}</p>}
    <MasteryOutline outline={p.mastery_outline}/>
    <section ref={projectContent} className="v2-project-content" aria-label="项目学习内容" tabIndex={-1}>
    <Tabs activeKey={tab} onChange={setTab} items={[
      {key:'study',label:'学习与任务',children:<>{p.tasks.length?<TaskList tasks={p.tasks}/>:<Blank description="先在“课程与资料”中选择材料。"/>}{active&&!!p.tasks.filter(t=>t.state==='deferred').length&&<Button onClick={()=>run(()=>Promise.all(p.tasks.filter(t=>t.state==='deferred').map(t=>apiV2('/tasks/'+t.id,'PATCH',{state:'todo'}))),'已恢复暂缓任务')}>恢复暂缓任务</Button>}</>},
      {key:'materials',label:'课程与资料',children:materialPanel},
      {key:'annual',label:'年度考纲与试卷',children:<ExamResources projectId={p.id} examYear={p.exam_year} active={active}/>},
      {key:'notes',label:'笔记与闪卡',children:<NotesPanel projectId={p.id} disabled={!active}/>},
      {key:'chat-history',label:'答疑记录',children:<ChatHistory key={p.id} projectId={p.id}/>},
      {key:'report',label:'证据与报告',children:<ReportPanel report={p.report}/>},
      {key:'plan',label:'计划设置',children:<><Form layout="vertical" key={p.revision} initialValues={{daily_minutes:p.daily_minutes,target_score:p.target_score,deadline:p.deadline}} onFinish={values=>run(()=>apiV2('/learning-projects/'+p.id+'/plans','POST',{...values,deadline:values.deadline||null,revision:p.revision},key()),'计划已更新，历史版本已保留')}><Form.Item name="daily_minutes" label="每日时间预算（分钟）"><InputNumber min={10} max={480} disabled={!active}/></Form.Item><Form.Item name="target_score" label="目标分数"><InputNumber min={0} max={100} disabled={!active}/></Form.Item><Form.Item name="deadline" label={scene==='final'?'考试日期（可选）':'目标日期（可选）'}><Input type="date" disabled={!active}/></Form.Item><Button htmlType="submit" type="primary" loading={busy} disabled={!active}>确认调整计划</Button></Form><Button danger style={{marginTop:32}} disabled={!active} onClick={()=>modal.confirm({title:'归档学习项目？',content:'项目将退出今日计划，历史记录仍保留。',onOk:()=>run(()=>apiV2('/learning-projects/'+p.id+'/archive','POST'),'已归档')})}>归档项目</Button></>},
    ]}/>
    </section>
    <Modal title="选择学习场景" open={sceneOpen} okText="应用场景" cancelText="取消"
      okButtonProps={{disabled:!selectedScene}} onOk={changeScene} onCancel={()=>setSceneOpen(false)}>
      <LearningSceneOptions value={selectedScene} onChange={setSelectedScene}/>
      <p className="muted">场景决定页面引导。资料、作答和进度仍在当前项目。</p>
    </Modal>
    <Modal title="添加个人学习资料" open={materialOpen} onCancel={()=>setMaterialOpen(false)} footer={null}><Form form={form} layout="vertical" onFinish={async values=>{const result=await run(()=>apiV2('/learning-projects/'+p.id+'/materials','POST',values,key()),'资料已添加');if(result){setMaterialOpen(false);form.resetFields()}}}><Form.Item name="title" label="资料标题" rules={[{required:true,whitespace:true}]}><Input maxLength={200}/></Form.Item><Form.Item name="text" label="资料正文" rules={[{required:true,whitespace:true}]}><Input.TextArea rows={12} maxLength={300000}/></Form.Item><Button type="primary" htmlType="submit" loading={busy}>保存并加入学习计划</Button></Form></Modal>
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
  return <><PageTitle title="学习报告" description="查看已经发生的学习和证据，让下一步更清楚。"/><Select style={{minWidth:240,marginBottom:24}} placeholder="选择学习项目" value={selected} onChange={setId} options={q.data?.map(p=>({value:p.id,label:p.title}))}/>{selected?<State query={report}>{report.data&&<ReportPanel report={report.data}/>}</State>:<Blank description="创建项目并开始学习后，将逐步形成报告。"/>}</>;
}
