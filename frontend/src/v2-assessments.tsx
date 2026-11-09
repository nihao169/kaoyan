import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Alert, App as AntApp, Button, Checkbox, Form, Input, InputNumber, Modal, Radio, Select, Space, Tag } from 'antd';
import { apiV2, key } from './api';
import { Blank, PageTitle, State, useRun } from './ui';
import { politicsPracticeNotice } from './v2-scenes';

type Question={id:string;origin:string;prompt:string;kind:string;options:Record<string,string>;answer?:string[];explanation?:string;knowledge:string};
type Answer={answer:string[];response_text:string;confidence:'normal'};
type Exam={id:string;project_id:string;title:string;state:string;mode:string;deadline_at:string;server_now:string;revision:number;paper_objective_score?:{earned:number;possible:number};drafts:Record<string,Answer>;entries:{task_id:string;points?:number;question:Question;result?:{correct?:boolean;feedback?:string;state?:string}}[]};

export function AssessmentsV2(){
  const [search,setSearch] = useSearchParams();
  const requestedProject = search.get('project');
  const mode = requestedProject&&search.get('mode')==='practice'?'practice':'mock';
  const exams=useQuery({queryKey:['v2-assessments'],queryFn:()=>apiV2<Exam[]>('/assessments')});
  const [open,setOpen] = useState(false);

  function close() {
    setOpen(false);
    if (requestedProject) {
      const next = new URLSearchParams(search);
      next.delete('project');
      next.delete('mode');
      setSearch(next,{replace:true});
    }
  }

  return <><PageTitle title="练习与模考" description="练习时理解，模考时独立，交卷后回到薄弱点。" action={<Button type="primary" onClick={()=>setOpen(true)}>创建测评</Button>}/><State query={exams}>{exams.data?.length?exams.data.map(a=><div className="v2-task" key={a.id}><div><Tag>{a.mode==='mock'?'限时模考':'成组练习'}</Tag><h3>{a.title}</h3><p>{a.state==='active'?'进行中，整组交卷后查看反馈':'已交卷，反馈已关联补学任务'}</p></div><Link to={'/learning/assessments/'+a.id}><Button>{a.state==='active'?'继续作答':'查看反馈'}</Button></Link></div>):<Blank description="先在学习项目中准备练习题，再从已校验题目组成测评。"/>}</State>
    {(open||requestedProject)&&<AssessmentSetup key={`${requestedProject}:${mode}`} requestedProject={requestedProject} mode={mode} onClose={close}/>}
  </>;
}

function AssessmentSetup({requestedProject,mode,onClose}:{requestedProject:string|null;mode:'mock'|'practice';onClose:()=>void}) {
  const projects = useQuery({queryKey:['v2-projects'],queryFn:()=>apiV2<{id:string;title:string;state:string;policy:string}[]>('/learning-projects')});
  const activeProjects = projects.data?.filter(p=>p.state==='active') ?? [];
  const [selected,setSelected] = useState(requestedProject ?? undefined);
  const [ids,setIds] = useState<string[]>([]);
  const project = activeProjects.find(p=>p.id===selected);
  const bank = useQuery({queryKey:['v2-bank',project?.id],queryFn:()=>apiV2<Question[]>('/learning-projects/'+project?.id+'/question-bank'),enabled:!!project});
  const {run,busy} = useRun();
  const navigate = useNavigate();
  const canStart = !!project&&!bank.error&&ids.length>0&&ids.length<=50&&ids.every(id=>bank.data?.some(q=>q.id===id));

  async function start(values:{title:string;mode:'mock'|'practice';minutes:number}) {
    if (!canStart||!project||busy) return;
    const assessment = await run(()=>apiV2<{id:string}>('/assessments','POST',{...values,project_id:project.id,question_ids:ids},key()));
    if (assessment) navigate('/learning/assessments/'+assessment.id);
  }

  return <Modal title="从项目题库组织测评" open onCancel={onClose} footer={null} closable={!busy} maskClosable={!busy} keyboard={!busy}>
    <State query={projects}><Form layout="vertical" initialValues={{mode,minutes:30}} onFinish={start}>
      <Form.Item label="学习项目" htmlFor="assessment-project" required>
        <Select id="assessment-project" value={project?.id} onChange={id=>{setSelected(id);setIds([])}} options={activeProjects.map(p=>({value:p.id,label:p.title}))}/>
      </Form.Item>
      <Form.Item name="title" label="测评名称" rules={[{required:true,whitespace:true}]}><Input maxLength={200}/></Form.Item>
      <Space wrap>
        <Form.Item name="mode" label="模式"><Select style={{width:140}} options={[{value:'mock',label:'限时模考'},{value:'practice',label:'成组练习'}]}/></Form.Item>
        <Form.Item name="minutes" label="时长（分钟）" rules={[{required:true,type:'integer'}]}><InputNumber min={5} max={180}/></Form.Item>
      </Space>
      <p>选择题目（最多 50 道，AI 生成题会标明来源）。{project?.policy==='kaoyan-politics-v1'&&politicsPracticeNotice}</p>
      {project&&<State query={bank}>
        <Checkbox.Group value={ids} onChange={setIds} style={{display:'grid',gap:12}} options={bank.data?.map(q=>({value:q.id,label:(q.origin==='past_paper'?'个人导入真题 · ':q.origin==='simulated_paper'?'模拟卷 · ':'AI生成 · ')+q.prompt}))}/>
        {!bank.data?.length&&<p className="muted">当前还没有可用题目。请先<Link to={'/learning/projects/'+project.id}>返回项目学习</Link>并准备练习。</p>}
      </State>}
      <Button style={{marginTop:24}} type="primary" loading={busy} disabled={!canStart} htmlType="submit">确认并开始</Button>
    </Form></State>
  </Modal>;
}

export function AssessmentV2(){
  const {assessmentId}=useParams();
  const query=useQuery({queryKey:['v2-assessment',assessmentId],queryFn:()=>apiV2<Exam>('/assessments/'+assessmentId)});
  return <State query={query}>{query.data&&<ExamWork key={query.data.id+query.data.state} exam={query.data}/>}</State>;
}

function ExamWork({exam}:{exam:Exam}){
  const {run,busy}=useRun();
  const {modal}=AntApp.useApp();
  const [answers,setAnswers]=useState<Record<string,Answer>>(exam.drafts);
  const current=useRef(answers);const revision=useRef(exam.revision);const saved=useRef(JSON.stringify(exam.drafts));
  const pending=useRef<Promise<void>|null>(null);const stopped=useRef(false);
  const [saveStatus,setSaveStatus]=useState('草稿已恢复');const [remaining,setRemaining]=useState(Math.max(0,Date.parse(exam.deadline_at)-Date.parse(exam.server_now)));
  const active=exam.state==='active';
  const offset=useRef(Date.parse(exam.server_now)-Date.now());
  async function saveDraft(){
    if(pending.current)await pending.current;
    const snapshot=JSON.stringify(current.current);
    if(snapshot===saved.current||stopped.current)return;
    const work=apiV2<{revision:number}>('/assessments/'+exam.id+'/draft','PUT',{revision:revision.current,answers:JSON.parse(snapshot)}).then(r=>{revision.current=r.revision;saved.current=snapshot;setSaveStatus('草稿已自动保存')}).catch(e=>{setSaveStatus(e.message);throw e});
    pending.current=work;
    try{await work}finally{pending.current=null}
  }
  async function submit(){
    stopped.current=true;
    if(pending.current)await pending.current.catch(()=>{});
    const result=await run(()=>apiV2('/assessments/'+exam.id+'/submit','POST',{answers:current.current},key()),'已交卷，下一步任务已更新');
    if(!result)setSaveStatus('交卷未完成，请点击提交重试；原草稿仍保留');
  }
  const submitRef=useRef(submit);submitRef.current=submit;
  useEffect(()=>{
    if(!active)return;
    const timer=window.setInterval(()=>{const ms=Date.parse(exam.deadline_at)-Date.now()-offset.current;setRemaining(Math.max(0,ms));if(ms<=0&&!stopped.current){stopped.current=true;void submitRef.current()}},1000);
    const saver=window.setInterval(()=>{if(Date.parse(exam.deadline_at)>Date.now()+offset.current)void saveDraft().catch(()=>{})},2000);
    return()=>{clearInterval(timer);clearInterval(saver)};
  },[exam.id,active]);
  function change(tid:string,value:Partial<Answer>){const previous=current.current[tid]||{answer:[],response_text:'',confidence:'normal' as const};const next={...current.current,[tid]:{...previous,...value}};current.current=next;setAnswers(next);setSaveStatus('有未保存的修改')}
  if(exam.state==='needs_review')return <><PageTitle title={exam.title} description="已结束，等待核查" action={<Link to="/learning/assessments">返回测评列表</Link>}/>
    <Alert type="warning" message="因资料或账号权限变化，本次未自动判分" description="服务器已保留最后成功保存的草稿。"/></>;
  return <><PageTitle title={exam.title} description={active?'独立作答，整组交卷后查看反馈。':'本次测评结果已保存，错题已进入补学流程。'} action={<Space wrap>
    {!active&&<Link to={'/learning/projects/'+exam.project_id}>返回学习项目查看补学</Link>}
    <Link to="/learning/assessments">返回测评列表</Link>
  </Space>}/>{active&&<Alert type="info" message={`剩余 ${Math.ceil(remaining/60000)} 分钟 · ${saveStatus}`} description={`每两秒自动保存。到时交卷以服务器最后保存的答案为准。${exam.mode==='mock'?'模考期间本项目助教暂停。':''}`}/>}
    {!active&&exam.paper_objective_score&&<Alert type="info" message={`客观题 ${exam.paper_objective_score.earned} / ${exam.paper_objective_score.possible} 分`} description="分析题训练反馈另列，未计入客观题分数。"/>}
    <div className="v2-exam-layout"><aside className="v2-answer-sheet"><h3>答题卡</h3><Space wrap>{exam.entries.map((entry,i)=><Button key={entry.task_id} type={answers[entry.task_id]?.answer.length||answers[entry.task_id]?.response_text?'primary':'default'} href={'#question-'+entry.task_id}>{i+1}</Button>)}</Space>{active&&<Button style={{marginTop:24}} type="primary" loading={busy} onClick={()=>modal.confirm({title:'确认整组交卷？',content:'未作答题目按未完成处理，交卷后可以查看解析并补学。',onOk:submit})}>提交本次测评</Button>}</aside><section>{exam.entries.map((entry,i)=><article className="v2-exam-question" id={'question-'+entry.task_id} key={entry.task_id}><Tag>第 {i+1} 题 · {entry.question.origin==='past_paper'?'个人导入真题':entry.question.origin==='simulated_paper'?'模拟卷':'AI生成练习'}{entry.points?` · ${entry.points} 分`:''}</Tag><h3>{entry.question.prompt}</h3>{entry.question.kind==='essay'?<Input.TextArea rows={6} disabled={!active} value={answers[entry.task_id]?.response_text||''} onChange={e=>change(entry.task_id,{response_text:e.target.value})}/>:entry.question.kind==='single'?<Radio.Group style={{display:'grid',gap:12}} disabled={!active} value={answers[entry.task_id]?.answer[0]} onChange={e=>change(entry.task_id,{answer:[e.target.value]})}>{Object.entries(entry.question.options).map(([k,v])=><Radio key={k} value={k}>{k}. {v}</Radio>)}</Radio.Group>:<Checkbox.Group disabled={!active} style={{display:'grid',gap:12}} value={answers[entry.task_id]?.answer||[]} options={Object.entries(entry.question.options).map(([k,v])=>({value:k,label:k+'. '+v}))} onChange={values=>change(entry.task_id,{answer:values as string[]})}/>} {!active&&<div className="v2-feedback"><strong>{entry.result?.state==='pending_ai'?'待AI训练评价':entry.result?.correct?'回答正确':'需要补学'}</strong><p>{entry.result?.feedback}</p><p>参考答案：{entry.question.answer?.join('、')}</p><p>{entry.question.explanation}</p></div>}</article>)}</section></div>
    {!active&&<Link to={'/learning/projects/'+exam.project_id}><Button type="primary">回到项目，开始下一轮学习</Button></Link>}
  </>;
}
