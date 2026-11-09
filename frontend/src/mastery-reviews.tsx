import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, Button, Input, Radio, Space, Tag } from 'antd';
import { Link, useParams } from 'react-router-dom';
import { apiV2, key } from './api';
import { Blank, PageTitle, State, useRun } from './ui';

type ReviewItem = {id:string;scope_id:string;title:string;knowledge:string;due_at:number;due:boolean;reason:string;next_step?:string};
type ReviewQueue = {enabled:boolean;items:ReviewItem[];history:{id:string;title:string;due_at?:string;state:string}[];
  pending:number;unavailable:boolean};
export type NativeQuestion = {question_id:string;prompt:string;options:{id:string;label:string;body:string}[];questions?:NativeQuestion[]};
type Question = NativeQuestion;
type ReviewSession = {state:string;request_id:string;question:Question|null;feedback:string};
const queueKey = ['mastery-reviews'];

export function useMasteryReviews() {
  return useQuery({queryKey:queueKey,queryFn:()=>apiV2<ReviewQueue>('/mastery-reviews')});
}

export function MasteryReviewQueue({dueOnly=false}:{dueOnly?:boolean}) {
  const query = useMasteryReviews();
  if (!query.data?.enabled) return null;
  const items = query.data.items.filter(item=>!dueOnly||item.due);
  return <section className="panel section-space" aria-label="Mastery Path 复习">
    <h2>Mastery Path 复习</h2>
    {query.data.unavailable&&<Alert type="warning" showIcon message="部分原生复习暂不可用"/>}
    {!!query.data.pending&&<Alert type="info" showIcon message={`${query.data.pending} 条学习证据正在同步`}/>}
    {!items.length?<Blank description="当前没有可展示的复习安排。"/>:<div className="v2-task-list">{items.map(item=>
      <div className="v2-task" key={item.scope_id+':'+item.id}>
        <div><Tag color={item.due?'orange':undefined}>{item.due?'已到期':'待到期'}</Tag><span>{item.title}</span>
          <h3>{item.knowledge}</h3><p>{item.reason}</p>
          {item.next_step==='review'&&<Tag color="blue">原生下一步</Tag>}
          <small>{new Date(item.due_at*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}</small></div>
        <Link to={'/reviews/native/'+item.scope_id}><Button>{item.due?'进入复习':'查看复习'}</Button></Link>
      </div>)}</div>}
  </section>;
}

export function MasteryReviewHistory() {
  const history = useMasteryReviews().data?.history;
  if (!history?.length) return null;
  return <section className="panel section-space"><h3>个人项目历史复习</h3><ul>
    {history.map(item=><li key={item.id}><Link to={'/learning/session/'+item.id}>{item.title}</Link>
      <Tag>{item.state==='completed'?'已完成':'已归档'}</Tag></li>)}
  </ul></section>;
}

export function ReviewQuestion({question,answers,setAnswer,disabled}:{question:Question;answers:Record<string,string>;
  setAnswer:(id:string,value:string)=>void;disabled:boolean}) {
  return <section><p>{question.prompt}</p>{question.questions?.length?question.questions.map((child,i)=>
    <div key={child.question_id}><strong>第 {i+1} 题</strong>
      <ReviewQuestion question={child} answers={answers} setAnswer={setAnswer} disabled={disabled}/>
    </div>):question.options.length?<Radio.Group disabled={disabled} value={answers[question.question_id]}
    onChange={event=>setAnswer(question.question_id,event.target.value)}>
      <Space direction="vertical">{question.options.map(option=><Radio key={option.id} value={option.label}>{option.label}. {option.body}</Radio>)}</Space>
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
  return <><PageTitle title="Mastery Path 复习" description="复习内容与下次到期时间由 DeepTutor 根据学习进度安排。"
    action={<Link to="/reviews"><Button>返回复习</Button></Link>}/>
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
