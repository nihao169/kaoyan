import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, Button, Input, Radio, Space } from 'antd';
import { Link, useParams } from 'react-router-dom';
import { apiV2, key } from './api';
import { PageTitle, State, useRun } from './ui';

type ReviewItem = {id:string;scope_id:string;title:string;knowledge:string;due:boolean};
type ReviewQueue = {enabled:boolean;items:ReviewItem[];unavailable:boolean};
export type NativeQuestion = {question_id:string;prompt:string;options:{id:string;label:string;body:string}[];questions?:NativeQuestion[];
  clarification?:boolean};
type Question = NativeQuestion;
type ReviewSession = {project_id?:string;state:string;request_id:string;question:Question|null;feedback:string};
const queueKey = ['mastery-reviews'];

export function ProjectReviewQueue({projectId,disabled,hasGuided,exclude}:{projectId:string;disabled:boolean;hasGuided:boolean;exclude:Set<string>}) {
  const query = useQuery({queryKey:[...queueKey,projectId],
    queryFn:()=>apiV2<ReviewQueue>('/mastery-reviews?'+new URLSearchParams({project_id:projectId})),
    retry:false});
  const items=query.data?.items.filter(item=>item.due&&!exclude.has(item.knowledge))??[];
  return <>{(query.data?.unavailable||query.isError)&&<Alert type="warning" message={query.error?.message??'部分复习暂不可用。'}
    action={<Button onClick={()=>void query.refetch()}>重试</Button>}/>}
    {!hasGuided&&query.isSuccess&&!query.data.unavailable&&!items.length&&<p className="muted">当前项目没有到期复习。</p>}
    {!!items.length&&<ul>{items.map(item=><li key={item.scope_id+':'+item.id}><Space wrap>
      <span>{item.knowledge} · {item.title}</span>
      {disabled?<Button disabled>进入复习</Button>:<Link to={'/reviews/native/'+item.scope_id}>进入复习</Link>}
    </Space></li>)}</ul>}</>;
}

export function ReviewQuestion({question,answers,setAnswer,disabled}:{question:Question;answers:Record<string,string>;
  setAnswer:(id:string,value:string)=>void;disabled:boolean}) {
  return <section><p>{question.prompt}</p>{question.questions?.length?question.questions.map((child,i)=>
    <div key={child.question_id}><strong>第 {i+1} 题</strong>
      <ReviewQuestion question={child} answers={answers} setAnswer={setAnswer} disabled={disabled}/>
    </div>):question.options.length?<Radio.Group disabled={disabled} value={answers[question.question_id]}
    onChange={event=>setAnswer(question.question_id,event.target.value)}>
    <Space direction="vertical">{question.options.map(option=><Radio key={option.id} value={option.label}>
      {option.label}{option.body&&(question.clarification?' · ':'. ')+option.body}</Radio>)}</Space>
    </Radio.Group>:<Input.TextArea aria-label="复习作答" rows={4} disabled={disabled} maxLength={8000}
    value={answers[question.question_id]??''} onChange={event=>setAnswer(question.question_id,event.target.value)}/>}</section>;
}

export function MasteryReview() {
  const {scopeId} = useParams();
  const path = '/mastery-reviews/'+scopeId+'/session';
  const client = useQueryClient();
  const {run,busy} = useRun();
  const [answer,setAnswer] = useState('');
  const [answers,setAnswers] = useState<Record<string,string>>({});
  const query = useQuery({queryKey:[path],queryFn:()=>apiV2<ReviewSession>(path),
    refetchInterval:q=>['running','queued','recovering','created','cancel_requested'].includes(q.state.data?.state??'')?1500:false});
  const session = query.data;
  const state = session?.state;
  const requestId = session?.request_id;
  useEffect(()=>{
    if (state==='idle'||state==='question') void client.invalidateQueries({queryKey:queueKey});
  },[client,state,requestId]);
  const canAnswer = session?.state==='question'||session?.state==='waiting_input';
  const question = session?.question;
  const groupAnswers = Object.fromEntries((question?.questions??[]).filter(child=>answers[child.question_id]?.trim())
    .map(child=>[child.question_id,answers[child.question_id]]));
  const reply = question?answers[question.question_id]??'':answer;
  async function action(operation:'start'|'answer') {
    await run(async()=>{
      const result = await apiV2<ReviewSession>(path,'POST',{operation,submission_id:key(),
        answer:operation==='answer'?reply:'',answers:operation==='answer'?groupAnswers:{},expected_id:session?.request_id??''});
      client.setQueryData([path],result);
      if (operation==='answer') {setAnswer('');setAnswers({});}
      return result;
    });
    void query.refetch();
    void client.invalidateQueries({queryKey:queueKey});
  }
  return <><PageTitle title="到期复习" description="复习内容与下次到期时间由 DeepTutor 根据学习进度安排。"
    action={<Link to={session?.project_id?'/learning/projects/'+session.project_id:'/learning/projects'}><Button>返回学习项目</Button></Link>}/>
    <State query={query}>{session&&<div className="panel">
      {session.feedback&&<p style={{whiteSpace:'pre-wrap'}}>{session.feedback}</p>}
      {question&&<ReviewQuestion question={question} answers={answers}
        setAnswer={(id,value)=>setAnswers(previous=>({...previous,[id]:value}))} disabled={!canAnswer||busy}/>}
      {canAnswer?<>{!question&&<Input.TextArea aria-label="复习作答" maxLength={12000} rows={4} value={answer} onChange={e=>setAnswer(e.target.value)}/>}
        <Space className="section-space"><Button type="primary" disabled={!reply.trim()&&!Object.keys(groupAnswers).length} loading={busy} onClick={()=>action('answer')}>提交复习作答</Button></Space></>
        :session.state==='idle'?<Button type="primary" loading={busy} onClick={()=>action('start')}>开始到期复习</Button>
          :<Alert type="info" showIcon message="DeepTutor 正在处理复习，可刷新或重新打开此页继续。"/>}
    </div>}</State></>;
}
