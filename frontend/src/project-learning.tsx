import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { MenuUnfoldOutlined } from '@ant-design/icons';
import { Alert, App, Button, Checkbox, Collapse, Drawer, Form, Input, InputNumber, Modal, Select, Space, Steps, Tag } from 'antd';
import { Link, useNavigate } from 'react-router-dom';
import { ApiError, apiV2, key } from './api';
import { Blank, State, useRun } from './ui';
import { LearningSceneOptions, type LearningScene } from './v2-scenes';
import { ConcentratedPractice } from './personal-learning';
import { ProjectReviewQueue, ReviewQuestion, type NativeQuestion } from './mastery-reviews';

export type LearningProject = {id:string;title:string;scenario:LearningScene;course_name:string;learning_goal:string;
  scene_confirmed:boolean;revision:number;exam_year:number;state:string};
type Point = {id:string;name:string;status:string;mastery:number;mastery_source:string};
type Curriculum = {path_revision:number;map:{counts:{mastered:number;total:number};modules:{id:string;name:string;knowledge_points:Point[]}[]};
  next:{reason?:string;knowledge_point_name?:string};reviews:{due:boolean;knowledge_point_name?:string;due_at?:number}[]};
type Batch={id:string;date?:string;state:string;budget?:number;seconds:number;error?:string;completed:number;last_question:boolean;question_id?:string;
  items:{id:string;name:string;minutes?:number;review?:boolean;result?:string;explained?:boolean}[]};
type LearningState = {state:string;error?:string;mode?:string;intake?:boolean;reading?:boolean;request_id?:string;question:NativeQuestion|null;
  messages:{role:string;content:string}[];curriculum?:Curriculum;has_materials?:boolean;
  command?:{id:string;state:string;error:string;label?:string};writable?:boolean;
  followup?:{state:string;submission_id?:string};
  due_reviews?:{id:string;name:string;in_daily_plan:boolean;can_start:boolean}[];
  daily_plan?:Batch;stage?:Batch;stage_sizes?:Record<string,number>;chapter_practice_id?:string;
  preparation?:Preparation;workflow?:Workflow};
type Preparation = {ready:boolean;too_many:boolean; checks:{id:string;label:string;state:string;
  items:{id:string;title:string;state:string;error:string}[]}[];
  scope_options:{id:string;title:string;sections:string[]}[];
  scope:{text?:string;file_id?:string;material_ids?:string[];sections?:{material_id:string;title:string}[]};
  papers:{id:string;title:string;year:number}[]};
type Workflow = {steps:string[];step:number;confirm_outline:boolean;actions:{id:string;label:string}[];
  practice_id?:string;mock_id?:string;mock_ready:boolean};
const running = new Set(['created','queued','running','recovering','cancel_requested']);
const readiness:Record<string,string>={ready:'就绪',missing:'待补齐',indexing:'正在建立索引',queued:'等待索引',running:'正在建立索引',failed:'需要处理'};

export function NativeLearningOverview() {
  const projects=useQuery({queryKey:['v2-projects'],queryFn:()=>apiV2<(LearningProject&{daily_minutes:number})[]>('/learning-projects')});
  return <State query={projects}>{projects.data?.filter(p=>p.state==='active').map(p=><LearningSummary key={p.id} project={p}/>)}
    {!projects.data?.some(p=>p.state==='active')&&<Blank description="创建一个学习项目，与助教一起确定目标和下一步。"/>}</State>;
}

export function LearningSummary({project}:{project:LearningProject&{daily_minutes:number}}) {
  const query=useQuery({queryKey:['project-learning',project.id,project.revision],queryFn:()=>apiV2<LearningState>('/learning-projects/'+project.id+'/learning'),enabled:project.scene_confirmed});
  const curriculum=query.data?.curriculum;
  return <article className="v2-task"><div><h2>{project.title}</h2><p>{project.course_name||'待确认课程'} · 每日 {project.daily_minutes} 分钟</p>
    <p>{!project.scene_confirmed?'先确认学习背景':query.error?'暂时无法读取助教进度，可进入项目重试':curriculum?
      `已掌握 ${curriculum.map.counts.mastered}/${curriculum.map.counts.total} 个知识点 · ${curriculum.reviews.filter(r=>r.due).length} 项到期复习`:'与助教一起确定下一步'}</p>
      {query.data?.daily_plan&&<p>今日任务已完成 {query.data.daily_plan.completed} / {query.data.daily_plan.items.length} 项</p>}
      {curriculum?.next.reason&&<p>助教建议：{curriculum.next.reason}</p>}</div>
    <Link to={'/learning/projects/'+project.id}><Button type="primary">{project.scene_confirmed?'继续学习':'确认并开始'}</Button></Link></article>;
}

export function LearningHistory({projectId}:{projectId:string}) {
  const path='/learning-projects/'+projectId+'/learning-history';
  const query=useQuery({queryKey:[path],queryFn:()=>apiV2<{id:string;created_at:string}[]>(path)});
  return <State query={query}>{!!query.data?.length&&<section className="panel section-space">
    <h3>以前的助教学习路径</h3>
    <Collapse items={query.data.map(item=>({key:item.id,
      label:new Date(item.created_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}),
      children:<HistoryPath path={path+'/'+item.id}/> }))}/>
  </section>}</State>;
}

function HistoryPath({path}:{path:string}) {
  const query=useQuery({queryKey:[path],queryFn:()=>apiV2<{map?:Curriculum['map'];evidence?:{count:number}}>(path)});
  const map=query.data?.map;
  return <State query={query}>{map?.modules.length?<><p>已掌握 {map.counts.mastered} / {map.counts.total} 个知识点，
    已记录 {query.data?.evidence?.count??0} 次理解检查。</p>
    <ul>{map.modules.map(module=><li key={module.id}>{module.name}
      <ul>{module.knowledge_points.map(point=><li key={point.id}>{point.name} · {point.status==='mastered'?'已掌握':point.status==='learning'?'学习中':'待学习'}</li>)}</ul>
    </li>)}</ul></>:<p>该路径尚未保存大纲。</p>}</State>;
}

export function LearningProfileForm({project,onDone}:{project:LearningProject;onDone?:()=>void}) {
  const {run,busy} = useRun();
  const [scene,setScene] = useState<LearningScene>(project.scenario);
  return <Form layout="vertical" initialValues={{course_name:project.course_name||project.title,
    learning_goal:project.learning_goal,exam_year:project.exam_year}} onFinish={async values=>{
      const result=await run(()=>apiV2('/learning-projects/'+project.id+'/learning-profile','PUT',{
        ...values,scenario:scene,revision:project.revision},key()),'学习背景已保存');
      if(result)onDone?.();
    }}>
    <p>选择场景后，项目会显示所需资料和学习阶段。</p>
    <LearningSceneOptions value={scene} onChange={setScene}/>
    <Form.Item name="course_name" label="课程名称" rules={[{required:true,whitespace:true}]}><Input maxLength={200}/></Form.Item>
    <Form.Item name="learning_goal" label="学习目标与范围"><Input.TextArea rows={3} maxLength={2000}
      placeholder="希望学会什么？考试范围是什么？也可以稍后与助教讨论。"/></Form.Item>
    {scene==='kaoyan'&&<Form.Item name="exam_year" label="考研年份" rules={[{required:true,type:'integer'}]}><InputNumber min={2026} max={2100}/></Form.Item>}
    {project.scene_confirmed&&<p className="muted">已有学习记录保留。目标变化后，请与助教讨论大纲调整，再确认修改。</p>}
    <Button htmlType="submit" type="primary" loading={busy}>确认学习背景</Button>
  </Form>;
}

export function ProjectLearning({project,materials,showMaterials,chooseMaterials,uploadingMaterials,showAnnual}:{project:LearningProject;
  materials:{id:string;title:string;state:string;text?:string}[];showMaterials:()=>void;
  chooseMaterials:()=>void;uploadingMaterials:boolean;
  showAnnual:(kind:'syllabus'|'past_paper')=>void}) {
  const path='/learning-projects/'+project.id+'/learning';
  const {run,busy}=useRun();
  const [followup,setFollowup]=useState('');
  const [clarification,setClarification]=useState('');
  const [answers,setAnswers]=useState<Record<string,string>>({});
  const [selectedMaterial,setSelectedMaterial]=useState<string>();
  const [selectedNotes,setSelectedNotes]=useState<string[]>([]);
  const [showNotes,setShowNotes]=useState(false);
  const [outlineOpen,setOutlineOpen]=useState(false);
  const [practiceOpen,setPracticeOpen]=useState(false);
  const [scopeOpen,setScopeOpen]=useState(false);
  const [summaryOpen,setSummaryOpen]=useState(false);
  const messagesRef=useRef<HTMLDivElement>(null);
  const lastQuestion=useRef('');
  const submission=useRef<{body:string;key:string}|undefined>(undefined);
  const query=useQuery({queryKey:['project-learning',project.id,project.revision],
    queryFn:()=>apiV2<LearningState>(path),enabled:project.scene_confirmed,
    refetchInterval:q=>running.has(q.state.data?.state??'')||running.has(q.state.data?.command?.state??'')
      ||q.state.data?.daily_plan?.state==='planning'
      ||q.state.data?.preparation?.checks.some(check=>check.items.some(item=>item.state==='indexing'||running.has(item.state)))?2000:
      q.state.data?.preparation?.checks.some(check=>check.items.some(item=>
        item.state==='failed'&&item.error.startsWith('DEEPTUTOR_KNOWLEDGE_UNAVAILABLE')))?10000:false});
  const notes=useQuery({queryKey:['project-learning-notes',project.id],queryFn:()=>apiV2<{id:string;title:string}[]>(
    '/learning-projects/'+project.id+'/notes'),enabled:showNotes});
  const data=query.data;
  const messageCount=data?.messages.length;
  const latestMessage=data?.messages.at(-1)?.content;
  useEffect(()=>{
    const messages=messagesRef.current;
    if(messages)messages.scrollTop=messages.scrollHeight;
  },[messageCount,latestMessage]);
  const prep=data?.preparation;
  const flow=data?.workflow;
  const question=data?.question;
  const requestId=data?.request_id??'';
  useEffect(()=>{
    if(lastQuestion.current!==requestId){setAnswers({});setClarification('');lastQuestion.current=requestId;}
  },[requestId]);
  const processing=running.has(data?.state??'')||running.has(data?.command?.state??'');
  const disabled=busy||processing||project.state!=='active'||data?.writable===false;
  const awaiting=!!question||data?.state==='waiting_input';
  const daily=data?.daily_plan;
  const pausedCard=daily?.state==='paused'&&daily.question_id===requestId;
  const processingNotice=data?.command?.label?'正在处理「'+data.command.label+'」':'助教正在处理，重新打开项目也可继续。';
  const countTime=daily?.state==='active'&&data?.writable!==false&&!processing&&!data?.reading&&!summaryOpen&&!practiceOpen;
  useEffect(()=>{
    if(!countTime)return;
    const ping=()=>{if(document.visibilityState==='visible'&&document.hasFocus())
      void apiV2<{reached:boolean}>(path+'/activity','POST').then(result=>{if(result.reached)void query.refetch();}).catch(()=>{});};
    ping();
    const timer=window.setInterval(ping,8000);
    return ()=>window.clearInterval(timer);
  },[countTime,path,query.refetch]);
  async function send(body:Record<string,unknown>) {
    const serialized=JSON.stringify(body);
    if(submission.current?.body!==serialized)submission.current={body:serialized,key:key()};
    const result=await run(()=>apiV2(path,'POST',body,submission.current!.key));
    if(result){
      submission.current=undefined;
      if(body.operation==='answer'){setClarification('');setAnswers({});}
      if(body.operation==='message')setFollowup('');
    }
    void query.refetch();
    return result;
  }
  const guided=(action_id:string,extra:Record<string,unknown>={})=>send({operation:'guided',action_id,...extra});
  const grouped=Object.fromEntries((question?.questions??[]).filter(q=>answers[q.question_id]?.trim()).map(q=>[q.question_id,answers[q.question_id]]));
  const answer=question?answers[question.question_id]??'':clarification;
  const dailyCanContinue=daily?.state==='ready'||daily?.state==='paused'||(daily?.state==='active'&&!awaiting);
  const canAsk=project.state==='active'&&data?.writable!==false&&prep?.ready!==false;

  if(!project.scene_confirmed)return <section className="learning-intake"><h2>先确认这个项目怎样学习</h2>
    <LearningProfileForm project={project}/></section>;
  const staleOnTimeout=!!query.data&&query.error instanceof ApiError&&query.error.status===503;
  const hasSavedLearning=!!(data?.curriculum||data?.messages.length||question);
  return <State query={staleOnTimeout?{...query,error:null}:query}>{flow&&<Steps className="guided-steps" responsive current={summaryOpen?3:flow.step}
    items={flow.steps.map(title=>({title}))}/>}
    {prep&&!prep.ready&&<section className="panel guided-preparation" aria-label="准备资料">
      <h2>准备资料</h2>
      {hasSavedLearning&&<p>已保存的学习记录可在下方查看。资料就绪后即可继续学习。</p>}
      {prep.checks.map(check=><div className="v2-material" key={check.id}>
        <div><strong>{check.label}</strong> <Tag color={check.state==='ready'?'green':undefined}>{readiness[check.state]}</Tag>
          {check.items.map(item=><p key={item.id}>{item.title} · {readiness[item.state]??item.state}{item.error&&' · '+item.error}</p>)}
        </div>
        {project.state==='active'&&<Space wrap>
          <Button loading={check.id==='books'&&uploadingMaterials}
            onClick={()=>check.id==='syllabus'?showAnnual('syllabus'):check.id==='scope'?setScopeOpen(true):chooseMaterials()}>
            {check.id==='syllabus'?'导入考纲':check.id==='scope'?'确认考试范围':'导入教材或讲义'}</Button>
          {check.items.some(item=>['missing','failed'].includes(item.state))&&<Button loading={busy}
            onClick={()=>run(()=>apiV2('/learning-projects/'+project.id+'/tutor-index','POST'))}>准备或重试索引</Button>}
        </Space>}
      </div>)}
      {prep.too_many&&<Alert type="warning" showIcon message="每条学习路径最多使用 16 份资料，请在课程与资料中整理。"/>}
      {project.scenario==='kaoyan'&&<p>考纲和教材就绪后可以开始。到历年真题阶段时再补一套有答案的往年试卷。</p>}
      {!hasSavedLearning&&<Button type="primary" disabled>{project.scenario==='final'?'生成复习范围':project.scenario==='kaoyan'?'生成考纲学习路线':'生成学习大纲'}</Button>}
    </section>}
    {project.state==='active'&&<section className="panel section-space" aria-label="到期复习">
      <h3>到期复习</h3>
      {!!data?.due_reviews?.length&&<ul>{data.due_reviews.filter(item=>item.in_daily_plan||item.can_start).map(item=><li key={item.id}><Space wrap>
        <span>{item.name}</span>
        {item.in_daily_plan?<Tag>已安排在今日任务</Tag>:
          <Button disabled={disabled||awaiting||data.reading||['active','paused'].includes(data.stage?.state??'')}
            onClick={()=>guided('due_review',{review_objective:item.id})}>开始复习</Button>}
      </Space></li>)}</ul>}
      {data?.mode==='review'&&awaiting&&!pausedCard&&<p>复习已开始，请继续下方题卡。</p>}
      <ProjectReviewQueue projectId={project.id} disabled={busy||processing||awaiting||staleOnTimeout}
        hasGuided={!!data?.due_reviews?.some(item=>item.in_daily_plan||item.can_start)||data?.mode==='review'&&awaiting}
        exclude={new Set((data?.due_reviews??[]).filter(item=>item.in_daily_plan).map(item=>item.name))}/>
    </section>}
    {(!prep||prep.ready||hasSavedLearning)&&<section className="native-learning" aria-label="项目引导学习">
    <div className="native-learning-heading"><div><h2>{data?.reading?'资料精读':'与助教一起学习'}</h2>
      <p>{project.course_name} · {data?.intake?'先聊目标与基础':({outline:'讨论大纲',study:'学习',review:'复习'}[data?.mode??'']??'准备学习')}</p></div>
      <Space wrap><Button icon={<MenuUnfoldOutlined aria-hidden="true"/>} aria-haspopup="dialog" aria-expanded={outlineOpen}
        onClick={()=>setOutlineOpen(true)}>学习大纲</Button>
        <Button disabled={disabled} onClick={showMaterials}>课程与资料</Button>
        {project.scenario==='final'&&prep&&<Button disabled={disabled} onClick={()=>setScopeOpen(true)}>调整考试范围</Button>}
        {project.scenario==='kaoyan'&&prep&&<a href="#past-paper-step">进入真题阶段</a>}
        {data?.reading&&<Button disabled={disabled||awaiting} onClick={()=>send({operation:'mode',mode:data.curriculum?.map.modules.length?'study':'outline'})}>返回引导学习</Button>}
        <Button onClick={()=>setPracticeOpen(true)}>集中练习</Button></Space></div>
    {data?.intake&&<Alert type="info" showIcon message="可以先与助教明确目标和基础"
      description="正式教学需要课程资料或个人资料，以及已就绪的助教索引。" action={<Button onClick={showMaterials}>准备资料</Button>}/>}
    {data?.command?.state==='failed'&&<Alert type="error" showIcon message={data.command.error||'学习请求未完成'}
      action={<Button disabled={data?.writable===false} loading={busy} onClick={()=>run(()=>apiV2(path+'/retry','POST'))}>恢复原请求</Button>}/>}
    {data?.error&&<Alert type="error" showIcon message={data.error}/>}
    {staleOnTimeout&&<Alert type="warning" showIcon message="暂时无法刷新学习进度，正在显示上次读取的记录"
      action={<Button onClick={()=>query.refetch()}>重试</Button>}/>}
    {daily&&<details className="native-daily" key={daily.id}>
      <summary><span>今日任务</span><span className="native-daily-meta">
        {daily.state==='planning'?'安排中':daily.state==='paused'?'已暂停 · ':daily.error?'需要处理 · ':''}
        {daily.state!=='planning'&&`已完成 ${daily.completed}/${daily.items.length} 项`}
      </span></summary>
      <div className="native-daily-content">
      <p>{daily.date} · 每日 {daily.budget} 分钟 · 已学习 {Math.floor(daily.seconds/60)} 分钟</p>
      {daily.state==='planning'&&<p>助教正在安排今日任务。</p>}
      {daily.state==='budget_reached'&&<p>今日时间预算已用完，未完成的任务会用于安排下一次学习。</p>}
      {daily.state==='completed'&&<p>今日任务已完成。</p>}
      {daily.error&&<Alert type="warning" showIcon message={daily.error}/>}
      <ol>{daily.items.map(item=><li key={item.id}>{item.name} · {item.minutes} 分钟{item.review?' · 到期复习':''} · {item.result?item.result==='correct'?'已完成检查':'待巩固':'待完成'}</li>)}</ol>
      <Space wrap>
        {pausedCard&&<Button type="primary" disabled={disabled||data?.reading}
          onClick={()=>guided('chapter_continue')}>继续今日任务</Button>}
        {daily.state==='active'&&<Button disabled={busy} onClick={()=>guided('chapter_pause')}>暂停学习</Button>}
        <Button disabled={busy||project.state!=='active'} onClick={async()=>{
          if(data?.writable===false||await guided('chapter_summary'))setSummaryOpen(true);
        }}>查看学习小结</Button>
      </Space>
      {data?.chapter_practice_id&&<p><Link to={'/learning/assessments/'+data.chapter_practice_id}>打开生成的章节练习</Link></p>}
      </div>
    </details>}
    {data?.stage&&data.stage.state!=='completed'&&<p>本组已完成 {data.stage.completed}/{data.stage.items.length} 道检查{data.stage.error?' · '+data.stage.error:''}</p>}
    {flow?.actions.some(action=>data?.stage_sizes?.[action.id]===0)&&
      <Alert type="warning" showIcon message="当前资料中没有可核对的检查题范围，请补充资料或调整考试范围。"/>}
    <Drawer title="学习大纲" placement="left" width="min(380px, 100vw)" open={outlineOpen}
      closable={{'aria-label':'关闭学习大纲'}} onClose={()=>setOutlineOpen(false)} destroyOnHidden>
      <div className="native-curriculum">
      {data?.curriculum?.map.modules.length?<><p>已掌握 {data.curriculum.map.counts.mastered} / {data.curriculum.map.counts.total} 个知识点</p>
        <div className="native-map">{data.curriculum.map.modules.map(module=><details key={module.id}><summary>{module.name}</summary>
          <ol>{module.knowledge_points.map(point=><li key={point.id}><span>{point.name}</span>
            <Tag color={point.status==='mastered'?'green':undefined}>{point.status==='mastered'?'已掌握':point.status==='learning'?'学习中':'待学习'}{point.mastery_source==='learner'?' · 自评':''}</Tag></li>)}</ol>
        </details>)}</div>
        {!!data.curriculum.reviews.length&&<p>复习安排 {data.curriculum.reviews.length} 项，其中 {data.curriculum.reviews.filter(r=>r.due).length} 项已到期。</p>}
      </>:<p className="muted">先告诉助教你想达到什么目标，再一起确定大纲。</p>}
      <hr/><h3>资料与笔记</h3>
      <Select aria-label="选择精读资料" placeholder="选择一份资料精读" value={selectedMaterial} onChange={setSelectedMaterial}
        options={materials.filter(m=>m.state==='ready').map(m=>({value:m.id,label:m.title}))}/>
      <Button disabled={disabled||awaiting||!selectedMaterial} onClick={async()=>{
        if(await send({operation:'read',material_id:selectedMaterial}))setOutlineOpen(false);
      }}>打开精读</Button>
      <Button disabled={disabled} onClick={()=>setShowNotes(!showNotes)}>选取笔记讨论大纲</Button>
      {showNotes&&<State query={notes}><Checkbox.Group value={selectedNotes} onChange={setSelectedNotes}
        options={notes.data?.map(note=>({value:note.id,label:note.title}))}/>
        {!notes.data?.length&&<p className="muted">先在笔记与闪卡中保存自己的理解。</p>}
        <Button disabled={disabled||awaiting||!selectedNotes.length} onClick={async()=>{
          if(await send({operation:'notes',note_ids:selectedNotes}))setOutlineOpen(false);
        }}>交给助教讨论</Button></State>}
      </div>
    </Drawer>
    <section className="native-conversation" aria-label="学习助教对话">
      <div className="native-messages" ref={messagesRef} aria-live="polite">
        {data?.messages.length?data.messages.map((message,i)=><article key={i} className={'native-message '+message.role}>
          <strong>{message.role==='user'?'我':'学习助教'}</strong><p>{message.content}</p></article>):
          <p className="native-empty-message">{question?'先完成下方的理解检查。':daily?'展开「今日任务」查看学习安排。':'资料已就绪。点击下方按钮，让助教准备本项目的学习安排。'}</p>}
      </div>
      {question&&<div className="native-question"><h3>{[daily,data?.stage].some(batch=>batch?.last_question&&batch.question_id===requestId)?'最后一题':'当前理解检查'}</h3>
        {project.state!=='active'?<Alert type="info" showIcon message="项目已归档，这道题只能查看。"/>:
          data?.writable===false?<Alert type="warning" showIcon message="学习资料尚未就绪，暂时不能作答。"/>:
          processing?<Alert type="info" showIcon message={processingNotice}/>:
          pausedCard?<Alert type="info" showIcon message={data?.reading?'今日学习已暂停，请先返回引导学习。':'今日学习已暂停，继续学习后可作答。'}
            action={!data?.reading&&<Button size="small" type="primary" loading={busy}
              onClick={()=>guided('chapter_continue')}>继续学习</Button>}/>:
          busy?<Alert type="info" showIcon message="正在提交，请稍候。"/>:null}
        <ReviewQuestion question={question} answers={answers}
          setAnswer={(id,value)=>setAnswers(previous=>({...previous,[id]:value}))} disabled={disabled||pausedCard}/></div>}
      {processing?(!question&&<Alert type="info" showIcon message={processingNotice}/>):
        <div className="native-composer">
          {!awaiting&&!data?.reading&&<Space wrap className="guided-actions">{flow?.actions.filter(action=>!['chapter_practice','due_review'].includes(action.id)&&(!daily||!['chapter_continue','chapter_summary'].includes(action.id))).map((action,i)=><Button key={action.id}
            type={i===0?'primary':'default'} loading={busy} disabled={disabled||data?.stage_sizes?.[action.id]===0}
            onClick={()=>send({operation:'guided',action_id:action.id})}>
            {flow.confirm_outline&&action.id.endsWith('_outline')?'确认并保存大纲':action.label}
            {data?.stage_sizes?.[action.id] ? '（'+data.stage_sizes[action.id]+' 题）':''}</Button>)}</Space>}
          {!awaiting&&!data?.reading&&dailyCanContinue&&<Button type="primary" loading={busy} disabled={disabled}
            onClick={()=>guided('chapter_continue')}>{daily?.state==='active'?'下一道检查':'继续学习'}</Button>}
          {!question&&awaiting&&<><label htmlFor="learning-answer">回答助教的问题</label>
            <Input.TextArea id="learning-answer" rows={3} maxLength={12000} value={clarification}
              onChange={e=>setClarification(e.target.value)} disabled={disabled||pausedCard}/></>}
          {awaiting&&<Button type="primary" loading={busy} disabled={disabled||pausedCard||(!answer.trim()&&!Object.keys(grouped).length)}
            onClick={()=>send({operation:'answer',text:answer,answers:grouped,expected_id:requestId})}>提交回答</Button>}
        </div>}
      {data?.followup?.state==='failed'&&data.followup.submission_id===data.command?.id&&data.command?.state!=='failed'&&
        <Alert type="warning" showIcon message="助教没有完成这次回复，可以重新发送提问。"/>}
      {canAsk&&<form className="native-composer native-followup" onSubmit={event=>{
        event.preventDefault();
        if(!disabled&&followup.trim())void send({operation:'message',text:followup.trim()});
      }}>
        <label htmlFor="learning-followup">向助教提问</label>
        <Input.TextArea id="learning-followup" rows={2} maxLength={12000} value={followup}
          onChange={event=>setFollowup(event.target.value)} disabled={disabled} placeholder="输入想问的问题"/>
        <Button htmlType="submit" type={awaiting?'default':'primary'} disabled={disabled||!followup.trim()}>发送提问</Button>
      </form>}
    </section>
    {project.scenario==='kaoyan'&&prep&&flow&&<PaperStep project={project} prep={prep} flow={flow}
      disabled={disabled||awaiting} showAnnual={()=>showAnnual('past_paper')}/>}
    <Modal title="生成集中练习" open={practiceOpen} footer={null} onCancel={()=>setPracticeOpen(false)} destroyOnHidden>
      {practiceOpen&&<ConcentratedPractice projectId={project.id} disabled={disabled}/>}
    </Modal>
    <Modal title="今日学习小结" open={summaryOpen} footer={null} onCancel={()=>setSummaryOpen(false)}>
      <p>已完成 {daily?.completed??0} 项检查，累计学习 {Math.floor((daily?.seconds??0)/60)} 分钟。</p>
      <ul>{daily?.items.map(item=><li key={item.id}>{item.name}{item.explained?' · 已讲解':''} · {item.result==='correct'?'已完成检查':item.result?'待巩固':'尚未完成检查'}</li>)}</ul>
    </Modal>
  </section>}
    {prep&&scopeOpen&&<ScopeDialog project={project} prep={prep} onClose={()=>setScopeOpen(false)} chooseMaterials={chooseMaterials}
      uploading={uploadingMaterials}/>}
  </State>;
}

function ScopeDialog({project,prep,onClose,chooseMaterials,uploading}:{project:LearningProject;prep:Preparation;onClose:()=>void;
  chooseMaterials:()=>void;uploading:boolean}) {
  const {run,busy}=useRun();
  const [whole,setWhole]=useState(prep.scope.material_ids??(prep.scope.file_id?[prep.scope.file_id]:[]));
  const [sections,setSections]=useState<Record<string,string[]>>(()=>{
    const saved:Record<string,string[]>={};
    for(const {material_id,title} of prep.scope.sections??[])(saved[material_id]??=[]).push(title);
    return saved;
  });
  const materialIds=prep.scope_options.filter(book=>whole.includes(book.id)).map(book=>book.id);
  const selectedSections=prep.scope_options.filter(book=>!materialIds.includes(book.id))
    .flatMap(book=>book.sections.filter(title=>sections[book.id]?.includes(title)).map(title=>({material_id:book.id,title})));
  const overLimit=new Set([...materialIds,...selectedSections.map(section=>section.material_id)]).size>16||selectedSections.length>30;

  async function save() {
    const result=await run(()=>apiV2('/learning-projects/'+project.id+'/study-scope','PUT',{
      revision:project.revision,material_ids:materialIds,sections:selectedSections},key()),'考试范围已保存');
    if(result)onClose();
  }
  return <Modal title="确认期末考试范围" open onCancel={onClose} onOk={()=>void save()} okText="保存考试范围"
    confirmLoading={busy} okButtonProps={{disabled:uploading||overLimit||(!materialIds.length&&!selectedSections.length)}}>
    {prep.scope.text&&<p>此前填写的范围：{prep.scope.text}</p>}
    {prep.scope_options.length?<><p>勾选资料可纳入全文，也可以展开后只勾选需要复习的章节。</p>
      <div className="scope-materials">{prep.scope_options.map(book=>{
        const all=materialIds.includes(book.id);
        const checked=sections[book.id]??[];
        return <div className="scope-material" key={book.id}>
          <Checkbox checked={all} indeterminate={!all&&checked.length>0}
            onChange={event=>setWhole(previous=>event.target.checked?[...previous,book.id]:previous.filter(id=>id!==book.id))}>
            {book.title}
          </Checkbox>
          {!!book.sections.length&&<details>
            <summary>选择章节{!all&&checked.length?'（已选 '+checked.length+'）':''}</summary>
            <div className="scope-chapters">{book.sections.map(title=><Checkbox key={title}
              checked={all||checked.includes(title)} disabled={all}
              onChange={event=>{
                const include=event.target.checked;
                setSections(previous=>{
                  const current=previous[book.id]??[];
                  return {...previous,[book.id]:include?[...current,title]:current.filter(section=>section!==title)};
                });
              }}>{title}</Checkbox>)}</div>
          </details>}
        </div>;
      })}</div></>:<p>项目还没有学习资料，请先上传教材或讲义。</p>}
    {overLimit&&<p role="alert">最多选择 16 份资料和 30 个章节。</p>}
    {!prep.scope_options.length&&<Button loading={uploading} onClick={chooseMaterials}>上传教材或讲义</Button>}
  </Modal>;
}

function PaperStep({project,prep,flow,disabled,showAnnual}:{project:LearningProject;prep:Preparation;flow:Workflow;disabled:boolean;showAnnual:()=>void}) {
  const {run,busy}=useRun();
  const {modal}=App.useApp();
  const navigate=useNavigate();
  const [id,setId]=useState<string>();
  const selected=prep.papers.some(paper=>paper.id===id)?id:prep.papers[0]?.id;
  async function start(mode:'practice'|'mock') {
    const exam=await run(()=>apiV2<{id:string}>('/assessments/from-past-paper','POST',{
      project_id:project.id,resource_id:selected,mode},key()));
    if(exam)navigate('/learning/assessments/'+exam.id);
  }
  return <section id="past-paper-step" className="panel section-space">
    <h3>历年真题与模考</h3>
    {!prep.papers.length?<p>请先导入一套早于 {project.exam_year} 年、带答案和分值的往年真题。</p>:
      <Space wrap>
        <Select aria-label="选择往年真题" value={selected} onChange={setId} options={prep.papers.map(p=>({label:p.title,value:p.id}))}/>
        <Button disabled={disabled} loading={busy} onClick={()=>start('practice')}>按原卷练习</Button>
        <Button disabled={disabled||!flow.mock_ready} loading={busy} onClick={()=>modal.confirm({title:'开始限时模考？',
          content:'开始后立即计时，交卷前暂停助教和原文查阅。',onOk:()=>start('mock')})}>开始限时模考</Button>
      </Space>}
    <Button className="section-space" disabled={disabled} onClick={showAnnual}>导入历年真题</Button>
    <Space wrap className="section-space">
      {flow.practice_id&&<Link to={'/learning/assessments/'+flow.practice_id}>查看上次真题成绩</Link>}
      {flow.mock_id&&<Link to={'/learning/assessments/'+flow.mock_id}>查看上次模考成绩</Link>}
    </Space>
  </section>;
}
