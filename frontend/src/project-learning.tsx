import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Alert, Button, Checkbox, Form, Input, InputNumber, Modal, Radio, Select, Space, Tag } from 'antd';
import { Link } from 'react-router-dom';
import { apiV2, key } from './api';
import { Blank, State, useRun } from './ui';
import { LearningSceneOptions, type LearningScene } from './v2-scenes';
import { ReviewQuestion, type NativeQuestion } from './mastery-reviews';

export type LearningProject = {id:string;title:string;scenario:LearningScene;course_name:string;learning_goal:string;
  scene_confirmed:boolean;revision:number;exam_year:number;state:string};
type Point = {id:string;name:string;status:string;mastery:number;mastery_source:string};
type Curriculum = {path_revision:number;map:{counts:{mastered:number;total:number};modules:{id:string;name:string;knowledge_points:Point[]}[]};
  next:{reason?:string;knowledge_point_name?:string};reviews:{due:boolean;knowledge_point_name?:string;due_at?:number}[]};
type LearningState = {state:string;error?:string;mode?:string;intake?:boolean;reading?:boolean;request_id?:string;question:NativeQuestion|null;
  messages:{role:string;content:string}[];curriculum?:Curriculum;has_materials?:boolean;
  command?:{id:string;state:string;error:string};writable?:boolean};
const running = new Set(['created','queued','running','recovering','cancel_requested']);

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
      {curriculum?.next.reason&&<p>助教建议：{curriculum.next.reason}</p>}</div>
    <Link to={'/learning/projects/'+project.id}><Button type="primary">{project.scene_confirmed?'继续学习':'确认并开始'}</Button></Link></article>;
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
    <p>场景告诉助教你的学习背景。后续大纲、教学与复习由助教与你一起确定。</p>
    <LearningSceneOptions value={scene} onChange={setScene}/>
    <Form.Item name="course_name" label="课程名称" rules={[{required:true,whitespace:true}]}><Input maxLength={200}/></Form.Item>
    <Form.Item name="learning_goal" label="学习目标与范围"><Input.TextArea rows={3} maxLength={2000}
      placeholder="希望学会什么？考试范围是什么？也可以稍后与助教讨论。"/></Form.Item>
    {scene==='kaoyan'&&<Form.Item name="exam_year" label="考研年份" rules={[{required:true,type:'integer'}]}><InputNumber min={2026} max={2100}/></Form.Item>}
    {project.scene_confirmed&&<p className="muted">已有学习记录保留。目标变化后，请与助教讨论大纲调整，再确认修改。</p>}
    <Button htmlType="submit" type="primary" loading={busy}>确认学习背景</Button>
  </Form>;
}

export function ProjectLearning({project,materials,showMaterials}:{project:LearningProject;
  materials:{id:string;title:string;state:string;text?:string}[];showMaterials:()=>void}) {
  const path='/learning-projects/'+project.id+'/learning';
  const {run,busy}=useRun();
  const [text,setText]=useState('');
  const [answers,setAnswers]=useState<Record<string,string>>({});
  const [selectedMaterial,setSelectedMaterial]=useState<string>();
  const [selectedNotes,setSelectedNotes]=useState<string[]>([]);
  const [showNotes,setShowNotes]=useState(false);
  const [practiceOpen,setPracticeOpen]=useState(false);
  const lastQuestion=useRef('');
  const submission=useRef<{body:string;key:string}|undefined>(undefined);
  const query=useQuery({queryKey:['project-learning',project.id,project.revision],
    queryFn:()=>apiV2<LearningState>(path),enabled:project.scene_confirmed,
    refetchInterval:q=>running.has(q.state.data?.state??'')||running.has(q.state.data?.command?.state??'')?2000: false});
  const notes=useQuery({queryKey:['project-learning-notes',project.id],queryFn:()=>apiV2<{id:string;title:string}[]>(
    '/learning-projects/'+project.id+'/notes'),enabled:showNotes});
  const data=query.data;
  const question=data?.question;
  const requestId=data?.request_id??'';
  useEffect(()=>{
    if(lastQuestion.current!==requestId){setAnswers({});lastQuestion.current=requestId;}
  },[requestId]);
  const processing=running.has(data?.state??'')||running.has(data?.command?.state??'');
  const disabled=busy||processing||project.state!=='active';
  const awaiting=!!question||data?.state==='waiting_input';
  async function send(body:Record<string,unknown>) {
    const serialized=JSON.stringify(body);
    if(submission.current?.body!==serialized)submission.current={body:serialized,key:key()};
    const result=await run(()=>apiV2(path,'POST',body,submission.current!.key));
    if(result){submission.current=undefined;setText('');setAnswers({});}
    void query.refetch();
  }
  const grouped=Object.fromEntries((question?.questions??[]).filter(q=>answers[q.question_id]?.trim()).map(q=>[q.question_id,answers[q.question_id]]));
  const answer=question?answers[question.question_id]??'':text;

  if(!project.scene_confirmed)return <section className="learning-intake"><h2>先确认这个项目怎样学习</h2>
    <LearningProfileForm project={project}/></section>;
  return <State query={query}><section className="native-learning" aria-label="项目引导学习">
    <div className="native-learning-heading"><div><h2>{data?.reading?'资料精读':'与助教一起学习'}</h2>
      <p>{project.course_name} · {data?.intake?'先聊目标与基础':({outline:'讨论大纲',study:'学习',review:'复习'}[data?.mode??'']??'准备学习')}</p></div>
      <Space wrap><Button disabled={disabled} onClick={showMaterials}>课程与资料</Button>
        <Button onClick={()=>setPracticeOpen(true)}>集中练习</Button></Space></div>
    {data?.intake&&<Alert type="info" showIcon message="可以先与助教明确目标和基础"
      description="正式教学需要课程资料或个人资料，以及已就绪的助教索引。" action={<Button onClick={showMaterials}>准备资料</Button>}/>}
    {data?.command?.state==='failed'&&<Alert type="error" showIcon message={data.command.error||'学习请求未完成'}
      action={<Button loading={busy} onClick={()=>run(()=>apiV2(path+'/retry','POST'))}>恢复原请求</Button>}/>}
    {data?.error&&<Alert type="error" showIcon message={data.error}/>}
    <div className="native-learning-grid"><aside className="native-curriculum" aria-label="学习大纲">
      <h3>学习大纲</h3>
      {data?.curriculum?.map.modules.length?<><p>已掌握 {data.curriculum.map.counts.mastered} / {data.curriculum.map.counts.total} 个知识点</p>
        <div className="native-map">{data.curriculum.map.modules.map(module=><details key={module.id} open><summary>{module.name}</summary>
          <ol>{module.knowledge_points.map(point=><li key={point.id}><span>{point.name}</span>
            <Tag color={point.status==='mastered'?'green':undefined}>{point.status==='mastered'?'已掌握':point.status==='learning'?'学习中':'待学习'}{point.mastery_source==='learner'?' · 自评':''}</Tag></li>)}</ol>
        </details>)}</div>
        {!!data.curriculum.reviews.length&&<p>复习安排 {data.curriculum.reviews.length} 项，其中 {data.curriculum.reviews.filter(r=>r.due).length} 项已到期。</p>}
      </>:<p className="muted">先告诉助教你想达到什么目标，再一起确定大纲。</p>}
      {!data?.intake&&data?.state!=='not_started'&&<Space wrap>
        <Button disabled={disabled||awaiting} onClick={()=>send({operation:'mode',mode:'outline'})}>讨论大纲</Button>
        <Button disabled={disabled||awaiting||!data?.curriculum?.map.modules.length} onClick={()=>send({operation:'mode',mode:'study'})}>{data?.reading?'返回引导学习':'继续学习'}</Button>
        <Button disabled={disabled||awaiting||!data?.curriculum?.map.modules.length} onClick={()=>send({operation:'mode',mode:'review'})}>复习</Button>
      </Space>}
      <hr/><h3>资料与笔记</h3>
      <Select aria-label="选择精读资料" placeholder="选择一份资料精读" value={selectedMaterial} onChange={setSelectedMaterial}
        options={materials.filter(m=>m.state==='ready').map(m=>({value:m.id,label:m.title}))}/>
      <Button disabled={disabled||awaiting||!selectedMaterial} onClick={()=>send({operation:'read',material_id:selectedMaterial})}>打开精读</Button>
      <Button disabled={disabled} onClick={()=>setShowNotes(!showNotes)}>选取笔记讨论大纲</Button>
      {showNotes&&<State query={notes}><Checkbox.Group value={selectedNotes} onChange={setSelectedNotes}
        options={notes.data?.map(note=>({value:note.id,label:note.title}))}/>
        {!notes.data?.length&&<p className="muted">先在笔记与闪卡中保存自己的理解。</p>}
        <Button disabled={disabled||awaiting||!selectedNotes.length} onClick={()=>send({operation:'notes',note_ids:selectedNotes})}>交给助教讨论</Button></State>}
    </aside><div className="native-conversation">
      <div className="native-messages" aria-live="polite">
        {data?.messages.length?data.messages.map((message,i)=><article key={i} className={'native-message '+message.role}>
          <strong>{message.role==='user'?'我':'学习助教'}</strong><p>{message.content}</p></article>):<Blank description="从你的目标或一个问题开始，助教会与你一起确定下一步。"/>}
      </div>
      {question&&<div className="native-question"><h3>当前理解检查</h3><ReviewQuestion question={question} answers={answers}
        setAnswer={(id,value)=>setAnswers(previous=>({...previous,[id]:value}))} disabled={disabled}/></div>}
      {processing?<Alert type="info" showIcon message="助教正在处理，刷新或重新打开项目也可继续。"/>:
        <div className="native-composer">
          {!question&&<><label htmlFor="learning-message">{awaiting?'回答助教的问题':'发给学习助教'}</label>
            <Input.TextArea id="learning-message" rows={4} maxLength={12000} value={text} onChange={e=>setText(e.target.value)}
              disabled={disabled} placeholder="说说你的目标、困惑，或请助教继续。"/></>}
          <Button type="primary" loading={busy} disabled={disabled||(!answer.trim()&&!Object.keys(grouped).length)}
            onClick={()=>send(awaiting?{operation:'answer',text:answer,answers:grouped,expected_id:requestId}:{operation:'message',text})}>
            {awaiting?'提交回答':'发送给助教'}</Button>
        </div>}
    </div></div>
    <Modal title="当前路径的集中练习" open={practiceOpen} footer={null} onCancel={()=>setPracticeOpen(false)} destroyOnHidden>
      {practiceOpen&&<NativePractice projectId={project.id} disabled={project.state!=='active'}/>}
    </Modal>
  </section></State>;
}

type PracticeEntry={id:number;question:string;question_type:string;options:Record<string,string>};
function NativePractice({projectId,disabled}:{projectId:string;disabled:boolean}) {
  const base='/learning-projects/'+projectId+'/learning/practice';
  const list=useQuery({queryKey:['native-practice',projectId],queryFn:()=>apiV2<{items:PracticeEntry[]}>(base)});
  const [selected,setSelected]=useState<number>();
  const [answer,setAnswer]=useState('');
  const [selfReport,setSelfReport]=useState(false);
  const [rating,setRating]=useState('good');
  const [result,setResult]=useState<{correct_answer:string;explanation:string}>();
  const submission=useRef(key());
  const {run,busy}=useRun();
  const question=useQuery({queryKey:['native-practice-question',projectId,selected],enabled:selected!==undefined,
    queryFn:()=>apiV2<{entry:PracticeEntry;version:number}>(base+'/'+selected)});
  return <State query={list}><p>这里练习助教已保存到当前学习路径的题目。练习记录单独保存，掌握状态以引导学习中的检验证据为准。</p>
    {!list.data?.items.length?<Blank description="当前路径还没有已保存的题目。可以先与助教学习并完成理解检查。"/>:
    <><Select aria-label="选择原生练习" value={selected} style={{width:'100%'}} placeholder="选择一道题"
      options={list.data.items.map(q=>({value:q.id,label:q.question.slice(0,80)}))} onChange={id=>{
        setSelected(id);setAnswer('');setResult(undefined);setSelfReport(false);submission.current=key();
      }}/>
      {selected!==undefined&&<State query={question}>{question.data&&<><p>{question.data.entry.question}</p>
        <p>{Object.entries(question.data.entry.options||{}).map(([id,text])=><span key={id}>{id}. {text}<br/></span>)}</p>
        <Input.TextArea aria-label="练习回答" value={answer} onChange={e=>setAnswer(e.target.value)} disabled={disabled||busy||!!result}/>
        <Checkbox checked={selfReport} disabled={disabled||busy||!!result} onChange={e=>setSelfReport(e.target.checked)}>此题使用自评</Checkbox>
        {selfReport&&<Radio.Group value={rating} disabled={!!result} onChange={e=>setRating(e.target.value)} options={[
          {value:'again',label:'需要重学'},{value:'hard',label:'较难'},{value:'good',label:'基本理解'},{value:'easy',label:'熟练'}]}/>}
        <Button type="primary" loading={busy} disabled={disabled||!answer.trim()||!!result} onClick={async()=>{
          const reply=await run(()=>apiV2<{correct_answer:string;explanation:string}>(base+'/'+selected,'POST',{
            answer,version:question.data!.version,self_report:selfReport,rating},submission.current));
          if(reply){setResult(reply);void question.refetch();}
        }}>提交练习</Button>
        {result&&<Alert type="info" message={'参考答案：'+result.correct_answer} description={result.explanation}/>}
      </>}</State>}</>}
  </State>;
}
